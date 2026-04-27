"""Tests for linearizer.best_order."""

from pg_purr.planner.cost_model import true_left_deep_cost
from pg_purr.planner.explain_parser import JoinGraph
from pg_purr.planner.linearizer import best_order
from pg_purr.planner.predicate_graph import is_connected_order


def _graph(rows: dict[str, float]) -> JoinGraph:
    return JoinGraph(tables=list(rows.keys()), row_counts=rows)


def test_chain_tree_returns_connected_order() -> None:
    tree = frozenset({frozenset({"a", "b"}), frozenset({"b", "c"})})
    edges = set(tree)
    g = _graph({"a": 100, "b": 100, "c": 100})
    order = best_order(tree, g, edges, true_left_deep_cost)
    assert is_connected_order(order, edges)
    assert set(order) == {"a", "b", "c"}


def test_star_tree_starts_with_small_leaf() -> None:
    tree = frozenset(
        {
            frozenset({"h", "a"}),
            frozenset({"h", "b"}),
            frozenset({"h", "c"}),
        }
    )
    edges = set(tree)
    g = _graph({"h": 1000, "a": 10, "b": 100, "c": 1000})
    order = best_order(tree, g, edges, true_left_deep_cost)
    assert is_connected_order(order, edges)
    assert order[0] == "a"


def test_long_path_preserves_connectivity() -> None:
    tree = frozenset(
        {
            frozenset({"a", "b"}),
            frozenset({"b", "c"}),
            frozenset({"c", "d"}),
            frozenset({"d", "e"}),
        }
    )
    edges = set(tree)
    g = _graph({"a": 10, "b": 20, "c": 30, "d": 40, "e": 50})
    order = best_order(tree, g, edges, true_left_deep_cost)
    assert is_connected_order(order, edges)
    assert set(order) == {"a", "b", "c", "d", "e"}


def test_single_vertex_graph_returns_singleton() -> None:
    g = _graph({"a": 5})
    order = best_order(frozenset(), g, set(), true_left_deep_cost)
    assert order == ["a"]


def test_branching_tree_outputs_connected_order() -> None:
    # Caterpillar: a-b-c with leaves x-b and y-c.
    tree = frozenset(
        {
            frozenset({"a", "b"}),
            frozenset({"b", "c"}),
            frozenset({"b", "x"}),
            frozenset({"c", "y"}),
        }
    )
    edges = set(tree)
    g = _graph({"a": 10, "b": 20, "c": 30, "x": 5, "y": 7})
    order = best_order(tree, g, edges, true_left_deep_cost)
    assert is_connected_order(order, edges)
    assert set(order) == {"a", "b", "c", "x", "y"}


def test_deterministic_output() -> None:
    tree = frozenset(
        {
            frozenset({"a", "b"}),
            frozenset({"b", "c"}),
            frozenset({"a", "c"}),  # actually a tree must not have cycles;
        }
    )
    # This is not a valid tree for the linearizer's contract, but
    # nx.minimum_spanning_tree never emits one, so we don't test
    # cycle inputs. Re-using a real tree:
    tree = frozenset({frozenset({"a", "b"}), frozenset({"b", "c"})})
    edges = set(tree)
    g = _graph({"a": 10, "b": 20, "c": 30})
    out_1 = best_order(tree, g, edges, true_left_deep_cost)
    out_2 = best_order(tree, g, edges, true_left_deep_cost)
    assert out_1 == out_2
