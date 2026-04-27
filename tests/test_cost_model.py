"""Tests for cost_model.edge_weights and true_left_deep_cost."""

import math

from pg_purr.planner.cost_model import edge_weights, true_left_deep_cost
from pg_purr.planner.explain_parser import JoinGraph


def _graph(rows: dict[str, float]) -> JoinGraph:
    return JoinGraph(tables=list(rows.keys()), row_counts=rows)


def test_edge_weight_decreases_with_smaller_relations() -> None:
    big = _graph({"a": 1000, "b": 100})
    small = _graph({"a": 10, "b": 5})
    edges = {frozenset({"a", "b"})}
    w_big = edge_weights(big, edges)[frozenset({"a", "b"})]
    w_small = edge_weights(small, edges)[frozenset({"a", "b"})]
    assert w_small < w_big


def test_edge_weight_is_log_scale() -> None:
    g = _graph({"a": 100, "b": 100})
    edges = {frozenset({"a", "b"})}
    w = edge_weights(g, edges)[frozenset({"a", "b"})]
    # |R_a| * |R_b| * sel = 100 * 100 / 100 = 100; log(100) ≈ 4.605
    assert math.isclose(w, math.log(100), rel_tol=1e-6)


def test_edge_weight_handles_missing_row_count() -> None:
    g = _graph({"a": 10})  # b missing
    edges = {frozenset({"a", "b"})}
    w = edge_weights(g, edges)[frozenset({"a", "b"})]
    # b falls back to 1; |R_a| * 1 * 1/10 = 1 ⇒ log(1) = 0
    assert math.isclose(w, 0.0, abs_tol=1e-9)


def test_left_deep_cost_prefers_smaller_intermediate() -> None:
    g = _graph({"a": 10, "b": 100, "c": 1000})
    edges = {frozenset({"a", "b"}), frozenset({"b", "c"})}
    cost_small_first = true_left_deep_cost(["a", "b", "c"], g, edges)
    cost_large_first = true_left_deep_cost(["c", "b", "a"], g, edges)
    assert cost_small_first <= cost_large_first


def test_disconnected_step_inflates_cost() -> None:
    g = _graph({"a": 10, "b": 10, "c": 10})
    only_a_b = {frozenset({"a", "b"})}
    connected = true_left_deep_cost(["a", "b"], g, only_a_b)
    cartesian = true_left_deep_cost(["a", "c"], g, only_a_b)
    assert cartesian > connected


def test_single_relation_is_zero_cost() -> None:
    g = _graph({"a": 5})
    assert true_left_deep_cost(["a"], g, set()) == 0.0


def test_empty_order_is_zero_cost() -> None:
    assert true_left_deep_cost([], _graph({}), set()) == 0.0
