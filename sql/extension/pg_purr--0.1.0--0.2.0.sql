-- pg_purr 0.1.0 -> 0.2.0
-- SPDX-License-Identifier: MIT
\echo Use "ALTER EXTENSION pg_purr UPDATE" to load this file. \quit

-- ------------------------------------------------------------------------
-- Refactor quantum_query_plan body to delegate to the shared pipeline
-- helper. Signature and result shape are unchanged.
-- ------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION purr.quantum_query_plan(
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

-- ------------------------------------------------------------------------
-- New: quantum_query_rewrite. Returns the rewritten SELECT, ready for
-- EXECUTE under `SET LOCAL join_collapse_limit = 1`. See the 0.2.0
-- base SQL for the full contract.
-- ------------------------------------------------------------------------
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
