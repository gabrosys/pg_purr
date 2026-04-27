"""pg_purr.planner: hybrid quantum query planner for PostgreSQL.

Parses EXPLAIN output, extracts the predicate graph from a SQL
query, generates candidate spanning trees of that graph, selects
one via QAOA on the local AerSimulator, and linearises it into a
connected join order. The classical scaffolding guarantees that
every emitted order is connected, regardless of the quantum step's
quality.
"""
