#!/usr/bin/env bash
# Run purr.quantum_query_plan with use_dwave := true — real QPU.
# No-op with a clear opt-in notice if DWAVE_API_TOKEN is not set.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNER_DIR="${REPO_ROOT}/examples/planner"

HAS_TOKEN=$(docker exec pg-purr-test psql -U test -d pg_purr_test -Atc "
DO LANGUAGE plpython3u \$\$
import os
plpy.notice('yes' if os.environ.get('DWAVE_API_TOKEN') else 'no')
\$\$;" 2>&1 | grep -oE 'yes|no' | head -1)

if [[ "${HAS_TOKEN}" != "yes" ]]; then
    cat <<'EOF'
==> DWAVE_API_TOKEN is not set in the container.

This step would submit the JOIN-ordering QUBO to a real D-Wave
quantum processing unit. To enable it:

    1. Sign up for a free D-Wave Leap account:
         https://cloud.dwavesys.com/leap/signup/
    2. Copy your API token from the Leap dashboard.
    3. Create examples/planner/.env by copying .env.example, and
       paste the token there.
    4. Re-run the setup so the token reaches the container:
         ./05_teardown.sh && ./00_setup.sh
    5. Re-run this step.

The free tier grants 1 minute of QPU time per month. Each call in
this demo uses single-digit milliseconds, so one month's quota is
plenty for repeated runs.

Skipping the D-Wave call. Next: ./05_teardown.sh
EOF
    exit 0
fi

cat <<'EOF'
==> Token detected. Submitting the JOIN-ordering QUBO to a real D-Wave QPU.

The first call in a fresh container is slower (~5-10 s) — the SDK
downloads solver metadata and performs minor embedding onto the QPU's
topology. Subsequent calls are milliseconds.

EOF

docker cp "${PLANNER_DIR}/query.sql" pg-purr-test:/tmp/query.sql >/dev/null

docker exec -i pg-purr-test bash -c '
QUERY=$(cat /tmp/query.sql)
psql -U test -d pg_purr_test <<SQL
SELECT step, table_name, estimated_cost
FROM purr.quantum_query_plan(
    \$q\$${QUERY}\$q\$,
    use_dwave := true
);
SQL
'

cat <<'EOF'

Verification: open https://cloud.dwavesys.com/leap/ and navigate to
Problems. A new entry should appear within a minute, listing the QPU
used, the problem size, and the microseconds of QPU-access time
consumed.

Next: ./05_teardown.sh
EOF
