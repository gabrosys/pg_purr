# Live QRNG demo

A hands-on walkthrough of the quantum random number generator shipped with [pg_purr](../..). In about five minutes you go from an empty entropy pool to real quantum random numbers arriving over HTTPS, verify their distribution looks uniform, and watch the daemon transparently fall back to a second source when the primary is unreachable.

This directory is meant to be self-contained: clone the repo, run the scripts in order, read what happens.

## What is going on, briefly

`pg_purr` is a PostgreSQL extension that exposes `purr.quantum_random()` — a drop-in replacement for SQL's `random()` whose values are drawn from a pool of true quantum random numbers. A small daemon (`pg-purr-filler`) keeps that pool topped up by calling an HTTP service that returns bytes from a real quantum random number generator.

Two external services are used, with automatic failover:

- **LfD OTH Regensburg** ([lfdr.de](https://lfdr.de/QRNG/)) — primary. A photon-detection QRNG card (ID Quantique Quantis PCIe) exposed over plain HTTP by a German research lab.
- **NIST Randomness Beacon v2.0** ([beacon.nist.gov](https://beacon.nist.gov)) — fallback. A US federal government service that publishes a 512-bit pulse every minute, each one signed and archived for public verification. Uses a photon-detector plus a Bell-test quantum source internally.

If the primary fails for any reason — rate limiting, network hiccup, service outage — the client walks the NIST pulse history to fulfil the request. The caller never sees the difference beyond a warning in the log.

## Prerequisites

- **Docker** with `docker compose`. Tested on Docker Desktop 29.x; any recent version should work.
- **Outbound HTTPS** to `lfdr.de` and `beacon.nist.gov`. If you are behind a strict corporate firewall you may need to allow these hosts.
- That is all. No Python on the host, no API keys, nothing else to install.

## The walkthrough

Six short lessons, one script each:

| Step | Script | What happens |
|---:|---|---|
| 0 | `00_setup.sh` | A PostgreSQL container boots with the `pg_purr` extension installed. The entropy pool starts empty. |
| 1 | `01_show_empty_pool.sh` | Calling `quantum_random()` on an empty pool **errors** — a function named "quantum random" refuses to silently return a non-quantum value. |
| 2 | `02_run_filler.sh` | The daemon runs for 30 seconds. Real quantum random numbers arrive into the pool over HTTPS. |
| 3 | `03_consume_and_inspect.sh` | Draw 1000 values. An ASCII histogram and a chi-square test confirm they look uniform. |
| 4 | `04_force_nist_fallback.sh` | Deliberately point the primary URL at an invalid host. Watch the chain automatically serve the request from NIST Beacon instead. |
| 5 | `05_teardown.sh` | Stop the container, remove the volume. |

Run them in order, from the repository root:

```bash
cd examples/qrng
./00_setup.sh
./01_show_empty_pool.sh
./02_run_filler.sh
./03_consume_and_inspect.sh
./04_force_nist_fallback.sh
./05_teardown.sh
```

Each script narrates what it is doing and what good output looks like. The container keeps running between steps, so you can open a psql session at any time and poke around:

```bash
docker exec -it pg-purr-test psql -U test -d pg_purr_test
```

## Tunables

Environment variables picked up by the scripts:

| Variable | Default | Script | What it does |
|---|---:|---|---|
| `DURATION` | `30` | `02` | Seconds the filler daemon runs for. |
| `TARGET` | `1000` | `02` | Fill the pool to this many values. |
| `THRESHOLD` | `500` | `02` | Trigger a refill when the pool drops below this. |
| `POLL_INTERVAL` | `5` | `02` | Seconds between refill checks. |
| `N` | `1000` | `03` | Number of samples to draw for the distribution check. |

Example — a longer, larger run:

```bash
DURATION=60 TARGET=5000 THRESHOLD=2500 ./02_run_filler.sh
N=5000 ./03_consume_and_inspect.sh
```

## Troubleshooting

**Step 2 is quiet for most of the 30 seconds.** The LfD service may be rate-limiting you, or a single request is taking longer than usual. Look for a `source 'lfd' failed` line followed by `served from fallback source 'nist'` — that is the chain doing its job, and the pool will still fill (more slowly, because NIST's per-request throughput is lower).

**Step 3's histogram looks very skewed.** The default of 1000 samples gives a statistically reliable verdict, but the chi-square test is still inherently probabilistic — about 1% of runs on truly uniform data will land below `p = 0.01` by pure chance. If it happens, rerun the step; persistent skew across several runs is a signal to truncate the pool and rerun step 2 to rule out stale values.

**Step 4 reports both sources failed.** A firewall or proxy may be blocking both `beacon.nist.gov` and `lfdr.de`. That is still a valid outcome — it confirms the extension raises a clean `RuntimeError("all QRNG sources failed: …")` rather than hanging.

**After step 5 `docker ps` shows nothing related to pg_purr.** That is the expected state. Re-run `00_setup.sh` to start over.
