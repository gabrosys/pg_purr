"""Shared planner pipeline used by the SQL-callable functions.

`quantum_query_plan` and `quantum_query_rewrite` both run the same
validate → EXPLAIN → parse → QUBO → solve → decode pipeline; the only
difference is what they do with the resulting order.
"""

from __future__ import annotations

import json

from pg_purr.planner.explain_parser import parse_explain_json
from pg_purr.planner.qubo_builder import build_qubo
from pg_purr.planner.query_validator import (
    UnsupportedQueryError,
    validate_and_build_explain_sql,
)
from pg_purr.planner.solver import (
    SolverError,
    decode_solution,
    solve_dwave,
    solve_local,
)


def compute_optimal_order(plpy, query: str, use_dwave: bool) -> tuple[list[str], dict[str, float]]:
    """Return `(optimal_order, row_counts)` for `query`.

    `plpy` is the PL/Python module proxy injected into the calling
    function body. `optimal_order` is a list of table aliases in the
    order chosen by the QUBO solver; `row_counts` maps each alias to
    its `Plan Rows` estimate from EXPLAIN. Trivial inputs short-circuit:

    * no tables   -> ([], {})
    * one table   -> ([t], {t: <rows>})

    All `plpy.error` exits propagate as PG errors; the function does
    not return on those paths.
    """
    try:
        explain_sql = validate_and_build_explain_sql(plpy, query)
    except UnsupportedQueryError as e:
        plpy.error(f"pg_purr: rejected query: {e}")

    explain_result = plpy.execute(explain_sql)
    explain_json = json.loads(explain_result[0]["QUERY PLAN"])
    join_graph = parse_explain_json(explain_json)

    if not join_graph.tables:
        return [], {}
    if len(join_graph.tables) < 2:
        return list(join_graph.tables), dict(join_graph.row_counts)

    bqm = build_qubo(join_graph)

    if use_dwave:
        try:
            sample_set = solve_dwave(bqm)
        except (SolverError, ImportError) as e:
            plpy.warning(f"pg_purr: D-Wave unavailable ({e}), falling back to local solver")
            sample_set = solve_local(bqm)
    else:
        sample_set = solve_local(bqm)

    try:
        optimal_order = decode_solution(sample_set, join_graph.tables)
    except SolverError as e:
        plpy.error(f"pg_purr: {e}")

    return optimal_order, dict(join_graph.row_counts)
