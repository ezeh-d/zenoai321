"""Mastery model (#20, #35) -- how well each topic is actually known.

Every topic moves through explicit states on real EVIDENCE, never on a single
lucky answer. "What am I weak in?" and "how much have I learned?" read straight
off this, so the numbers are honest: progress is a fraction of tracked topics
that reached understanding, not an invented percentage.

Persistent, per course, kept in ZENO's learning store (separate from spatial
memory). Deterministic -- no model in the loop.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_ROOT = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "learning" / "mastery"

# ordered states
NOT_STARTED = "NOT_STARTED"
INTRODUCED = "INTRODUCED"
LEARNING = "LEARNING"
UNDERSTOOD = "UNDERSTOOD"
PRACTICED = "PRACTICED"
MASTERED = "MASTERED"
NEEDS_REVISION = "NEEDS_REVISION"

_ORDER = {NOT_STARTED: 0, INTRODUCED: 1, LEARNING: 2, UNDERSTOOD: 3,
          PRACTICED: 4, MASTERED: 5}
# NEEDS_REVISION is off the linear scale: a regression, not a rank.

# thresholds -- mastery needs sustained correctness, never one answer (#20)
_PRACTICED_CORRECT = 2
_MASTERED_CORRECT = 4
_MASTERED_SESSIONS = 2


def _course_key(course: str) -> str:
    return "".join(c for c in str(course or "general").lower() if c.isalnum() or c in "-_") or "general"


@dataclass
class Topic:
    name: str
    state: str = NOT_STARTED
    correct: int = 0
    attempts: int = 0
    sessions: list[str] = field(default_factory=list)   # distinct study/quiz days
    updated: float = 0.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.name, "state": self.state, "correct": self.correct,
                "attempts": self.attempts, "sessions": len(self.sessions),
                "updated": self.updated, "note": self.note}


class MasteryTracker:
    def __init__(self, root: Path = _ROOT) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    # -- storage -----------------------------------------------------------
    def _path(self, course: str) -> Path:
        return self._root / f"{_course_key(course)}.json"

    def _load(self, course: str) -> dict[str, Topic]:
        p = self._path(course)
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                return {k: Topic(**v) for k, v in raw.items()}
            except (ValueError, OSError, TypeError):
                pass
        return {}

    def _save(self, course: str, topics: dict[str, Topic]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {k: t.__dict__ for k, t in topics.items()}
        p = self._path(course)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    @staticmethod
    def _session_id(now: float | None = None) -> str:
        t = now if now is not None else _now()
        return time.strftime("%Y-%m-%d", time.gmtime(t))

    # -- evidence ----------------------------------------------------------
    def introduce(self, topic: str, *, course: str = "") -> dict[str, Any]:
        return self._transition(course, topic, event="introduce")

    def studied(self, topic: str, *, course: str = "") -> dict[str, Any]:
        return self._transition(course, topic, event="studied")

    def answered(self, topic: str, *, correct: bool, course: str = "",
                 session: str = "") -> dict[str, Any]:
        return self._transition(course, topic, event="answer", correct=correct,
                                session=session)

    def _transition(self, course: str, topic: str, *, event: str,
                    correct: bool | None = None, session: str = "") -> dict[str, Any]:
        with self._lock:
            topics = self._load(course)
            key = str(topic).strip().lower()
            if not key:
                return {"ok": False, "error": "empty topic"}
            t = topics.get(key) or Topic(name=str(topic).strip())
            sid = session or self._session_id()
            if sid not in t.sessions:
                t.sessions.append(sid)

            if event == "introduce":
                if _ORDER.get(t.state, 0) < _ORDER[INTRODUCED]:
                    t.state = INTRODUCED
            elif event == "studied":
                if t.state in (NOT_STARTED, INTRODUCED):
                    t.state = LEARNING
            elif event == "answer":
                t.attempts += 1
                if correct:
                    t.correct += 1
                    # a wrong-then-right recovery clears the revision flag
                    if t.state in (LEARNING, INTRODUCED, NOT_STARTED, NEEDS_REVISION):
                        t.state = UNDERSTOOD
                    if t.correct >= _PRACTICED_CORRECT and _ORDER.get(t.state, 0) >= _ORDER[UNDERSTOOD]:
                        t.state = PRACTICED
                    if (t.correct >= _MASTERED_CORRECT
                            and len(t.sessions) >= _MASTERED_SESSIONS):
                        t.state = MASTERED   # sustained, across sessions -- not one answer
                else:
                    # a miss on something previously understood is a regression
                    if _ORDER.get(t.state, 0) >= _ORDER[UNDERSTOOD] or t.state == MASTERED:
                        t.state = NEEDS_REVISION
                    elif t.state == NOT_STARTED:
                        t.state = LEARNING

            t.updated = _now()
            topics[key] = t
            self._save(course, topics)
            return {"ok": True, "topic": t.name, "state": t.state,
                    "correct": t.correct, "attempts": t.attempts}

    def flag_revision(self, topic: str, *, course: str = "") -> dict[str, Any]:
        with self._lock:
            topics = self._load(course)
            key = str(topic).strip().lower()
            t = topics.get(key)
            if not t:
                return {"ok": False, "error": f"unknown topic '{topic}'"}
            t.state = NEEDS_REVISION
            t.updated = _now()
            self._save(course, topics)
            return {"ok": True, "topic": t.name, "state": t.state}

    # -- queries -----------------------------------------------------------
    def state_of(self, topic: str, *, course: str = "") -> str:
        return (self._load(course).get(str(topic).strip().lower())
                or Topic(name=topic)).state

    def weak_topics(self, *, course: str = "") -> list[dict[str, Any]]:
        weak = [t for t in self._load(course).values()
                if t.state in (NEEDS_REVISION, LEARNING, INTRODUCED)]
        weak.sort(key=lambda t: (t.state != NEEDS_REVISION, _ORDER.get(t.state, 0)))
        return [t.as_dict() for t in weak]

    def report(self, *, course: str = "") -> dict[str, Any]:
        topics = self._load(course)
        if not topics:
            return {"ok": True, "course": course or "general", "topics": 0,
                    "progress": 0, "note": "nothing tracked yet"}
        counts: dict[str, int] = {}
        for t in topics.values():
            counts[t.state] = counts.get(t.state, 0) + 1
        understood_plus = sum(counts.get(s, 0)
                              for s in (UNDERSTOOD, PRACTICED, MASTERED))
        total = len(topics)
        # honest progress: fraction of tracked topics that reached understanding
        progress = round(100 * understood_plus / total) if total else 0
        return {"ok": True, "course": course or "general", "topics": total,
                "progress": progress, "by_state": counts,
                "mastered": counts.get(MASTERED, 0),
                "practiced": counts.get(PRACTICED, 0),
                "understood": counts.get(UNDERSTOOD, 0),
                "learning": counts.get(LEARNING, 0) + counts.get(INTRODUCED, 0),
                "needs_revision": counts.get(NEEDS_REVISION, 0),
                "detail": [t.as_dict() for t in sorted(
                    topics.values(), key=lambda x: -_ORDER.get(x.state, 0))]}

    def reset(self, *, course: str = "") -> dict[str, Any]:
        with self._lock:
            p = self._path(course)
            existed = p.exists()
            p.unlink(missing_ok=True)
            return {"ok": True, "course": course or "general", "cleared": existed}


def _now() -> float:
    try:
        return time.time()
    except Exception:  # noqa: BLE001
        return 0.0


_tracker: MasteryTracker | None = None
_tracker_lock = threading.Lock()


def get_mastery_tracker() -> MasteryTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = MasteryTracker()
    return _tracker
