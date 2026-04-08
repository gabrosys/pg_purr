"""Fill the PostgreSQL quantum_entropy pool with true random numbers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from psycopg2.extras import execute_values

from pg_purr.qrng.qrng_client import fetch_quantum_random

DEFAULT_POOL_TARGET = 2000
DEFAULT_POOL_THRESHOLD = 500
DEFAULT_POLL_INTERVAL_S = 30.0
DEFAULT_BACKOFF_MAX_S = 600.0

log = logging.getLogger("pg_purr.entropy_filler")


def get_pool_size(conn) -> int:
    """Return the number of entropy values in the pool."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM purr.quantum_entropy")
        return cur.fetchone()[0]
    finally:
        cur.close()


def fill_entropy_pool(
    conn,
    target: int = DEFAULT_POOL_TARGET,
    threshold: int = DEFAULT_POOL_THRESHOLD,
) -> int:
    """Fetch quantum random values and insert them into the entropy pool.

    Requires `conn.autocommit = True`. Holding an open transaction
    across the HTTP fetch would leave the backend `idle in transaction`
    for up to a minute or more on the fallback path, which any
    well-configured `idle_in_transaction_session_timeout` would kill.

    Only fills if current pool size is below threshold. Returns the
    number of values inserted (0 if pool was above threshold).
    """
    current = get_pool_size(conn)
    if current >= threshold:
        return 0

    needed = target - current
    values = fetch_quantum_random(count=needed, data_type="uint16")

    cur = conn.cursor()
    try:
        execute_values(
            cur,
            "INSERT INTO purr.quantum_entropy (value) VALUES %s",
            [(v,) for v in values],
        )
        # No-op under autocommit per psycopg2 docs; safety net otherwise.
        conn.commit()
    finally:
        cur.close()

    return len(values)


def run_forever(
    conn_factory: Callable[[], object],
    target: int = DEFAULT_POOL_TARGET,
    threshold: int = DEFAULT_POOL_THRESHOLD,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    backoff_max_s: float = DEFAULT_BACKOFF_MAX_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll the pool; refill when below threshold.

    `conn_factory` is invoked each iteration so a stale connection gets
    replaced. The returned connection is put into autocommit mode so
    no transaction is held across the HTTP fetch. On any exception,
    back off exponentially up to `backoff_max_s` before retrying.
    `sleep` is injectable for testing.
    """
    backoff = poll_interval_s
    while True:
        try:
            conn = conn_factory()
            conn.autocommit = True
            try:
                inserted = fill_entropy_pool(conn, target=target, threshold=threshold)
            finally:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
            if inserted:
                log.info("refilled entropy pool with %d values", inserted)
            backoff = poll_interval_s
        except Exception as exc:
            log.warning("refill failed, backing off %.1fs: %s", backoff, exc)
            sleep(backoff)
            backoff = min(backoff * 2, backoff_max_s)
            continue
        sleep(poll_interval_s)
