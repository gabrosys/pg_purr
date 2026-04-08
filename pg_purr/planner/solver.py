"""Solve QUBO problems using simulated annealing (local) or D-Wave (cloud)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

import dimod
import neal


class SolverError(RuntimeError):
    """Solver failure. Never carries raw D-Wave credentials."""


_TOKEN_PATTERN = re.compile(r"DW-[A-Za-z0-9_-]{6,}")


def _scrub(message: str, token: str | None) -> str:
    if token:
        message = message.replace(token, "***REDACTED***")
    return _TOKEN_PATTERN.sub("***REDACTED***", message)


def solve_local(
    bqm: dimod.BinaryQuadraticModel,
    num_reads: int = 1000,
    seed: int | None = None,
) -> dimod.SampleSet:
    """Solve using local simulated annealing (no quantum hardware needed)."""
    sampler = neal.SimulatedAnnealingSampler()
    kwargs: dict = {"num_reads": num_reads}
    if seed is not None:
        kwargs["seed"] = seed
    return sampler.sample(bqm, **kwargs)


def solve_dwave(
    bqm: dimod.BinaryQuadraticModel,
    num_reads: int = 100,
    token: str | None = None,
) -> dimod.SampleSet:
    """Solve using D-Wave quantum hardware.

    Token resolution: explicit `token` argument, then `DWAVE_API_TOKEN`
    environment variable.

    Raises:
        SolverError: on missing token or any D-Wave error; messages are
            scrubbed of token material.
        ImportError: if `dwave-system` is not installed.
    """
    token = token or os.environ.get("DWAVE_API_TOKEN")
    if not token:
        raise SolverError(
            "D-Wave API token not configured. Set the DWAVE_API_TOKEN "
            "environment variable on the PostgreSQL server process."
        )

    from dwave.system import DWaveSampler, EmbeddingComposite

    try:
        sampler = EmbeddingComposite(DWaveSampler(token=token))
        return sampler.sample(bqm, num_reads=num_reads)
    except Exception as exc:
        # `from None` drops __cause__ so the raw exception (whose args
        # may echo the token) is not chained into the traceback.
        raise SolverError(f"D-Wave solver failed: {_scrub(str(exc), token)}") from None


def _decode_permutation(sample: Mapping[str, int], n: int) -> list[int] | None:
    """Return `order[step] = table_idx` for a valid permutation, else None."""
    order: list[int | None] = [None] * n
    seen_tables: set[int] = set()

    for var_name, value in sample.items():
        if value != 1:
            continue
        parts = var_name.split("_")
        if len(parts) != 3 or parts[0] != "x":
            return None
        try:
            table_idx = int(parts[1])
            step = int(parts[2])
        except ValueError:
            return None
        if not (0 <= table_idx < n and 0 <= step < n):
            return None
        if order[step] is not None or table_idx in seen_tables:
            return None
        order[step] = table_idx
        seen_tables.add(table_idx)

    if any(o is None for o in order):
        return None
    return order  # type: ignore[return-value]


def decode_solution(
    sample_set: dimod.SampleSet,
    tables: list[str],
) -> list[str]:
    """Return the lowest-energy valid permutation from `sample_set`.

    Raises:
        SolverError: if no sample represents a valid permutation.
    """
    n = len(tables)
    for record in sample_set.data(sorted_by="energy"):
        order = _decode_permutation(record.sample, n)
        if order is not None:
            return [tables[i] for i in order]

    raise SolverError(
        f"no valid permutation found in {len(sample_set)} samples; "
        f"increase num_reads or inspect QUBO penalty weight"
    )
