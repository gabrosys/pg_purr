-- pg_purr 0.2.0
-- SPDX-License-Identifier: MIT
\echo Use "CREATE EXTENSION pg_purr" to load this file. \quit

-- ========================================================================
-- Entropy pool
-- ========================================================================
CREATE UNLOGGED TABLE purr.quantum_entropy (
    id         BIGSERIAL PRIMARY KEY,
    value      INT4 NOT NULL CHECK (value BETWEEN 0 AND 65535),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
WITH (
    autovacuum_vacuum_scale_factor = 0.0,
    autovacuum_vacuum_threshold = 500,
    autovacuum_analyze_scale_factor = 0.0,
    autovacuum_analyze_threshold = 500
);

REVOKE ALL ON TABLE purr.quantum_entropy FROM PUBLIC;
SELECT pg_catalog.pg_extension_config_dump('purr.quantum_entropy', '');

-- ========================================================================
-- Quantum random: consumes one entry from the pool.
-- Empty pool is a hard error unless pg_purr.allow_prng_fallback is set.
-- ========================================================================
CREATE FUNCTION purr.quantum_random()
RETURNS FLOAT8
LANGUAGE plpython3u
VOLATILE
PARALLEL UNSAFE
SECURITY INVOKER
COST 10000
SET search_path = purr, pg_catalog
AS $PL$
    result = plpy.execute("""
        WITH oldest AS (
            SELECT id FROM purr.quantum_entropy
            ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
        )
        DELETE FROM purr.quantum_entropy USING oldest
        WHERE purr.quantum_entropy.id = oldest.id
        RETURNING purr.quantum_entropy.value
    """)

    if result.nrows() > 0:
        return result[0]["value"] / 65536.0

    guc = plpy.execute(
        "SELECT current_setting('pg_purr.allow_prng_fallback', true) AS v"
    )
    allow = (guc[0]["v"] or "").lower()
    if allow in ("on", "true", "yes", "1"):
        plpy.warning(
            "pg_purr: entropy pool empty; returning pg random() because "
            "pg_purr.allow_prng_fallback is enabled -- NOT quantum"
        )
        return plpy.execute("SELECT random() AS r")[0]["r"]

    plpy.error(
        "pg_purr: entropy pool empty and pg_purr.allow_prng_fallback is "
        "not enabled. Run the pg-purr-filler daemon or "
        "SET pg_purr.allow_prng_fallback = 'on' to permit PRNG fallback."
    )
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_random() FROM PUBLIC;

-- ========================================================================
-- Quantum random in a caller-specified range.
-- ========================================================================
CREATE FUNCTION purr.quantum_random_in_range(low FLOAT8, high FLOAT8)
RETURNS FLOAT8
LANGUAGE plpython3u
VOLATILE
PARALLEL UNSAFE
SECURITY INVOKER
COST 10000
SET search_path = purr, pg_catalog
AS $PL$
    if low >= high:
        plpy.error("pg_purr: low must be less than high")
    result = plpy.execute("SELECT purr.quantum_random() AS qr")
    qr = result[0]["qr"]
    return low + qr * (high - low)
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_random_in_range(FLOAT8, FLOAT8) FROM PUBLIC;

-- ========================================================================
-- Explicit PRNG wrapper for callers who want PG random() on purpose.
-- ========================================================================
CREATE FUNCTION purr.prng_random()
RETURNS FLOAT8
LANGUAGE SQL
VOLATILE
PARALLEL SAFE
SECURITY INVOKER
AS $$
    SELECT random()
$$;

REVOKE ALL ON FUNCTION purr.prng_random() FROM PUBLIC;

-- ========================================================================
-- Quantum query planner — returns the QUBO-chosen join order as a
-- table of (step, table_name, estimated_cost) rows. Advisory only:
-- the caller must reorder the query themselves (or use
-- quantum_query_rewrite below).
--
-- Input is validated via plpy.prepare (PG's own parser), which rejects
-- multi-statement input and ill-formed SQL. Non-SELECT shapes that
-- pass the parser are rejected by EXPLAIN itself. Per-caller access to
-- functions or tables is enforced by SECURITY INVOKER. Callers must
-- pass schema-qualified table references -- `public` is not in the
-- function's search_path. D-Wave token is read from the
-- DWAVE_API_TOKEN environment variable.
-- ========================================================================
CREATE FUNCTION purr.quantum_query_plan(
    query TEXT,
    use_dwave BOOLEAN DEFAULT false
)
RETURNS TABLE(step INT, table_name TEXT, estimated_cost FLOAT8)
LANGUAGE plpython3u
VOLATILE
PARALLEL UNSAFE
SECURITY INVOKER
COST 10000
SET search_path = purr, pg_catalog
AS $PL$
    from pg_purr.planner.pipeline import compute_optimal_order

    optimal_order, row_counts = compute_optimal_order(plpy, query, use_dwave)

    return [
        {
            "step": idx + 1,
            "table_name": table,
            "estimated_cost": row_counts.get(table, 0.0),
        }
        for idx, table in enumerate(optimal_order)
    ]
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_query_plan(TEXT, BOOLEAN) FROM PUBLIC;

-- ========================================================================
-- Quantum query rewriter — runs the same QUBO pipeline as
-- quantum_query_plan and returns the rewritten SELECT, ready for
-- EXECUTE. The rewrite is a left-deep INNER-JOIN tree in the chosen
-- order with all original ON predicates hoisted into WHERE
-- (semantics-preserving for INNER joins).
--
-- The returned text does NOT contain a `SET LOCAL join_collapse_limit`
-- prefix: callers must pin `join_collapse_limit = 1` themselves
-- (typically inside a transaction) so PG honours the order verbatim.
--
-- Rejects (with an error) anything the rewriter cannot safely
-- reorder: outer joins, NATURAL/USING, CTEs, set operations,
-- subqueries in FROM. Trivial inputs (zero or one table) are
-- returned unchanged.
-- ========================================================================
CREATE FUNCTION purr.quantum_query_rewrite(
    query TEXT,
    use_dwave BOOLEAN DEFAULT false
)
RETURNS TEXT
LANGUAGE plpython3u
VOLATILE
PARALLEL UNSAFE
SECURITY INVOKER
COST 10000
SET search_path = purr, pg_catalog
AS $PL$
    from pg_purr.planner.pipeline import compute_optimal_order
    from pg_purr.planner.query_rewriter import rewrite_query
    from pg_purr.planner.query_validator import UnsupportedQueryError

    optimal_order, _ = compute_optimal_order(plpy, query, use_dwave)

    if len(optimal_order) < 2:
        return query

    try:
        return rewrite_query(query, optimal_order)
    except UnsupportedQueryError as e:
        plpy.error(f"pg_purr: cannot rewrite query: {e}")
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_query_rewrite(TEXT, BOOLEAN) FROM PUBLIC;

-- ========================================================================
-- Extension version.
-- ========================================================================
CREATE FUNCTION purr.pg_purr_version()
RETURNS TEXT
LANGUAGE SQL
STABLE
PARALLEL SAFE
AS $$
    SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'pg_purr'
$$;

REVOKE ALL ON FUNCTION purr.pg_purr_version() FROM PUBLIC;
