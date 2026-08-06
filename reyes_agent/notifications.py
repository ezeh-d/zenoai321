"""Notification centre: settings, state machine, de-duplication, history.

WHY NOTIFICATIONS WERE OFF
--------------------------
Not a bug in the listener. `web.py::_boot_background_services` was reduced
to `_set_boot_phase("ready")` during the WebView2 lag work, so
`notification_listener.start_background()` (along with activity, e-mail
and proactive sweeps) simply stopped being called. The listener code was
fine and untouched; nothing was starting it. Restoring it therefore has
to respect the reason it was removed -- hence `enabled` defaults to the
user's stored preference and the poll cadence stays modest.

DESIGN
------
* Settings persist to the vault as JSON and survive restarts.
* Every notification carries a state: NEW -> READ / ACTION_REQUIRED ->
  REPLIED / DISMISSED.
* De-duplication is by content fingerprint within a window, so the same
  alert re-firing every poll cannot spam the user -- the existing record's
  `count` increments instead of a new row appearing.
* Priority: low / normal / high / urgent. Do-Not-Disturb suppresses
  delivery (never recording) below `urgent`; priority-only mode suppresses
  below `high`. Suppressed items are still stored and visible in history,
  because silently discarding them would lose information the user may
  want later.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_SETTINGS_PATH = config.VAULT_PATH / "07-System" / "notification_settings.json"

NEW = "NEW"
READ = "READ"
ACTION_REQUIRED = "ACTION_REQUIRED"
REPLIED = "REPLIED"
DISMISSED = "DISMISSED"
STATES = (NEW, READ, ACTION_REQUIRED, REPLIED, DISMISSED)

PRIORITIES = ("low", "normal", "high", "urgent")
_PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITIES)}

# Identical content inside this window increments a counter instead of
# creating a second notification.
_DEDUP_WINDOW_S = 300

_lock = threading.Lock()


@dataclass
class NotificationSettings:
    enabled: bool = True
    read_aloud: bool = False          # off by default: speaking every alert is intrusive
    desktop_toast: bool = True
    priority_only: bool = False
    do_not_disturb: bool = False
    volume: float = 0.7               # 0-1, applied by the panel when speaking
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings() -> NotificationSettings:
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        known = {f for f in NotificationSettings().as_dict()}
        return NotificationSettings(**{k: v for k, v in raw.items() if k in known})
    except Exception:  # noqa: BLE001 -- a corrupt file must not disable notifications
        return NotificationSettings()


def save_settings(**changes: Any) -> NotificationSettings:
    s = load_settings()
    for key, value in changes.items():
        if value is None or not hasattr(s, key):
            continue
        if key == "volume":
            value = max(0.0, min(1.0, float(value)))
        elif key in ("quiet_hours_start", "quiet_hours_end"):
            value = None if value == "" else int(value)
        elif isinstance(getattr(s, key), bool):
            value = bool(value)
        setattr(s, key, value)
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(s.as_dict(), indent=2), encoding="utf-8")
        tmp.replace(_SETTINGS_PATH)     # atomic: never leave a half-written settings file
    except OSError:
        pass
    return s


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notifications ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source TEXT, title TEXT, "
        "body TEXT, priority TEXT, state TEXT, fingerprint TEXT, count INTEGER DEFAULT 1, "
        "reply TEXT, delivered INTEGER DEFAULT 0, suppressed_reason TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_fp ON notifications(fingerprint, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_state ON notifications(state, ts)")
    return conn


@dataclass
class Notification:
    id: int
    ts: float
    source: str
    title: str
    body: str
    priority: str
    state: str
    count: int = 1
    reply: str = ""
    delivered: bool = False
    suppressed_reason: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts_human"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))
        return d


def _fingerprint(source: str, title: str, body: str) -> str:
    return hashlib.sha256(f"{source}|{title}|{body}".encode("utf-8")).hexdigest()[:24]


def _in_quiet_hours(s: NotificationSettings) -> bool:
    if s.quiet_hours_start is None or s.quiet_hours_end is None:
        return False
    hour = time.localtime().tm_hour
    start, end = s.quiet_hours_start, s.quiet_hours_end
    return (start <= hour < end) if start < end else (hour >= start or hour < end)


def _delivery_decision(priority: str, s: NotificationSettings) -> tuple[bool, str]:
    """Should this be shown/spoken now? Returns (deliver, reason_if_not)."""
    if not s.enabled:
        return False, "notifications are turned off"
    rank = _PRIORITY_RANK.get(priority, 1)
    if s.do_not_disturb and rank < _PRIORITY_RANK["urgent"]:
        return False, "do not disturb"
    if _in_quiet_hours(s) and rank < _PRIORITY_RANK["urgent"]:
        return False, "quiet hours"
    if s.priority_only and rank < _PRIORITY_RANK["high"]:
        return False, "priority-only mode"
    return True, ""


def notify(title: str, body: str = "", *, source: str = "zeno",
           priority: str = "normal", action_required: bool = False,
           extra: dict | None = None) -> dict[str, Any]:
    """Record a notification, de-duplicate it, and deliver if allowed.

    ALWAYS records, even when suppressed -- history should reflect what
    happened, not only what got through.
    """
    priority = priority if priority in PRIORITIES else "normal"
    fp = _fingerprint(source, title, body)
    now = time.time()
    settings = load_settings()
    deliver, reason = _delivery_decision(priority, settings)

    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id, count, state FROM notifications "
            "WHERE fingerprint = ? AND ts >= ? ORDER BY id DESC LIMIT 1",
            (fp, now - _DEDUP_WINDOW_S),
        ).fetchone()
        if row:
            # Same alert again inside the window: bump the counter, do NOT
            # deliver again. This is the anti-spam rule.
            nid, count, state = row
            conn.execute("UPDATE notifications SET count = ?, ts = ? WHERE id = ?",
                         (count + 1, now, nid))
            return {"id": nid, "duplicate": True, "count": count + 1,
                    "delivered": False, "reason": "duplicate within 5 minutes",
                    "state": state}

        state = ACTION_REQUIRED if action_required else NEW
        cur = conn.execute(
            "INSERT INTO notifications (ts, source, title, body, priority, state, "
            "fingerprint, count, reply, delivered, suppressed_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, ?)",
            (now, source, title, body, priority, state, fp, 1 if deliver else 0,
             "" if deliver else reason),
        )
        nid = cur.lastrowid

    payload = {"id": nid, "title": title, "body": body, "source": source,
               "priority": priority, "state": state, "extra": extra or {},
               "read_aloud": bool(settings.read_aloud and deliver),
               "volume": settings.volume, "desktop_toast": settings.desktop_toast}

    if deliver:
        try:
            from reyes_agent import notification_bus

            notification_bus.publish({"type": "zeno_notification", **payload})
        except Exception:  # noqa: BLE001 -- delivery must not break recording
            pass
    try:
        from reyes_agent import event_bus

        event_bus.publish("notification.created",
                          {"id": nid, "source": source, "priority": priority,
                           "delivered": deliver, "reason": reason},
                          source="notifications")
    except Exception:  # noqa: BLE001
        pass

    return {"id": nid, "duplicate": False, "delivered": deliver,
            "reason": reason, "state": state}


def set_state(notification_id: int, state: str, reply: str = "") -> bool:
    if state not in STATES:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE notifications SET state = ?, reply = COALESCE(NULLIF(?, ''), reply) "
            "WHERE id = ?", (state, reply, notification_id))
        return cur.rowcount > 0


def history(limit: int = 50, state: str = "", include_dismissed: bool = False) -> list[dict]:
    sql = ("SELECT id, ts, source, title, body, priority, state, count, reply, "
           "delivered, suppressed_reason FROM notifications")
    clauses, params = [], []
    if state:
        clauses.append("state = ?")
        params.append(state)
    elif not include_dismissed:
        clauses.append("state != ?")
        params.append(DISMISSED)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    return [Notification(id=r[0], ts=r[1], source=r[2], title=r[3], body=r[4],
                         priority=r[5], state=r[6], count=r[7], reply=r[8] or "",
                         delivered=bool(r[9]), suppressed_reason=r[10] or "").as_dict()
            for r in rows]


def unread_count() -> int:
    try:
        with _connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE state IN (?, ?)",
                (NEW, ACTION_REQUIRED)).fetchone()[0]
    except sqlite3.Error:
        return 0


def status() -> dict[str, Any]:
    s = load_settings()
    # The listener does NOT own a thread -- it registers a periodic job with
    # the shared scheduler (notification_listener.start_background). An
    # earlier version of this check looked for `_thread` and therefore
    # always reported False even while polling was live. Ask the scheduler.
    running = False
    detail = ""
    try:
        from reyes_agent.scheduler import get_scheduler

        m = get_scheduler().metrics()
        job = next((j for j in m.get("scheduled", [])
                    if j.get("name") == "notification-listener"), None)
        running = bool(job) and bool(m.get("alive"))
        if job:
            detail = (f"polling every {job.get('interval_s')}s, "
                      f"{job.get('runs', 0)} run(s), next in {job.get('next_run_s')}s")
    except Exception as exc:  # noqa: BLE001
        detail = f"scheduler unavailable ({type(exc).__name__})"
    return {
        "settings": s.as_dict(),
        "listener_running": running,
        "listener_detail": detail,
        "unread": unread_count(),
        "in_quiet_hours": _in_quiet_hours(s),
        "recent": history(limit=10),
    }
