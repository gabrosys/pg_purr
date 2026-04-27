"""Tests for the query validator."""

from unittest.mock import MagicMock

import pytest

from pg_purr.planner.query_validator import (
    UnsupportedQueryError,
    validate_and_build_explain_sql,
    validate_supported_shape,
)

# --- shape validation (no plpy) ---------------------------------------------


def test_simple_two_table_inner_join_is_accepted() -> None:
    aliases = validate_supported_shape("SELECT * FROM a INNER JOIN b ON a.id = b.a_id")
    assert aliases == ["a", "b"]


def test_implicit_inner_keyword_is_accepted() -> None:
    aliases = validate_supported_shape("SELECT * FROM a JOIN b ON a.id = b.a_id")
    assert aliases == ["a", "b"]


def test_alias_in_from_and_join_is_accepted() -> None:
    aliases = validate_supported_shape("SELECT * FROM a x JOIN b y ON x.id = y.x_id")
    assert aliases == ["x", "y"]


def test_chain_of_three_inner_joins_is_accepted() -> None:
    aliases = validate_supported_shape(
        "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id"
    )
    assert aliases == ["a", "b", "c"]


def test_single_table_select_is_accepted_with_one_alias() -> None:
    assert validate_supported_shape("SELECT * FROM t") == ["t"]


def test_empty_query_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="empty"):
        validate_supported_shape("")


def test_whitespace_only_query_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="empty"):
        validate_supported_shape("   \n\t  ")


def test_semicolon_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="multi-statement"):
        validate_supported_shape("SELECT * FROM t;")


def test_multi_statement_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="multi-statement"):
        validate_supported_shape("SELECT 1; DROP TABLE t")


def test_non_select_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="only SELECT"):
        validate_supported_shape("UPDATE t SET x = 1")


def test_left_outer_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="OUTER"):
        validate_supported_shape("SELECT * FROM a LEFT JOIN b ON a.id = b.a_id")


def test_right_outer_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="OUTER"):
        validate_supported_shape("SELECT * FROM a RIGHT JOIN b ON a.id = b.a_id")


def test_full_outer_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="OUTER"):
        validate_supported_shape("SELECT * FROM a FULL OUTER JOIN b ON a.id = b.a_id")


def test_natural_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="NATURAL"):
        validate_supported_shape("SELECT * FROM a NATURAL JOIN b")


def test_using_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="USING"):
        validate_supported_shape("SELECT * FROM a JOIN b USING (id)")


def test_cross_join_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="CROSS"):
        validate_supported_shape("SELECT * FROM a CROSS JOIN b")


def test_cte_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="CTEs"):
        validate_supported_shape("WITH c AS (SELECT 1) SELECT * FROM c")


def test_subquery_in_from_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="table reference"):
        validate_supported_shape("SELECT * FROM (SELECT 1) sub JOIN b ON sub.x = b.y")


def test_disconnected_predicate_graph_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="disconnected"):
        validate_supported_shape("SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON c.x = c.y")


def test_duplicate_alias_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError, match="duplicate"):
        validate_supported_shape("SELECT * FROM a x JOIN b x ON x.id = x.id")


def test_garbage_input_is_rejected() -> None:
    with pytest.raises(UnsupportedQueryError):
        validate_supported_shape("not a query at all !!!")


# --- validate_and_build_explain_sql (with plpy mock) ------------------------


def test_returns_explain_sql_for_valid_query() -> None:
    plpy = MagicMock()
    query = "SELECT * FROM t"
    out = validate_and_build_explain_sql(plpy, query)
    assert out == "EXPLAIN (FORMAT JSON, COSTS) SELECT * FROM t"
    plpy.prepare.assert_called_once_with(query, [])


def test_rejects_when_prepare_raises() -> None:
    plpy = MagicMock()
    plpy.prepare.side_effect = Exception("relation does not exist")
    with pytest.raises(UnsupportedQueryError, match="rejected by parser"):
        validate_and_build_explain_sql(plpy, "SELECT * FROM nonexistent_table")


def test_explain_sql_short_circuits_on_shape_failure() -> None:
    plpy = MagicMock()
    with pytest.raises(UnsupportedQueryError, match="multi-statement"):
        validate_and_build_explain_sql(plpy, "SELECT 1; DROP TABLE t")
    plpy.prepare.assert_not_called()
