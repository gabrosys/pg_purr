"""Tests for the IBM-hardware QAOA path of tree_selector.

The hardware path differs from the AerSimulator path in one critical
way: circuits are transpiled to a backend's *physical* qubit width,
which previously broke the qiskit-algorithms ``MinimumEigenOptimizer``
flow (observable / eigenstate qubit-count mismatch). These tests drive
the dependency-injected solver ``_solve_qaoa_hardware`` with a *fake*
fixed-width backend's pass manager plus a seeded local AerSimulator
sampler, so the layout-sensitive path is exercised end-to-end with no
IBM credentials and no network.
"""

import pytest
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer.primitives import SamplerV2
from qiskit_ibm_runtime.fake_provider import FakeManilaV2

from pg_purr.planner.tree_selector import (
    _one_hot_program,
    _resolve_max_iter,
    _resolve_mode,
    _solve_qaoa_fixed_angle,
    _solve_qaoa_hardware,
    pick,
)

_SEED = 42
_SHOTS = 4096


class _CountingSampler:
    """Wraps a sampler and counts ``run`` invocations (== QPU jobs)."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.runs = 0

    def run(self, pubs, **kwargs):
        self.runs += 1
        return self.inner.run(pubs, **kwargs)


def _hardware_fixtures(seed: int = _SEED, shots: int = _SHOTS):
    """A fixed-width (5-qubit) backend pass manager + seeded local sampler.

    FakeManilaV2 forces transpilation to 5 physical qubits, reproducing
    the width expansion that only happens on real hardware. The seeded
    AerSimulator sampler executes the resulting ISA circuit locally and
    deterministically.
    """
    pass_manager = generate_preset_pass_manager(
        optimization_level=1, backend=FakeManilaV2(), seed_transpiler=seed
    )
    sampler = SamplerV2(seed=seed, default_shots=shots)
    return sampler, pass_manager


# Cost vectors with a unique minimum; the selected candidate must be that
# minimum. Asserting optimality (not an exact index) keeps these robust to
# seed / transpiler-layout drift.
_MIN_COST_CASES = [
    [50.0, 10.0, 90.0],
    [10.0, 100.0],
    [100.0, 90.0, 80.0, 70.0],
    [100.0, 50.0, 10.0, 200.0],
]


@pytest.mark.parametrize("costs", _MIN_COST_CASES)
def test_hardware_path_selects_min_cost_on_fixed_width_backend(costs: list[float]) -> None:
    sampler, pass_manager = _hardware_fixtures()
    candidates = [f"t{i}" for i in range(len(costs))]

    chosen = _solve_qaoa_hardware(
        _one_hot_program(costs), candidates, costs, sampler, pass_manager, reps=2, max_iter=50
    )

    assert costs[candidates.index(chosen)] == min(costs)


def test_hardware_path_completes_without_qubit_mismatch() -> None:
    """Regression: the original bug raised a circuit-vs-observable qubit
    mismatch on a fixed-width backend. The solver must now complete and
    return a valid candidate."""
    sampler, pass_manager = _hardware_fixtures()
    costs = [50.0, 10.0, 90.0]

    chosen = _solve_qaoa_hardware(
        qp=_one_hot_program(costs),
        candidates=["a", "b", "c"],
        costs=costs,
        sampler=sampler,
        pass_manager=pass_manager,
        reps=2,
        max_iter=20,
    )

    assert chosen in {"a", "b", "c"}


def test_hardware_path_is_deterministic_under_fixed_seed() -> None:
    costs = [100.0, 50.0, 10.0, 200.0]
    candidates = ["a", "b", "c", "d"]

    first = _solve_qaoa_hardware(
        _one_hot_program(costs), candidates, costs, *_hardware_fixtures(), reps=2, max_iter=50
    )
    second = _solve_qaoa_hardware(
        _one_hot_program(costs), candidates, costs, *_hardware_fixtures(), reps=2, max_iter=50
    )

    assert first == second


# --- fixed-angle mode (PG_PURR_QAOA_MODE=fixed_angle) -----------------------


def test_fixed_angle_fires_exactly_one_qpu_job() -> None:
    """Fixed-angle mode submits exactly one QPU job."""
    sampler, pass_manager = _hardware_fixtures()
    counting = _CountingSampler(sampler)
    costs = [50.0, 10.0, 90.0]

    _solve_qaoa_fixed_angle(_one_hot_program(costs), ["a", "b", "c"], costs, counting, pass_manager)

    assert counting.runs == 1


@pytest.mark.parametrize("costs", _MIN_COST_CASES)
def test_fixed_angle_selects_min_cost_on_fixed_width_backend(costs: list[float]) -> None:
    sampler, pass_manager = _hardware_fixtures()
    candidates = [f"t{i}" for i in range(len(costs))]

    chosen = _solve_qaoa_fixed_angle(
        _one_hot_program(costs), candidates, costs, sampler, pass_manager
    )

    assert costs[candidates.index(chosen)] == min(costs)


def test_fixed_angle_is_deterministic_under_fixed_seed() -> None:
    costs = [100.0, 50.0, 10.0, 200.0]
    candidates = ["a", "b", "c", "d"]

    first = _solve_qaoa_fixed_angle(
        _one_hot_program(costs), candidates, costs, *_hardware_fixtures()
    )
    second = _solve_qaoa_fixed_angle(
        _one_hot_program(costs), candidates, costs, *_hardware_fixtures()
    )

    assert first == second


# --- mode resolution --------------------------------------------------------


def test_resolve_mode_defaults_to_variational(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_PURR_QAOA_MODE", raising=False)
    assert _resolve_mode() == "variational"


def test_resolve_mode_reads_fixed_angle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PURR_QAOA_MODE", "fixed_angle")
    assert _resolve_mode() == "fixed_angle"


def test_resolve_mode_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PURR_QAOA_MODE", "bogus")
    with pytest.raises(ValueError, match="PG_PURR_QAOA_MODE"):
        _resolve_mode()


def test_resolve_max_iter_defaults_to_80(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_PURR_QAOA_MAX_ITER", raising=False)
    assert _resolve_max_iter() == 80


def test_resolve_max_iter_reads_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PURR_QAOA_MAX_ITER", "10")
    assert _resolve_max_iter() == 10


def test_resolve_max_iter_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PURR_QAOA_MAX_ITER", "lots")
    with pytest.raises(ValueError, match="PG_PURR_QAOA_MAX_ITER"):
        _resolve_max_iter()


def test_pick_fixed_angle_mode_runs_on_simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through pick() on AerSimulator (no token): fixed-angle
    mode must still select the lowest-cost candidate."""
    monkeypatch.delenv("QISKIT_IBM_TOKEN", raising=False)
    monkeypatch.setenv("PG_PURR_QAOA_MODE", "fixed_angle")

    chosen = pick(["A", "B", "C"], [50.0, 10.0, 90.0], seed=_SEED)

    assert chosen == "B"
