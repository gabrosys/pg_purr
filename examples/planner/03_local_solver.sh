#!/usr/bin/env bash
# Run purr.quantum_query_plan on the demo query.
# QAOA on AerSimulator — no token needed, deterministic.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

echo "==> Calling purr.quantum_query_plan(...)..."
docker cp "${PLANNER_DIR}/query.sql" pg-purr-test:/tmp/query.sql >/dev/null

docker exec -i pg-purr-test bash -c '
QUERY=$(cat /tmp/query.sql)
psql -U test -d pg_purr_test <<SQL
SELECT step, table_name, estimated_cost
FROM purr.quantum_query_plan(
    \$q\$${QUERY}\$q\$
);
SQL
'

cat <<'EOF'

This is the join order chosen by the hybrid Qiskit pipeline:
candidate spanning trees of the predicate graph were generated
classically, QAOA on AerSimulator picked the lowest-cost tree, and
DFS linearisation produced the connected order printed above.

Each row is one table in the chosen JOIN order; estimated_cost is
PostgreSQL's own row-count estimate. The order is connected — every
new relation shares a predicate edge with at least one already in
scope — so PG never has to fall back to a Cartesian product.

Next: ./05_teardown.sh
EOF
