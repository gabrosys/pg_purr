#!/usr/bin/env bash
# Boot the test container with the token layered in, install dwave-system
# inside the container, install the extension, and report token status.
# Idempotent: safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

# Source .env if present; otherwise the override file substitutes an empty
# token, the container still starts, and step 04 will print an opt-in notice.
if [[ -f "${PLANNER_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PLANNER_DIR}/.env"
    set +a
fi

COMPOSE=(
    docker compose
    -f "${REPO_ROOT}/docker/docker-compose.test.yaml"
    -f "${PLANNER_DIR}/docker-compose.override.yaml"
)

echo "==> Bringing up the test container..."
"${COMPOSE[@]}" up -d --build --wait

echo
echo "==> Installing dwave-system inside the container (first run: ~1-2 min)..."
docker exec pg-purr-test /opt/pg_purr/.venv/bin/pip install --quiet dwave-system

echo
echo "==> Installing the extension..."
docker exec pg-purr-test psql -U test -d pg_purr_test -v ON_ERROR_STOP=1 -c "
CREATE EXTENSION IF NOT EXISTS plpython3u;
CREATE EXTENSION IF NOT EXISTS pg_purr;
SELECT purr.pg_purr_version() AS pg_purr_version;
"

echo
echo "==> Token status:"
# Ask the container itself whether DWAVE_API_TOKEN is set. We check the
# postgres process's env via plpython3u so the answer reflects what the
# extension will actually see.
HAS_TOKEN=$(docker exec pg-purr-test psql -U test -d pg_purr_test -Atc "
DO LANGUAGE plpython3u \$\$
import os
plpy.notice('yes' if os.environ.get('DWAVE_API_TOKEN') else 'no')
\$\$;" 2>&1 | grep -oE 'yes|no' | head -1)

if [[ "${HAS_TOKEN}" == "yes" ]]; then
    cat <<'EOF'

DWAVE_API_TOKEN is set in the container — step 04 will use the real
D-Wave QPU.

Next: ./01_seed_schema.sh
EOF
else
    cat <<'EOF'

DWAVE_API_TOKEN is not set. Steps 01-03 and 05 work without a token.
Step 04 will print a one-paragraph opt-in notice and exit 0.

To enable the D-Wave path:
    cp examples/planner/.env.example examples/planner/.env
    # edit .env, paste your D-Wave Leap token
    ./05_teardown.sh && ./00_setup.sh

Next: ./01_seed_schema.sh
EOF
fi
