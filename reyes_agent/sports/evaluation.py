"""Scoring ZENO's own predictions honestly: Brier, log-loss, calibration.

A prediction system is only trustworthy if it MEASURES itself. This grades stored
predictions against actual results with proper probabilistic metrics -- not just
"did the favourite win". Calibration is the key one: when ZENO says 70% over many
games, the outcome should happen ~70% of the time. Pure math, deterministic.
"""

from __future__ import annotations

import math
from typing import Any

_OUTCOMES = ("home_win", "draw", "away_win")


def outcome_of(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home_win"
    if home_goals == away_goals:
        return "draw"
    return "away_win"


def brier_score(probs: dict[str, float], actual: str) -> float:
    """Multi-class Brier score in [0,2]; lower is better. 0 = perfect."""
    return sum((float(probs.get(o, 0.0)) - (1.0 if o == actual else 0.0)) ** 2
               for o in _OUTCOMES)


def log_loss(probs: dict[str, float], actual: str, eps: float = 1e-9) -> float:
    p = min(1.0, max(eps, float(probs.get(actual, 0.0))))
    return -math.log(p)


class PredictionEvaluator:
    """Accumulate (predicted probs, actual outcome) and report calibration."""

    def __init__(self) -> None:
        self._records: list[tuple[dict[str, float], str]] = []

    def record(self, probs: dict[str, float], actual: str) -> None:
        if actual in _OUTCOMES and isinstance(probs, dict):
            self._records.append(({o: float(probs.get(o, 0.0)) for o in _OUTCOMES}, actual))

    def __len__(self) -> int:
        return len(self._records)

    def metrics(self) -> dict[str, Any]:
        n = len(self._records)
        if n == 0:
            return {"n": 0, "brier": None, "log_loss": None,
                    "result_accuracy": None, "calibration_error": None}
        brier = sum(brier_score(p, a) for p, a in self._records) / n
        ll = sum(log_loss(p, a) for p, a in self._records) / n
        correct = sum(1 for p, a in self._records
                      if max(p, key=p.get) == a)
        return {
            "n": n,
            "brier": round(brier, 4),
            "log_loss": round(ll, 4),
            "result_accuracy": round(correct / n, 4),
            "calibration_error": round(self._calibration_error(), 4),
        }

    def calibration_table(self, bins: int = 10) -> list[dict[str, Any]]:
        """For each predicted-probability bin, the mean predicted vs the actual
        frequency, across ALL outcome classes (one point per class per game)."""
        buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
        for probs, actual in self._records:
            for o in _OUTCOMES:
                p = probs[o]
                idx = min(bins - 1, int(p * bins))
                buckets[idx].append((p, 1.0 if o == actual else 0.0))
        table = []
        for b, points in enumerate(buckets):
            if not points:
                continue
            mean_pred = sum(p for p, _ in points) / len(points)
            mean_actual = sum(y for _, y in points) / len(points)
            table.append({"bin": f"{int(b / bins * 100)}-{int((b + 1) / bins * 100)}%",
                          "predicted": round(mean_pred, 3),
                          "actual": round(mean_actual, 3),
                          "count": len(points)})
        return table

    def _calibration_error(self, bins: int = 10) -> float:
        """Expected Calibration Error: weighted mean |predicted - actual|."""
        table = self.calibration_table(bins)
        total = sum(row["count"] for row in table) or 1
        return sum(abs(row["predicted"] - row["actual"]) * row["count"] for row in table) / total
