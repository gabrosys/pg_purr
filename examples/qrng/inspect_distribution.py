"""ASCII histogram + chi-square uniformity check for a stream of uint16
or [0, 1) float samples read from stdin (one per line).

Pure stdlib. No numpy, no scipy, no matplotlib.
"""

from __future__ import annotations

import math
import sys

BUCKETS = 16
BAR_WIDTH = 40


def read_samples() -> list[float]:
    values: list[float] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    return values


def normalise_to_unit_interval(values: list[float]) -> list[float]:
    """Accept either uint16 (0-65535) or [0, 1) floats; return [0, 1)."""
    if not values:
        return values
    if max(values) > 1.5:
        return [v / 65536.0 for v in values]
    return values


def bucketise(values: list[float], n: int) -> list[int]:
    counts = [0] * n
    for v in values:
        idx = min(int(v * n), n - 1)
        counts[idx] += 1
    return counts


def chi_square_p_value(counts: list[int], expected_per_bucket: float) -> float:
    """Pearson chi-square test against the uniform distribution.

    Returns a p-value in (0, 1]. Uses Q(k, x) = Γ(k, x/2) / Γ(k) with
    k = (buckets - 1) / 2 for the survival function of the chi-square
    distribution.
    """
    chi2 = sum((c - expected_per_bucket) ** 2 / expected_per_bucket for c in counts)
    dof = len(counts) - 1
    return _chi_square_sf(chi2, dof)


def _chi_square_sf(x: float, k: int) -> float:
    """Survival function of chi-square with k degrees of freedom, via
    the regularised upper incomplete gamma function.
    """
    return _gammaincc(k / 2.0, x / 2.0)


def _gammaincc(s: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(s, x). Simpson-rule
    integration of the unregularised form, normalised by Γ(s).
    Accurate to ~3-4 decimals, plenty for this demo.
    """
    if x <= 0:
        return 1.0
    # Use a series expansion of the lower regularised gamma P(s, x),
    # then return 1 - P.
    term = 1.0 / s
    total = term
    for i in range(1, 500):
        term *= x / (s + i)
        total += term
        if abs(term) < 1e-12 * abs(total):
            break
    lower = total * math.exp(-x + s * math.log(x) - math.lgamma(s))
    return max(0.0, 1.0 - lower)


def render(values: list[float]) -> None:
    n = len(values)
    if n == 0:
        print("No samples read from stdin.")
        return

    unit = normalise_to_unit_interval(values)
    counts = bucketise(unit, BUCKETS)
    peak = max(counts)

    print(f"samples:    {n}")
    print(f"buckets:    {BUCKETS}")
    print(f"expected:   {n / BUCKETS:.1f} per bucket")
    print()

    for i, c in enumerate(counts):
        lo = i / BUCKETS
        hi = (i + 1) / BUCKETS
        bar = "#" * int((c / peak) * BAR_WIDTH) if peak else ""
        print(f"  [{lo:.3f}, {hi:.3f})  {c:5d}  {bar}")

    expected = n / BUCKETS
    p = chi_square_p_value(counts, expected)
    verdict = (
        "consistent with uniform"
        if p > 0.01
        else "suspiciously non-uniform (p <= 0.01)"
    )
    print()
    print(f"chi-square p-value: {p:.4f}  ({verdict})")


if __name__ == "__main__":
    render(read_samples())
