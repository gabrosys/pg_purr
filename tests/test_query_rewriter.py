"""Unit tests for the SQL query rewriter."""

import pytest
from pglast import parse_sql

from pg_purr.planner.query_rewriter import rewrite_query
from pg_purr.planner.query_validator import UnsupportedQueryError


def _strip_set_local(sql: str) -> str:
    prefix = "SET LOCAL join_collapse_limit = 1;"
    assert sql.startswith(prefix)
    return sql[len(prefix) :].lstrip()


def test_rewrites_three_way_inner_join():
    query = (
        "SELECT * FROM orders o "
        "JOIN customers c ON o.cust_id = c.id "
        "JOIN products p ON o.prod_id = p.id"
    )
    out = rewrite_query(query, ["c", "p", "o"])
    body = _strip_set_local(out)

    # Output must round-trip through the parser.
    parsed = parse_sql(body)
    assert len(parsed) == 1

    assert out.index("customers") < out.index("products")
    assert out.index("products") < out.index("orders")


def test_hoists_on_quals_into_where():
    query = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id WHERE o.total > 100"
    out = rewrite_query(query, ["c", "o"])
    body = _strip_set_local(out)

    assert "o.total > 100" in body
    assert "o.cust_id = c.id" in body


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
    body = _strip_set_local(out)

    parsed = parse_sql(body)
    assert len(parsed) == 1
    assert "analytics" in body
    assert "public" in body


def test_string_literal_with_join_keyword():
    query = "SELECT * FROM orders o JOIN customers c ON o.cust_id = c.id WHERE o.note = 'JOIN ME'"
    out = rewrite_query(query, ["c", "o"])
    body = _strip_set_local(out)
    parsed = parse_sql(body)
    assert len(parsed) == 1


def test_nested_parens_in_on_condition():
    query = "SELECT * FROM a JOIN b ON ((a.x = b.x) AND (a.y = b.y))"
    out = rewrite_query(query, ["b", "a"])
    body = _strip_set_local(out)
    parsed = parse_sql(body)
    assert len(parsed) == 1
