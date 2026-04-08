"""Unit tests for the QUBO builder."""

import math

import dimod

from pg_purr.planner.explain_parser import JoinGraph
from pg_purr.planner.qubo_builder import DEFAULT_PENALTY_SCALE, build_qubo


def _make_join_graph(n_tables: int) -> JoinGraph:
    tables = [f"t{i}" for i in range(n_tables)]
    row_counts = {t: (i + 1) * 100 for i, t in enumerate(tables)}
    costs = {}
    for i, t1 in enumerate(tables):
        for j, t2 in enumerate(tables):
            if i != j:
                costs[(t1, t2)] = row_counts[t1] * row_counts[t2]
    return JoinGraph(tables=tables, row_counts=row_counts, costs=costs)


def _zero_cost_graph(n_tables: int) -> JoinGraph:
    tables = [f"t{i}" for i in range(n_tables)]
    row_counts = dict.fromkeys(tables, 0.0)
    costs = {(t1, t2): 0.0 for i, t1 in enumerate(tables) for j, t2 in enumerate(tables) if i != j}
    return JoinGraph(tables=tables, row_counts=row_counts, costs=costs)


def test_build_qubo_returns_bqm():
    bqm = build_qubo(_make_join_graph(4))
    assert isinstance(bqm, dimod.BinaryQuadraticModel)


def test_qubo_has_correct_variable_count():
    bqm = build_qubo(_make_join_graph(4))
    assert len(bqm.variables) == 16


def test_qubo_variable_names():
    bqm = build_qubo(_make_join_graph(3))
    expected_vars = {f"x_{i}_{t}" for i in range(3) for t in range(3)}
    assert set(bqm.variables) == expected_vars


def test_qubo_is_binary():
    bqm = build_qubo(_make_join_graph(3))
    assert bqm.vartype == dimod.BINARY


def test_penalty_nonzero_when_all_costs_zero():
    bqm = build_qubo(_zero_cost_graph(2))
    # When all pairwise costs are zero, A falls back to scale_factor.
    # Constraint penalty coefficient between x_0_0 and x_1_0 is 2 * A.
    coeff = bqm.get_quadratic("x_0_0", "x_1_0")
    assert coeff == 2.0 * DEFAULT_PENALTY_SCALE
    assert not any(math.isnan(v) for v in bqm.linear.values())


def test_scale_factor_override():
    bqm_default = build_qubo(_zero_cost_graph(2))
    bqm_scaled = build_qubo(_zero_cost_graph(2), scale_factor=5.0)
    default = bqm_default.get_quadratic("x_0_0", "x_1_0")
    scaled = bqm_scaled.get_quadratic("x_0_0", "x_1_0")
    assert scaled == default * (5.0 / DEFAULT_PENALTY_SCALE)
