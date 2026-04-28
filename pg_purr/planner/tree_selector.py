"""Quantum candidate selector via QAOA.

Builds a one-hot QUBO over K candidate spanning trees:

    minimise   Σ_i c_i · x_i
    subject to Σ_i x_i = 1
    x_i ∈ {0, 1}

and solves it with QAOA driven by `qiskit_optimization`'s
`MinimumEigenOptimizer`. The chosen candidate is the index whose
binary variable is set in the optimum bitstring.

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
"""

from __future__ import annotations

import os
from typing import TypeVar

from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from qiskit_algorithms import QAOA
from qiskit_algorithms.optimizers import COBYLA
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer

T = TypeVar("T")


def _build_ibm_runtime(num_qubits: int, default_shots: int):
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


def pick(
    candidates: list[T],
    costs: list[float],
    seed: int = 42,
    default_shots: int = 2048,
    reps: int = 2,
    max_iter: int = 80,
) -> T:
    """Return the candidate selected by QAOA on the one-hot QUBO.

    Args:
        candidates: K ≥ 1 items to select among.
        costs: K floats; lower is preferred. Must have the same
            length as ``candidates``.
        seed: SamplerV2 RNG seed. Honoured by the AerSimulator
            path; ignored on real hardware (shot noise).
        default_shots: Number of measurement shots per evaluation.
        reps: QAOA layer count (``p`` in the paper).
        max_iter: COBYLA iteration cap.

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

    qp = QuadraticProgram(name="tree_selection")
    for i in range(len(candidates)):
        qp.binary_var(name=f"x{i}")
    qp.minimize(linear={f"x{i}": float(costs[i]) for i in range(len(candidates))})
    qp.linear_constraint(
        linear={f"x{i}": 1 for i in range(len(candidates))},
        sense="==",
        rhs=1,
        name="one_hot",
    )

    sampler, pass_manager = _build_ibm_runtime(len(candidates), default_shots)
    if sampler is None:
        sampler = SamplerV2(seed=seed, default_shots=default_shots)
        pass_manager = generate_preset_pass_manager(optimization_level=1, backend=AerSimulator())
    qaoa = QAOA(
        sampler=sampler,
        optimizer=COBYLA(maxiter=max_iter),
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
