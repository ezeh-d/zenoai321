"""Response latency timeline -- developer diagnostics, measured not guessed.

WHAT THIS ANSWERS
-----------------
"ZENO feels slow" is not actionable. "Time to first audio is 2.4s, of which
1.9s is the model and 0.3s is TTS" is. This module records the twelve marks
of a turn as they genuinely happen and derives the durations between them.

THE HONESTY RULE
----------------
A derived duration is returned ONLY when both of its endpoints were really
recorded. If TTS never ran, `time_to_first_audio` is `None` -- not zero, not
an estimate, not the model latency reused as a stand-in. A missing number is
information; a fabricated one destroys the whole point of measuring.

CLOCKS
------
The browser owns the marks it alone can see (speech start, endpoint
detection, first audio out of the speaker); the server owns the rest. Both
run on the same machine and both use wall-clock seconds, so they are
directly comparable. Cross-machine use would need clock-skew handling and
this module does not pretend to do it.

COST
----
A mark is a dict write under a lock. Turns live in a bounded ring buffer, so
a long session cannot grow this. Nothing here is on the critical path of
producing an answer, and every entry point swallows its own errors --
instrumentation that can break the thing it measures is worse than none.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

# The canonical marks, in the order they occur. Order matters for display
# and for working out which phase is missing.
MARKS = (
    "speech_started",       # mic detected the user starting to talk        (browser)
    "speech_finished",      # energy VAD saw the user stop                  (browser)
    "endpoint_detected",    # linguistic endpointing decided he is done     (browser)
    "stt_final",            # final transcript in hand                      (browser)
    "intent_ready",         # cognition.route() finished                    (server)
    "context_ready",        # prompt/context assembled                      (server)
    "model_requested",      # request handed to the provider                (server)
    "first_model_token",    # first streamed token came back                (server)
    "first_sentence_ready", # enough text to start speaking                 (server)
    "tts_requested",        # speech synthesis asked for                    (server)
    "first_audio",          # first audio actually played                   (browser)
    "response_finished",    # turn complete                                 (server)
)
# Optional paths must be accepted and measured without making an ordinary
# turn look incomplete. Most fast replies never need a thinking ack.
OPTIONAL_MARKS = (
    "thinking_ack_audio",   # cached progress speech reached the speaker     (browser)
)
_MARK_SET = frozenset(MARKS + OPTIONAL_MARKS)

# Each derived metric is (name, start_mark, end_mark, from_origin).
#
# `from_origin` metrics answer "how long until the user saw/heard
# something", so on a typed turn they legitimately measure from when the
# message arrived instead of from a speech endpoint that never existed.
#
# Everything else measures one specific phase. Those must NOT be rebased:
# `stt_latency` on a typed turn is not zero, it is absent -- there was no
# speech recognition to time. Reporting 0.0 there would be exactly the kind
# of invented number this module exists to avoid.
_DERIVED = (
    ("stt_latency",          "endpoint_detected", "stt_final",         False),
    ("intent_latency",       "stt_final",         "intent_ready",      False),
    ("context_latency",      "intent_ready",      "context_ready",     False),
    ("model_latency",        "model_requested",   "first_model_token", False),
    ("time_to_first_token",  "endpoint_detected", "first_model_token", True),
    ("tts_latency",          "tts_requested",     "first_audio",       False),
    ("time_to_ack_audio",    "endpoint_detected", "thinking_ack_audio", True),
    ("time_to_first_audio",  "endpoint_detected", "first_audio",       True),
    ("total_latency",        "endpoint_detected", "response_finished", True),
)

# For a typed turn there is no speech, so latency is measured from when the
# message arrived instead of from an endpoint that never happened.
_TYPED_ORIGIN = "stt_final"

_MAX_TURNS = 200

_lock = threading.RLock()
_turns: dict[str, dict[str, Any]] = {}
_order: deque[str] = deque(maxlen=_MAX_TURNS)
_wake_ack_samples: deque[dict[str, Any]] = deque(maxlen=200)
_barge_in_samples: deque[dict[str, Any]] = deque(maxlen=200)
_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> bool:
    """Diagnostics can be switched off entirely; marks then cost nothing."""
    global _enabled
    _enabled = bool(value)
    return _enabled


def begin(turn_id: str = "", *, kind: str = "voice", message_preview: str = "") -> str:
    """Open a turn timeline. `kind` is 'voice' or 'typed'."""
    turn_id = str(turn_id or uuid.uuid4().hex[:12])
    if not _enabled:
        return turn_id
    kind = kind if kind in {"voice", "typed"} else "voice"
    with _lock:
        existing = _turns.get(turn_id)
        if existing is not None:
            # The browser fires its marks the instant they happen, so an
            # early mark can arrive before the chat request opens the turn
            # and auto-creates it with a default kind. The explicit begin()
            # is the authority on what kind of turn this is -- observed
            # 2026-08-07 mislabelling typed turns as voice.
            existing["kind"] = kind
            if message_preview and not existing.get("preview"):
                existing["preview"] = str(message_preview)[:60]
            return turn_id
        if turn_id not in _turns:
            _order.append(turn_id)
            _turns[turn_id] = {
                "turn_id": turn_id,
                "kind": kind,
                # Deliberately a short preview, never the full utterance:
                # this is a performance record, not a transcript store.
                "preview": str(message_preview or "")[:60],
                "marks": {},
                "created": time.time(),
            }
            while len(_turns) > _MAX_TURNS:
                oldest = _order[0] if _order else None
                if oldest is None:
                    break
                _order.popleft()
                _turns.pop(oldest, None)
    return turn_id


def mark(turn_id: str, name: str, at: float | None = None) -> bool:
    """Record one mark. Never raises; returns whether it was stored.

    A mark that arrives twice keeps the FIRST timestamp -- "first token"
    means the first one, and a duplicate listener firing it again must not
    quietly move the measurement.
    """
    if not _enabled:
        return False
    try:
        name = str(name or "")
        if name not in _MARK_SET or not turn_id:
            return False
        stamp = float(at) if at else time.time()
        with _lock:
            turn = _turns.get(turn_id)
            if turn is None:
                begin(turn_id)
                turn = _turns.get(turn_id)
                if turn is None:
                    return False
            if name in turn["marks"]:
                return False
            turn["marks"][name] = stamp
        return True
    except Exception:  # noqa: BLE001 -- diagnostics never break a turn
        return False


def _origin(turn: dict[str, Any]) -> str:
    """Where 'the clock starts' for this turn."""
    if turn.get("kind") == "typed":
        return _TYPED_ORIGIN
    return "endpoint_detected" if "endpoint_detected" in turn["marks"] else _TYPED_ORIGIN


def timeline(turn_id: str) -> dict[str, Any] | None:
    """One turn's marks plus every duration that could really be computed."""
    with _lock:
        turn = _turns.get(turn_id)
        if turn is None:
            return None
        marks = dict(turn["marks"])
        meta = {k: turn[k] for k in ("turn_id", "kind", "preview", "created")}

    origin_name = _origin({"kind": meta["kind"], "marks": marks})
    origin = marks.get(origin_name)

    derived: dict[str, float | None] = {}
    for name, start, end, from_origin in _DERIVED:
        start_name = origin_name if (from_origin and start not in marks) else start
        a, b = marks.get(start_name), marks.get(end)
        derived[name] = round(b - a, 4) if (a is not None and b is not None and b >= a) else None

    return {
        **meta,
        "marks": marks,
        "offsets_s": ({k: round(v - origin, 4) for k, v in sorted(marks.items(), key=lambda kv: kv[1])}
                      if origin else {}),
        "derived": derived,
        "missing_marks": [m for m in MARKS if m not in marks],
        "complete": "response_finished" in marks,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 4)


