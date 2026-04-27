"""Validate and gate user-supplied SQL for the planner.

The planner accepts a narrow query shape:

* single SELECT statement, no embedded ``;``
* single FROM item that is a base table reference
* zero or more INNER JOINs over base tables
* no OUTER / NATURAL / USING / LATERAL / CROSS joins
* no CTEs (``WITH``)
* no subqueries in FROM (no derived tables)
* the predicate graph induced by the FROM/JOIN aliases must be
  connected — disconnected predicate graphs would force a
  Cartesian product under ``join_collapse_limit = 1``

``validate_supported_shape`` performs every check that does not
require a live PostgreSQL backend and raises
``UnsupportedQueryError`` on the first violation.
``validate_and_build_explain_sql`` runs that check, defers syntax
and catalogue validation to PG via ``plpy.prepare``, and returns
the EXPLAIN SQL string.
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

from pg_purr.planner.predicate_graph import extract_join_edges

_DIALECT = "postgres"


class UnsupportedQueryError(ValueError):
    """Raised when a query is rejected as unsafe to plan."""


def _alias_of(table: exp.Table) -> str:
    return table.alias or table.name


def _is_predicate_graph_connected(aliases: list[str], edges: set[frozenset[str]]) -> bool:
    if len(aliases) <= 1:
        return True
    neighbours: dict[str, set[str]] = {a: set() for a in aliases}
    for edge in edges:
        u, v = sorted(edge)
        if u in neighbours and v in neighbours:
            neighbours[u].add(v)
            neighbours[v].add(u)
    seen = {aliases[0]}
    queue = [aliases[0]]
    while queue:
        node = queue.pop()
        for nxt in neighbours[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen == set(aliases)


def validate_supported_shape(query: str) -> list[str]:
    """Raise on unsupported shapes; return the alias list otherwise.

    The returned aliases preserve their order in the FROM/JOIN
    chain. The pipeline short-circuits for ``len(aliases) < 2``.
    """
    stripped = query.strip()
    if not stripped:
        raise UnsupportedQueryError("empty query")
    if ";" in stripped:
        raise UnsupportedQueryError("query must not contain ';' (multi-statement not supported)")

    try:
        parsed = sqlglot.parse_one(stripped, read=_DIALECT)
    except sqlglot.errors.ParseError as e:
        raise UnsupportedQueryError(f"parse failed: {e}") from e

    if not isinstance(parsed, exp.Select):
        raise UnsupportedQueryError(f"only SELECT is supported (got {type(parsed).__name__})")
    if parsed.args.get("with"):
        raise UnsupportedQueryError("CTEs are not supported")

    from_ = parsed.args.get("from")
    if from_ is None:
        raise UnsupportedQueryError("missing FROM clause")
    if from_.expressions:
        # `FROM a, b` and similar comma-style FROM lists are folded
        # into `from_.this + a Join` by sqlglot; a populated
        # `expressions` list signals an unusual shape such as
        # `FROM a CROSS JOIN LATERAL ...`.
        raise UnsupportedQueryError("only a single FROM item is supported")

    first_table = from_.this
    if not isinstance(first_table, exp.Table):
        raise UnsupportedQueryError(
            f"FROM item must be a table reference (got {type(first_table).__name__})"
        )
    aliases: list[str] = [_alias_of(first_table)]

    for join in parsed.args.get("joins") or []:
        if not isinstance(join.this, exp.Table):
            raise UnsupportedQueryError(
                f"JOIN target must be a table reference (got {type(join.this).__name__})"
            )
        side = join.args.get("side")
        if side:
            raise UnsupportedQueryError(f"OUTER joins are not supported (got side={side})")
        kind = join.args.get("kind")
        if kind and kind.upper() == "CROSS":
            raise UnsupportedQueryError("CROSS joins are not supported")
        if kind and kind.upper() not in {"INNER", ""}:
            raise UnsupportedQueryError(f"only INNER JOIN is supported (got kind={kind})")
        method = join.args.get("method")
        if method and method.upper() == "NATURAL":
            raise UnsupportedQueryError("NATURAL joins are not supported")
        if join.args.get("using"):
            raise UnsupportedQueryError("USING joins are not supported")
        alias = _alias_of(join.this)
        if alias in aliases:
            raise UnsupportedQueryError(f"duplicate FROM alias {alias!r}")
        aliases.append(alias)

    if len(aliases) >= 2:
        edges = extract_join_edges(stripped)
        if not _is_predicate_graph_connected(aliases, edges):
            raise UnsupportedQueryError(
                "predicate graph is disconnected; refusing to produce a Cartesian-prone join order"
            )

    return aliases


def validate_and_build_explain_sql(plpy, query: str) -> str:
    """Validate ``query`` and return the EXPLAIN SQL string.

    Runs the supported-shape checks first, then defers syntax and
    catalogue checks to PostgreSQL via ``plpy.prepare``. Caller-level
    authorisation relies on SECURITY INVOKER on the SQL functions: a
    role that cannot call a function directly cannot reach it via
    ``purr.quantum_query_plan`` either.
    """
    validate_supported_shape(query)
    stripped = query.strip()
    try:
        plpy.prepare(stripped, [])
    except Exception as e:
        raise UnsupportedQueryError(f"query rejected by parser: {e}") from e
    return "EXPLAIN (FORMAT JSON, COSTS) " + stripped
