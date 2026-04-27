-- pg_purr 0.1.0 -> 0.2.0
-- SPDX-License-Identifier: MIT
\echo Use "ALTER EXTENSION pg_purr UPDATE" to load this file. \quit

-- The 0.2.0 release rewires the planner around a Qiskit-based
-- hybrid pipeline (predicate graph -> candidate spanning trees ->
-- QAOA selection on AerSimulator -> DFS linearisation). The
-- public surface narrows: `purr.quantum_query_plan` loses the
-- backend-selection parameter, and a new `purr.quantum_query_rewrite`
-- is added. The 0.1.0 function must be dropped before the new
-- signature can be created.

DROP FUNCTION purr.quantum_query_plan(TEXT, BOOLEAN);

CREATE FUNCTION purr.quantum_query_plan(query TEXT)
RETURNS TABLE(step INT, table_name TEXT, estimated_cost FLOAT8)
LANGUAGE plpython3u
VOLATILE
PARALLEL UNSAFE
SECURITY INVOKER
COST 10000
SET search_path = purr, pg_catalog
AS $PL$
    from pg_purr.planner.pipeline import compute_optimal_order

    optimal_order, row_counts = compute_optimal_order(plpy, query)

    return [
        {
            "step": idx + 1,
            "table_name": table,
            "estimated_cost": row_counts.get(table, 0.0),
        }
        for idx, table in enumerate(optimal_order)
    ]
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_query_plan(TEXT) FROM PUBLIC;

CREATE FUNCTION purr.quantum_query_rewrite(query TEXT)
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

    optimal_order, _ = compute_optimal_order(plpy, query)

    if len(optimal_order) < 2:
        return query

    try:
        return rewrite_query(query, optimal_order)
    except UnsupportedQueryError as e:
        plpy.error(f"pg_purr: cannot rewrite query: {e}")
$PL$;

REVOKE ALL ON FUNCTION purr.quantum_query_rewrite(TEXT) FROM PUBLIC;
