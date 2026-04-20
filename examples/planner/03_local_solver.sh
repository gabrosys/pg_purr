#!/usr/bin/env bash
# Run purr.quantum_query_plan with use_dwave := false.
# Classical simulated annealing on CPU — no token needed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

echo "==> Calling purr.quantum_query_plan(..., use_dwave := false)..."
docker cp "${PLANNER_DIR}/query.sql" pg-purr-test:/tmp/query.sql >/dev/null

# The query must be passed as a single text argument to the function.
# Use dollar-quoting ($q$ ... $q$) to avoid escaping the single quotes
# inside the WHERE clause. The whole SELECT is built on the fly as a
# here-doc piped into psql.
docker exec -i pg-purr-test bash -c '
QUERY=$(cat /tmp/query.sql)
psql -U test -d pg_purr_test <<SQL
SELECT step, table_name, estimated_cost
FROM purr.quantum_query_plan(
    \$q\$${QUERY}\$q\$,
    use_dwave := false
);
SQL
'

cat <<'EOF'

This is the QUBO-based ordering solved by classical simulated
annealing (dwave-neal, CPU). Each row is one table in the chosen
JOIN order; estimated_cost is PostgreSQL's own row-count estimate
used as the QUBO weight.

All 13 tables should appear exactly once, with step values 1..13.

Next: ./04_dwave_solver.sh — same query, real D-Wave QPU (needs a
token).
EOF
