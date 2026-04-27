"""Unit tests for the SQL query rewriter."""

import pytest
import sqlglot

from pg_purr.planner.query_rewriter import rewrite_query
from pg_purr.planner.query_validator import UnsupportedQueryError


def _parse(sql: str):
    return sqlglot.parse(sql, read="postgres")


def test_rewrites_three_way_inner_join():
    query = (
        "SELECT * FROM orders o "
        "JOIN customers c ON o.cust_id = c.id "
        "JOIN products p ON o.prod_id = p.id"
    )
    out = rewrite_query(query, ["c", "p", "o"])

    # Output must round-trip through the parser.
    parsed = _parse(out)
    assert len(parsed) == 1

    assert out.index("customers") < out.index("products")
    assert out.index("products") < out.index("orders")


def test_hoists_on_quals_into_where():
    query = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id WHERE o.total > 100"
    out = rewrite_query(query, ["c", "o"])

    assert "o.total > 100" in out
    assert "o.cust_id = c.id" in out


def test_hoists_multi_condition_on_into_where():
    # Catnap demo shape: a single ON clause that ANDs two equalities
    # across three tables. Both must end up in the WHERE clause.
    query = (
        "SELECT * FROM shipments sh "
        "JOIN orders o ON o.id = sh.order_id "
        "JOIN shipment_items si ON si.shipment_id = sh.id "
        "                       AND si.order_item_id = o.id"
    )
    out = rewrite_query(query, ["si", "sh", "o"])
    parsed = _parse(out)
    assert len(parsed) == 1

    # Original ON predicates must all appear in WHERE.
    where_clause = out.split(" WHERE ", 1)[1]
    assert "si.shipment_id = sh.id" in where_clause
    assert "si.order_item_id = o.id" in where_clause
    assert "o.id = sh.order_id" in where_clause
    # Joins must use ON TRUE placeholders (real predicates moved to
    # WHERE), not the original predicates.
    from_clause = out.split(" WHERE ", 1)[0]
    assert "si.shipment_id" not in from_clause
    assert "si.order_item_id" not in from_clause


def test_returned_sql_has_no_set_local_prefix():
    query = "SELECT * FROM a JOIN b ON a.id = b.id"
    out = rewrite_query(query, ["b", "a"])

    # Caller is responsible for pinning join_collapse_limit; the
    # rewriter must not bundle the GUC change into the returned text.
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
