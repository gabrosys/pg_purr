#!/usr/bin/env bash
# Stop the test container and remove its volumes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

COMPOSE=(
    docker compose
    -f "${REPO_ROOT}/docker/docker-compose.test.yaml"
    -f "${PLANNER_DIR}/docker-compose.override.yaml"
)

echo "==> Tearing down the test container..."
"${COMPOSE[@]}" down -v --remove-orphans

echo
if docker ps --format '{{.Names}}' | grep -q '^pg-purr-test$'; then
    echo "!! Container still running — teardown did not complete."
    exit 1
fi

echo "All done. No residual container, no volume, no schema."
