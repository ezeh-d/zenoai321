"""Daily-work monitoring: samples which app/window is in the foreground
and whether the user is actually active, so REYES can honestly answer
"where did my day go" instead of guessing.

Local-only. Samples stay in the same heartbeat state.db on this machine,
nothing is sent anywhere. Window titles can be sensitive (document names,
chat headers), which is exactly why this is local and only runs because
the user asked for it -- it can be turned off by not starting it.

Idle time (GetLastInputInfo) gates what counts as "active": if the user
hasn't touched keyboard/mouse for a while, that sample is marked idle and
left out of active-time totals, so leaving a window open while away
doesn't inflate the numbers.
"""

from __future__ import annotations

import ctypes
import sqlite3
import threading
import time
from ctypes import wintypes
from datetime import datetime

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_SAMPLE_INTERVAL_S = 60
_IDLE_THRESHOLD_S = 180  # 3 min without input -> that sample doesn't count as active work


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, "
        "app TEXT, title TEXT, idle INTEGER)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_day ON activity_log(day)")
    return conn


def _idle_seconds() -> float:
    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    tick = ctypes.windll.kernel32.GetTickCount()
    return (tick - lii.dwTime) / 1000.0


def foreground_app() -> tuple[str, str]:
    """(process_name, window_title) of whatever's in front right now."""
    import psutil

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name()
    except Exception:  # noqa: BLE001
        app = "unknown"
    return app, title


def _sample() -> None:
    # Digital DNA kill switch. Checked HERE, at the point of collection,
    # so "disabled" means no sample is ever written -- not merely hidden
    # from the report. A privacy toggle that still collects would be a lie.
    if (config.VAULT_PATH / "07-System" / "dna_disabled.flag").exists():
        return
    app, title = foreground_app()
    if not app:
        return
    idle = 1 if _idle_seconds() > _IDLE_THRESHOLD_S else 0
    with _connect() as conn:
        conn.execute(
            "INSERT INTO activity_log (ts, day, app, title, idle) VALUES (?, ?, ?, ?, ?)",
            (time.time(), datetime.now().strftime("%Y-%m-%d"), app, title, idle),
        )


_FRIENDLY = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "slack.exe": "Slack",
    "code.exe": "VS Code",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "claude.exe": "Claude",
    "explorer.exe": "File Explorer",
    "whatsapp.exe": "WhatsApp",
    "spotify.exe": "Spotify",
    "python.exe": "Python",
    "phoneexperiencehost.exe": "Phone Link",
}


def _friendly(app: str) -> str:
    return _FRIENDLY.get(app.lower(), app.rsplit(".", 1)[0].title())


@register(
    name="daily_activity_summary",
    description=(
        "Summarize where the user's active time went on the computer for a "
        "given day (which apps, roughly how long) -- based on REYES's own "
        "background activity sampling. Idle time (away from the keyboard) "
        "is excluded. Use when the user asks what they did today, where "
        "their time went, or for a work recap."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "day": {
                "type": "string",
                "description": "Day as YYYY-MM-DD. Default: today.",
            },
        },
    },
    light=True,
)
def daily_activity_summary(day: str = "") -> str:
    day = day.strip() or datetime.now().strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT app, COUNT(*) FROM activity_log "
            "WHERE day = ? AND idle = 0 GROUP BY app ORDER BY COUNT(*) DESC",
            (day,),
        ).fetchall()
        idle_count = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE day = ? AND idle = 1", (day,)
        ).fetchone()[0]
    if not rows:
        return (
            f"No activity recorded for {day} yet. (Monitoring samples once a "
            "minute while REYES is running -- there just isn't data for that day.)"
        )
    total_active = sum(c for _app, c in rows)  # each sample ~= 1 minute
    lines = [f"Active time on {day}: about {total_active} min across these apps:"]
    for app, count in rows:
        lines.append(f"  {_friendly(app)}: ~{count} min")
    if idle_count:
        lines.append(f"(plus ~{idle_count} min idle/away, not counted)")
    return "\n".join(lines)


@register(
    name="current_activity",
    description="What app/window is in the foreground on the computer right now.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def current_activity() -> str:
    app, title = foreground_app()
    if not app:
        return "Couldn't read the foreground window."
    return f"{_friendly(app)}" + (f" -- {title}" if title else "")


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler

    get_scheduler().schedule(
        "activity-monitor", _sample, interval=_SAMPLE_INTERVAL_S,
        priority=80, timeout=10,
    )
