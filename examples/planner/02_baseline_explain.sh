#!/usr/bin/env bash
# Show PostgreSQL's own plan for the 13-table JOIN query.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

echo "==> GEQO configuration (default geqo_threshold = 12):"
docker exec pg-purr-test psql -U test -d pg_purr_test -c "
SHOW geqo;
SHOW geqo_threshold;
"

echo
echo "==> PostgreSQL's plan (EXPLAIN):"
docker cp "${PLANNER_DIR}/query.sql" pg-purr-test:/tmp/query.sql >/dev/null
docker exec pg-purr-test bash -c "
    echo 'EXPLAIN (FORMAT TEXT, COSTS)' > /tmp/explain.sql
    cat /tmp/query.sql >> /tmp/explain.sql
    psql -U test -d pg_purr_test -f /tmp/explain.sql
"

cat <<'EOF'

Read the plan top-down: the first table that appears is the deepest
left-leaf of the join tree — that is what PG chose to start from. Since
this is a 13-way join and geqo_threshold = 12, PostgreSQL used its
genetic optimiser (a heuristic) rather than exhaustive dynamic
programming to pick an order.

The next step runs the same query through pg_purr's hybrid Qiskit
pipeline (QAOA on AerSimulator) so you can compare the chosen order
against PG's own.

Next: ./03_local_solver.sh
EOF
