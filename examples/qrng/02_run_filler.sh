#!/usr/bin/env bash
# Run the pg-purr-filler daemon inside the container for ~30 s against the
# real QRNG chain (LfD primary, NIST fallback). Watch entropy arrive live.

set -euo pipefail

DURATION="${DURATION:-30}"
TARGET="${TARGET:-1000}"
THRESHOLD="${THRESHOLD:-500}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

cat <<EOF
==> Running pg-purr-filler for ${DURATION}s.

    target=${TARGET}  threshold=${THRESHOLD}  poll_interval=${POLL_INTERVAL}s

Watch the INFO / WARNING lines below. A successful pull emits:
    pg_purr.entropy_filler: refilled entropy pool with N values

If LfD is rate-limited or unreachable, you will see:
    pg_purr.qrng_client: QRNG source 'lfd' failed: ...
    pg_purr.qrng_client: QRNG: served from fallback source 'nist'

Both outcomes are valid — either way real quantum entropy ends up in
the pool.

EOF

# `timeout` sends SIGTERM which __main__.py handles cleanly.
# `|| true` keeps the script green when timeout exits non-zero on SIGTERM.
docker exec pg-purr-test bash -c "
    timeout --preserve-status ${DURATION}s /opt/pg_purr/.venv/bin/pg-purr-filler \
        --dsn 'host=localhost port=5432 dbname=pg_purr_test user=test password=test' \
        --target ${TARGET} \
        --threshold ${THRESHOLD} \
        --poll-interval ${POLL_INTERVAL} \
        --log-level INFO
" || true

echo
echo "==> Pool state after the run:"
docker exec pg-purr-test psql -U test -d pg_purr_test -c "
SELECT count(*)           AS pool_size,
       min(fetched_at)    AS oldest_value,
       max(fetched_at)    AS newest_value
FROM purr.quantum_entropy;
"

cat <<'EOF'

Real quantum random numbers now live in purr.quantum_entropy. Each row's
`value` is a uint16 (0-65535) and `fetched_at` is when the filler
inserted it.

Next: ./03_consume_and_inspect.sh — draw values out and check they look
uniform.
EOF
