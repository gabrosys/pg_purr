#!/usr/bin/env bash
# Prove the strict-default contract: an empty pool makes quantum_random() error
# rather than silently downgrade to PG random().

set -euo pipefail

echo "==> Draining the pool and confirming allow_prng_fallback is off..."
docker exec pg-purr-test psql -U test -d pg_purr_test -v ON_ERROR_STOP=1 -c "
TRUNCATE purr.quantum_entropy;
SET pg_purr.allow_prng_fallback = off;
SELECT count(*) AS pool_size FROM purr.quantum_entropy;
"

echo
echo "==> Calling purr.quantum_random() on an empty pool (expected: ERROR)..."
# Capture both stdout and stderr so the error message is visible.
# The `|| true` + exit-code check is because psql exits non-zero on ERROR.
set +e
OUTPUT=$(docker exec pg-purr-test psql -U test -d pg_purr_test -c "
SET pg_purr.allow_prng_fallback = off;
SELECT purr.quantum_random();
" 2>&1)
RC=$?
set -e

echo "$OUTPUT"

if [[ $RC -ne 0 ]] && echo "$OUTPUT" | grep -q "entropy pool empty"; then
    cat <<'EOF'

That is the contract. A function named quantum_random() refuses to
return a non-quantum value on an empty pool. The operator who wants
silent PRNG fallback must opt in explicitly via:

    ALTER SYSTEM SET pg_purr.allow_prng_fallback = 'on';
    SELECT pg_reload_conf();

Next: ./02_run_filler.sh — put real entropy into the pool.
EOF
    exit 0
else
    echo
    echo "!! Unexpected outcome. Expected an ERROR about 'entropy pool empty'."
    echo "!! See the output above."
    exit 1
fi
