"""Property tests for the planner's structural feasibility guarantee.

The spanning-tree linearisation theorem asserts that any DFS
pre-order of a spanning tree T of G is a connected order in G.
This module generates random connected graphs, runs the planner's
spanning-tree + linearisation steps, and asserts the output is
connected — every time, regardless of the cost-side decisions.

Hypothesis is bounded to small graphs and a modest example budget;
the QAOA tree-selection step is not exercised here (it is covered
by `test_tree_selector.py`). The intent is to drive a wide variety
of structural shapes through the cheap classical core.
"""

from __future__ import annotations

import networkx as nx
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pg_purr.planner.cost_model import edge_weights, true_left_deep_cost
from pg_purr.planner.explain_parser import JoinGraph
from pg_purr.planner.linearizer import best_order
from pg_purr.planner.predicate_graph import is_connected_order
from pg_purr.planner.spanning_trees import candidates


@st.composite
def connected_graphs(
    draw: st.DrawFn, min_n: int = 3, max_n: int = 12
) -> tuple[set[str], set[frozenset[str]]]:
    n = draw(st.integers(min_value=min_n, max_value=max_n))
    p = draw(st.floats(min_value=0.3, max_value=0.85))
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    graph = nx.gnp_random_graph(n, p, seed=seed)
    if not nx.is_connected(graph):
        components = list(nx.connected_components(graph))
        for i in range(len(components) - 1):
            u = next(iter(components[i]))
            v = next(iter(components[i + 1]))
            graph.add_edge(u, v)
    name = {i: f"v{i}" for i in range(n)}
    vertices = set(name.values())
    edges = {frozenset({name[u], name[v]}) for u, v in graph.edges()}
    return vertices, edges


@given(connected_graphs())
@settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_every_spanning_tree_linearises_to_connected_order(
    graph: tuple[set[str], set[frozenset[str]]],
) -> None:
    vertices, edges = graph
    rows = {v: 100.0 + i for i, v in enumerate(sorted(vertices))}
    jg = JoinGraph(tables=sorted(vertices), row_counts=rows, edges=edges)

    weights = edge_weights(jg, edges)
    trees = candidates(edges, weights, k=4, seed=42)
    assert trees, "candidates must always produce at least one spanning tree"

    for tree in trees:
        order = best_order(tree, jg, edges, true_left_deep_cost)
        assert set(order) == vertices
        assert is_connected_order(order, edges)
