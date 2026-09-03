"""Compatibility façade for ZENO's one native proactive heartbeat.

The historical public helpers remain available to the web UI, calendar and
other integrations. Scheduling, persistence, overlap control and delivery
belong to the shared engine, store and delivery policy; this module owns no
separate loop or worker.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.heartbeat_engine import CheckContext, HeartbeatEngine
from reyes_agent.proactive_delivery import ProactiveDeliveryService
from reyes_agent.proactive_models import CheckResult, DeliveryState, Importance, OverlapPolicy, ScheduledCheck
from reyes_agent.proactive_store import ProactiveStore
from reyes_agent.tools import register


_STATE_DIR = config.VAULT_PATH / "07-System" / "heartbeat"
_DB_PATH = _STATE_DIR / "state.db"
_CHECKS_PATH = Path(__file__).parent / "state" / "heartbeat_checks.json"
_POLL_INTERVAL_S = 30

_runtime_lock = threading.RLock()
_store: ProactiveStore | None = None
_engine: HeartbeatEngine | None = None
_delivery: ProactiveDeliveryService | None = None


def _connect_legacy() -> sqlite3.Connection:
    """Keep the old kill-switch settings readable while sharing its DB."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def _calendar_handler(_context: CheckContext) -> CheckResult:
    """Run the existing local calendar capability; it records real notices."""
    from reyes_agent.tools import calendar

    calendar.check_due_events()
    return CheckResult.no_change("calendar")


def _register_builtin_checks(engine: HeartbeatEngine) -> None:
    engine.register(
        ScheduledCheck(
            id="calendar.due",
            description="Check due events in ZENO's local calendar",
            enabled=True,
            interval_s=30,
            priority=50,
            timeout_s=15,
            overlap_policy=OverlapPolicy.SKIP,
            quiet_hours_policy="hold",
            handler_id="calendar.due",
        ),
        _calendar_handler,
    )


def _migrate_legacy_notices(store: ProactiveStore) -> None:
    """Copy visible old notices once so an upgrade never drops an update."""
    with _connect_legacy() as conn:
        done = conn.execute("SELECT value FROM settings WHERE key='proactive_v1_migrated'").fetchone()
        if done is not None:
            return
        try:
            rows = conn.execute("SELECT id, check_name, message, dismissed FROM notices ORDER BY id").fetchall()
        except sqlite3.Error:
            rows = []
        for legacy_id, source, message, dismissed in rows:
            if dismissed:
                continue
            result = CheckResult.changed(
                str(source or "legacy"),
                f"legacy-{legacy_id}",
                hashlib.sha256(str(message or "").encode("utf-8")).hexdigest()[:16],
                str(message or "Legacy proactive update"),
                importance_hint=Importance.INBOX,
            )
            store.upsert_notice(result, importance=Importance.INBOX, title="Earlier ZENO update")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('proactive_v1_migrated', '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )


def _runtime() -> tuple[ProactiveStore, HeartbeatEngine, ProactiveDeliveryService]:
    global _store, _engine, _delivery
    with _runtime_lock:
        if _store is None:
            _store = ProactiveStore(_DB_PATH)
            _store.migrate()
            _migrate_legacy_notices(_store)
        if _engine is None:
            _engine = HeartbeatEngine(_store, tick_interval_s=_POLL_INTERVAL_S)
            _register_builtin_checks(_engine)
            if _store.get_setting("focus_mode") == "1":
                _engine.pause("focus mode")
        if _delivery is None:
            _delivery = ProactiveDeliveryService(_store)
        return _store, _engine, _delivery


def _configure_for_tests(
    database_path: Path, *, scheduler: Any, worker_pool: Any, clock: Any = lambda: 100.0
) -> None:
    """Inject finite fakes for unit tests without starting process services."""
    global _DB_PATH, _STATE_DIR, _store, _engine, _delivery
    with _runtime_lock:
        _DB_PATH = Path(database_path)
        _STATE_DIR = _DB_PATH.parent
        _store = ProactiveStore(_DB_PATH, clock=clock)
        _store.migrate()
        _engine = HeartbeatEngine(
            _store, scheduler=scheduler, worker_pool=worker_pool, clock=clock,
            tick_interval_s=_POLL_INTERVAL_S,
        )
        _register_builtin_checks(_engine)
        _delivery = ProactiveDeliveryService(_store, notifier=lambda **_payload: {"delivered": True})


# --- kill switch -----------------------------------------------------------


def is_killed() -> bool:
    with _connect_legacy() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='killed'").fetchone()
    return row is not None and row[0] == "1"


def set_killed(value: bool) -> None:
    with _connect_legacy() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('killed', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if value else "0",),
        )
    _store, engine, _delivery = _runtime()
    if value:
        engine.pause("kill switch")
    else:
        engine.resume()


