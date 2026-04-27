"""Quantum candidate selector via QAOA on the local AerSimulator.

Builds a one-hot QUBO over K candidate spanning trees:

    minimise   Σ_i c_i · x_i
    subject to Σ_i x_i = 1
    x_i ∈ {0, 1}

and solves it with QAOA driven by `qiskit_optimization`'s
`MinimumEigenOptimizer`. The chosen candidate is the index whose
binary variable is set in the optimum bitstring.

With K ≤ 16 the QAOA circuit fits comfortably in state-vector
simulation on a developer laptop. Determinism comes from a fixed
SamplerV2 seed and shot count, COBYLA's gradient-free outer loop,
and an explicit (constant) ``initial_point`` passed to QAOA — when
``initial_point`` is left ``None`` QAOA samples a random point on
each construction, breaking reproducibility.
"""

from __future__ import annotations

from typing import TypeVar

from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from qiskit_algorithms import QAOA
from qiskit_algorithms.optimizers import COBYLA
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer

T = TypeVar("T")


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
        seed: SamplerV2 RNG seed.
        default_shots: Number of measurement shots per evaluation.
        reps: QAOA layer count (``p`` in the paper).
        max_iter: COBYLA iteration cap.

    Returns:
        The candidate at the chosen index.

    A single candidate is returned without invoking the simulator.
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
