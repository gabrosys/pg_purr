"""Extract the join-predicate graph from a SQL query.

Produces the unordered set of alias-pairs that the input query
connects via a boolean predicate (in any `ON` clause or in
`WHERE`). The planner uses this graph for two things: (1) building
candidate spanning trees whose DFS linearisations are guaranteed
to be connected join orders; (2) the output-side connectivity
guard that refuses any order that would force a Cartesian product
under `join_collapse_limit = 1`.
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

_DIALECT = "postgres"


def _walk_predicate_leaves(node: exp.Expression):
    """Yield each leaf boolean predicate, descending through AND / OR / NOT."""
    if isinstance(node, exp.And | exp.Or):
        yield from _walk_predicate_leaves(node.this)
        yield from _walk_predicate_leaves(node.expression)
    elif isinstance(node, exp.Not):
        yield from _walk_predicate_leaves(node.this)
    else:
        yield node


def _edges_from_predicate(predicate: exp.Expression, edges: set[frozenset[str]]) -> None:
    for leaf in _walk_predicate_leaves(predicate):
        tables = {col.table for col in leaf.find_all(exp.Column) if col.table}
        if len(tables) < 2:
            continue
        ordered = sorted(tables)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                edges.add(frozenset((ordered[i], ordered[j])))


def is_connected_order(order: list[str], edges: set[frozenset[str]]) -> bool:
    """Return True iff ``order`` is a connected join order over ``edges``.

    "Connected" means: at every step ≥ 1, the table introduced
    shares a predicate edge with at least one table already in
    scope. Any disconnected step would, under
    `join_collapse_limit = 1`, force a Cartesian product, so the
    pipeline must refuse to produce or accept disconnected orders.
    """
    if len(order) < 2:
        return True
    visited: set[str] = {order[0]}
    for step in range(1, len(order)):
        new_table = order[step]
        if not any(frozenset((new_table, prior)) in edges for prior in visited):
            return False
        visited.add(new_table)
    return True


def extract_join_edges(query: str) -> set[frozenset[str]]:
    """Return the set of unordered alias-pairs joined by a predicate.

    Walks every ON clause and the WHERE clause. Each leaf predicate
    that references columns from two or more distinct table aliases
    contributes an edge between every pair of referenced aliases.

    Returns an empty set if the query cannot be parsed or is not a
    SELECT; the caller decides whether that condition is fatal.
    """
    try:
        parsed = sqlglot.parse_one(query, read=_DIALECT)
    except Exception:
        return set()
    if not isinstance(parsed, exp.Select):
        return set()

    edges: set[frozenset[str]] = set()
    for join in parsed.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            _edges_from_predicate(on, edges)
    where = parsed.args.get("where")
    if where is not None:
        _edges_from_predicate(where.this, edges)
    return edges