def _in_quiet_hours() -> bool:
    if config.QUIET_HOURS_START is None or config.QUIET_HOURS_END is None:
        return False
    hour = time.localtime().tm_hour
    start, end = config.QUIET_HOURS_START, config.QUIET_HOURS_END
    return start <= hour < end if start <= end else hour >= start or hour < end


# --- compatibility schedule tools -----------------------------------------


def load_checks() -> list[dict[str, Any]]:
    if not _CHECKS_PATH.exists():
        return []
    try:
        data = json.loads(_CHECKS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_checks(checks: list[dict[str, Any]]) -> None:
    _CHECKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CHECKS_PATH.write_text(json.dumps(checks, indent=2), encoding="utf-8")


@register(
    name="schedule_check",
    description="Save a recurring proactive request for assignment to an explicit typed ZENO check. It never starts unattended model polling.",
    input_schema={"type": "object", "properties": {
        "name": {"type": "string"}, "interval_minutes": {"type": "integer"},
        "check": {"type": "string"}, "urgent": {"type": "boolean"},
    }, "required": ["name", "interval_minutes", "check"]},
)
def schedule_check(name: str, interval_minutes: int, check: str, urgent: bool = False) -> str:
    checks = [item for item in load_checks() if item.get("name") != name]
    checks.append({
        "name": str(name).strip()[:80], "interval_minutes": max(1, int(interval_minutes)),
        "check": str(check).strip()[:500], "urgent": bool(urgent), "state": "NEEDS_TYPED_HANDLER",
    })
    _save_checks(checks)
    return (
        f"Saved '{name}' for review every {max(1, int(interval_minutes))} minute(s). "
        "ZENO will not run an unattended model loop; assign it to a supported typed check first."
    )


@register(
    name="list_scheduled_checks",
    description="List saved recurring proactive requests and their typed-handler state.",
    input_schema={"type": "object", "properties": {}},
)
def list_scheduled_checks() -> str:
    checks = load_checks()
    if not checks:
        return "No recurring checks scheduled."
    return "\n".join(
        f"{item.get('name', 'unnamed')} -- every {item.get('interval_minutes', 0)}m -- "
        f"{item.get('check', '')} [{item.get('state', 'NEEDS_TYPED_HANDLER')}]"
        for item in checks
    )


@register(
    name="cancel_scheduled_check",
    description="Cancel a saved recurring proactive request by name.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
def cancel_scheduled_check(name: str) -> str:
    checks = load_checks()
    remaining = [item for item in checks if item.get("name") != name]
    if len(remaining) == len(checks):
        return f"No scheduled check named '{name}'."
    _save_checks(remaining)
    return f"Cancelled '{name}'."


# --- compatibility inbox ---------------------------------------------------


def _add_notice(check_name: str, message: str) -> None:
    store, _engine, delivery = _runtime()
    digest = hashlib.sha256(str(message or "").encode("utf-8")).hexdigest()[:16]
    result = CheckResult.changed(
        str(check_name or "proactive"), str(check_name or "proactive"), digest,
        str(message or "Proactive update"), importance_hint=Importance.NOTIFY,
    )
    store.upsert_notice(result, importance=Importance.NOTIFY, title=str(check_name or "ZENO"))
    delivery.surface_pending()


def _push_to_telegram(_check_name: str, _message: str) -> None:
    """Deprecated transport hook; delivery is centrally policy-gated now."""
    return None


def list_notices(include_dismissed: bool = False) -> list[dict[str, Any]]:
    store, _engine, _delivery = _runtime()
    notices = store.list_notices(limit=500)
    if not include_dismissed:
        notices = [notice for notice in notices if notice.delivery_state not in {DeliveryState.DISMISSED, DeliveryState.EXPIRED}]
    return [store.public_notice(notice) for notice in notices]


def proactive_status() -> dict[str, Any]:
    """Safe diagnostics for the desktop and paired-companion status views."""
    store, engine, _delivery = _runtime()
    return {
        "enabled": not is_killed(),
        "focus_mode": store.get_setting("focus_mode") == "1",
        "engine": engine.diagnostics(),
        "inbox": {
            "new": len(store.list_notices(state=DeliveryState.NEW)),
            "held": len(store.list_notices(state=DeliveryState.HELD)),
            "surfaced": len(store.list_notices(state=DeliveryState.SURFACED)),
        },
    }


def set_focus_mode(enabled: bool) -> None:
    store, engine, _delivery = _runtime()
    store.set_setting("focus_mode", "1" if enabled else "0")
    if enabled:
        engine.pause("focus mode")
    else:
        engine.resume()


def catch_up_notices(limit: int = 5) -> dict[str, Any]:
    _store, _engine, delivery = _runtime()
    return delivery.catch_up(limit=limit)


@register(
    name="proactive_control",
    description="Show, pause, resume, focus, or catch up ZENO's one proactive heartbeat. It never starts a separate assistant or scheduler.",
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["status", "focus_on", "focus_off", "pause", "resume", "catch_up"]},
        "limit": {"type": "integer"},
    }, "required": ["action"]},
    light=True,
)
def proactive_control(action: str, limit: int = 5) -> str:
    selected = str(action or "status").strip().casefold()
    if selected == "focus_on":
        set_focus_mode(True)
        return json.dumps(proactive_status())
    if selected == "focus_off":
        set_focus_mode(False)
        return json.dumps(proactive_status())
    if selected == "pause":
        get_heartbeat_engine().pause("manual")
        return json.dumps(proactive_status())
    if selected == "resume":
        if proactive_status()["focus_mode"]:
            return json.dumps({"error": "Focus mode is still enabled; turn it off before resuming."})
        get_heartbeat_engine().resume()
        return json.dumps(proactive_status())
    if selected == "catch_up":
        return json.dumps(catch_up_notices(limit=max(1, min(int(limit), 20))))
    if selected == "status":
        return json.dumps(proactive_status())
    return json.dumps({"error": f"Unknown proactive action '{action}'."})


def dismiss_notice(notice_id: str | int) -> bool:
    store, _engine, _delivery = _runtime()
    notice = next((item for item in store.list_notices(limit=500) if item.id == str(notice_id)), None)
    if notice is None:
        return False
    try:
        if notice.delivery_state is DeliveryState.NEW:
            notice = store.transition_notice(notice.id, DeliveryState.HELD)
        if notice.delivery_state in {DeliveryState.HELD, DeliveryState.SURFACED, DeliveryState.SEEN, DeliveryState.ACKNOWLEDGED}:
            store.transition_notice(notice.id, DeliveryState.DISMISSED)
        return True
    except ValueError:
        return False


# --- one shared scheduler job ---------------------------------------------


def get_heartbeat_engine() -> HeartbeatEngine:
    _store, engine, _delivery = _runtime()
    return engine


def _tick() -> None:
    if not is_killed():
        get_heartbeat_engine().tick()


def start_background() -> None:
    if not is_killed():
        get_heartbeat_engine().start()
