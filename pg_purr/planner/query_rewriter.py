"""Rewrite SQL queries with optimised JOIN ordering.

Uses sqlglot (pure Python). pglast cannot be used here: it bundles
libpg_query, which embeds PG parser globals and SIGSEGVs when loaded
inside a plpython3u backend. libpg_query is documented as
out-of-server only.
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

from pg_purr.planner.query_validator import UnsupportedQueryError

_DIALECT = "postgres"


def _alias_of(table: exp.Table) -> str:
    """Return the alias if present, else the bare relation name."""
    return table.alias or table.name


def _validate_join(join: exp.Join) -> None:
    if not isinstance(join.this, exp.Table):
        raise UnsupportedQueryError(
            f"JOIN target must be a table reference (got {type(join.this).__name__})"
        )
    side = join.args.get("side")
    if side:
        raise UnsupportedQueryError(f"OUTER joins are not supported (got side={side})")
    kind = join.args.get("kind")
    if kind and kind.upper() != "INNER":
        raise UnsupportedQueryError(f"only INNER JOIN is supported (got kind={kind})")
    method = join.args.get("method")
    if method and method.upper() == "NATURAL":
        raise UnsupportedQueryError("NATURAL joins are not supported")
    if join.args.get("using"):
        raise UnsupportedQueryError("USING joins are not supported")


def rewrite_query(original_query: str, optimal_order: list[str]) -> str:
    """Reorder INNER JOINs in `original_query` according to `optimal_order`.

    ON predicates are hoisted into WHERE; the new FROM is a left chain
    of `INNER JOIN ... ON TRUE`. Caller must pin
    `join_collapse_limit = 1` for PG to honour the order.

    Raises:
        UnsupportedQueryError: anything other than a single SELECT
            whose FROM clause is a chain of INNER joins over plain
            table references.
    """
    try:
        statements = sqlglot.parse(original_query, read=_DIALECT)
    except sqlglot.errors.ParseError as e:
        raise UnsupportedQueryError(f"parse failed: {e}") from e

    if len(statements) != 1:
        raise UnsupportedQueryError("exactly one statement is required")

    parsed = statements[0]
    if parsed is None:
        raise UnsupportedQueryError("empty statement")

    if not isinstance(parsed, exp.Select):
        raise UnsupportedQueryError(f"only SELECT is supported (got {type(parsed).__name__})")
    if parsed.args.get("with"):
        raise UnsupportedQueryError("CTEs are not supported")

    from_ = parsed.args.get("from")
    if from_ is None:
        raise UnsupportedQueryError("missing FROM clause")
    if from_.expressions:
        # sqlglot folds `FROM a, b` into from_.this + a Join, so a
        # populated .expressions here means an unusual shape such as
        # `FROM a CROSS JOIN LATERAL ...`.
        raise UnsupportedQueryError("only a single FROM item is supported")

    first_table = from_.this
    if not isinstance(first_table, exp.Table):
        raise UnsupportedQueryError(
            f"FROM item must be a table reference (got {type(first_table).__name__})"
        )

    items: dict[str, exp.Table] = {_alias_of(first_table): first_table}
    quals: list[exp.Expression] = []

    for join in parsed.args.get("joins") or []:
        _validate_join(join)
        alias = _alias_of(join.this)
        if alias in items:
            raise UnsupportedQueryError(f"duplicate FROM alias {alias!r}")
        items[alias] = join.this
        on = join.args.get("on")
        if on is not None:
            quals.append(on)

    if set(optimal_order) != set(items):
        raise UnsupportedQueryError(
            f"optimal_order {optimal_order!r} does not match FROM items {sorted(items)!r}"
        )

    # `ON TRUE` keeps `INNER JOIN` syntactically valid; real
    # predicates are placed in WHERE below.
    parsed.set("from", exp.From(this=items[optimal_order[0]].copy()))
    parsed.set(
        "joins",
        [
            exp.Join(this=items[name].copy(), kind="INNER", on=exp.true())
            for name in optimal_order[1:]
        ],
    )

    where_clause = parsed.args.get("where")
    combined: exp.Expression | None = where_clause.this if where_clause else None
    for q in quals:
        combined = q.copy() if combined is None else exp.And(this=combined, expression=q.copy())
    parsed.set("where", exp.Where(this=combined) if combined is not None else None)

    return parsed.sql(dialect=_DIALECT)
