"""Anticipation -- what usually happens next, learned from what really did.

THE ONE THING THAT MAKES AN ASSISTANT FEEL LIKE JARVIS
------------------------------------------------------
Not the voice, and not the wit. It is that it already knows what you are
about to need. That only works if it has genuinely watched you; anything
else is a horoscope.

So this module learns ONLY from `activity_log` -- the foreground-window
samples `activity_monitor` has already been recording. Nothing new is
watched, nothing is inferred about the owner as a person, and no signal is
invented.

WHAT "CONFIDENCE" MEANS HERE
----------------------------
A real proportion over a real count. "You are in Chrome at 10am on Mondays
7 times out of 9" is a prediction. "You seem like a morning person" is not,
and this module will not say it.

Two hard rules:

* Below `MIN_SAMPLES` observations, there is NO prediction -- `predict()`
  returns None and says the evidence is thin. Silence is the correct output
  of an under-trained model.
* Every prediction carries the counts it came from, so a caller (and the
  owner) can see exactly how much it is worth.

PRIVACY
-------
Window TITLES are never learned from -- only executable names. A title can
contain a document name, a customer, a message. The pattern "he uses Chrome
at 10am" is useful; "he read "X" at 10am" is surveillance.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reyes_agent import config

_DB = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

# Evidence thresholds. Deliberately conservative: a wrong anticipation is
# worse than none, because it teaches the owner to ignore them.
MIN_SAMPLES = 8            # per slot, before that slot may be predicted from
MIN_CONFIDENCE = 0.34      # below this the "usual" app is not usual enough
MIN_TRANSITIONS = 5        # before "after X you usually open Y"
_MODEL_TTL_S = 1800.0      # relearn at most twice an hour
_MAX_ROWS = 20_000

_lock = threading.Lock()
_model: "Model | None" = None
_model_at = 0.0


@dataclass
class Prediction:
    kind: str                       # "app" | "transition"
    value: str
    confidence: float               # observed proportion, 0..1
    observations: int               # how many samples support it
    basis: str                      # human-readable evidence
    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value,
                "confidence": round(self.confidence, 3),
                "observations": self.observations, "basis": self.basis}


@dataclass
class Model:
    """Counts, not weights. Everything here is directly countable."""

    slots: dict[tuple[int, int], Counter] = field(default_factory=lambda: defaultdict(Counter))
    transitions: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    hours_active: Counter = field(default_factory=Counter)
    total_samples: int = 0
    span_hours: float = 0.0
    learned_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"total_samples": self.total_samples,
                "span_hours": round(self.span_hours, 1),
                "slots_learned": len(self.slots),
                "apps_with_transitions": len(self.transitions),
                "learned_at": self.learned_at}


def _friendly(app: str) -> str:
    """`chrome.exe` -> `Chrome`. Uses the existing mapping where present."""
    try:
        from reyes_agent.activity_monitor import _friendly as shared

        return shared(app)
    except Exception:  # noqa: BLE001
        return str(app or "").replace(".exe", "").title()


def learn(force: bool = False) -> Model:
    """Build the counts from real samples. Cached for `_MODEL_TTL_S`."""
    global _model, _model_at
    with _lock:
        if not force and _model is not None and (time.time() - _model_at) < _MODEL_TTL_S:
            return _model

    model = Model()
    try:
        conn = sqlite3.connect(_DB, timeout=3)
        try:
            rows = conn.execute(
                # Titles are deliberately NOT selected. Learn from the most
                # recent bounded window, not the oldest records forever.
                "SELECT ts, app, idle FROM ("
                "SELECT ts, app, idle FROM activity_log ORDER BY ts DESC LIMIT ?"
                ") ORDER BY ts ASC",
                (_MAX_ROWS,)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- no history yet is a normal state
        rows = []

    previous_app = None
    previous_ts = None
    for ts, app, idle in rows:
        if idle or not app:
            previous_app = None            # an idle gap breaks the chain
            continue
        when = datetime.fromtimestamp(ts)
        model.slots[(when.weekday(), when.hour)][app] += 1
        model.hours_active[when.hour] += 1
        model.total_samples += 1
        # A transition only counts if the samples are adjacent in time.
        # Two apps either side of a six-hour gap are not a habit.
        if previous_app and previous_app != app and previous_ts and (ts - previous_ts) <= 180:
            model.transitions[previous_app][app] += 1
        previous_app = app
        previous_ts = ts

    if rows:
        model.span_hours = (rows[-1][0] - rows[0][0]) / 3600.0

    with _lock:
        _model = model
        _model_at = time.time()
    return model


def predict_app(weekday: int | None = None, hour: int | None = None) -> Prediction | None:
    """What the owner is usually doing in this slot, or None.

    Returning None is a real answer -- it means the evidence for this hour
    does not support a claim.
    """
    now = datetime.now()
    weekday = now.weekday() if weekday is None else weekday
    hour = now.hour if hour is None else hour
    model = learn()

    counts = model.slots.get((weekday, hour))
    if not counts:
        return None
    total = sum(counts.values())
    if total < MIN_SAMPLES:
        return None
    app, seen = counts.most_common(1)[0]
    confidence = seen / total
    if confidence < MIN_CONFIDENCE:
        return None
    day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday]
    return Prediction(
        kind="app", value=_friendly(app), confidence=confidence, observations=total,
        basis=f"{seen} of {total} samples at {day} {hour:02d}:00")


def predict_next(current_app: str) -> Prediction | None:
    """After this app, what usually follows."""
    if not current_app:
        return None
    model = learn()
    counts = model.transitions.get(current_app)
    if not counts:
        return None
    total = sum(counts.values())
    if total < MIN_TRANSITIONS:
        return None
    app, seen = counts.most_common(1)[0]
    confidence = seen / total
    if confidence < MIN_CONFIDENCE:
        return None
    return Prediction(
        kind="transition", value=_friendly(app), confidence=confidence, observations=total,
        basis=f"after {_friendly(current_app)}, {seen} of {total} times")


def quiet_hours() -> list[int]:
    """Hours with essentially no observed activity.

    Useful for NOT interrupting. Derived from real counts, so on a machine
    with little history this correctly returns almost nothing.
    """
    model = learn()
    if model.total_samples < MIN_SAMPLES * 4:
        return []
    busiest = max(model.hours_active.values()) if model.hours_active else 0
    if not busiest:
        return []
    return sorted(h for h in range(24) if model.hours_active.get(h, 0) < busiest * 0.05)


def readiness() -> dict[str, Any]:
    """How much this model is actually worth. Reported, never implied."""
    model = learn()
    usable_slots = sum(1 for counts in model.slots.values() if sum(counts.values()) >= MIN_SAMPLES)
    return {
        "total_samples": model.total_samples,
        "span_hours": round(model.span_hours, 1),
        "slots_with_enough_evidence": usable_slots,
        "slots_seen": len(model.slots),
        "ready": usable_slots >= 3,
        "min_samples_per_slot": MIN_SAMPLES,
        "note": ("Learned only from foreground executable names already sampled by "
                 "activity_monitor. Window titles are never used. A slot below "
                 f"{MIN_SAMPLES} samples produces no prediction at all."),
    }


def directive() -> str:
    """Per-turn prompt fragment, or nothing.

    Kept to one short line and only emitted when a prediction genuinely
    clears the evidence bar -- so on a fresh install ZENO says nothing
    rather than pretending to know the owner.
    """
    try:
        prediction = predict_app()
    except Exception:  # noqa: BLE001 -- anticipation must never break a turn
        return ""
    if prediction is None:
        return ""
    return (f"[Pattern: around this hour he is usually in {prediction.value} "
            f"({prediction.confidence:.0%}, {prediction.basis}). Context only -- "
            "do not mention it unless it is directly useful, and never present a "
            "pattern as certainty.]")


def reset() -> None:
    """Test hook."""
    global _model, _model_at
    with _lock:
        _model = None
        _model_at = 0.0
