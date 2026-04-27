"""DFS linearisation of a spanning tree into a connected join order.

The spanning-tree linearisation theorem: any DFS pre-order
traversal of a spanning tree T of G yields a permutation whose
every prefix induces a connected subgraph of G. This module
iterates over every vertex as the DFS root, scores each pre-order
under the supplied cost function, and returns the lowest-cost
permutation.

The output is a connected order by construction, regardless of
the cost function — feasibility is structural, not searched.
"""

from __future__ import annotations

from collections.abc import Callable

import networkx as nx

from pg_purr.planner.explain_parser import JoinGraph

CostFn = Callable[[list[str], JoinGraph, set[frozenset[str]]], float]


def best_order(
    tree_edges: frozenset[frozenset[str]],
    graph: JoinGraph,
    edges: set[frozenset[str]],
    cost_fn: CostFn,
) -> list[str]:
    """Return the lowest-cost DFS pre-order of `tree_edges`.

    Args:
        tree_edges: Edge set of a spanning tree of the predicate
            graph. Vertices are inferred from the edges.
        graph: Source of row-count estimates for `cost_fn`.
        edges: The full predicate-graph edge set used by `cost_fn`
            to credit selectivities at every step.
        cost_fn: Permutation scorer, lower is better.

    Returns:
        A permutation of the tree's vertices forming a connected
        order in `edges`. For a single-vertex graph (tree empty),
        returns the lone vertex from `graph.tables`.
    """
    tree = nx.Graph()
    vertices: set[str] = set()
    for edge in tree_edges:
        u, v = sorted(edge)
        tree.add_edge(u, v)
        vertices.update(edge)
    if not tree_edges:
        vertices = set(graph.tables)
        for v in vertices:
            tree.add_node(v)
    if len(vertices) <= 1:
        return list(vertices)

    roots = sorted(vertices)
    best = list(nx.dfs_preorder_nodes(tree, source=roots[0], sort_neighbors=sorted))
    best_cost = cost_fn(best, graph, edges)
    for root in roots[1:]:
        order = list(nx.dfs_preorder_nodes(tree, source=root, sort_neighbors=sorted))
        cost = cost_fn(order, graph, edges)
        if cost < best_cost:
            best_cost = cost
            best = order
    return best
