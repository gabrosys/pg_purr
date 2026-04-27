"""Integration tests for pg_purr (require a running PostgreSQL instance).

Run with: make test-integration
Tests run inside the Docker container (localhost:5432) via docker exec.
When running from the host, PG is forwarded to localhost:5433.
"""

import os

import psycopg2
import pytest

pytestmark = pytest.mark.integration

PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = os.getenv("PGPORT", "5433")
PG_DB = os.getenv("PGDATABASE", "pg_purr_test")
PG_USER = os.getenv("PGUSER", "test")
PG_PASS = os.getenv("PGPASSWORD", "test")


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS)
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture(scope="module", autouse=True)
def setup_pg_purr(conn):
    cur = conn.cursor()
    cur.execute("DROP EXTENSION IF EXISTS pg_purr CASCADE")
    cur.execute("CREATE EXTENSION IF NOT EXISTS plpython3u")
    cur.execute("CREATE EXTENSION pg_purr")
    cur.execute(
        "INSERT INTO purr.quantum_entropy (value)"
        " SELECT (random() * 65535)::int FROM generate_series(1, 100)"
    )
    cur.close()


def test_quantum_random_returns_float(conn):
    cur = conn.cursor()
    cur.execute("SELECT purr.quantum_random()")
    val = cur.fetchone()[0]
    assert isinstance(val, float)
    assert 0.0 <= val <= 1.0
    cur.close()


def test_quantum_random_in_range(conn):
    cur = conn.cursor()
    cur.execute("SELECT purr.quantum_random_in_range(10.0, 20.0)")
    val = cur.fetchone()[0]
    assert 10.0 <= val <= 20.0
    cur.close()


def test_quantum_random_errors_on_empty_pool_strict(conn):
    cur = conn.cursor()
    cur.execute("TRUNCATE purr.quantum_entropy")
    cur.execute("SET pg_purr.allow_prng_fallback = off")
    with pytest.raises(psycopg2.errors.InternalError_):
        cur.execute("SELECT purr.quantum_random()")
    cur.close()
    # Refill for subsequent tests.
    cur2 = conn.cursor()
    cur2.execute(
        "INSERT INTO purr.quantum_entropy (value)"
        " SELECT (random() * 65535)::int FROM generate_series(1, 100)"
    )
    cur2.close()


def test_quantum_random_falls_back_when_guc_set(conn):
    cur = conn.cursor()
    cur.execute("TRUNCATE purr.quantum_entropy")
    cur.execute("SET pg_purr.allow_prng_fallback = on")
    cur.execute("SELECT purr.quantum_random()")
    val = cur.fetchone()[0]
    assert 0.0 <= val < 1.0
    cur.execute("SET pg_purr.allow_prng_fallback = off")
    cur.close()
    cur2 = conn.cursor()
    cur2.execute(
        "INSERT INTO purr.quantum_entropy (value)"
        " SELECT (random() * 65535)::int FROM generate_series(1, 100)"
    )
    cur2.close()


def test_prng_random_returns_float(conn):
    cur = conn.cursor()
    cur.execute("SELECT purr.prng_random()")
    val = cur.fetchone()[0]
    assert 0.0 <= val < 1.0
    cur.close()


def test_pg_purr_version(conn):
    cur = conn.cursor()
    cur.execute("SELECT purr.pg_purr_version()")
    assert cur.fetchone()[0] == "0.2.0"
    cur.close()


def test_quantum_query_plan_rejects_injection(conn):
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.InternalError_):
        cur.execute("SELECT * FROM purr.quantum_query_plan('SELECT 1; DROP TABLE test_a')")
    cur.close()


def test_quantum_query_plan_basic(conn):
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS public.test_a (id int PRIMARY KEY, val text)")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS public.test_b "
        "(id int PRIMARY KEY, a_id int REFERENCES public.test_a(id))"
    )
    cur.execute(
        "INSERT INTO public.test_a SELECT g, 'val' FROM generate_series(1,100) g "
        "ON CONFLICT DO NOTHING"
    )
    cur.execute(
        "INSERT INTO public.test_b SELECT g, (g % 100) + 1 "
        "FROM generate_series(1,500) g ON CONFLICT DO NOTHING"
    )
    cur.execute("ANALYZE public.test_a; ANALYZE public.test_b")

    cur.execute(
        "SELECT * FROM purr.quantum_query_plan("
        "'SELECT * FROM public.test_a "
        "JOIN public.test_b ON public.test_a.id = public.test_b.a_id')"
    )
    rows = cur.fetchall()
    assert len(rows) == 2
    table_names = {row[1] for row in rows}
    assert table_names == {"test_a", "test_b"}
    cur.close()


def test_quantum_query_rewrite_returns_select(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT purr.quantum_query_rewrite("
        "'SELECT * FROM public.test_a "
        "JOIN public.test_b ON public.test_a.id = public.test_b.a_id')"
    )
    rewritten = cur.fetchone()[0]
    assert isinstance(rewritten, str)
    # Caller is responsible for the GUC; the function must not bundle it.
    assert "SET LOCAL" not in rewritten
    assert rewritten.lstrip().upper().startswith("SELECT")
    # Both tables must appear in the rewritten FROM.
    assert "test_a" in rewritten
    assert "test_b" in rewritten
    cur.close()


def test_quantum_query_rewrite_preserves_semantics(conn):
    """The rewritten query must return the same rows as the original."""
    original = (
        "SELECT public.test_a.id, public.test_b.id "
        "FROM public.test_a "
        "JOIN public.test_b ON public.test_a.id = public.test_b.a_id "
        "ORDER BY public.test_a.id, public.test_b.id"
    )
    cur = conn.cursor()
    cur.execute(original)
    expected = cur.fetchall()

    cur.execute("SELECT purr.quantum_query_rewrite(%s)", (original,))
    rewritten = cur.fetchone()[0]

    # SET LOCAL only takes effect inside an explicit transaction;
    # the shared `conn` fixture is autocommit, so flip it briefly.
    conn.autocommit = False
    try:
        cur.execute("SET LOCAL join_collapse_limit = 1")
        cur.execute(rewritten)
        actual = cur.fetchall()
        conn.commit()
    finally:
        conn.autocommit = True

    assert actual == expected
    cur.close()


def test_quantum_query_rewrite_rejects_outer_join(conn):
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.InternalError_):
        cur.execute(
            "SELECT purr.quantum_query_rewrite("
            "'SELECT * FROM public.test_a "
            "LEFT JOIN public.test_b ON public.test_a.id = public.test_b.a_id')"
        )
    cur.close()
