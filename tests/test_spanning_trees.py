"""Tests for spanning_trees.candidates."""

import networkx as nx

from pg_purr.planner.spanning_trees import candidates


def _vertices(edges: set[frozenset[str]]) -> set[str]:
    out: set[str] = set()
    for edge in edges:
        out.update(edge)
    return out


def _is_spanning_tree(tree: frozenset[frozenset[str]], vertices: set[str]) -> bool:
    graph = nx.Graph()
    graph.add_nodes_from(vertices)
    for edge in tree:
        u, v = sorted(edge)
        graph.add_edge(u, v)
    return nx.is_tree(graph) and set(graph.nodes()) == vertices


def test_chain_graph_yields_single_tree() -> None:
    edges = {frozenset({"a", "b"}), frozenset({"b", "c"})}
    weights = {e: 1.0 for e in edges}
    out = candidates(edges, weights, k=8, seed=42)
    assert len(out) == 1
    assert _is_spanning_tree(out[0], _vertices(edges))


def test_triangle_yields_multiple_trees() -> None:
    edges = {
        frozenset({"a", "b"}),
        frozenset({"b", "c"}),
        frozenset({"a", "c"}),
    }
    weights = {e: 1.0 for e in edges}
    out = candidates(edges, weights, k=8, seed=42, perturbation=0.5)
    assert len(out) > 1
    assert len(out) <= 3
    vertices = _vertices(edges)
    for tree in out:
        assert _is_spanning_tree(tree, vertices)


def test_complete_graph_outputs_are_valid_spanning_trees() -> None:
    vertices = {"a", "b", "c", "d"}
    edges = {frozenset({u, v}) for u in vertices for v in vertices if u < v}
    weights = {e: 1.0 for e in edges}
    out = candidates(edges, weights, k=12, seed=7, perturbation=0.4)
    assert len(out) >= 1
    for tree in out:
        assert _is_spanning_tree(tree, vertices)


def test_deterministic_with_fixed_seed() -> None:
    edges = {
        frozenset({"a", "b"}),
        frozenset({"b", "c"}),
        frozenset({"a", "c"}),
    }
    weights = {e: 1.0 for e in edges}
    out_1 = candidates(edges, weights, k=8, seed=42, perturbation=0.5)
    out_2 = candidates(edges, weights, k=8, seed=42, perturbation=0.5)
    assert out_1 == out_2


def test_outputs_are_deduplicated() -> None:
    edges = {
        frozenset({"a", "b"}),
        frozenset({"b", "c"}),
        frozenset({"a", "c"}),
    }
    weights = {e: 1.0 for e in edges}
    out = candidates(edges, weights, k=16, seed=42, perturbation=0.5)
    assert len(set(out)) == len(out)


def test_low_weight_edges_appear_more_often() -> None:
    # Triangle where one edge is much cheaper. The MST should
    # include it in every candidate when perturbation is moderate.
    cheap = frozenset({"a", "b"})
    edges = {cheap, frozenset({"b", "c"}), frozenset({"a", "c"})}
    weights = {cheap: 0.1, frozenset({"b", "c"}): 5.0, frozenset({"a", "c"}): 5.0}
    out = candidates(edges, weights, k=8, seed=11, perturbation=0.3)
    assert all(cheap in tree for tree in out)
