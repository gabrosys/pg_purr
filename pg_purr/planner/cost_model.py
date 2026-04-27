"""Cost model for left-deep join orders.

Two functions:

- `edge_weights` returns `log(|R_u| * |R_v| * sel_e)` for each
  predicate edge. Spanning-tree candidate generation uses these
  weights to bias the MST search toward small-cardinality joins.

- `true_left_deep_cost` evaluates a complete permutation under a
  nested-loop model: it sums intermediate cardinalities, with the
  carry-forward cardinality discounted by the multiplicative
  selectivity of every connecting predicate at each step.

Both functions read row counts from the `JoinGraph` produced by
`explain_parser.parse_explain_json`. Finer-grained per-column
selectivity statistics are not yet wired in; the per-edge
selectivity falls back to `1 / max(|R_u|, |R_v|)`, which models a
uniform foreign-key join (roughly one matching row on the larger
side per row on the smaller side).
"""

from __future__ import annotations

import math

from pg_purr.planner.explain_parser import JoinGraph


def _selectivity(row_u: float, row_v: float) -> float:
    larger = max(row_u, row_v, 1.0)
    return 1.0 / larger


def edge_weights(graph: JoinGraph, edges: set[frozenset[str]]) -> dict[frozenset[str], float]:
    """Return `log(|R_u| * |R_v| * sel_e)` per edge.

    Lower weight ⇒ the join produces fewer rows ⇒ preferred by the
    spanning-tree selector. Missing or zero row counts fall back to
    1 so the log is well-defined.
    """
    weights: dict[frozenset[str], float] = {}
    for edge in edges:
        u, v = sorted(edge)
        ru = max(graph.row_counts.get(u, 0.0), 1.0)
        rv = max(graph.row_counts.get(v, 0.0), 1.0)
        sel = _selectivity(ru, rv)
        weights[edge] = math.log(ru * rv * sel)
    return weights


def true_left_deep_cost(order: list[str], graph: JoinGraph, edges: set[frozenset[str]]) -> float:
    """Sum of intermediate cardinalities for the left-deep chain.

    A step with no connecting predicate contributes a Cartesian
    product (`sel = 1`), inflating the running cardinality — which
    is exactly why disconnected orders cost so much in this model.
    """
    if len(order) < 2:
        return 0.0
    running = max(graph.row_counts.get(order[0], 0.0), 1.0)
    cost = 0.0
    for t in range(1, len(order)):
        new = order[t]
        new_rows = max(graph.row_counts.get(new, 0.0), 1.0)
        sel = 1.0
        for p in order[:t]:
            if frozenset({new, p}) in edges:
                rp = max(graph.row_counts.get(p, 0.0), 1.0)
                sel *= _selectivity(rp, new_rows)
        running = max(running * new_rows * sel, 1.0)
        cost += running
    return cost
