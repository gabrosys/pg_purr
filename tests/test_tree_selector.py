"""Tests for tree_selector.pick.

QAOA + AerSimulator runs are slow relative to pure-Python tests
(seconds per call). Most cases stay under 4 candidates / few QAOA
layers to keep the unit-test suite snappy.
"""

import pytest

from pg_purr.planner.tree_selector import pick


def test_pick_lowest_cost_two_candidates() -> None:
    chosen = pick(["A", "B"], [10.0, 100.0], seed=42, default_shots=1024)
    assert chosen == "A"


def test_pick_lowest_cost_three_candidates() -> None:
    chosen = pick(["A", "B", "C"], [50.0, 10.0, 90.0], seed=42, default_shots=1024)
    assert chosen == "B"


def test_pick_lowest_cost_four_candidates() -> None:
    chosen = pick(
        ["A", "B", "C", "D"],
        [100.0, 50.0, 10.0, 200.0],
        seed=42,
        default_shots=2048,
    )
    assert chosen == "C"


def test_pick_single_candidate_skips_qaoa() -> None:
    assert pick(["only"], [42.0]) == "only"


def test_pick_empty_candidates_raises() -> None:
    with pytest.raises(ValueError):
        pick([], [])


def test_pick_mismatched_lengths_raises() -> None:
    with pytest.raises(ValueError):
        pick(["A", "B"], [1.0])


def test_pick_deterministic_with_fixed_seed() -> None:
    cands = ["A", "B", "C", "D"]
    costs = [100.0, 90.0, 80.0, 70.0]
    out_1 = pick(cands, costs, seed=42, default_shots=1024)
    out_2 = pick(cands, costs, seed=42, default_shots=1024)
    assert out_1 == out_2
