from __future__ import annotations

from math import sqrt
from statistics import mean, median, stdev
from typing import Iterable


def summarize_values(values: Iterable[float]) -> dict[str, float]:
    data = [float(value) for value in values]
    if not data:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
        }
    mu = mean(data)
    med = median(data)
    std = stdev(data) if len(data) > 1 else 0.0
    margin = 1.96 * (std / sqrt(len(data))) if len(data) > 1 else 0.0
    return {
        "mean": mu,
        "median": med,
        "std": std,
        "min": min(data),
        "max": max(data),
        "ci95_low": mu - margin,
        "ci95_high": mu + margin,
    }


def percentage_difference(baseline: float, comparison: float) -> float:
    baseline = float(baseline)
    comparison = float(comparison)
    if baseline == 0.0:
        return 0.0
    return ((comparison - baseline) / baseline) * 100.0
