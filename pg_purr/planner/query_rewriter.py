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


def _split_and(expr: exp.Expression) -> list[exp.Expression]:
    """Flatten an AND-chain into its atoms."""
    if isinstance(expr, exp.And):
        return _split_and(expr.this) + _split_and(expr.expression)
    return [expr]


def _and_chain(predicates: list[exp.Expression]) -> exp.Expression | None:
    """Combine predicates with AND, returning None for an empty list."""
    if not predicates:
        return None
    combined = predicates[0]
    for p in predicates[1:]:
        combined = exp.And(this=combined, expression=p)
    return combined


def _predicate_tables(predicate: exp.Expression) -> set[str]:
    """Return the set of distinct table aliases referenced by `predicate`."""
    return {col.table for col in predicate.find_all(exp.Column) if col.table}


def rewrite_query(original_query: str, optimal_order: list[str]) -> str:
    """Reorder INNER JOINs in `original_query` according to `optimal_order`.

    For each INNER JOIN in the new chain, the rewriter pushes the
    original predicates down to the **earliest** JOIN where all the
    predicate's referenced tables are in scope. Predicates that
    cannot be attached to any JOIN (single-table filters,
    unqualified columns, references outside the FROM list) stay in
    WHERE.

    The rewriter NEVER emits `ON TRUE`. If any step in
    ``optimal_order`` introduces a table that shares no predicate
    with the tables already in scope, it raises — refusing to
    produce a Cartesian-prone JOIN. The pipeline guarantees a
    connected order upstream, so reaching this branch indicates a
    direct call with a malformed input.

    Caller must pin `join_collapse_limit = 1` so PG honours the
    chosen order.

    Raises:
        UnsupportedQueryError: anything other than a single SELECT
            whose FROM clause is a chain of INNER joins over plain
            table references; or `optimal_order` introduces a step
            with no connecting predicate.
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
    on_quals: list[exp.Expression] = []

    for join in parsed.args.get("joins") or []:
        _validate_join(join)
        alias = _alias_of(join.this)
        if alias in items:
            raise UnsupportedQueryError(f"duplicate FROM alias {alias!r}")
        items[alias] = join.this
        on = join.args.get("on")
        if on is not None:
            on_quals.append(on)

    if set(optimal_order) != set(items):
        raise UnsupportedQueryError(
            f"optimal_order {optimal_order!r} does not match FROM items {sorted(items)!r}"
        )

    # Collect every original predicate atom from ON clauses + WHERE,
    # split through any top-level ANDs so we can attach each one
    # independently.
    where_clause = parsed.args.get("where")
    where_root = where_clause.this if where_clause else None
    all_predicates: list[exp.Expression] = []
    for q in on_quals:
        all_predicates.extend(_split_and(q))
    if where_root is not None:
        all_predicates.extend(_split_and(where_root))

    # Push each predicate down to the earliest JOIN that has all its
    # referenced tables in scope. Non-pushable predicates (single
    # table, unqualified columns, references outside the FROM list)
    # stay in WHERE.
    position = {alias: idx for idx, alias in enumerate(optimal_order)}
    on_by_step: list[list[exp.Expression]] = [[] for _ in optimal_order]
    where_residual: list[exp.Expression] = []

    for predicate in all_predicates:
        tables = _predicate_tables(predicate)
        if len(tables) < 2 or not tables.issubset(position):
            where_residual.append(predicate.copy())
            continue
        max_step = max(position[t] for t in tables)
        if max_step == 0:
            # Multi-table predicate referencing only the FROM table —
            # can't happen geometrically, but stay in WHERE if it does.
            where_residual.append(predicate.copy())
            continue
        on_by_step[max_step].append(predicate.copy())

    # Build the reordered FROM + JOIN chain. A step with no
    # connecting predicate would force a Cartesian product under
    # `join_collapse_limit = 1`; refuse instead of emitting
    # `ON TRUE`. The pipeline guarantees connectivity upstream.
    parsed.set("from", exp.From(this=items[optimal_order[0]].copy()))
    new_joins = []
    for step in range(1, len(optimal_order)):
        on_expr = _and_chain(on_by_step[step])
        if on_expr is None:
            raise UnsupportedQueryError(
                f"step {step} introduces {optimal_order[step]!r} with no "
                f"predicate to {optimal_order[:step]!r}; refusing to emit "
                f"a Cartesian-prone JOIN"
            )
        new_joins.append(exp.Join(this=items[optimal_order[step]].copy(), kind="INNER", on=on_expr))
    parsed.set("joins", new_joins)

    parsed.set(
        "where",
        exp.Where(this=_and_chain(where_residual)) if where_residual else None,
    )

    return parsed.sql(dialect=_DIALECT, pretty=True)
