"""Edge-perturbed minimum spanning tree candidate generator.

Given a connected predicate graph G with edge weights `w_e`, emit
up to K distinct spanning trees by adding small Gaussian noise to
each weight and running NetworkX's MST per draw. The output feeds
the quantum tree selector, which picks the lowest-cost tree under
the true left-deep cost model.

Determinism: seeded via `numpy.random.default_rng(seed)`.
"""

from __future__ import annotations

import networkx as nx
import numpy as np


def candidates(
    edges: set[frozenset[str]],
    weights: dict[frozenset[str], float],
    k: int = 16,
    seed: int = 0,
    perturbation: float = 0.3,
) -> list[frozenset[frozenset[str]]]:
    """Return up to `k` distinct spanning trees of the predicate graph.

    Each candidate is the edge set of a spanning tree, expressed as
    a `frozenset[frozenset[str]]` so callers can compare for
    equality. Vertices are inferred from `edges`; callers must
    ensure the graph is connected.

    Args:
        edges: Predicate edges.
        weights: Edge weights (typically from
            `cost_model.edge_weights`).
        k: Maximum candidates to emit.
        seed: RNG seed for reproducibility.
        perturbation: Std of additive Gaussian noise applied per
            edge, per draw. Larger values increase diversity.

    Returns:
        Deduplicated list of candidate spanning-tree edge sets.
        Length ≤ k, always non-empty for a connected graph.
    """
    rng = np.random.default_rng(seed)
    seen: set[frozenset[frozenset[str]]] = set()
    out: list[frozenset[frozenset[str]]] = []
    attempts = max(k * 4, k + 1)
    for _ in range(attempts):
        if len(out) >= k:
            break
        graph = nx.Graph()
        for edge in edges:
            u, v = sorted(edge)
            base = weights.get(edge, 0.0)
            graph.add_edge(u, v, weight=base + rng.normal(0.0, perturbation))
        tree = nx.minimum_spanning_tree(graph, weight="weight")
        tree_edges = frozenset(frozenset({u, v}) for u, v in tree.edges())
        if tree_edges not in seen:
            seen.add(tree_edges)
            out.append(tree_edges)
    return out
