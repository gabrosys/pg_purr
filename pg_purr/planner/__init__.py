"""pg_purr.planner: Quantum-annealing-based query plan optimizer.

Provides tools to parse PostgreSQL EXPLAIN output, build QUBO
(Quadratic Unconstrained Binary Optimization) models for JOIN ordering,
and solve them using simulated or quantum annealing.
"""
