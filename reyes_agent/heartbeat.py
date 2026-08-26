"""Tier 5: REYES's own native heartbeat.

Runs entirely inside REYES -- doesn't depend on Hermes (or any other
external scheduler) being onboarded. Reads scheduled checks from
`state/heartbeat_checks.json`, persists next-due times in SQLite so a
restart doesn't refire everything, skips a check if its previous run is
still going, respects quiet hours, and holds anything noteworthy in a
dismissible queue (`notices`) -- caught up on next look, never fired into
the void and lost. Hermes (see AGENT.md's Tier 5 section) can still be
wired up as an *additional* trigger later; it was never required for this
to work.

Each check runs through the exact same `agent.run_agent` core as every
other front door, framed as an unattended background turn and required to
reply exactly NOTHING unless something's genuinely worth surfacing --
quiet by default is enforced in the prompt, not assumed of the caller.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from reyes_agent import config
from reyes_agent.tools import register

# `agent` (and therefore `provider`) is imported lazily inside `_run_check`,
# not here -- this module is itself imported from `tools/__init__.py` (so
# `schedule_check` etc. are registered regardless of which front door
# starts first), and `agent.py` imports back from `reyes_agent.tools`.
# A module-level import here would be circular.

_STATE_DIR = config.VAULT_PATH / "07-System" / "heartbeat"
_DB_PATH = _STATE_DIR / "state.db"
_CHECKS_PATH = Path(__file__).parent / "state" / "heartbeat_checks.json"

_POLL_INTERVAL_S = 30
_running_checks: set[str] = set()
_run_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS check_state ("
        "name TEXT PRIMARY KEY, next_due_at REAL, last_run_at REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notices ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, "
        "check_name TEXT, message TEXT, dismissed INTEGER DEFAULT 0)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return conn


# --- kill switch -----------------------------------------------------------


def is_killed() -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='killed'").fetchone()
    return row is not None and row[0] == "1"


def set_killed(value: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('killed', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if value else "0",),
        )


# --- quiet hours -------------------------------------------------------


def _in_quiet_hours() -> bool:
    if not config.QUIET_HOURS_START or not config.QUIET_HOURS_END:
        return False
    now_h = time.localtime().tm_hour
    start, end = config.QUIET_HOURS_START, config.QUIET_HOURS_END
    if start <= end:
        return start <= now_h < end
    return now_h >= start or now_h < end  # wraps past midnight, e.g. 22 -> 8


# --- checks config -------------------------------------------------------


def load_checks() -> list[dict]:
    if not _CHECKS_PATH.exists():
        return []
    try:
        return json.loads(_CHECKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_checks(checks: list[dict]) -> None:
    _CHECKS_PATH.write_text(json.dumps(checks, indent=2), encoding="utf-8")


@register(
    name="schedule_check",
    description=(
        "Set up a recurring background check REYES will run on its own, on "
        "a schedule, surfacing a notice only if it finds something worth "
        "telling the user -- quiet by default. Use when the user asks to "
        "be proactively checked on/reminded/watched for something recurring."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short unique label for this check."},
            "interval_minutes": {"type": "integer", "description": "How often to run it, in minutes."},
            "check": {
                "type": "string",
                "description": "What to check for, in plain language, e.g. 'see if any new notes were added'.",
            },
            "urgent": {
                "type": "boolean",
                "description": "If true, this check's notices ignore quiet hours. Default false.",
            },
        },
        "required": ["name", "interval_minutes", "check"],
    },
)
def schedule_check(name: str, interval_minutes: int, check: str, urgent: bool = False) -> str:
    checks = load_checks()
    checks = [c for c in checks if c["name"] != name]  # replace if it already exists
    checks.append(
        {
            "name": name,
            "interval_minutes": max(1, int(interval_minutes)),
            "check": check,
            "urgent": bool(urgent),
        }
    )
    _save_checks(checks)
    return f"Scheduled '{name}' to run every {interval_minutes} minute(s)."


@register(
    name="list_scheduled_checks",
    description="List REYES's recurring background checks.",
    input_schema={"type": "object", "properties": {}},
)
def list_scheduled_checks() -> str:
    checks = load_checks()
    if not checks:
        return "No recurring checks scheduled."
    return "\n".join(
        f"{c['name']} -- every {c['interval_minutes']}m -- {c['check']}"
        + (" [urgent]" if c.get("urgent") else "")
        for c in checks
    )


@register(
    name="cancel_scheduled_check",
    description="Cancel a recurring background check by name.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The check's name."}},
        "required": ["name"],
    },
)
def cancel_scheduled_check(name: str) -> str:
    checks = load_checks()
    remaining = [c for c in checks if c["name"] != name]
    if len(remaining) == len(checks):
        return f"No scheduled check named '{name}'."
    _save_checks(remaining)
    return f"Cancelled '{name}'."


# --- notices (dismissible, held-until-seen) -------------------------------


def _add_notice(check_name: str, message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notices (created_at, check_name, message) VALUES (?, ?, ?)",
            (time.strftime("%Y-%m-%d %H:%M"), check_name, message),
        )


def _push_to_telegram(check_name: str, message: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_NOTIFY_CHAT_ID:
        return  # no configured push target -- the notices list is still the record
    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_NOTIFY_CHAT_ID, "text": f"[{check_name}] {message}"},
            timeout=10,
        )
    except Exception:  # noqa: BLE001 -- a failed push must not lose the notice, it's still in the list
        pass


def list_notices(include_dismissed: bool = False) -> list[dict]:
    query = "SELECT id, created_at, check_name, message, dismissed FROM notices"
    if not include_dismissed:
        query += " WHERE dismissed = 0"
    query += " ORDER BY id DESC"
    with _connect() as conn:
        rows = conn.execute(query).fetchall()
    return [
        {"id": r[0], "created_at": r[1], "check_name": r[2], "message": r[3], "dismissed": bool(r[4])}
        for r in rows
    ]


def dismiss_notice(notice_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("UPDATE notices SET dismissed = 1 WHERE id = ?", (notice_id,))
        return cur.rowcount > 0


# --- the scheduler loop --------------------------------------------------


def _ensure_scheduled(name: str, interval_minutes: int) -> None:
    """First time this check has ever been seen: give it a next-due time
    one interval out, without claiming a run -- a freshly-added check
    shouldn't fire the instant it's created. No-op if already known
    (`INSERT OR IGNORE`), including across a restart.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO check_state (name, next_due_at, last_run_at) VALUES (?, ?, 0)",
            (name, time.time() + interval_minutes * 60),
        )


