#!/usr/bin/env bash
# Deliberately break the primary source and observe the NIST fallback.

set -euo pipefail

cat <<'EOF'
==> Pointing LFD_API_URL at an invalid host, then fetching 5 uint16 values.

Expected output includes both:
    WARNING  pg_purr.qrng_client: QRNG source 'lfd' failed: ...
    WARNING  pg_purr.qrng_client: QRNG: served from fallback source 'nist'

followed by 5 real uint16 values served by the NIST Randomness Beacon.
EOF
echo

docker exec -i pg-purr-test /opt/pg_purr/.venv/bin/python - <<'PY'
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s  %(name)s: %(message)s")

from pg_purr.qrng import qrng_client

# Sabotage the primary. The fallback should transparently serve the request.
qrng_client.LFD_API_URL = "https://example.invalid/qrng"

values = qrng_client.fetch_quantum_random(count=5, data_type="uint16")
print()
print(f"got {len(values)} values via fallback:", values)
PY

cat <<'EOF'

The chain worked under induced failure. In production this is the
self-healing behaviour you inherit for free: a single source outage
does not take down the entropy supply.

Next: ./05_teardown.sh
EOF
