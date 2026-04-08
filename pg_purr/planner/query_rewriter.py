"""Rewrite SQL queries with optimized JOIN ordering."""

from __future__ import annotations

from pglast import ast, parse_sql
from pglast.enums import BoolExprType, JoinType, SetOperation
from pglast.stream import RawStream

from pg_purr.planner.query_validator import UnsupportedQueryError


def _collect_from_items(expr) -> dict[str, ast.RangeVar]:
    items: dict[str, ast.RangeVar] = {}

    def visit(node) -> None:
        if isinstance(node, ast.RangeVar):
            alias = node.alias.aliasname if node.alias is not None else node.relname
            if alias in items:
                raise UnsupportedQueryError(f"duplicate FROM alias {alias!r}")
            items[alias] = node
            return
        if isinstance(node, ast.JoinExpr):
            if node.jointype != JoinType.JOIN_INNER:
                raise UnsupportedQueryError(
                    f"only INNER JOIN is supported (got {node.jointype.name})"
                )
            if node.isNatural or node.usingClause:
                raise UnsupportedQueryError("NATURAL / USING joins are not supported")
            visit(node.larg)
            visit(node.rarg)
            return
        raise UnsupportedQueryError(f"unsupported FROM item: {type(node).__name__}")

    visit(expr)
    return items


def _collect_on_quals(expr) -> list:
    quals: list = []

    def visit(node) -> None:
        if isinstance(node, ast.JoinExpr):
            if node.quals is not None:
                quals.append(node.quals)
            visit(node.larg)
            visit(node.rarg)

    visit(expr)
    return quals


def rewrite_query(original_query: str, optimal_order: list[str]) -> str:
    """Reorder INNER JOINs in `original_query` according to `optimal_order`.

    ON quals are hoisted into the WHERE clause — semantically equivalent
    for INNER joins and keeps reordering sound. Prepends
    `SET LOCAL join_collapse_limit = 1;` so the setting never leaks
    beyond the enclosing transaction.

    Raises:
        UnsupportedQueryError: for anything other than a single SELECT
            whose FROM clause is a chain of INNER joins over table
            references.
    """
    try:
        stmts = parse_sql(original_query)
    except Exception as e:
        raise UnsupportedQueryError(f"parse failed: {e}") from e

    if len(stmts) != 1:
        raise UnsupportedQueryError("exactly one statement is required")

    raw = stmts[0].stmt
    if not isinstance(raw, ast.SelectStmt):
        raise UnsupportedQueryError("only SELECT is supported")
    if raw.withClause is not None:
        raise UnsupportedQueryError("CTEs are not supported")
    if raw.op != SetOperation.SETOP_NONE:
        raise UnsupportedQueryError("set operations are not supported")
    if not raw.fromClause or len(raw.fromClause) != 1:
        raise UnsupportedQueryError("exactly one FROM item is required")

    items = _collect_from_items(raw.fromClause[0])
    quals = _collect_on_quals(raw.fromClause[0])

    if set(optimal_order) != set(items):
        raise UnsupportedQueryError(
            f"optimal_order {optimal_order!r} does not match FROM items {sorted(items)!r}"
        )

    cur = items[optimal_order[0]]
    for name in optimal_order[1:]:
        cur = ast.JoinExpr(
            jointype=JoinType.JOIN_INNER,
            larg=cur,
            rarg=items[name],
            quals=None,
        )
    raw.fromClause = (cur,)

    combined = raw.whereClause
    for q in quals:
        combined = (
            q
            if combined is None
            else ast.BoolExpr(
                boolop=BoolExprType.AND_EXPR,
                args=(combined, q),
            )
        )
    raw.whereClause = combined

    body = RawStream()(raw)
    return f"SET LOCAL join_collapse_limit = 1;\n{body}"
