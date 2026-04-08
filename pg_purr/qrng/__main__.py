"""CLI entrypoint for the pg_purr entropy-pool filler daemon.

Usage:
    python -m pg_purr.qrng --dsn "host=... dbname=... user=... password=..."
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

import psycopg2

from pg_purr.qrng.entropy_filler import (
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_POOL_TARGET,
    DEFAULT_POOL_THRESHOLD,
    run_forever,
)


def main() -> int:
    p = argparse.ArgumentParser(prog="pg-purr-filler")
    p.add_argument("--dsn", default=os.environ.get("PG_PURR_DSN"))
    p.add_argument("--target", type=int, default=DEFAULT_POOL_TARGET)
    p.add_argument("--threshold", type=int, default=DEFAULT_POOL_THRESHOLD)
    p.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S)
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.dsn:
        print("error: --dsn or PG_PURR_DSN required", file=sys.stderr)
        return 2

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    run_forever(
        conn_factory=lambda: psycopg2.connect(args.dsn),
        target=args.target,
        threshold=args.threshold,
        poll_interval_s=args.poll_interval,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
