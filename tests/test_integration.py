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


# --- 17-table retail-shape stress test ---------------------------------------

_RETAIL_TABLES = [
    "suppliers",
    "products",
    "categories",
    "inventory",
    "warehouses",
    "order_items",
    "orders",
    "customers",
    "addresses",
    "payments",
    "payment_methods",
    "shipments",
    "shipment_items",
    "reviews",
    "promotion_rules",
    "promotions",
]
# `pc` (parent category) reuses the `categories` table — modelled here as
# a self-join via `categories AS pc` in the rewrite query.

_RETAIL_QUERY = """
SELECT s.id AS supplier_id, count(*) AS shipment_count
FROM public.suppliers        s
JOIN public.products         p     ON p.supplier_id  = s.id
JOIN public.categories       c     ON c.id           = p.category_id
JOIN public.categories       pc    ON pc.id          = c.parent_id
JOIN public.inventory        inv   ON inv.product_id = p.id
JOIN public.warehouses       w     ON w.id           = inv.warehouse_id
JOIN public.order_items      oi    ON oi.product_id  = p.id
JOIN public.orders           o     ON o.id           = oi.order_id
JOIN public.customers        cu    ON cu.id          = o.customer_id
JOIN public.addresses        a     ON a.id           = o.address_id
JOIN public.payments         pay   ON pay.order_id   = o.id
JOIN public.payment_methods  pm    ON pm.id          = pay.payment_method_id
JOIN public.shipments        sh    ON sh.order_id    = o.id
JOIN public.shipment_items   si    ON si.shipment_id = sh.id
                                  AND si.order_item_id = oi.id
JOIN public.reviews          r     ON r.product_id   = p.id
                                  AND r.customer_id = cu.id
JOIN public.promotion_rules  pr    ON pr.category_id = c.id
JOIN public.promotions       promo ON promo.id       = pr.promotion_id
GROUP BY s.id
""".strip()


@pytest.fixture(scope="module")
def retail_schema(conn):
    cur = conn.cursor()
    for table in _RETAIL_TABLES:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS public.{table} ("
            "id SERIAL PRIMARY KEY, "
            "supplier_id INT, category_id INT, parent_id INT, "
            "product_id INT, warehouse_id INT, order_id INT, "
            "customer_id INT, address_id INT, payment_method_id INT, "
            "shipment_id INT, order_item_id INT, promotion_id INT, "
            "rating INT, region TEXT, name TEXT, "
            "order_date DATE, start_date DATE, end_date DATE, "
            "total NUMERIC, min_order_total NUMERIC)"
        )
        cur.execute(
            f"INSERT INTO public.{table} (id) "
            f"SELECT g FROM generate_series(1, 50) g "
            "ON CONFLICT DO NOTHING"
        )
    for table in _RETAIL_TABLES:
        cur.execute(f"ANALYZE public.{table}")
    cur.close()


def test_retail_shape_rewrite_returns_connected_select(conn, retail_schema):
    import sqlglot

    cur = conn.cursor()
    cur.execute("SELECT purr.quantum_query_rewrite(%s)", (_RETAIL_QUERY,))
    rewritten = cur.fetchone()[0]
    assert isinstance(rewritten, str)
    assert rewritten.lstrip().upper().startswith("SELECT")

    parsed = sqlglot.parse_one(rewritten, read="postgres")
    aliases: set[str] = set()
    from_ = parsed.args.get("from")
    if from_ is not None and from_.this is not None:
        aliases.add(from_.this.alias or from_.this.name)
    for join in parsed.args.get("joins") or []:
        if join.this is not None:
            aliases.add(join.this.alias or join.this.name)

    expected = {
        "s",
        "p",
        "c",
        "pc",
        "inv",
        "w",
        "oi",
        "o",
        "cu",
        "a",
        "pay",
        "pm",
        "sh",
        "si",
        "r",
        "pr",
        "promo",
    }
    assert aliases == expected, f"alias set mismatch: got {aliases}, expected {expected}"
    cur.close()


def test_retail_shape_rewrite_runs_under_pinned_collapse_limit(conn, retail_schema):
    cur = conn.cursor()
    cur.execute("SELECT purr.quantum_query_rewrite(%s)", (_RETAIL_QUERY,))
    rewritten = cur.fetchone()[0]

    conn.autocommit = False
    try:
        cur.execute("SET LOCAL join_collapse_limit = 1")
        cur.execute(rewritten)
        cur.fetchall()
        conn.commit()
    finally:
        conn.autocommit = True
    cur.close()


def test_retail_shape_rewrite_is_stable_across_runs(conn, retail_schema):
    """Repeat the rewrite 20 times; every run must succeed deterministically."""
    cur = conn.cursor()
    outputs = []
    for _ in range(20):
        cur.execute("SELECT purr.quantum_query_rewrite(%s)", (_RETAIL_QUERY,))
        outputs.append(cur.fetchone()[0])
    cur.close()
    assert all(out.lstrip().upper().startswith("SELECT") for out in outputs)
    # Determinism: identical input + seed → identical rewrite.
    assert all(out == outputs[0] for out in outputs)
