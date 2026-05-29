# Live planner demo

A hands-on walkthrough of the quantum-augmented query planner
shipped with [pg_purr](../..). In about five minutes you go from a
fresh PostgreSQL container to a multi-table retail schema whose
JOIN ordering is solved by — depending on what you bring —
PostgreSQL's own genetic optimiser, or the hybrid Qiskit pipeline
running on a local AerSimulator (and, optionally, a real IBM
Quantum backend over the network).

This directory is meant to be self-contained: clone the repo, run
the scripts in order, read what happens. No credentials are
required for the default walkthrough.

## What is going on, briefly

`pg_purr` exposes two SQL functions:

- `purr.quantum_query_plan(query TEXT)` — returns the chosen join
  order as a `(step, table_name, estimated_cost)` table.
- `purr.quantum_query_rewrite(query TEXT)` — returns the rewritten
  SELECT, ready for `EXECUTE` under
  `SET LOCAL join_collapse_limit = 1`.

Internally the planner:

1. Validates the input against a narrow supported-query contract
   (single SELECT, INNER JOINs over base tables, connected
   predicate graph; everything else is refused upfront).
2. Runs `EXPLAIN (FORMAT JSON)` on it to extract the tables
   involved and their row-count estimates.
3. Builds the predicate graph from the original SQL via `sqlglot`.
4. Generates K candidate spanning trees of the predicate graph by
   perturbing edge weights and running NetworkX's MST per draw.
5. Selects one candidate via QAOA on a one-hot QUBO. The QAOA runs
   on the local `AerSimulator` by default; an IBM Quantum backend
   can be enabled by setting `QISKIT_IBM_TOKEN` in the postgres
   process environment.
6. Linearises the chosen tree by enumerating DFS pre-orders rooted
   at every vertex and picking the lowest-cost permutation under
   a left-deep cost model.

The classical scaffolding (steps 4 + 6) makes connectivity a
**theorem**, not a sampling outcome: every emitted order
introduces each new relation via at least one predicate edge to
the prior prefix. The QAOA layer contributes to cost selection
within the structurally-feasible candidate set.

PostgreSQL's own planner uses exhaustive dynamic programming up to
12 tables, then falls back to GEQO. The demo's query crosses that
threshold, so you can compare GEQO's heuristic ordering against
the hybrid quantum planner.

## Prerequisites

- **Docker** with `docker compose`. Any recent version works.
- **Outbound HTTPS** — only required if you opt into the IBM
  Quantum hardware path. The local AerSimulator path is fully
  offline.
- Nothing else. The default walkthrough does not need any external
  account.

## The real-QPU step is optional

Steps 0, 1, 2, 3, and 5 give you a complete walkthrough — no
external account, no token, no credentials. Step 3 runs the full
hybrid pipeline (QAOA on `AerSimulator`) on your CPU; that is the
same algorithm the IBM Quantum backend would execute, just on a
local simulator with deterministic seeds.

### Opting in — getting an IBM Quantum token

1. **Sign up** at [quantum.cloud.ibm.com](https://quantum.cloud.ibm.com/).
2. **Find your token** in the dashboard.
3. **Create the `.env` file** for this demo:
   ```bash
   cp examples/planner/.env.example examples/planner/.env
   ```
4. **Paste the token** and instance metadata into
   `examples/planner/.env`:
   ```
   QISKIT_IBM_TOKEN=...
   QISKIT_IBM_INSTANCE=...
   QISKIT_IBM_CHANNEL=ibm_quantum_platform
   ```
5. `examples/planner/.env` is covered by the repository's
   `.gitignore` — do not force-add it or commit it.

### Quota and cost

The Open Plan currently provides ~10 minutes of QPU time per
28-day rolling window. Each rewrite call uses on the order of
seconds of compute on the simulator and significantly more on real
hardware (queue + execute). A handful of runs per month are fine;
repeated CI on real hardware is not.

## The walkthrough

Five short lessons, one script each:

| Step | Script | What happens |
|---:|---|---|
| 0 | `00_setup.sh` | Boot the container, install the `pg_purr` extension, report the IBM-token status. |
| 1 | `01_seed_schema.sh` | Create the retail schema and seed sample rows. Print per-table row counts. |
| 2 | `02_baseline_explain.sh` | Show PostgreSQL's own plan for the multi-way JOIN (GEQO is active beyond `geqo_threshold = 12`). |
| 3 | `03_local_solver.sh` | Call `purr.quantum_query_plan(...)`. QAOA via Qiskit (local `AerSimulator` by default, deterministic; IBM Quantum if a token is set). Works without a token. |
| 5 | `05_teardown.sh` | Stop the container, remove the volume. |

Run them in order:

```bash
cd examples/planner
./00_setup.sh
./01_seed_schema.sh
./02_baseline_explain.sh
./03_local_solver.sh
./05_teardown.sh
```

Each script narrates what it is doing and what good output looks
like. The container keeps running between steps, so you can open a
psql session any time:

```bash
docker exec -it pg-purr-test psql -U test -d pg_purr_test
```

## Tunables

Environment variables — set in your shell before invoking the
scripts:

| Variable | Default | Used by | What it does |
|---|---|---|---|
| `QISKIT_IBM_TOKEN` | — | 00 | Enables the IBM Quantum hardware path. Usually set via `examples/planner/.env`. |
| `QISKIT_IBM_INSTANCE` | — | 00 | IBM Quantum instance identifier (CRN or hub/group/project). |
| `QISKIT_IBM_CHANNEL` | `ibm_quantum_platform` | 00 | Runtime channel. |
| `PG_PURR_QAOA_MODE` | `variational` | postgres env | QAOA mode: `variational` (full COBYLA loop) or `fixed_angle` (one circuit, one QPU job). Use `fixed_angle` on the free Open Plan. |
| `PG_PURR_QAOA_MAX_ITER` | `80` | postgres env | COBYLA iteration cap for `variational` mode. |

## Troubleshooting

**Step 2 looks confusingly long.** That is normal — `EXPLAIN` on a
many-way join has a big plan tree, and GEQO's chosen ordering may
look non-obvious. Focus on which table PG picked as the deepest
left-leaf.

**Step 3 reports a Python import error.** The container's Python
env is missing one of the Qiskit packages. Re-run `00_setup.sh` to
reinstall from the pinned `docker/requirements.txt`.

**Step 3 reports `predicate graph is disconnected`.** The query
has a relation with no join predicate to the rest. Add the missing
join condition or drop the dangling relation. The planner refuses
to produce Cartesian-prone orders by design.

**The plan is unexpectedly slow.** QAOA at `reps=2` on
`AerSimulator` for ~16 candidate trees runs in seconds. If you see
minutes, you are on the real-QPU path: in the default `variational`
mode each COBYLA iteration is a separate QPU job (tens of queued
jobs). Set `PG_PURR_QAOA_MODE=fixed_angle` in your `.env` to run a
single QPU job instead, or `unset QISKIT_IBM_TOKEN` to fall back to
the simulator entirely.

**After step 5 `docker ps` shows nothing related to pg_purr.**
That is the expected state. Re-run `00_setup.sh` to start over.