def summary(limit: int = 50) -> dict[str, Any]:
    """Percentiles across recent turns, per derived metric.

    `samples` is reported next to every statistic on purpose: a p95 over
    three turns is not a p95, and the reader should be able to see that.
    """
    with _lock:
        recent = [t for t in list(_order)[-limit:]]
    stats: dict[str, Any] = {}
    collected: dict[str, list[float]] = {name: [] for name, *_rest in _DERIVED}
    complete = 0
    for turn_id in recent:
        line = timeline(turn_id)
        if line is None:
            continue
        complete += bool(line["complete"])
        for name, value in line["derived"].items():
            if value is not None:
                collected[name].append(value)
    for name, values in collected.items():
        stats[name] = {
            "samples": len(values),
            "median_s": _percentile(values, 0.5),
            "p90_s": _percentile(values, 0.90),
            "p95_s": _percentile(values, 0.95),
            "min_s": round(min(values), 4) if values else None,
            "max_s": round(max(values), 4) if values else None,
        }
    with _lock:
        wake_values = [float(row["latency_s"]) for row in _wake_ack_samples]
        barge_values = [float(row["latency_s"]) for row in _barge_in_samples]
    return {
        "turns_considered": len(recent),
        "turns_complete": complete,
        "metrics": stats,
        "enabled": _enabled,
        "wake_ack": {
            "samples": len(wake_values),
            "median_s": _percentile(wake_values, 0.5),
            "p90_s": _percentile(wake_values, 0.90),
            "p95_s": _percentile(wake_values, 0.95),
            "worst_s": round(max(wake_values), 4) if wake_values else None,
            "target_s": [0.15, 0.40],
        },
        "barge_in": {
            "samples": len(barge_values),
            "median_s": _percentile(barge_values, 0.5),
            "p90_s": _percentile(barge_values, 0.90),
            "p95_s": _percentile(barge_values, 0.95),
            "worst_s": round(max(barge_values), 4) if barge_values else None,
            "target_s": [0.10, 0.30],
        },
        "note": ("A metric with 0 samples was never measurable in these turns -- "
                 "for example time_to_first_audio when TTS did not run. Absent is "
                 "reported as absent, never as zero."),
    }