def _try_claim(name: str, interval_minutes: int) -> bool:
    """Atomically claim this check for a run if it's due, immediately
    pushing its next-due time forward -- a SQLite compare-and-set, so
    this is safe even if more than one REYES front door is running the
    scheduler at once, not just safe against overlap within one process.
    """
    now = time.time()
    next_due = now + interval_minutes * 60
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE check_state SET next_due_at = ?, last_run_at = ? "
            "WHERE name = ? AND next_due_at <= ?",
            (next_due, now, name, now),
        )
        return cur.rowcount > 0


def _run_check(check: dict) -> None:
    from reyes_agent.agent import run_agent
    from reyes_agent.provider import ProviderError

    name = check["name"]
    with _run_lock:
        if name in _running_checks:
            return  # a slow previous run of THIS process is still going
        _running_checks.add(name)
    try:
        history = [
            {
                "role": "user",
                "content": (
                    f"[Automated background check '{name}' -- not a live message, the user "
                    f"isn't watching right now. Check: {check['check']}\n"
                    "If there's nothing worth telling the user, reply with exactly NOTHING "
                    "and nothing else. Quiet by default is the rule, not the exception.]"
                ),
            }
        ]
        try:
            run_agent(
                history,
                action_source="background",
                owner_authenticated=False,
            )
            reply = history[-1]["content"].strip()
        except ProviderError:
            reply = None  # a failed check is not itself a notice -- stay silent, try next cycle

        if reply and reply.upper() != "NOTHING":
            _add_notice(name, reply)
            # The notices list always holds it either way (dismissible,
            # catch-up-on-return); a push is the *extra* interruption, so
            # that's the part quiet hours gate -- urgent checks skip the gate.
            if check.get("urgent") or not _in_quiet_hours():
                _push_to_telegram(name, reply)
    finally:
        with _run_lock:
            _running_checks.discard(name)
        # next_due_at was already advanced atomically at claim time in
        # _try_claim -- nothing left to update here.


def _tick() -> None:
    if is_killed():
        return
    from reyes_agent.tools import calendar

    calendar.check_due_events()
    for check in load_checks():
        name, interval = check["name"], check["interval_minutes"]
        _ensure_scheduled(name, interval)
        if _try_claim(name, interval):
            # Urgent checks always run on schedule; non-urgent ones still
            # run on schedule too -- quiet hours hold the *push*, not the
            # check itself, so "did anything happen overnight" is still
            # answered the moment someone looks in the morning.
            from reyes_agent.worker_pool import PRIORITY_BACKGROUND, QueueFullError, get_worker_pool

            try:
                get_worker_pool().submit(
                    _run_check, check, name=f"heartbeat:{name}",
                    priority=PRIORITY_BACKGROUND, timeout=180, retries=1,
                )
            except QueueFullError:
                # Leave next_due_at advanced; a busy system must not build an
                # unbounded backlog of stale background checks.
                pass


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler

    get_scheduler().schedule(
        "heartbeat", _tick, delay=10.0, interval=_POLL_INTERVAL_S, priority=50,
        timeout=30,
    )
