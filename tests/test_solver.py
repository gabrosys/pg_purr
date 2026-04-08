"""Unit tests for the solver."""

from unittest.mock import patch

import dimod
import pytest

from pg_purr.planner.explain_parser import JoinGraph
from pg_purr.planner.qubo_builder import build_qubo
from pg_purr.planner.solver import (
    SolverError,
    _scrub,
    decode_solution,
    solve_dwave,
    solve_local,
)


def _make_join_graph() -> JoinGraph:
    tables = ["a", "b", "c", "d"]
    row_counts = {"a": 100, "b": 1000, "c": 50, "d": 500}
    costs = {}
    for t1 in tables:
        for t2 in tables:
            if t1 != t2:
                costs[(t1, t2)] = row_counts[t1] * row_counts[t2]
    return JoinGraph(tables=tables, row_counts=row_counts, costs=costs)


def _valid_sample(n: int, order: list[int]) -> dict[str, int]:
    sample = {f"x_{i}_{t}": 0 for i in range(n) for t in range(n)}
    for step, table_idx in enumerate(order):
        sample[f"x_{table_idx}_{step}"] = 1
    return sample


def test_solve_local_returns_sampleset():
    graph = _make_join_graph()
    bqm = build_qubo(graph)
    result = solve_local(bqm, num_reads=100, seed=42)
    assert len(result) > 0


def test_decode_solution_returns_valid_permutation():
    graph = _make_join_graph()
    bqm = build_qubo(graph)
    result = solve_local(bqm, num_reads=200, seed=42)
    order = decode_solution(result, graph.tables)
    assert set(order) == set(graph.tables)
    assert len(order) == len(set(order))


def test_decode_skips_invalid_and_picks_next():
    tables = ["a", "b", "c"]
    bad = _valid_sample(3, [0, 0, 1])  # duplicate table at steps 0 and 1
    good = _valid_sample(3, [2, 0, 1])
    sample_set = dimod.SampleSet.from_samples(
        [bad, good],
        energy=[0.0, 1.0],  # bad has lower energy
        vartype=dimod.BINARY,
    )
    order = decode_solution(sample_set, tables)
    assert order == ["c", "a", "b"]


def test_decode_raises_when_no_sample_valid():
    tables = ["a", "b"]
    # Two invalid samples: both assign table 0 twice.
    s1 = _valid_sample(2, [0, 0])
    s2 = _valid_sample(2, [1, 1])
    sample_set = dimod.SampleSet.from_samples(
        [s1, s2],
        energy=[0.0, 1.0],
        vartype=dimod.BINARY,
    )
    with pytest.raises(SolverError):
        decode_solution(sample_set, tables)


def test_decode_rejects_out_of_range_indices():
    tables = ["a"]
    sample = {"x_9_9": 1}
    sample_set = dimod.SampleSet.from_samples(
        [sample],
        energy=[0.0],
        vartype=dimod.BINARY,
    )
    with pytest.raises(SolverError):
        decode_solution(sample_set, tables)


def test_solve_dwave_missing_token_raises_solver_error(monkeypatch):
    monkeypatch.delenv("DWAVE_API_TOKEN", raising=False)
    with pytest.raises(SolverError) as exc:
        solve_dwave(object())
    assert "DW-" not in str(exc.value)


def test_solve_dwave_scrubs_token_from_error():
    pytest.importorskip("dwave.system")
    secret = "DW-API-SECRET12345"

    class FakeSampler:
        def __init__(self, *a, **kw):
            raise RuntimeError(f"auth failed for token={secret}")

    with patch("dwave.system.DWaveSampler", FakeSampler):
        with pytest.raises(SolverError) as exc:
            solve_dwave(object(), token=secret)
    message = str(exc.value)
    assert secret not in message
    assert "***REDACTED***" in message


def test_scrub_redacts_pattern_fallback():
    result = _scrub("error: DW-API-ABCDEFGH failed", token=None)
    assert "DW-API-ABCDEFGH" not in result
    assert "***REDACTED***" in result
