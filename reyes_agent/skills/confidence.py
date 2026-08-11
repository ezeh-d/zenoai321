"""How much a skill has earned, from what actually happened to it.

    EXPERIMENTAL  composed or watched. Never run.
    LOW           it has run, but not enough to mean anything.
    MEDIUM        works more often than not, over a real number of runs.
    HIGH          reliably works.
    VERIFIED      reliably works, recently, over a long run of successes.

"A skill should not become VERIFIED after one run." So every rung has BOTH
a minimum number of runs and a minimum success rate, and the top rung also
requires a recent success -- a skill that worked twenty times last year and
has not been touched since is not verified, it is stale.

Confidence is DERIVED, never set. It is a reading of `history`, which the
executor writes from real outcomes, so it cannot be talked upward.
"""

from __future__ import annotations

import time
from typing import Any

EXPERIMENTAL = "EXPERIMENTAL"
LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
VERIFIED = "VERIFIED"

LADDER = (EXPERIMENTAL, LOW, MEDIUM, HIGH, VERIFIED)

# (level, min_runs, min_success_rate)
_RUNGS = (
    (VERIFIED, 10, 0.9),
    (HIGH, 6, 0.85),
    (MEDIUM, 3, 0.7),
    (LOW, 1, 0.0),
)

# VERIFIED also requires a success this recently.
FRESH_S = 60 * 60 * 24 * 30

# The planner should prefer a skill at or above this.
TRUSTED_FROM = HIGH


def level_of(skill: Any) -> str:
    """The rung this skill has actually earned."""
    history = getattr(skill, "history", None)
    if history is None or not getattr(history, "runs", 0):
        return EXPERIMENTAL

    runs = history.runs
    rate = history.success_rate
    for level, min_runs, min_rate in _RUNGS:
        if runs >= min_runs and rate >= min_rate:
            if level == VERIFIED:
                last = getattr(history, "last_success_at", 0.0) or 0.0
                if (time.time() - last) > FRESH_S:
                    return HIGH          # proven, but stale
            return level
    return LOW


def trusted(skill: Any) -> bool:
    return LADDER.index(level_of(skill)) >= LADDER.index(TRUSTED_FROM)


def compare(left: Any, right: Any) -> Any:
    """The better of two skills that do the same thing.

    Confidence first, then success rate, then recency. A faster skill that
    fails a third of the time is not the better skill.
    """
    ranking = [(LADDER.index(level_of(s)),
                getattr(getattr(s, "history", None), "success_rate", 0.0),
                getattr(getattr(s, "history", None), "last_success_at", 0.0), s)
               for s in (left, right)]
    ranking.sort(key=lambda row: (-row[0], -row[1], -row[2]))
    return ranking[0][3]


def explain(skill: Any) -> dict[str, Any]:
    history = getattr(skill, "history", None)
    level = level_of(skill)
    runs = getattr(history, "runs", 0) if history else 0
    rate = getattr(history, "success_rate", 0.0) if history else 0.0

    if level == EXPERIMENTAL:
        say = "never run, so I cannot tell you whether it works"
    elif level == VERIFIED:
        say = f"worked {runs} times, {int(rate * 100)}% of the time, recently"
    else:
        need = next((f"{r[1]} runs at {int(r[2] * 100)}%" for r in _RUNGS
                     if LADDER.index(r[0]) > LADDER.index(level)), "")
        say = (f"{runs} run(s), {int(rate * 100)}% successful"
               + (f"; needs {need} to rank higher" if need else ""))

    return {"level": level, "trusted": trusted(skill), "runs": runs,
            "success_rate": round(rate, 3), "say": say}


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "ladder": list(LADDER),
        "thresholds": [{"level": lv, "min_runs": r, "min_success_rate": s}
                       for lv, r, s in _RUNGS],
        "verified_needs_recent_success_days": round(FRESH_S / 86400),
        "trusted_from": TRUSTED_FROM,
        "note": ("Derived from real outcomes, never set. A skill cannot become "
                 "VERIFIED on one run, and a skill that has not succeeded recently "
                 "drops back to HIGH however good its record was."),
    }
