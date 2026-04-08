"""Unit tests for the query validator."""

from unittest.mock import MagicMock

import pytest

from pg_purr.planner.query_validator import (
    UnsupportedQueryError,
    validate_and_build_explain_sql,
)


def test_returns_explain_sql_for_valid_query():
    plpy = MagicMock()
    out = validate_and_build_explain_sql(plpy, "SELECT 1")
    assert out == "EXPLAIN (FORMAT JSON, COSTS) SELECT 1"
    plpy.prepare.assert_called_once_with("SELECT 1", [])


def test_rejects_multi_statement():
    plpy = MagicMock()
    with pytest.raises(UnsupportedQueryError) as exc:
        validate_and_build_explain_sql(plpy, "SELECT 1; DROP TABLE t")
    assert "multi-statement" in str(exc.value)
    plpy.prepare.assert_not_called()


def test_rejects_trailing_semicolon():
    plpy = MagicMock()
    with pytest.raises(UnsupportedQueryError):
        validate_and_build_explain_sql(plpy, "SELECT 1;")
    plpy.prepare.assert_not_called()


def test_rejects_when_prepare_raises():
    plpy = MagicMock()
    plpy.prepare.side_effect = Exception("syntax error")
    with pytest.raises(UnsupportedQueryError) as exc:
        validate_and_build_explain_sql(plpy, "BOGUS")
    assert "query rejected by parser" in str(exc.value)


def test_rejects_empty_query():
    plpy = MagicMock()
    with pytest.raises(UnsupportedQueryError):
        validate_and_build_explain_sql(plpy, "")
    with pytest.raises(UnsupportedQueryError):
        validate_and_build_explain_sql(plpy, "   \n\t  ")
    plpy.prepare.assert_not_called()
