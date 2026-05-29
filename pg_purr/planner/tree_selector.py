"""Quantum candidate selector via QAOA.

Builds a one-hot QUBO over K candidate spanning trees:

    minimise   Σ_i c_i · x_i
    subject to Σ_i x_i = 1
    x_i ∈ {0, 1}

and solves it with QAOA. The chosen candidate is the set binary
variable in the resulting bitstring: the local AerSimulator path
decodes it via `qiskit_optimization`'s `MinimumEigenOptimizer`,
while the IBM-hardware and fixed-angle paths take the lowest-cost
feasible (one-hot) measured bitstring directly (see below).

Two execution paths:

* Default — local `AerSimulator`. With K ≤ 16 the QAOA circuit
  fits comfortably in state-vector simulation on a developer
  laptop. Determinism comes from a fixed SamplerV2 seed and shot
  count, COBYLA's gradient-free outer loop, and an explicit
  (constant) ``initial_point`` passed to QAOA — when
  ``initial_point`` is left ``None`` QAOA samples a random point
  on each construction, breaking reproducibility.

* Opt-in — real IBM Quantum hardware via ``qiskit-ibm-runtime``.
  Activated when ``QISKIT_IBM_TOKEN`` is present in the
  environment. ``QISKIT_IBM_INSTANCE`` and ``QISKIT_IBM_CHANNEL``
  are forwarded if set. The least-busy operational backend with
  enough qubits for K is selected. Hardware shot noise makes runs
  non-deterministic regardless of ``seed``.

  The hardware path does not use ``MinimumEigenOptimizer``: an ISA
  circuit is at the device's *physical* width, which mismatches the
  logical-width cost observable and eigenstate. The QAOA cost
  Hamiltonian is diagonal, so ``_solve_qaoa_hardware`` estimates each
  energy from sampled bitstrings (no observable submitted) and decodes
  via ``measure_all`` classical bits (no transpiler-layout lookup).

Execution mode is selected by ``PG_PURR_QAOA_MODE``:

* ``variational`` (default) — the full COBYLA loop; on real hardware
  one QPU job per energy evaluation. See ``_solve_qaoa_hardware``.
* ``fixed_angle`` — a single fixed-angle QAOA execution (one QPU job);
  the lowest-cost feasible sample is chosen, without the variational
  loop. See ``_solve_qaoa_fixed_angle``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, TypeVar

from qiskit.circuit.library import QAOAAnsatz
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from qiskit_algorithms import QAOA
from qiskit_algorithms.optimizers import COBYLA
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer
from qiskit_optimization.converters import QuadraticProgramToQubo

T = TypeVar("T")

_DEFAULT_MAX_ITER = 80
_FIXED_ANGLE_SHOTS = 8192
_VALID_MODES = ("variational", "fixed_angle")


def _resolve_mode() -> str:
    """QAOA execution mode from ``PG_PURR_QAOA_MODE`` (default
    ``variational``). Unknown values raise rather than silently
    selecting the slow variational path.
    """
    mode = os.environ.get("PG_PURR_QAOA_MODE") or "variational"
    if mode not in _VALID_MODES:
        raise ValueError(f"PG_PURR_QAOA_MODE must be one of {_VALID_MODES}, got {mode!r}")
    return mode


def _resolve_max_iter() -> int:
    """COBYLA iteration cap from ``PG_PURR_QAOA_MAX_ITER`` (default 80).

    Lower values cut the QPU jobs per plan call; applies to
    ``variational`` mode only.
    """
    raw = os.environ.get("PG_PURR_QAOA_MAX_ITER")
    if not raw:
        return _DEFAULT_MAX_ITER
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"PG_PURR_QAOA_MAX_ITER must be an integer, got {raw!r}") from None


def _build_ibm_runtime(num_qubits: int, default_shots: int) -> tuple[Any, Any]:
    """Return ``(sampler, pass_manager)`` targeting an IBM Quantum
    backend, or ``(None, None)`` if ``QISKIT_IBM_TOKEN`` is unset.

    Raised exceptions from `qiskit-ibm-runtime` (auth failure, no
    matching backend, network error) propagate to the caller — a
    silent fallback to the simulator would mask misconfiguration
    of an explicit opt-in.
    """
    token = os.environ.get("QISKIT_IBM_TOKEN")
    if not token:
        return None, None

    from qiskit_ibm_runtime import QiskitRuntimeService
    from qiskit_ibm_runtime import SamplerV2 as RuntimeSamplerV2

    service = QiskitRuntimeService(
        channel=os.environ.get("QISKIT_IBM_CHANNEL") or None,
        token=token,
        instance=os.environ.get("QISKIT_IBM_INSTANCE") or None,
    )
    backend = service.least_busy(min_num_qubits=num_qubits, operational=True)
    sampler = RuntimeSamplerV2(mode=backend, options={"default_shots": default_shots})
    pass_manager = generate_preset_pass_manager(optimization_level=1, backend=backend)
    return sampler, pass_manager


def _one_hot_program(costs: list[float]) -> QuadraticProgram:
    """Build the one-hot QUBO ``minimise Σ c_i·x_i s.t. Σ x_i = 1``."""
    qp = QuadraticProgram(name="tree_selection")
    for i in range(len(costs)):
        qp.binary_var(name=f"x{i}")
    qp.minimize(linear={f"x{i}": float(costs[i]) for i in range(len(costs))})
    qp.linear_constraint(
        linear={f"x{i}": 1 for i in range(len(costs))},
        sense="==",
        rhs=1,
        name="one_hot",
    )
    return qp


def _transpiled_qaoa_ansatz(qp: QuadraticProgram, reps: int, pass_manager):
    """Return ``(qubo, isa_ansatz)`` for ``qp``.

    ``measure_all`` is applied to the logical ansatz *before*
    transpilation, so classical bit ``i`` maps to candidate ``i``
    regardless of how the transpiler lays the circuit onto the device —
    measurements are decoded without a transpiler-layout lookup.
    """
    qubo = QuadraticProgramToQubo().convert(qp)
    cost_operator, _ = qubo.to_ising()
    ansatz = QAOAAnsatz(cost_operator, reps=reps)
    ansatz.measure_all()
    return qubo, pass_manager.run(ansatz)


def _logical_bits(measurement: int, k: int) -> list[int]:
    """Decode a measurement integer into K candidate bits."""
    return [(measurement >> i) & 1 for i in range(k)]


def _lowest_cost_feasible(
    counts: dict[int, int],
    costs: list[float],
    k: int,
    current: tuple[int, float] | None = None,
) -> tuple[int, float] | None:
    """Return ``(index, cost)`` of the lowest-cost feasible (one-hot)
    bitstring in ``counts``, never worse than ``current``.

    ``None`` is returned only when ``counts`` holds no one-hot bitstring
    and ``current`` was ``None`` — the caller then falls back to
    classical ``argmin``.
    """
    best = current
    for measurement in counts:
        bits = _logical_bits(measurement, k)
        if sum(bits) == 1:
            index = bits.index(1)
            if best is None or costs[index] < best[1]:
                best = (index, costs[index])
    return best


def _solve_qaoa_hardware(
    qp: QuadraticProgram,
    candidates: list[T],
    costs: list[float],
    sampler,
    pass_manager,
    reps: int = 2,
    max_iter: int = 80,
) -> T:
    """Select a candidate by running variational QAOA on an IBM backend.

    The diagonal cost Hamiltonian lets each energy be estimated from
    sampled bitstrings alone (no observable submitted), avoiding the
    physical-vs-logical width mismatch that breaks
    ``MinimumEigenOptimizer`` on transpiled circuits. The lowest-cost
    feasible (one-hot) bitstring seen across the loop is returned;
    classical ``argmin`` is the fallback only if no feasible bitstring
    is ever sampled.
    """
    qubo, isa_ansatz = _transpiled_qaoa_ansatz(qp, reps, pass_manager)

    k = len(candidates)
    best: tuple[int, float] | None = None

    def energy(params: Sequence[float]) -> float:
        nonlocal best
        counts = (
            sampler.run([(isa_ansatz.assign_parameters(params),)])
            .result()[0]
            .data.meas.get_int_counts()
        )
        best = _lowest_cost_feasible(counts, costs, k, best)
        shots = sum(counts.values())
        return sum(
            (count / shots) * qubo.objective.evaluate(_logical_bits(measurement, k))
            for measurement, count in counts.items()
        )

    optimized = COBYLA(maxiter=max_iter).minimize(energy, x0=[0.5] * (2 * reps))
    best = _lowest_cost_feasible(
        sampler.run([(isa_ansatz.assign_parameters(optimized.x),)])
        .result()[0]
        .data.meas.get_int_counts(),
        costs,
        k,
        best,
    )

    chosen = best[0] if best is not None else min(range(k), key=lambda i: costs[i])
    return candidates[chosen]


def _solve_qaoa_fixed_angle(
    qp: QuadraticProgram,
    candidates: list[T],
    costs: list[float],
    sampler,
    pass_manager,
    reps: int = 1,
    shots: int = _FIXED_ANGLE_SHOTS,
) -> T:
    """Select a candidate from a single fixed-angle QAOA execution.

    Runs one circuit — exactly one QPU job (one queue wait). The angles
    are not optimised, so the choice is the lowest-cost feasible
    (one-hot) bitstring sampled; for K ≤ 16 with enough shots the
    optimum is reliably present. Classical ``argmin`` is the fallback if
    no feasible bitstring is sampled. ``reps`` defaults to 1: without a
    variational loop, extra depth only adds gates and noise.
    """
    _, isa_ansatz = _transpiled_qaoa_ansatz(qp, reps, pass_manager)

    k = len(candidates)
    counts = (
        sampler.run([(isa_ansatz.assign_parameters([0.5] * (2 * reps)),)], shots=shots)
        .result()[0]
        .data.meas.get_int_counts()
    )
    best = _lowest_cost_feasible(counts, costs, k)

    chosen = best[0] if best is not None else min(range(k), key=lambda i: costs[i])
    return candidates[chosen]


def pick(
    candidates: list[T],
    costs: list[float],
    seed: int = 42,
    default_shots: int = 2048,
    reps: int = 2,
    max_iter: int | None = None,
) -> T:
    """Return the candidate selected by QAOA on the one-hot QUBO.

    Args:
        candidates: K ≥ 1 items to select among.
        costs: K floats; lower is preferred. Must have the same
            length as ``candidates``.
        seed: SamplerV2 RNG seed. Honoured by the AerSimulator
            path; ignored on real hardware (shot noise).
        default_shots: Number of measurement shots per evaluation.
        reps: QAOA layer count (``p`` in the paper). Variational mode
            only; ``fixed_angle`` mode always uses a single layer.
        max_iter: COBYLA iteration cap; when ``None``, read from
            ``PG_PURR_QAOA_MAX_ITER`` (default 80). Variational mode only.

    Returns:
        The candidate at the chosen index.

    A single candidate is returned without invoking the backend.
    """
    if len(candidates) != len(costs):
        raise ValueError("candidates and costs must have the same length")
    if not candidates:
        raise ValueError("candidates must be non-empty")
    if len(candidates) == 1:
        return candidates[0]

    qp = _one_hot_program(costs)

    sampler, pass_manager = _build_ibm_runtime(len(candidates), default_shots)
    on_hardware = sampler is not None
    if not on_hardware:
        # Local AerSimulator path: deterministic under a fixed seed.
        sampler = SamplerV2(seed=seed, default_shots=default_shots)
        pass_manager = generate_preset_pass_manager(optimization_level=1, backend=AerSimulator())

    if _resolve_mode() == "fixed_angle":
        return _solve_qaoa_fixed_angle(qp, candidates, costs, sampler, pass_manager)

    iterations = _resolve_max_iter() if max_iter is None else max_iter
    if on_hardware:
        return _solve_qaoa_hardware(
            qp, candidates, costs, sampler, pass_manager, reps=reps, max_iter=iterations
        )

    qaoa = QAOA(
        sampler=sampler,
        optimizer=COBYLA(maxiter=iterations),
        reps=reps,
        initial_point=[0.5] * (2 * reps),
        transpiler=pass_manager,
    )
    result = MinimumEigenOptimizer(qaoa).solve(qp)

    # Highest assignment wins; ties break toward lower cost.
    chosen = max(
        range(len(candidates)),
        key=lambda i: (float(result.x[i]), -costs[i]),
    )
    return candidates[chosen]
