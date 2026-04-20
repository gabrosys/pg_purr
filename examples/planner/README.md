# Live planner demo

A hands-on walkthrough of the quantum query planner shipped with [pg_purr](../..). In about five minutes you go from a fresh PostgreSQL container to a 13-table e-commerce schema whose JOIN ordering is solved by — depending on what you bring — PostgreSQL's own genetic optimiser, a classical simulated-annealing sampler on your CPU, or a real D-Wave quantum processing unit in Canada.

This directory is meant to be self-contained: clone the repo, run the scripts in order, read what happens. A D-Wave Leap account is optional — steps 0-3 and 5 work for anyone, step 4 exercises the real QPU when a token is configured.

## What is going on, briefly

`pg_purr` exposes a SQL function `purr.quantum_query_plan(query TEXT, use_dwave BOOLEAN)` that:

1. Parses your query (via PostgreSQL itself — not a second parser).
2. Runs `EXPLAIN (FORMAT JSON)` on it to extract the tables involved and their row-count estimates.
3. Formulates the JOIN-ordering problem as a **QUBO** — Quadratic Unconstrained Binary Optimisation — with one binary variable per (table, step) slot and penalty terms encoding the "each table appears exactly once" constraint.
4. Solves the QUBO either locally via simulated annealing (default) or on a real quantum annealing processor via D-Wave's Leap cloud (`use_dwave := true`).
5. Returns the optimal table ordering as a result set.

PostgreSQL's own planner uses exhaustive dynamic programming up to 12 tables, then falls back to the GEQO (Genetic Query Optimiser) heuristic. This demo's 13-table query deliberately crosses that threshold, so you see GEQO in action for the baseline — and can compare its ordering against the annealing-based alternatives.

## Prerequisites

- **Docker** with `docker compose`. Any recent version works.
- **Outbound HTTPS** — step 0 downloads the `dwave-system` SDK into the container (~200 MB). Step 4 optionally reaches `cloud.dwavesys.com` if you have supplied a token.
- Nothing else. A D-Wave Leap account is only needed if you want step 4 to run on real hardware — see "The real-QPU step is optional" below.

## The real-QPU step is optional

You get a complete, satisfying walkthrough with steps 0, 1, 2, 3, and 5 alone — no external account, no token, no credentials. Step 3 runs the full QUBO pipeline via classical simulated annealing on your CPU; that is the same algorithmic family a real quantum annealer uses, just executed on different physics. Skipping step 4 loses the "watch it run on a real QPU in Canada" moment, not the algorithmic story.

Step 4 exists for readers who are curious enough to opt in.

### Opting in — getting a D-Wave token

**Heads-up on signup friction.** D-Wave Leap's registration form asks for more than an email address: name, company, country, and typically a short use-case description. For a casual demo that is more than some readers want to share. There is no lower-friction alternative today for annealing hardware — gate-based providers (IBM, etc.) have lighter signup but would require a different solver in the extension.

If you are fine with the signup, here is the walkthrough:

1. **Sign up** at [cloud.dwavesys.com/leap/signup](https://cloud.dwavesys.com/leap/signup/).
2. **Find your token** in the Leap dashboard — the section labelled "API Token" shows it with a copy-to-clipboard button.
3. **Create the `.env` file** for this demo:
   ```bash
   cp examples/planner/.env.example examples/planner/.env
   ```
4. **Paste the token** into `examples/planner/.env`:
   ```
   DWAVE_API_TOKEN=DEV-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
5. That is it. `examples/planner/.env` is covered by the repository's `.gitignore` — do not force-add it or commit it.

### Quota and cost

The free tier grants **1 minute of QPU time per month**. Each call in this demo uses single-digit milliseconds of QPU-access time, so one month's quota comfortably covers hundreds of runs of step 4. You can check current usage on the Leap dashboard under Admin → Usage.

## The walkthrough

Six short lessons, one script each:

| Step | Script | What happens |
|---:|---|---|
| 0 | `00_setup.sh` | Boot the container with the token injected (if any), install `dwave-system`, install the `pg_purr` extension, report the token status. |
| 1 | `01_seed_schema.sh` | Create the 13-table retail schema and seed ~20 000 rows. Print per-table row counts. |
| 2 | `02_baseline_explain.sh` | Show PostgreSQL's own plan for the 13-way JOIN (GEQO is active because 13 ≥ the default `geqo_threshold` of 12). |
| 3 | `03_local_solver.sh` | Call `purr.quantum_query_plan(..., use_dwave := false)`. Classical simulated annealing on CPU. Works without a token. |
| 4 | `04_dwave_solver.sh` | Same query with `use_dwave := true`. Real QPU when a token is set; clean opt-in notice otherwise. |
| 5 | `05_teardown.sh` | Stop the container, remove the volume. |

Run them in order:

```bash
cd examples/planner
./00_setup.sh
./01_seed_schema.sh
./02_baseline_explain.sh
./03_local_solver.sh
./04_dwave_solver.sh
./05_teardown.sh
```

Each script narrates what it is doing and what good output looks like. The container keeps running between steps, so you can open a psql session any time:

```bash
docker exec -it pg-purr-test psql -U test -d pg_purr_test
```

## Tunables

Environment variables — set in your shell before invoking the scripts:

| Variable | Default | Used by | What it does |
|---|---|---|---|
| `DWAVE_API_TOKEN` | — | 00, 04 | Enables the D-Wave path. Usually set via `examples/planner/.env`. |

Additional knobs live inside the scripts as comments — e.g. `num_reads` for the annealing sampler is currently hardcoded, adjust it in `pg_purr/planner/solver.py` if you want to experiment.

## Troubleshooting

**Step 0 hangs downloading `dwave-system`.** First-time installs pull in ~200 MB of transitive deps (numpy, scipy, dimod, minorminer, dwave-cloud-client, …). On a slow link this takes a couple of minutes. Subsequent runs reuse the container's cache.

**Step 2 looks confusingly long.** That is normal — EXPLAIN on a 13-way join has a big plan tree, and GEQO's chosen ordering may look non-obvious. Focus on which table PG picked as the deepest left-leaf.

**Step 3 reports `no valid permutation found`.** The simulated annealer occasionally fails to find a feasible solution on the first run — rerun the step. If it persists, something is off with the QUBO weights; see `pg_purr/planner/qubo_builder.py`.

**Step 4 errors with `insufficient quota`.** You have used up your monthly QPU minute. Wait for the next month's reset, or upgrade your Leap plan.

**Step 4 errors with `no embedding found`.** The QUBO graph exceeds what the QPU's topology can host in a single call. The 13-table demo fits comfortably on current Advantage / Advantage2 systems; if the error happens, Leap may be rotating solvers — retry in a few minutes.

**Step 4 reports `D-Wave unavailable, falling back to local solver`.** A transient problem reaching `cloud.dwavesys.com`, a malformed token, or revoked credentials. The extension degrades gracefully and returns the local result. Inspect the warning message for details — tokens are automatically scrubbed from the output.

**After step 5 `docker ps` shows nothing related to pg_purr.** That is the expected state. Re-run `00_setup.sh` to start over.
