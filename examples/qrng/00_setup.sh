#!/usr/bin/env bash
# Boot the test container, install plpython3u + pg_purr, report the baseline pool state.
# Idempotent: safe to re-run against an already-running container.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="docker compose -f ${REPO_ROOT}/docker/docker-compose.test.yaml"

echo "==> Bringing up the test container..."
$COMPOSE up -d --build --wait

echo
echo "==> Installing the extension..."
docker exec pg-purr-test psql -U test -d pg_purr_test -v ON_ERROR_STOP=1 -c "
CREATE EXTENSION IF NOT EXISTS plpython3u;
CREATE EXTENSION IF NOT EXISTS pg_purr;
SELECT purr.pg_purr_version() AS pg_purr_version;
"

echo "==> Baseline pool state:"
docker exec pg-purr-test psql -U test -d pg_purr_test -c "
SELECT count(*) AS pool_size FROM purr.quantum_entropy;
"

cat <<'EOF'

Ready. The pool starts empty — no entropy has been fetched yet.

Next: ./01_show_empty_pool.sh
EOF
