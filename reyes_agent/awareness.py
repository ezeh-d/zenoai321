"""Situational awareness -- one picture of what is actually going on.

WHY THIS EXISTS
---------------
ZENO already had a lot of senses: it samples the foreground window, tracks
idle time, watches notifications, knows its own health, holds a calendar,
runs tasks. What it did not have was a place where those become ONE
picture. Each sensor answered its own question and nobody asked "so what is
happening right now?"

That gap is the difference between an assistant that answers questions and
one that seems to be in the room with you. A reply written while knowing
"he has been in the editor for 90 minutes, a build is running, and his
calendar has a call in 12 minutes" is a different reply from the same words
written blind -- without ever mentioning any of it.

WHAT IT REFUSES TO DO
---------------------
* It never invents a signal. If the activity monitor has not sampled yet,
  the field is `None` and `summary()` omits it rather than guessing.
* It does not add a sensor. Everything here is read from a subsystem that
  was already running; nothing new is polled, watched or recorded.
* It is CACHED. This runs on every turn, so a cold read is ~1 query and a
  warm read is a dict copy. An awareness layer that costs latency would be
  paid for by the owner on every single message.
* It states what it CANNOT know. There is no location, no biometrics, no
  camera unless the owner explicitly asks for vision.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reyes_agent import config

# The picture is re-fused at most this often. Situations do not change
# meaningfully faster than this, and a per-turn rebuild would be waste.
_TTL_S = 20.0
_DB = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

_lock = threading.Lock()
_cached: "Situation | None" = None
_cached_at = 0.0


def _part_of_day(hour: int) -> str:
    if hour < 5:
        return "late night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


@dataclass
class Situation:
    """What is observably true right now. Unknown fields stay None."""

    at: float = field(default_factory=time.time)
    # time
    hour: int = 0
    weekday: str = ""
    part_of_day: str = ""
    # workspace
    app: str | None = None
    window: str | None = None
    focus_minutes: float | None = None      # how long in this app, continuously
    idle_seconds: float | None = None
    session_minutes: float | None = None    # continuous active work this session
    # ZENO itself
    conversation_state: str | None = None
    running_tasks: int = 0
    task_titles: list[str] = field(default_factory=list)
    website_projects: int = 0
    # environment
    battery_percent: int | None = None
    battery_charging: bool | None = None
    next_event: str | None = None
    next_event_minutes: int | None = None
    # honesty
    unavailable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    def summary(self) -> str:
        """One compact line per known fact. Empty when nothing is known.

        Deliberately terse: this goes into the system prompt on every turn,
        and prompt length is latency.
        """
        bits: list[str] = [f"{self.part_of_day} ({self.weekday} {self.hour:02d}:00)"]
        if self.app:
            focused = f" for {self.focus_minutes:.0f}m" if self.focus_minutes and self.focus_minutes >= 5 else ""
            bits.append(f"in {self.app}{focused}")
        if self.idle_seconds is not None and self.idle_seconds > 300:
            bits.append(f"away from the keyboard {self.idle_seconds / 60:.0f}m")
        elif self.session_minutes and self.session_minutes >= 90:
            bits.append(f"working continuously {self.session_minutes:.0f}m")
        if self.running_tasks:
            titles = ", ".join(self.task_titles[:2])
            bits.append(f"{self.running_tasks} task(s) running: {titles}")
        if self.next_event and self.next_event_minutes is not None and self.next_event_minutes <= 120:
            bits.append(f"'{self.next_event}' in {self.next_event_minutes}m")
        if self.battery_percent is not None and self.battery_percent <= 25 and not self.battery_charging:
            bits.append(f"battery {self.battery_percent}%")
        return "; ".join(bits)


def _read_activity(situation: Situation) -> None:
    """Foreground app, how long it has been focused, and idle time.

    Reads activity_monitor's existing samples -- it is already running and
    already writing them, so this adds no polling of its own.
    """
    try:
        from reyes_agent.activity_monitor import foreground_app

        app, title = foreground_app()
        situation.app = app or None
        situation.window = (title or "")[:120] or None
    except Exception:  # noqa: BLE001 -- a missing sensor is not an error
        situation.unavailable.append("foreground window")

    try:
        from reyes_agent.activity_monitor import _idle_seconds

        situation.idle_seconds = round(_idle_seconds(), 1)
    except Exception:  # noqa: BLE001
        situation.unavailable.append("idle time")

    if not situation.app:
        return
    # How long has this app been continuously in front, and how long has the
    # current active stretch run? Both come from the samples already stored.
    try:
        conn = sqlite3.connect(_DB, timeout=2)
        try:
            rows = conn.execute(
                "SELECT ts, app, idle FROM activity_log ORDER BY ts DESC LIMIT 400").fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        situation.unavailable.append("activity history")
        return

    now = time.time()
    # A run of samples only proves continuity if the samples are actually
    # CONTIGUOUS. activity_monitor samples every 60s while ZENO runs, so a
    # gap beyond this means it was not watching -- not that the owner was
    # working through it. Measured 2026-08-07 with a 10-minute threshold:
    # real samples average ~6.6 minutes apart, so nothing ever broke the
    # chain and ZENO claimed a 65-hour continuous session. A number that
    # wrong is worse than no number.
    max_gap = 180.0

    focus_start = None
    previous_ts = None
    for ts, app, _idle in rows:
        if app != situation.app:
            break
        if previous_ts is not None and previous_ts - ts > max_gap:
            break
        focus_start = ts
        previous_ts = ts
    if focus_start is not None:
        situation.focus_minutes = round((now - focus_start) / 60.0, 1)

    session_start = None
    previous_ts = None
    exhausted = True
    for ts, _app, idle in rows:
        if idle:
            exhausted = False
            break
        if previous_ts is not None and previous_ts - ts > max_gap:
            exhausted = False
            break
        session_start = ts
        previous_ts = ts
    if session_start is not None and not exhausted:
        situation.session_minutes = round((now - session_start) / 60.0, 1)
    # `exhausted` means the walk ran out of fetched rows without finding an
    # end, so the true session start is unknown. Reporting the window edge
    # as if it were the start would be a guess dressed as a measurement.


def _read_zeno(situation: Situation) -> None:
    try:
        from reyes_agent import conversation_state

        situation.conversation_state = conversation_state.current()
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent import task_engine

        live = [t for t in task_engine.active() if t["current_status"] not in
                {"COMPLETED", "FAILED", "CANCELLED"}]
        situation.running_tasks = len(live)
        situation.task_titles = [t["title"][:60] for t in live[:3]]
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent import website_builder

        situation.website_projects = len(website_builder.projects())
    except Exception:  # noqa: BLE001
        pass


def _read_environment(situation: Situation) -> None:
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is not None:
            situation.battery_percent = int(battery.percent)
            situation.battery_charging = bool(battery.power_plugged)
    except Exception:  # noqa: BLE001 -- desktops have no battery; that is not a failure
        pass

    try:
        conn = sqlite3.connect(_DB, timeout=2)
        try:
            row = conn.execute(
                "SELECT title, due_at FROM calendar_events WHERE due_at > ? "
                "ORDER BY due_at ASC LIMIT 1", (time.time(),)).fetchone()
        finally:
            conn.close()
        if row:
            situation.next_event = str(row[0])[:80]
            situation.next_event_minutes = int((row[1] - time.time()) / 60)
    except Exception:  # noqa: BLE001 -- no calendar table yet is normal
        pass


def observe(force: bool = False) -> Situation:
    """The current picture. Cached for `_TTL_S`."""
    global _cached, _cached_at
    with _lock:
        if not force and _cached is not None and (time.time() - _cached_at) < _TTL_S:
            return _cached

    now = datetime.now()
    situation = Situation(hour=now.hour, weekday=now.strftime("%A"),
                          part_of_day=_part_of_day(now.hour))
    _read_activity(situation)
    _read_zeno(situation)
    _read_environment(situation)

    with _lock:
        _cached = situation
        _cached_at = time.time()
    return situation


def directive() -> str:
    """The per-turn prompt fragment. Short, or absent.

    Awareness is CONTEXT, not an instruction to narrate. The wording is
    explicit that ZENO must not recite the situation back -- an assistant
    that opens every reply with "I see you've been in Chrome for 40
    minutes" is worse than one that says nothing.
    """
    try:
        situation = observe()
    except Exception:  # noqa: BLE001 -- awareness must never break a turn
        return ""
    summary = situation.summary()
    if not summary:
        return ""
    return (f"[Situation: {summary}. Use this only when it genuinely changes your answer -- "
            "do not narrate it back to him, and never claim to sense anything not listed here.]")


def reset() -> None:
    """Test hook."""
    global _cached, _cached_at
    with _lock:
        _cached = None
        _cached_at = 0.0


def cannot_sense() -> list[str]:
    """Stated plainly so ZENO never implies otherwise."""
    return [
        "physical location or movement",
        "who else is in the room",
        "the owner's health, mood or biometrics",
        "anything on screen unless he asks for a screenshot or OCR",
        "anything through the camera or webcam unless he explicitly asks for it",
        "audio in the room unless a microphone session is running",
    ]
