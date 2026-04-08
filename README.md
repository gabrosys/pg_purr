[![CI](https://github.com/gabrosys/pg_purr/actions/workflows/ci.yaml/badge.svg)](https://github.com/gabrosys/pg_purr/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

# pg_purr

**P**ostgreSQL **U**nified **R**andom & **R**outing.

A PostgreSQL extension (via PL/Python) that brings quantum computing capabilities to your database:

1. **Quantum Query Planner** — optimise complex JOIN ordering using quantum annealing (D-Wave or simulated), outperforming PostgreSQL's GEQO for queries with 12+ tables.
2. **QRNG (Quantum Random Number Generator)** — replace `random()` with true quantum randomness served from a pre-filled entropy pool. The default source is the LfD OTH Regensburg QRNG service (ID Quantique Quantis photon-detection hardware); the NIST Randomness Beacon is documented as a drop-in alternative.

## Requirements

- PostgreSQL 17 or 18 with `plpython3u`
- Python 3.11+ with: `dwave-neal`, `dimod`, `requests`, `numpy`, `pglast`
- Optional: `dwave-system` for real D-Wave quantum hardware

## Quick start

```bash
# Build the Docker image (PG17 + plpython3u + pg_purr)
make docker-build

# Run unit tests
make test

# Run integration tests (starts a PG container)
make test-integration

# Test against a specific PG version
make test-integration PG_VERSION=18

# Test against all supported PG versions
make test-all-versions
```

## Installation

### 1. Install the Python package on the server

```bash
pip install .
```

This must run against the Python interpreter used by `plpython3u` on the target PostgreSQL server.

### 2. Install the extension SQL into PostgreSQL's share dir

```bash
make pg-install     # copies pg_purr.control + sql/extension/pg_purr--0.1.0.sql
                    # into $(pg_config --sharedir)/extension/
```

### 3. Create the extension

```sql
CREATE EXTENSION pg_purr;  -- requires superuser (depends on plpython3u)
```

All pg_purr objects live in the `purr` schema. Address them with a fully-qualified name (e.g., `purr.quantum_random()`).

## SQL functions

```sql
-- Quantum Query Planner: get an optimal JOIN order for a complex query.
-- Queries must use fully-qualified table names.
SELECT * FROM purr.quantum_query_plan(
    'SELECT ... FROM public.t1 JOIN public.t2 ON ... (15+ tables)',
    use_dwave := false
);

-- QRNG: get a true quantum random number in [0, 1).
-- Requires a populated entropy pool (see "Running the entropy filler").
SELECT purr.quantum_random();

-- QRNG: get a quantum random number in a custom range.
SELECT purr.quantum_random_in_range(0.0, 100.0);

-- Explicit non-quantum PRNG wrapper (no entropy pool required).
SELECT purr.prng_random();

-- Extension version.
SELECT purr.pg_purr_version();
```

## Configuration

### D-Wave token

The quantum query planner can use real D-Wave quantum hardware. The token is read from the `DWAVE_API_TOKEN` environment variable of the PostgreSQL server process.

- **Bare metal / VM:** add `Environment=DWAVE_API_TOKEN=...` to a `postgresql.service` drop-in unit and restart.
- **CloudNativePG:** set `spec.env[].valueFrom.secretKeyRef` on the Cluster manifest so the token flows in from a Kubernetes Secret.
- **Docker / plain k8s:** inject the variable into the container environment.
- **RDS / CloudSQL:** not supported (no user-controlled process env); use the local solver or run D-Wave outside the database.

Get a free token at [D-Wave Leap](https://cloud.dwavesys.com/leap/).

### Network egress (entropy pool fallback)

`purr.quantum_random()` never performs network I/O from inside a backend. If the entropy pool is empty it raises an error by default. To allow a non-quantum PRNG fallback when the pool is empty:

```sql
ALTER SYSTEM SET pg_purr.allow_prng_fallback = 'on';
SELECT pg_reload_conf();
```

When the fallback fires, the function emits a `WARNING` and the returned value is `random()` — not quantum.

### Permissions

All pg_purr functions are revoked from `PUBLIC` on install. Grant explicitly:

```sql
GRANT USAGE ON SCHEMA purr TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_random() TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_random_in_range(FLOAT8, FLOAT8) TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_query_plan(TEXT, BOOLEAN) TO your_role;
GRANT EXECUTE ON FUNCTION purr.prng_random() TO your_role;
```

## Running the entropy filler

`purr.quantum_random()` consumes pre-filled entropy. A separate daemon fetches values from the QRNG HTTP endpoint (LfD OTH Regensburg by default) and keeps the pool above a configurable threshold.

```bash
pg-purr-filler --dsn "host=... dbname=... user=pg_purr_filler password=..."
```

Or in Docker:

```bash
python -m pg_purr.qrng --dsn "$PG_PURR_DSN" --target 2000 --threshold 500
```

The filler is safe to run as a long-lived service (systemd, Kubernetes Deployment, Docker Compose service).

## Architecture

```
  PostgreSQL 17 / 18
  ├── purr schema
  │   ├── quantum_query_plan()  ──> pg_purr.planner
  │   │   ├── query_validator  (plpy.prepare + semicolon reject)
  │   │   ├── explain_parser   (EXPLAIN JSON → JoinGraph)
  │   │   ├── qubo_builder     (JoinGraph → QUBO Hamiltonian)
  │   │   ├── solver           (QUBO → optimal order via annealing)
  │   │   └── query_rewriter   (reorder SQL JOINs via AST)
  │   ├── quantum_random()     ──> quantum_entropy pool (UNLOGGED)
  │   ├── quantum_random_in_range(low, high)
  │   ├── prng_random()        ──> SQL random() wrapper
  │   └── pg_purr_version()
  │
  └── pg-purr-filler (out-of-process daemon)
      └── QRNG HTTP endpoint (LfD) ──> purr.quantum_entropy
```

## Uninstall

```sql
DROP EXTENSION pg_purr;
```

Then optionally:

```bash
make pg-uninstall
```

## License

MIT
