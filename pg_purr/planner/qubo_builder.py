"""Build a QUBO (BinaryQuadraticModel) from a JoinGraph for quantum annealing."""

from __future__ import annotations

import dimod

from pg_purr.planner.explain_parser import JoinGraph

DEFAULT_PENALTY_SCALE = 2.0


def build_qubo(
    join_graph: JoinGraph,
    *,
    scale_factor: float = DEFAULT_PENALTY_SCALE,
) -> dimod.BinaryQuadraticModel:
    """Transform a JoinGraph into a BinaryQuadraticModel.

    Binary variables x_{i}_{t} = 1 means table i is processed at step t.

    Hamiltonian has three terms:
      - Constraint 1: each step t has exactly one table  (penalty A)
      - Constraint 2: each table i is in exactly one step (penalty A)
      - Objective: minimize sequential join cost           (weight B)

    A is floored at `scale_factor` so the permutation constraint still
    dominates the objective when every pairwise cost is zero.
    """
    n = len(join_graph.tables)
    bqm = dimod.BinaryQuadraticModel(vartype=dimod.BINARY)

    raw_max = max(join_graph.costs.values(), default=0.0) if join_graph.costs else 0.0
    A = max(raw_max, 1.0) * scale_factor
    B = 1.0
    denom = raw_max if raw_max > 0 else 1.0

    def var(i: int, t: int) -> str:
        return f"x_{i}_{t}"

    for i in range(n):
        for t in range(n):
            bqm.add_variable(var(i, t), 0.0)

    for t in range(n):
        for i in range(n):
            bqm.add_linear(var(i, t), -A)
            for j in range(i + 1, n):
                bqm.add_quadratic(var(i, t), var(j, t), 2.0 * A)

    for i in range(n):
        for t in range(n):
            bqm.add_linear(var(i, t), -A)
            for s in range(t + 1, n):
                bqm.add_quadratic(var(i, t), var(i, s), 2.0 * A)

    for t in range(n - 1):
        for i in range(n):
            for j in range(n):
                if i != j:
                    t1 = join_graph.tables[i]
                    t2 = join_graph.tables[j]
                    cost = join_graph.costs.get((t1, t2), 0.0)
                    normalized = cost / denom
                    bqm.add_quadratic(var(i, t), var(j, t + 1), B * normalized)

    return bqm
