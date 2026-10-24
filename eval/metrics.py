"""Small, deterministic metrics used by the offline evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Callable, Sequence

DEFAULT_SEED = 20261024


@dataclass(frozen=True)
class Metric:
    value: float
    ci_low: float
    ci_high: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "value": round(self.value, 6),
            "ci_low": round(self.ci_low, 6),
            "ci_high": round(self.ci_high, 6),
            "n": self.n,
        }


def f1_from_counts(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return 0.0 if denominator == 0 else (2 * tp) / denominator


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein edits divided by reference length."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for row, ref_char in enumerate(reference, start=1):
        current = [row]
        for column, hyp_char in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_char != hyp_char),
                )
            )
        previous = current
    return previous[-1] / len(reference)


def bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = mean,
    n_resamples: int = 1000,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), float(values[0])
    rng = Random(seed)
    samples = []
    for _ in range(n_resamples):
        resample = [values[rng.randrange(len(values))] for _ in values]
        samples.append(statistic(resample))
    samples.sort()
    low = samples[int(0.025 * len(samples))]
    high = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    return low, high


def mean_metric(values: Sequence[float], *, seed: int = DEFAULT_SEED) -> Metric:
    if not values:
        return Metric(0.0, 0.0, 0.0, 0)
    low, high = bootstrap_ci(values, seed=seed)
    return Metric(float(mean(values)), low, high, len(values))


def exact_match(values: Sequence[bool], *, seed: int = DEFAULT_SEED) -> Metric:
    numbers = [1.0 if value else 0.0 for value in values]
    return mean_metric(numbers, seed=seed)


def cohen_kappa(labels_a: Sequence[object], labels_b: Sequence[object]) -> float:
    if len(labels_a) != len(labels_b):
        raise ValueError("annotator label lists must be the same length")
    if not labels_a:
        return 0.0
    observed = sum(a == b for a, b in zip(labels_a, labels_b)) / len(labels_a)
    categories = set(labels_a) | set(labels_b)
    expected = sum(
        (labels_a.count(category) / len(labels_a))
        * (labels_b.count(category) / len(labels_b))
        for category in categories
    )
    if expected == 1.0:
        return 0.0
    return (observed - expected) / (1.0 - expected)
