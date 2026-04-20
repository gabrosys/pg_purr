#!/usr/bin/env bash
# Draw N quantum random values, then inspect the distribution.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
N="${N:-1000}"

echo "==> Ensuring pool has at least ${N} values..."
POOL_SIZE=$(docker exec pg-purr-test psql -U test -d pg_purr_test -Atc \
    "SELECT count(*) FROM purr.quantum_entropy;")

if [[ "$POOL_SIZE" -lt "$N" ]]; then
    echo "   Pool has ${POOL_SIZE} < ${N}. Running a short filler burst..."
    docker exec pg-purr-test bash -c "
        timeout --preserve-status 20s /opt/pg_purr/.venv/bin/pg-purr-filler \
            --dsn 'host=localhost port=5432 dbname=pg_purr_test user=test password=test' \
            --target ${N} --threshold ${N} --poll-interval 2 --log-level INFO
    " || true
fi

echo
echo "==> Drawing ${N} quantum random values..."
docker exec pg-purr-test psql -U test -d pg_purr_test -Atc "
SELECT (purr.quantum_random() * 65536)::int FROM generate_series(1, ${N});
" > /tmp/pg_purr_samples.txt

echo "   First 10 samples:"
head -10 /tmp/pg_purr_samples.txt | sed 's/^/     /'

echo
echo "==> Distribution analysis:"
docker cp "${REPO_ROOT}/examples/qrng/inspect_distribution.py" \
    pg-purr-test:/tmp/inspect_distribution.py >/dev/null
# `docker exec -i` attaches stdin so the python process actually receives
# the piped samples.
docker exec -i pg-purr-test /opt/pg_purr/.venv/bin/python \
    /tmp/inspect_distribution.py < /tmp/pg_purr_samples.txt

rm -f /tmp/pg_purr_samples.txt

cat <<'EOF'

A uniform distribution across 16 buckets with chi-square p-value above
~0.01 is exactly what you want. If the bars look flat and the verdict
line reads "consistent with uniform", you just consumed entropy that
came from a real photon-detector measurement.

Next: ./04_force_nist_fallback.sh — break the primary source and see
the chain pick the NIST Beacon instead.
EOF
