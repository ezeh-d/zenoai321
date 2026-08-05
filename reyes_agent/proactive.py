"""Proactive nudges: ZENO noticing things without being asked -- a long
unbroken work session, low battery -- and saying something about it once,
not spamming. Reuses the same background-service pattern as
notification_listener/email_watcher (own thread, no LLM cost per check)
and the SAME notice/Telegram/speak plumbing as heartbeat, so this is
genuinely wired into the existing proactive-behavior system, not a new
parallel one.

Deliberately NOT built: "you normally open VS Code at this time" style
routine-prediction (needs real pattern-learning over weeks of data this
build doesn't have yet), or a general open-ended "notice anything
interesting" loop (that's just re-inventing heartbeat's schedule_check,
which already exists and lets the user define exactly that).
"""

from __future__ import annotations

import threading
import time

from reyes_agent import config

_CHECK_INTERVAL_S = 300  # 5 minutes
_LONG_SESSION_MIN = 120  # nudge after 2h of continuous active work
_LOW_BATTERY_PCT = 20

_last_session_nudge_at = 0.0
_battery_nudge_fired = False  # resets once charging or level recovers


def _speak(text: str) -> None:
    from reyes_agent.voice.tts import TTSError, speak

    try:
        speak(text, threading.Event())
    except TTSError:
        pass


def _notice(check_name: str, message: str) -> None:
    from reyes_agent import heartbeat

    heartbeat._add_notice(check_name, message)
    if not heartbeat._in_quiet_hours():
        _speak(message)


def _check_long_session() -> None:
    global _last_session_nudge_at
    from reyes_agent.activity_monitor import _connect
    from datetime import datetime

    now = time.time()
    if now - _last_session_nudge_at < _LONG_SESSION_MIN * 60:
        return  # already nudged this stretch -- don't repeat every tick

    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = now - _LONG_SESSION_MIN * 60
    with _connect() as conn:
        rows = conn.execute(
            "SELECT app, idle FROM activity_log WHERE day = ? AND ts >= ? ORDER BY ts ASC",
            (today, cutoff),
        ).fetchall()
    # Need a full window of samples, all active (not idle), same app the
    # whole time -- a genuinely continuous unbroken session, not just
    # "the app happened to be open."
    if len(rows) < (_LONG_SESSION_MIN * 60) // 90:  # allow some sample gaps
        return
    apps = {app for app, idle in rows}
    any_idle = any(idle for _app, idle in rows)
    if len(apps) == 1 and not any_idle:
        _last_session_nudge_at = now
        app = next(iter(apps))
        _notice("proactive", f"You've been in {app} for a couple hours straight. Worth a short break?")


def _check_battery() -> None:
    global _battery_nudge_fired
    import psutil

    batt = psutil.sensors_battery()
    if batt is None:
        return  # desktop machine, no battery -- nothing to check
    if batt.power_plugged or batt.percent > _LOW_BATTERY_PCT:
        _battery_nudge_fired = False  # reset so a future low-battery episode nudges again
        return
    if not _battery_nudge_fired:
        _battery_nudge_fired = True
        _notice("proactive", f"Battery's at {batt.percent} percent and not charging.")


_DREAM_IDLE_MIN = 10  # user away this long before Dream Mode maintenance runs
_DREAM_COOLDOWN_S = 3 * 3600  # don't re-run more than once per 3h even if idle the whole time
_last_dream_at = 0.0


def _check_dream_mode() -> None:
    """Idle housekeeping: reindex the vault so search stays current. Stops
    immediately (next tick just won't run) the moment the user is back --
    checked fresh via GetLastInputInfo every call, not a one-shot timer
    that keeps working after the user returns.
    """
    global _last_dream_at
    from reyes_agent.activity_monitor import _idle_seconds

    now = time.time()
    if now - _last_dream_at < _DREAM_COOLDOWN_S:
        return
    if _idle_seconds() < _DREAM_IDLE_MIN * 60:
        return
    _last_dream_at = now
    try:
        from reyes_agent.tools.rag import reindex_vault

        result = reindex_vault()
        from reyes_agent import heartbeat

        heartbeat._add_notice("dream", f"Dream Mode maintenance: {result}")
    except Exception:  # noqa: BLE001 -- maintenance failing must not crash the loop
        pass


def _check_morning() -> None:
    """Queue the morning brief as a notice once per day, the first time the
    user is actually active in the morning.

    Deliberately a NOTICE, not speech: an assistant that starts talking at
    you unprompted the moment you sit down is worse than one that waits to
    be asked. The panel shows it; the user can ask for the full brief.
    """
    from datetime import datetime

    from reyes_agent import heartbeat

    now = datetime.now()
    if not (5 <= now.hour < 12):
        return
    marker = config.VAULT_PATH / "07-System" / "last_morning_notice.txt"
    today = now.strftime("%Y-%m-%d")
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
            return
    except OSError:
        pass
    # Only if the user is genuinely at the machine right now.
    try:
        from reyes_agent.activity_monitor import _idle_seconds

        if _idle_seconds() > 120:
            return
    except Exception:  # noqa: BLE001
        return
    try:
        from reyes_agent.tools.companion_tools import morning_brief

        brief = morning_brief(force=True)
        heartbeat._add_notice("morning", brief.split("\n(Read this")[0].strip())
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(today, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _tick() -> None:
    from reyes_agent import heartbeat

    if not heartbeat.is_killed():
        _check_morning()
        _check_long_session()
        _check_battery()
        _check_dream_mode()


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler

    get_scheduler().schedule(
        "proactive", _tick, delay=10.0, interval=_CHECK_INTERVAL_S,
        priority=80, timeout=120,
    )
