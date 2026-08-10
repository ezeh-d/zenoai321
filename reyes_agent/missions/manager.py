"""Long-running missions that survive a restart.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR
----------------------------------------
Not for "what's the time" and not for a reminder -- the brief is explicit
that trivial one-step commands must never become missions, and the existing
scheduler already handles timers. This is for work measured in stages:
"research these companies over the next few days and prepare a report."

THE RESTART PROPERTY
--------------------
    ensure(key=...)  ->  creates a mission, or returns the existing one

After a crash, ZENO calls `ensure()` with the same key and gets the SAME
mission back, positioned at the step it had reached. `resume()` then picks
it up from the last committed checkpoint. Nothing is inferred from memory,
because memory is what the restart destroyed.

TEMPORAL
--------
Temporal is the right tool for this at scale and `temporal_backend.py`
records how it would attach. It is not installed here and running a server
for one desktop assistant would be infrastructure for its own sake, so the
default backend is local, durable and honest about being local.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent.missions import store

# States, as the brief lists them.
CREATED = "CREATED"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
WAITING = "WAITING"
PAUSED = "PAUSED"
RETRYING = "RETRYING"
BLOCKED = "BLOCKED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

STATES = (CREATED, QUEUED, RUNNING, WAITING, PAUSED, RETRYING,
          BLOCKED, COMPLETED, FAILED, CANCELLED)

# A mission that is finished stays finished; resume() must never restart one.
TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})

# Interrupted rather than finished -- these are what recovery picks up.
RESUMABLE = frozenset({CREATED, QUEUED, RUNNING, WAITING, RETRYING, PAUSED})

MAX_ATTEMPTS_PER_STEP = 3

# A mission whose heartbeat is older than this was almost certainly killed
# mid-flight rather than being legitimately slow.
STALE_AFTER_S = 900.0


@dataclass
class Mission:
    mission_id: str
    key: str
    title: str
    description: str = ""
    state: str = CREATED
    steps: list[dict[str, Any]] = field(default_factory=list)
    cursor: int = 0
    attempts: int = 0
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    heartbeat_at: float = 0.0

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL

    @property
    def progress(self) -> float:
        return (self.cursor / len(self.steps)) if self.steps else 0.0

    @property
    def stale(self) -> bool:
        return (self.state == RUNNING and self.heartbeat_at > 0
                and (time.time() - self.heartbeat_at) > STALE_AFTER_S)

    def as_dict(self) -> dict[str, Any]:
        return {"mission_id": self.mission_id, "key": self.key, "title": self.title,
                "description": self.description, "state": self.state,
                "steps": self.steps, "cursor": self.cursor, "attempts": self.attempts,
                "progress": round(self.progress, 3), "result": self.result[:2000],
                "error": self.error[:1000], "finished": self.finished,
                "stale": self.stale, "created_at": self.created_at,
                "updated_at": self.updated_at}

    def summary(self) -> str:
        done = f"{self.cursor}/{len(self.steps)} steps"
        if self.state == COMPLETED:
            return f"'{self.title}' completed ({done})"
        if self.state == FAILED:
            return f"'{self.title}' failed at step {self.cursor + 1}: {self.error[:120]}"
        return f"'{self.title}' is {self.state} -- {done}"

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Mission":
        return cls(mission_id=row["mission_id"], key=row["key"], title=row["title"],
                   description=row.get("description", ""), state=row["state"],
                   steps=json.loads(row["steps"] or "[]"), cursor=int(row.get("cursor", 0)),
                   attempts=int(row.get("attempts", 0)), result=row.get("result", ""),
                   error=row.get("error", ""), created_at=float(row.get("created_at", 0)),
                   updated_at=float(row.get("updated_at", 0)),
                   heartbeat_at=float(row.get("heartbeat_at", 0)))


def key_for(title: str, steps: list[dict[str, Any]] | None = None) -> str:
    """A stable identity for 'this mission', derived from the request itself.

    Deliberately NOT random and NOT time-based: after a restart ZENO must
    arrive at the same key from the same request, which is the only reason
    it can recognise the mission as one it already has.
    """
    material = json.dumps({"title": str(title).strip().lower(),
                           "steps": [s.get("action", "") for s in steps or []]},
                          sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def ensure(title: str, steps: list[dict[str, Any]] | None = None, *,
           description: str = "", key: str = "") -> tuple[Mission, bool]:
    """Get the mission for this request, creating it only if it is new.

    Returns (mission, created). `created is False` after a restart -- that is
    the signal that ZENO is resuming rather than starting again.
    """
    steps = list(steps or [])
    identity = key or key_for(title, steps)

    existing = store.by_key(identity)
    if existing:
        return Mission.from_row(existing), False

    now = time.time()
    mission = Mission(mission_id=uuid.uuid4().hex[:16], key=identity, title=str(title),
                      description=str(description), state=CREATED, steps=steps,
                      created_at=now, updated_at=now)
    inserted = store.insert({
        "mission_id": mission.mission_id, "key": mission.key, "title": mission.title,
        "description": mission.description, "state": mission.state,
        "steps": json.dumps(mission.steps, default=str), "cursor": 0, "attempts": 0,
        "result": "", "error": "", "created_at": now, "updated_at": now,
        "heartbeat_at": 0.0})
    if not inserted:
        # Lost a race against another worker; theirs is the real one.
        row = store.by_key(identity)
        return Mission.from_row(row), False

    store.checkpoint(mission.mission_id, -1, CREATED, f"mission created: {title}")
    return mission, True


def get(mission_id: str) -> Mission | None:
    row = store.by_id(mission_id)
    return Mission.from_row(row) if row else None


def advance(mission: Mission, runner: Callable[[dict[str, Any], int], tuple[bool, str]],
            *, max_steps: int = 0, cancel_check: Callable[[], None] | None = None) -> Mission:
    """Run steps from wherever the mission actually is, checkpointing each.

    `runner(step, index) -> (ok, detail)`. Every outcome is committed to disk
    before the next step begins, so a kill at any point loses at most the
    step that was in flight.
    """
    if mission.finished:
        return mission

    store.update(mission.mission_id, state=RUNNING, heartbeat_at=time.time())
    mission.state = RUNNING
    ran = 0

    while mission.cursor < len(mission.steps):
        if max_steps and ran >= max_steps:
            store.update(mission.mission_id, state=WAITING)
            mission.state = WAITING
            return mission
        if cancel_check:
            try:
                cancel_check()
            except Exception:  # noqa: BLE001
                store.update(mission.mission_id, state=CANCELLED)
                store.checkpoint(mission.mission_id, mission.cursor, CANCELLED, "cancelled")
                mission.state = CANCELLED
                return mission

        index = mission.cursor
        step = mission.steps[index]
        store.checkpoint(mission.mission_id, index, RUNNING,
                         f"step {index + 1}: {step.get('action', '')}")
        try:
            ok, detail = runner(step, index)
        except Exception as exc:  # noqa: BLE001 -- a bad step must not kill the mission
            ok, detail = False, f"{type(exc).__name__}: {exc}"

        ran += 1
        if ok:
            mission.cursor = index + 1
            mission.attempts = 0
            store.update(mission.mission_id, cursor=mission.cursor, attempts=0)
            store.checkpoint(mission.mission_id, index, COMPLETED, detail)
            continue

        mission.attempts += 1
        if mission.attempts < MAX_ATTEMPTS_PER_STEP:
            store.update(mission.mission_id, state=RETRYING, attempts=mission.attempts)
            store.checkpoint(mission.mission_id, index, RETRYING,
                             f"attempt {mission.attempts}: {detail}")
            mission.state = RETRYING
            continue

        # Bounded: three attempts and it stops. No endless loop.
        store.update(mission.mission_id, state=FAILED, error=detail[:1000])
        store.checkpoint(mission.mission_id, index, FAILED, detail)
        mission.state, mission.error = FAILED, detail
        return mission

    store.update(mission.mission_id, state=COMPLETED, result=f"{len(mission.steps)} steps")
    store.checkpoint(mission.mission_id, mission.cursor, COMPLETED, "all steps done")
    mission.state = COMPLETED
    return mission


def resume_all(runner: Callable[[dict[str, Any], int], tuple[bool, str]] | None = None
               ) -> list[Mission]:
    """What ZENO calls on startup: pick up whatever the crash interrupted."""
    resumed = []
    for row in store.list_missions(tuple(RESUMABLE)):
        mission = Mission.from_row(row)
        if mission.finished:
            continue
        store.checkpoint(mission.mission_id, mission.cursor, QUEUED,
                         "resumed after restart")
        if runner is not None:
            mission = advance(mission, runner)
        else:
            store.update(mission.mission_id, state=QUEUED)
            mission.state = QUEUED
        resumed.append(mission)
    return resumed


def cancel(mission_id: str, why: str = "") -> bool:
    mission = get(mission_id)
    if mission is None or mission.finished:
        return False
    store.update(mission_id, state=CANCELLED, error=why[:500])
    store.checkpoint(mission_id, mission.cursor, CANCELLED, why)
    return True


def history(mission_id: str) -> list[dict[str, Any]]:
    return store.checkpoints(mission_id)


def status() -> dict[str, Any]:
    rows = store.list_missions()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    active = [r for r in rows if r["state"] not in TERMINAL]
    return {
        "state": "ONLINE",
        "total": len(rows),
        "active": len(active),
        "by_state": counts,
        "states": list(STATES),
        "backend": "local durable store (SQLite, committed per step)",
        "temporal": "not installed; see missions/temporal_backend.py",
        "max_attempts_per_step": MAX_ATTEMPTS_PER_STEP,
        "restart_safe": ("creation is idempotent on a key derived from the request "
                         "and enforced by a UNIQUE index, so a restart resumes the "
                         "existing mission instead of starting a second one"),
        "not_for": "one-step commands and reminders -- those stay on the scheduler",
    }
