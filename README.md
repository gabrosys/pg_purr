[![CI](https://github.com/gabrosys/pg_purr/actions/workflows/ci.yaml/badge.svg)](https://github.com/gabrosys/pg_purr/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

# pg_purr

**P**ostgreSQL **U**nified **R**andom & **R**outing.

A PostgreSQL extension (via PL/Python) that brings quantum
computing to your database:

1. **Quantum-augmented Query Planner** — a hybrid Qiskit pipeline
   that picks a connectivity-preserving join order for queries
   with up to ~17 base relations. The classical scaffolding (k
   spanning-tree candidates + DFS linearisation) guarantees every
   emitted order is connected; QAOA on a local AerSimulator picks
   the best candidate. Optional: target IBM Quantum hardware via
   `qiskit-ibm-runtime` when a token is supplied.
2. **QRNG (Quantum Random Number Generator)** — replace `random()`
   with true quantum randomness served from a pre-filled entropy
   pool. The default source is the LfD OTH Regensburg QRNG service
   (ID Quantique Quantis photon-detection hardware); the NIST
   Randomness Beacon is documented as a drop-in alternative.

## Requirements

- PostgreSQL 17 or 18 with `plpython3u`
- Python 3.11+ with: `qiskit`, `qiskit-aer`, `qiskit-algorithms`,
  `qiskit-optimization`, `qiskit-ibm-runtime`, `networkx`, `numpy`,
  `requests`, `sqlglot`

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

## Try it live

Two hands-on demos live under `examples/`:

- **`examples/qrng/`** — walkthrough of the QRNG against real
  quantum random number services (LfD OTH Regensburg + NIST
  Randomness Beacon). Six scripts; boots a container, fills the
  entropy pool over HTTPS, confirms the distribution is uniform,
  and demonstrates the automatic fallback when the primary source
  fails. No credentials needed.

  ```bash
  cd examples/qrng
  ./00_setup.sh && ./01_show_empty_pool.sh && ./02_run_filler.sh
  ./03_consume_and_inspect.sh && ./04_force_nist_fallback.sh
  ./05_teardown.sh
  ```

- **`examples/planner/`** — walkthrough of
  `purr.quantum_query_plan` and `purr.quantum_query_rewrite` on a
  multi-table retail schema. Boots a container, seeds the schema,
  compares PostgreSQL's own GEQO plan against the hybrid quantum
  planner running on `AerSimulator` by default. An IBM Quantum
  backend is opt-in via `QISKIT_IBM_TOKEN` — the demo's README
  documents the token setup.

  ```bash
  cd examples/planner
  ./00_setup.sh && ./01_seed_schema.sh && ./02_baseline_explain.sh
  ./03_local_solver.sh
  ./05_teardown.sh
  ```

## Installation

### 1. Install the Python package on the server

```bash
pip install .
```

This must run against the Python interpreter used by `plpython3u`
on the target PostgreSQL server.

### 2. Install the extension SQL into PostgreSQL's share dir

```bash
make pg-install     # copies pg_purr.control + sql/extension/pg_purr--*.sql
                    # into $(pg_config --sharedir)/extension/
```

### 3. Create the extension

```sql
CREATE EXTENSION pg_purr;  -- requires superuser (depends on plpython3u)
```

All pg_purr objects live in the `purr` schema. Address them with a
fully-qualified name (e.g., `purr.quantum_random()`).

## SQL functions

```sql
-- Quantum-augmented Query Planner (advisory): get the optimal
-- JOIN order for a complex query as a list of
-- (step, table_name, estimated_cost) rows. Queries must use
-- fully-qualified table names.
SELECT * FROM purr.quantum_query_plan(
    'SELECT ... FROM public.t1 JOIN public.t2 ON ... (up to 17 tables)'
);

-- Quantum Query Rewrite: same pipeline, returns the rewritten
-- SELECT ready for EXECUTE. Wrap in a transaction with
-- join_collapse_limit = 1 so PG honours the order verbatim.
SELECT purr.quantum_query_rewrite(
    'SELECT ... FROM public.t1 JOIN public.t2 ON ...'
) AS rewritten \gset
BEGIN;
SET LOCAL join_collapse_limit = 1;
EXPLAIN ANALYZE :rewritten ;
COMMIT;

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

The planner accepts a narrow query shape: single SELECT, INNER
JOINs only over base tables, no OUTER / NATURAL / USING / LATERAL
/ CROSS joins, no CTEs, no subqueries in FROM, and a connected
predicate graph. Anything else is rejected upfront with a clear
error message.

## Configuration

### IBM Quantum token (optional)

The planner runs on a local `AerSimulator` by default and produces
deterministic results given a fixed seed and shot count — no
external services are required. To target real IBM Quantum
hardware via `qiskit-ibm-runtime`, set the following environment
variables on the PostgreSQL server process:

- `QISKIT_IBM_TOKEN` — the API token from your IBM Quantum
  Platform account.
- `QISKIT_IBM_INSTANCE` — the instance name (CRN or hub/group/
  project).
- `QISKIT_IBM_CHANNEL` — typically `ibm_quantum_platform`.

How to inject them depends on your deployment:

- **Bare metal / VM:** add an `Environment=` line to a
  `postgresql.service` drop-in unit and restart.
- **CloudNativePG:** set `spec.env[].valueFrom.secretKeyRef` on
  the Cluster manifest so the token flows in from a Kubernetes
  Secret.
- **Docker / plain k8s:** inject the variable into the container
  environment.
- **RDS / CloudSQL:** not supported (no user-controlled process
  env); use the simulator path.

Get a free token at the [IBM Quantum
Platform](https://quantum.cloud.ibm.com/). The Open Plan currently
provides ~10 minutes of QPU time per 28-day rolling window — fine
for occasional demonstration runs, not for repeated CI.

### QAOA execution mode (optional)

Two further environment variables tune the QAOA selector, on either
backend (read from the PostgreSQL server process environment):

- `PG_PURR_QAOA_MODE` — `variational` (default) runs the full COBYLA
  optimisation loop; `fixed_angle` runs a single fixed-angle QAOA
  circuit. On real hardware `variational` submits one QPU job per
  COBYLA iteration (tens of queued jobs), while `fixed_angle` is a
  single job. `fixed_angle` is recommended on the free Open Plan,
  where Sessions (which would batch the jobs) are unavailable.
- `PG_PURR_QAOA_MAX_ITER` — COBYLA iteration cap for `variational`
  mode (default 80). Lowering it cuts QPU job count; it has no effect
  in `fixed_angle` mode.

### Network egress (entropy pool fallback)

`purr.quantum_random()` never performs network I/O from inside a
backend. If the entropy pool is empty it raises an error by
default. To allow a non-quantum PRNG fallback when the pool is
empty:

```sql
ALTER SYSTEM SET pg_purr.allow_prng_fallback = 'on';
SELECT pg_reload_conf();
```

When the fallback fires, the function emits a `WARNING` and the
returned value is `random()` — not quantum.

### Permissions

All pg_purr functions are revoked from `PUBLIC` on install. Grant
explicitly:

```sql
GRANT USAGE ON SCHEMA purr TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_random() TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_random_in_range(FLOAT8, FLOAT8) TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_query_plan(TEXT) TO your_role;
GRANT EXECUTE ON FUNCTION purr.quantum_query_rewrite(TEXT) TO your_role;
GRANT EXECUTE ON FUNCTION purr.prng_random() TO your_role;
```

## Running the entropy filler

`purr.quantum_random()` consumes pre-filled entropy. A separate
daemon fetches values from the QRNG HTTP endpoint (LfD OTH
Regensburg by default) and keeps the pool above a configurable
threshold.

```bash
pg-purr-filler --dsn "host=... dbname=... user=pg_purr_filler password=..."
```

Or in Docker:

```bash
python -m pg_purr.qrng --dsn "$PG_PURR_DSN" --target 2000 --threshold 500
```

The filler is safe to run as a long-lived service (systemd,
Kubernetes Deployment, Docker Compose service).

## Architecture

```
  PostgreSQL 17 / 18
  ├── purr schema
  │   ├── quantum_query_plan()     ──> pg_purr.planner.pipeline
  │   ├── quantum_query_rewrite()  ──> pg_purr.planner.pipeline + query_rewriter
  │   │   ├── query_validator    (supported-shape contract; refused upfront)
  │   │   ├── explain_parser     (EXPLAIN JSON → JoinGraph)
  │   │   ├── predicate_graph    (extract edges from SQL via sqlglot)
  │   │   ├── cost_model         (edge weights + true left-deep cost)
  │   │   ├── spanning_trees     (k edge-perturbed MST candidates)
  │   │   ├── tree_selector      (QAOA on AerSimulator or IBM Quantum → best candidate)
  │   │   ├── linearizer         (DFS pre-order → connected join order)
  │   │   └── query_rewriter     (sqlglot AST rewrite)
  │   ├── quantum_random()       ──> quantum_entropy pool (UNLOGGED)
  │   ├── quantum_random_in_range(low, high)
  │   ├── prng_random()          ──> SQL random() wrapper
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
