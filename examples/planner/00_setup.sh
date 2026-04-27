#!/usr/bin/env bash
# Boot the test container, install the extension, report whether an
# IBM Quantum token is available. Idempotent: safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

# Source .env if present; otherwise the override file substitutes empty
# values, the container starts, and the demo runs on the local
# AerSimulator.
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
echo "==> Installing the extension..."
docker exec pg-purr-test psql -U test -d pg_purr_test -v ON_ERROR_STOP=1 -c "
CREATE EXTENSION IF NOT EXISTS plpython3u;
CREATE EXTENSION IF NOT EXISTS pg_purr;
SELECT purr.pg_purr_version() AS pg_purr_version;
"

echo
echo "==> IBM Quantum token status:"
HAS_TOKEN=$(docker exec pg-purr-test psql -U test -d pg_purr_test -Atc "
DO LANGUAGE plpython3u \$\$
import os
plpy.notice('yes' if os.environ.get('QISKIT_IBM_TOKEN') else 'no')
\$\$;" 2>&1 | grep -oE 'yes|no' | head -1)

if [[ "${HAS_TOKEN}" == "yes" ]]; then
    cat <<'EOF'

QISKIT_IBM_TOKEN is set in the container — the planner can target
real IBM Quantum hardware via qiskit-ibm-runtime. Note that real
hardware runs are subject to queue waits and Open Plan quotas.

Next: ./01_seed_schema.sh
EOF
else
    cat <<'EOF'

QISKIT_IBM_TOKEN is not set. The planner will run on the local
AerSimulator — fully offline, deterministic, no quotas. This is
the recommended path for the demo.

To enable the IBM Quantum hardware path:
    cp examples/planner/.env.example examples/planner/.env
    # edit .env, paste your IBM Quantum token + instance metadata
    ./05_teardown.sh && ./00_setup.sh

Next: ./01_seed_schema.sh
EOF
fi