def recent(limit: int = 10) -> list[dict[str, Any]]:
    with _lock:
        ids = list(_order)[-max(1, min(limit, 50)):]
    return [line for line in (timeline(t) for t in reversed(ids)) if line]


def finish(turn_id: str) -> dict[str, Any] | None:
    """Close the turn and publish its timeline for the diagnostics panel."""
    mark(turn_id, "response_finished")
    line = timeline(turn_id)
    if line is None:
        return None
    try:
        from reyes_agent import event_bus

        event_bus.publish("latency.turn", {
            "turn_id": turn_id, "kind": line["kind"],
            "derived": line["derived"], "missing": line["missing_marks"],
        }, source="latency", correlation_id=turn_id)
    except Exception:  # noqa: BLE001
        pass
    # Feed the existing performance monitor rather than starting a second
    # metrics store next to it.
    try:
        from reyes_agent.performance_monitor import record_latency

        for name in ("model_latency", "time_to_first_token", "total_latency"):
            value = line["derived"].get(name)
            if value is not None:
                record_latency(f"turn.{name}", value)
    except Exception:  # noqa: BLE001
        pass
    return line


def record_wake_ack(*, detected_at: float, audio_started_at: float,
                    phrase: str = "", source: str = "browser") -> dict[str, Any]:
    """Store a real local-wake-to-audible-playback measurement."""
    detected = float(detected_at)
    started = float(audio_started_at)
    if detected <= 0 or started < detected or started - detected > 30:
        raise ValueError("Invalid wake acknowledgement timestamps")
    row = {
        "detected_at": detected,
        "audio_started_at": started,
        "latency_s": round(started - detected, 4),
        "phrase": str(phrase)[:40],
        "source": str(source)[:40],
    }
    with _lock:
        _wake_ack_samples.append(row)
    try:
        from reyes_agent import event_bus

        event_bus.publish("latency.wake_ack", row, source="latency")
    except Exception:
        pass
    return row


def record_barge_in(*, detected_at: float, audio_stopped_at: float,
                    source: str = "browser") -> dict[str, Any]:
    detected = float(detected_at)
    stopped = float(audio_stopped_at)
    if detected <= 0 or stopped < detected or stopped - detected > 10:
        raise ValueError("Invalid barge-in timestamps")
    row = {"detected_at": detected, "audio_stopped_at": stopped,
           "latency_s": round(stopped - detected, 4), "source": str(source)[:40]}
    with _lock:
        _barge_in_samples.append(row)
    try:
        from reyes_agent import event_bus

        event_bus.publish("latency.barge_in", row, source="latency")
    except Exception:
        pass
    return row


def reset() -> None:
    """Test hook."""
    with _lock:
        _turns.clear()
        _order.clear()
        _wake_ack_samples.clear()
        _barge_in_samples.clear()
