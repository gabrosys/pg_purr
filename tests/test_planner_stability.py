"""17-table retail-shape stability test for the planner core.

The retail-schema predicate graph has 17 vertices with multiple
leaves and degree-2 hubs — a structural shape that stresses the
connectivity-preservation guarantee. Run the planner core (no PG,
no plpy) under five different seeds and assert every run returns a
connected order. This is a unit-level proxy for the full
integration acceptance test.
"""

from __future__ import annotations

import pytest

from pg_purr.planner.cost_model import edge_weights, true_left_deep_cost
from pg_purr.planner.explain_parser import JoinGraph
from pg_purr.planner.linearizer import best_order
from pg_purr.planner.predicate_graph import is_connected_order
from pg_purr.planner.spanning_trees import candidates as spanning_tree_candidates
from pg_purr.planner.tree_selector import pick as pick_tree

# 17-table retail-schema predicate graph.
_RETAIL_EDGES = frozenset(
    {
        frozenset({"s", "p"}),
        frozenset({"p", "c"}),
        frozenset({"c", "pc"}),
        frozenset({"inv", "p"}),
        frozenset({"w", "inv"}),
        frozenset({"oi", "p"}),
        frozenset({"o", "oi"}),
        frozenset({"cu", "o"}),
        frozenset({"a", "o"}),
        frozenset({"pay", "o"}),
        frozenset({"pm", "pay"}),
        frozenset({"sh", "o"}),
        frozenset({"si", "sh"}),
        frozenset({"si", "oi"}),
        frozenset({"r", "p"}),
        frozenset({"r", "cu"}),
        frozenset({"pr", "c"}),
        frozenset({"promo", "pr"}),
    }
)


def _retail_graph() -> JoinGraph:
    vertices = sorted({v for edge in _RETAIL_EDGES for v in edge})
    rows = {v: 1000.0 + 100.0 * i for i, v in enumerate(vertices)}
    return JoinGraph(tables=vertices, row_counts=rows, edges=set(_RETAIL_EDGES))


def _run_planner_core(seed: int) -> list[str]:
    graph = _retail_graph()
    edges = set(_RETAIL_EDGES)
    weights = edge_weights(graph, edges)
    trees = spanning_tree_candidates(edges, weights, k=8, seed=seed)
    costs = [
        true_left_deep_cost(
            best_order(tree, graph, edges, true_left_deep_cost),
            graph,
            edges,
        )
        for tree in trees
    ]
    chosen = pick_tree(trees, costs, seed=seed, default_shots=2048)
    return best_order(chosen, graph, edges, true_left_deep_cost)


def test_retail_graph_has_seventeen_vertices() -> None:
    vertices = {v for edge in _RETAIL_EDGES for v in edge}
    assert len(vertices) == 17


@pytest.mark.parametrize("seed", [0, 1, 42, 1337, 2024])
def test_planner_returns_connected_order_for_retail(seed: int) -> None:
    order = _run_planner_core(seed)
    edges = set(_RETAIL_EDGES)
    assert len(order) == 17
    assert set(order) == {v for edge in _RETAIL_EDGES for v in edge}
    assert is_connected_order(order, edges)


def test_planner_is_deterministic_for_fixed_seed() -> None:
    a = _run_planner_core(42)
    b = _run_planner_core(42)
    assert a == b
