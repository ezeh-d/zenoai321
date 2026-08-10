"""The computer agent's lifecycle, published as events the dashboard can follow.

WHY EVENTS RATHER THAN RETURN VALUES
------------------------------------
A computer-use run is the one thing in ZENO the owner most wants to watch
while it happens. A function that returns an outcome at the end tells them
nothing during the twenty seconds it is clicking around their machine, and
"trust me, I'm working" is exactly the wrong posture for software driving
someone else's mouse.

So each stage is published to the EXISTING `event_bus` -- not a second bus.
The dashboard already subscribes there.

THE ONE RULE
------------
An event is emitted when the thing has ACTUALLY happened. `ACTION_COMPLETED`
after the input was really sent, `VERIFICATION` carrying what the screen
really said afterwards. Emitting an optimistic event is the same lie as a
fake progress bar, and this project has been explicit about that from the
first phase.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

# The stages, exactly as the brief lists them.
OBSERVATION = "OBSERVATION"
PLAN_CREATED = "PLAN_CREATED"
ACTION_REQUESTED = "ACTION_REQUESTED"
ACTION_STARTED = "ACTION_STARTED"
ACTION_COMPLETED = "ACTION_COMPLETED"
VERIFICATION = "VERIFICATION"
RETRY = "RETRY"
FAILURE = "FAILURE"
SUCCESS = "SUCCESS"

STAGES = (OBSERVATION, PLAN_CREATED, ACTION_REQUESTED, ACTION_STARTED,
          ACTION_COMPLETED, VERIFICATION, RETRY, FAILURE, SUCCESS)

# Stages that may only be emitted once something real has been confirmed.
_EVIDENCE_REQUIRED = frozenset({ACTION_COMPLETED, VERIFICATION, SUCCESS})

_TOPIC = "zeno.computer."


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def emit(stage: str, run_id: str, payload: dict[str, Any] | None = None,
         *, evidence: str = "") -> bool:
    """Publish one lifecycle stage. Returns whether it was published.

    Stages that assert something happened are refused without evidence --
    the caller has to say WHAT it observed, not merely that it finished.
    """
    if stage not in STAGES:
        return False
    if stage in _EVIDENCE_REQUIRED and not evidence:
        return False

    body = {"run_id": run_id, "stage": stage, "at": time.time(), **(payload or {})}
    if evidence:
        body["evidence"] = str(evidence)[:600]
    try:
        from reyes_agent import event_bus

        event_bus.publish(_TOPIC + stage.lower(), body, source="computer")
        return True
    except Exception:  # noqa: BLE001 -- telemetry must never break the action
        return False


def observed(run_id: str, scene: Any) -> None:
    """What was actually on screen, including whether the read was any good."""
    coverage = getattr(scene, "coverage", None)
    emit(OBSERVATION, run_id, {
        "window": getattr(scene, "window", ""),
        "elements": len(getattr(scene, "elements", []) or []),
        "interactive": len(getattr(scene, "interactive", []) or []),
        "reliable": bool(getattr(scene, "reliable", True)),
        "coverage": coverage.state if coverage is not None else None,
    })


def planned(run_id: str, goal: str, steps: list[dict], backend: str = "") -> None:
    emit(PLAN_CREATED, run_id, {"goal": str(goal)[:300], "steps": len(steps),
                                "backend": backend,
                                "actions": [s.get("action", "") for s in steps][:12]})


def requested(run_id: str, index: int, action: str, target: str, risk: str = "") -> None:
    emit(ACTION_REQUESTED, run_id, {"index": index, "action": action,
                                    "target": str(target)[:160], "risk": risk})


def started(run_id: str, index: int, action: str, backend: str = "") -> None:
    emit(ACTION_STARTED, run_id, {"index": index, "action": action, "backend": backend})


def completed(run_id: str, index: int, action: str, detail: str) -> None:
    emit(ACTION_COMPLETED, run_id, {"index": index, "action": action}, evidence=detail)


def verified(run_id: str, index: int, changed: bool, detail: str) -> None:
    emit(VERIFICATION, run_id, {"index": index, "changed": bool(changed)}, evidence=detail)


def retried(run_id: str, index: int, attempt: int, why: str) -> None:
    emit(RETRY, run_id, {"index": index, "attempt": attempt, "why": str(why)[:300]})


def failed(run_id: str, reason: str, index: int = -1) -> None:
    emit(FAILURE, run_id, {"index": index, "reason": str(reason)[:600]})


def succeeded(run_id: str, summary: str, steps: int = 0) -> None:
    emit(SUCCESS, run_id, {"steps": steps}, evidence=summary)


def timeline(run_id: str = "", limit: int = 60) -> list[dict[str, Any]]:
    """Replay a run, in order. What the dashboard draws."""
    try:
        from reyes_agent import event_bus

        events = event_bus.history(limit=max(limit, 200))
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for event in events:
        kind = getattr(event, "event_type", None) or (
            event.get("event_type") if isinstance(event, dict) else "")
        if not str(kind).startswith(_TOPIC):
            continue
        payload = getattr(event, "payload", None) or (
            event.get("payload") if isinstance(event, dict) else {}) or {}
        if run_id and payload.get("run_id") != run_id:
            continue
        rows.append({"stage": payload.get("stage", ""), "at": payload.get("at", 0),
                     "run_id": payload.get("run_id", ""), "detail": payload})
    rows.sort(key=lambda r: r["at"])
    return rows[-limit:]


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "stages": list(STAGES),
        "topic": _TOPIC + "*",
        "bus": "the existing event_bus -- not a second bus",
        "evidence_required": sorted(_EVIDENCE_REQUIRED),
        "note": ("A stage is published when it has really happened. The stages that "
                 "assert an outcome cannot be emitted without saying what was "
                 "observed, so the dashboard can never show a completed step that "
                 "did not occur."),
    }
