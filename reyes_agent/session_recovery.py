"""Crash recovery -- persist and restore the working session.

WHAT IS ACTUALLY RESTORABLE, AND WHAT IS NOT
--------------------------------------------
Restored on next start:
  * conversation history (the real message list web.py serves from)
  * open missions and campaigns -- already durable in SQLite, so they
    survive by construction; recorded here so the restore banner can
    report them
  * agent runtime metrics from the previous run (for the report only --
    workers themselves are started fresh, which is correct: a thread
    cannot be resurrected across a process boundary)
  * companion orb position (browser localStorage, restored by the panel)
  * browser automation profile -- Playwright's on-disk user-data-dir means
    LOGINS genuinely survive; in-flight page state does NOT

NOT restorable, and not pretended otherwise:
  * an in-progress model call (it was in flight when the process died)
  * unsaved desktop-app state belonging to other applications
  * the exact scroll/selection state of the panel

The snapshot is written periodically and on clean shutdown. A crash means
the last periodic snapshot is what survives, so the restore banner reports
the snapshot's age instead of implying nothing was lost.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from reyes_agent import config

_STATE_DIR = config.VAULT_PATH / "07-System" / "session"
_SNAPSHOT = _STATE_DIR / "last_session.json"
_SNAPSHOT_INTERVAL = 60.0
_MAX_HISTORY = 60          # keep the tail; a whole day of chat is not useful to reload

_clean_exit = False


def _live_web():
    """The module object that is ACTUALLY serving requests.

    The server starts as `python -m reyes_agent.web`, so that file is
    executed as `__main__` AND is importable again as `reyes_agent.web` --
    two separate module objects with two separate `_history` lists. The
    running server appends to `__main__`'s; a plain `from reyes_agent
    import web` reads the other, permanently empty one.

    Found 2026-08-04 by testing restore for real: the snapshot wrote
    `history: []` after a genuine conversation, and session restore would
    have silently been a no-op for ever. Always resolve the live module.
    """
    import sys

    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_history") and hasattr(main, "app"):
        return main
    from reyes_agent import web as _w

    return _w


def _gather() -> dict:
    from reyes_agent import agent_runtime

    web = _live_web()
    data: dict = {
        "saved_at": time.time(),
        "clean_exit": _clean_exit,
        "history": [],
        "missions": [],
        "campaigns": [],
        "agents": {},
    }
    try:
        data["history"] = list(web._history)[-_MAX_HISTORY:]
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.tools.missions import list_missions_dicts

        data["missions"] = [{"id": m["id"], "name": m["name"], "status": m["status"],
                             "progress": m["progress"]} for m in list_missions_dicts()]
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent import campaigns

        data["campaigns"] = [c for c in campaigns.list_campaigns(20)
                             if c["status"] in ("running", "paused", "approved")]
    except Exception:  # noqa: BLE001
        pass
    try:
        h = agent_runtime.health()
        data["agents"] = {a["agent"]: {"tasks_completed": a["tasks_completed"],
                                        "tasks_failed": a["tasks_failed"],
                                        "restarts": a["restarts"]} for a in h["agents"]}
    except Exception:  # noqa: BLE001
        pass
    return data


def save_snapshot() -> bool:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _SNAPSHOT.with_suffix(".tmp")
        tmp.write_text(json.dumps(_gather(), default=str), encoding="utf-8")
        tmp.replace(_SNAPSHOT)   # atomic: a crash mid-write can't corrupt the snapshot
        return True
    except Exception:  # noqa: BLE001
        return False


def load_snapshot() -> dict | None:
    try:
        return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def restore() -> dict:
    """Restore what genuinely can be restored. Returns a factual report."""
    snap = load_snapshot()
    if not snap:
        return {"restored": False, "reason": "no previous session snapshot found"}

    age = time.time() - float(snap.get("saved_at") or 0)
    result = {
        "restored": True,
        "clean_exit": bool(snap.get("clean_exit")),
        "snapshot_age_s": round(age),
        "messages_restored": 0,
        "open_missions": len(snap.get("missions") or []),
        "active_campaigns": len(snap.get("campaigns") or []),
    }

    try:
        web = _live_web()   # same double-import trap applies on the way back in
        history = snap.get("history") or []
        if history and not web._history:
            web._history.extend(history)
            result["messages_restored"] = len(history)
    except Exception:  # noqa: BLE001
        pass

    try:
        from reyes_agent import event_bus

        event_bus.publish("session.restored", result, source="session_recovery")
    except Exception:  # noqa: BLE001
        pass
    return result


def summary_line(result: dict) -> str:
    if not result.get("restored"):
        return "Fresh session -- no previous state to restore."
    parts = [f"{result['messages_restored']} message(s) restored"]
    if result["open_missions"]:
        parts.append(f"{result['open_missions']} open mission(s)")
    if result["active_campaigns"]:
        parts.append(f"{result['active_campaigns']} active campaign(s)")
    how = "after a clean shutdown" if result["clean_exit"] else (
        f"after an unexpected exit; snapshot was {result['snapshot_age_s']}s old, "
        "so anything in the final minute may be missing")
    return "Previous session restored: " + ", ".join(parts) + f" ({how})."


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler

    get_scheduler().schedule(
        "session-snapshot", save_snapshot, delay=_SNAPSHOT_INTERVAL,
        interval=_SNAPSHOT_INTERVAL, priority=80, timeout=30,
    )


def mark_clean_exit() -> bool:
    global _clean_exit
    _clean_exit = True
    saved = save_snapshot()
    try:
        from reyes_agent.scheduler import get_scheduler

        get_scheduler().cancel("session-snapshot")
    except Exception:  # noqa: BLE001
        pass
    return saved
