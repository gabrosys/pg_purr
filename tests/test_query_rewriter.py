"""Unit tests for the SQL query rewriter."""

import pytest
import sqlglot

from pg_purr.planner.query_rewriter import rewrite_query
from pg_purr.planner.query_validator import UnsupportedQueryError


def _parse(sql: str):
    return sqlglot.parse(sql, read="postgres")


def _on_clauses(sql: str) -> list[str]:
    """Return the ON-clause text of every JOIN in `sql`, in order."""
    parsed = sqlglot.parse_one(sql, read="postgres")
    out = []
    for join in parsed.args.get("joins") or []:
        on = join.args.get("on")
        out.append(on.sql(dialect="postgres") if on is not None else "")
    return out


def _where_clause(sql: str) -> str:
    parsed = sqlglot.parse_one(sql, read="postgres")
    where = parsed.args.get("where")
    return where.this.sql(dialect="postgres") if where is not None else ""


def test_rewrites_three_way_inner_join():
    # Edges are {c-o, o-p}. A valid (connected) reorder must visit
    # `o` between the leaves; ["c", "o", "p"] qualifies.
    query = (
        "SELECT * FROM orders o "
        "JOIN customers c ON o.cust_id = c.id "
        "JOIN products p ON o.prod_id = p.id"
    )
    out = rewrite_query(query, ["c", "o", "p"])

    parsed = _parse(out)
    assert len(parsed) == 1

    assert out.index("customers") < out.index("orders")
    assert out.index("orders") < out.index("products")


def test_pushes_join_predicate_to_earliest_join():
    # Order [c, o]: o.cust_id = c.id has both tables in scope at step 1
    # (when o is joined). Single-table filter stays in WHERE.
    query = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id WHERE o.total > 100"
    out = rewrite_query(query, ["c", "o"])

    on_clauses = _on_clauses(out)
    assert len(on_clauses) == 1
    assert "o.cust_id = c.id" in on_clauses[0]
    assert "o.total > 100" in _where_clause(out)


def test_pushes_each_predicate_to_step_where_all_tables_are_in_scope():
    # 3 ON-predicate atoms across 3 tables.
    #   o.id = sh.order_id            -> {o, sh}
    #   si.shipment_id = sh.id        -> {si, sh}
    #   si.order_item_id = o.id       -> {si, o}
    # Order [si, sh, o]: positions si=0, sh=1, o=2
    #   step 1 (joining sh): {si, sh} predicates -> "si.shipment_id = sh.id"
    #   step 2 (joining o):  {o, sh} and {si, o} both arrive in scope
    query = (
        "SELECT * FROM shipments sh "
        "JOIN orders o ON o.id = sh.order_id "
        "JOIN shipment_items si ON si.shipment_id = sh.id "
        "                       AND si.order_item_id = o.id"
    )
    out = rewrite_query(query, ["si", "sh", "o"])
    on_clauses = _on_clauses(out)
    assert len(on_clauses) == 2

    assert "si.shipment_id = sh.id" in on_clauses[0]
    assert "o.id = sh.order_id" in on_clauses[1]
    assert "si.order_item_id = o.id" in on_clauses[1]


def test_single_table_filter_stays_in_where():
    query = "SELECT * FROM a JOIN b ON a.id = b.aid WHERE a.region = 'EU' AND b.flag = TRUE"
    out = rewrite_query(query, ["a", "b"])

    where = _where_clause(out)
    assert "a.region = 'EU'" in where
    assert "b.flag = TRUE" in where

    on_clauses = _on_clauses(out)
    assert "a.id = b.aid" in on_clauses[0]


def test_rejects_disconnected_step_instead_of_emitting_on_true():
    # b shares no multi-table predicate with a. Under the old
    # rewriter this fell back to `ON TRUE`, which forces a Cartesian
    # under join_collapse_limit = 1. The current rewriter must
    # refuse rather than emit an unsafe JOIN.
    query = "SELECT * FROM a JOIN b ON TRUE WHERE a.x = 1 AND b.y = 2"
    with pytest.raises(UnsupportedQueryError, match="Cartesian"):
        rewrite_query(query, ["a", "b"])


def test_returned_sql_has_no_set_local_prefix():
    query = "SELECT * FROM a JOIN b ON a.id = b.id"
    out = rewrite_query(query, ["b", "a"])

    assert "SET LOCAL" not in out
    assert out.lstrip().upper().startswith("SELECT")


def test_rejects_multi_statement():
    with pytest.raises(UnsupportedQueryError):
        rewrite_query("SELECT 1; DROP TABLE t", ["t"])


def test_rejects_non_select():
    with pytest.raises(UnsupportedQueryError):
        rewrite_query("UPDATE t SET x = 1", ["t"])


def test_rejects_outer_join():
    query = "SELECT * FROM a LEFT JOIN b ON a.id = b.id"
    with pytest.raises(UnsupportedQueryError):
        rewrite_query(query, ["a", "b"])


def test_rejects_subquery_in_from():
    query = "SELECT * FROM (SELECT 1) s JOIN b ON b.id = 1"
    with pytest.raises(UnsupportedQueryError):
        rewrite_query(query, ["s", "b"])


def test_rejects_cte():
    query = "WITH x AS (SELECT 1) SELECT * FROM x JOIN b ON b.id = 1"
    with pytest.raises(UnsupportedQueryError):
        rewrite_query(query, ["x", "b"])


def test_rejects_order_mismatch():
    query = "SELECT * FROM a JOIN b ON a.id = b.id"
    with pytest.raises(UnsupportedQueryError):
        rewrite_query(query, ["a"])


def test_accepts_schema_qualified_tables():
    query = "SELECT * FROM public.orders o JOIN analytics.customers c ON o.cust_id = c.id"
    out = rewrite_query(query, ["c", "o"])

    parsed = _parse(out)
    assert len(parsed) == 1
    assert "analytics" in out
    assert "public" in out


def test_string_literal_with_join_keyword():
    query = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id WHERE o.note = 'JOIN ME'"
    out = rewrite_query(query, ["c", "o"])
    parsed = _parse(out)
    assert len(parsed) == 1


def test_nested_parens_in_on_condition():
    query = "SELECT * FROM a JOIN b ON ((a.x = b.x) AND (a.y = b.y))"
    out = rewrite_query(query, ["b", "a"])
    parsed = _parse(out)
    assert len(parsed) == 1
