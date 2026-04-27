"""Shared planner pipeline used by the SQL-callable functions.

`quantum_query_plan` and `quantum_query_rewrite` both run the same
validate → EXPLAIN → predicate graph → spanning trees → quantum
selection → DFS linearisation pipeline; only the post-step differs.

Connectivity of every prefix in the returned order is guaranteed
by the spanning-tree linearisation theorem and verified by an
output-side assertion.
"""

from __future__ import annotations

import json

from pg_purr.planner.cost_model import edge_weights, true_left_deep_cost
from pg_purr.planner.explain_parser import parse_explain_json
from pg_purr.planner.linearizer import best_order
from pg_purr.planner.predicate_graph import extract_join_edges, is_connected_order
from pg_purr.planner.query_validator import (
    UnsupportedQueryError,
    validate_and_build_explain_sql,
)
from pg_purr.planner.spanning_trees import candidates as spanning_tree_candidates
from pg_purr.planner.tree_selector import pick as pick_tree

_DEFAULT_K = 16
_DEFAULT_SEED = 42
_DEFAULT_SHOTS = 2048


def compute_optimal_order(plpy, query: str) -> tuple[list[str], dict[str, float]]:
    """Return ``(optimal_order, row_counts)`` for ``query``.

    ``plpy`` is the PL/Python module proxy injected into the calling
    function body. ``optimal_order`` is a list of table aliases in
    the order selected by the planner; ``row_counts`` maps each
    alias to its EXPLAIN ``Plan Rows`` estimate. Trivial inputs
    short-circuit:

    * no tables   → ``([], {})``
    * one table   → ``([t], {t: <rows>})``
    """
    try:
        explain_sql = validate_and_build_explain_sql(plpy, query)
    except UnsupportedQueryError as e:
        plpy.error(f"pg_purr: rejected query: {e}")

    explain_result = plpy.execute(explain_sql)
    explain_json = json.loads(explain_result[0]["QUERY PLAN"])
    join_graph = parse_explain_json(explain_json)

    if not join_graph.tables:
        return [], {}
    if len(join_graph.tables) < 2:
        return list(join_graph.tables), dict(join_graph.row_counts)

    edges = extract_join_edges(query)
    join_graph.edges = edges
    if not edges:
        plpy.error("pg_purr: rejected query: no join predicates found between tables")

    weights = edge_weights(join_graph, edges)
    trees = spanning_tree_candidates(edges, weights, k=_DEFAULT_K, seed=_DEFAULT_SEED)
    costs = [
        true_left_deep_cost(
            best_order(tree, join_graph, edges, true_left_deep_cost),
            join_graph,
            edges,
        )
        for tree in trees
    ]
    chosen_tree = pick_tree(trees, costs, seed=_DEFAULT_SEED, default_shots=_DEFAULT_SHOTS)
    optimal_order = best_order(chosen_tree, join_graph, edges, true_left_deep_cost)

    if not is_connected_order(optimal_order, edges):
        plpy.error("pg_purr: internal error: planner produced a disconnected order")

    return optimal_order, dict(join_graph.row_counts)
