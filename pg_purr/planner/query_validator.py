"""Validate user-supplied SQL before running EXPLAIN."""

from __future__ import annotations


class UnsupportedQueryError(ValueError):
    """Raised when a query is rejected as unsafe to plan."""


def validate_and_build_explain_sql(plpy, query: str) -> str:
    """Validate `query` via PG's own parser and return the EXPLAIN SQL.

    The query must be a single SQL statement. Multi-statement input
    is rejected by a semicolon check because both `plpy.prepare` and
    `plpy.execute` silently accept and run multiple statements. Legit
    queries with ';' inside string literals are also rejected — an
    acceptable trade-off for a single-statement contract.

    `plpy.prepare` then delegates syntax and catalogue checks to PG.
    Non-SELECT shapes that pass parsing are rejected by EXPLAIN with a
    "non-query statement" error. Caller-level authorisation is
    enforced by SECURITY INVOKER: a role that cannot call a function
    directly cannot reach it via `quantum_query_plan` either.
    """
    stripped = query.strip()
    if not stripped:
        raise UnsupportedQueryError("empty query")
    if ";" in stripped:
        raise UnsupportedQueryError("query must not contain ';' (multi-statement not supported)")
    try:
        plpy.prepare(stripped, [])
    except Exception as e:
        raise UnsupportedQueryError(f"query rejected by parser: {e}") from e
    return "EXPLAIN (FORMAT JSON, COSTS) " + stripped
