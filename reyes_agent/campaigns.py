"""Campaign Engine -- batched work with one approval gate, full preview,
and live control (pause / resume / cancel / retry).

THE SAFETY MODEL, AND WHY THIS IS DIFFERENT FROM "MASS AUTOMATION"
------------------------------------------------------------------
The objection to bulk automation was never the batching -- it was firing
irreversible, outward-facing actions that nobody ever actually looked at.
This engine keeps the batching and removes that problem:

* A campaign is built in DRAFT. Nothing runs while drafting.
* `preview` renders EVERY action with its real, resolved arguments --
  not a summary, not a sample. What you read is exactly what will run.
* Approval is one explicit act on the whole campaign, recorded with a
  timestamp. An unapproved campaign cannot be started; `run` refuses.
* Items are checked against the SAME autonomy policy as everything else
  at execution time. Money-movement tools stay blocked
  (config.AUTONOMY_NEVER_AUTO_TOOLS) even inside an approved campaign --
  batch approval is not a way to launder a category that has no flag.
* Pause and cancel take effect between items, so a campaign that starts
  going wrong is stopped in seconds rather than after 100 sends.
* Every item is retried up to `max_attempts`, then recorded as failed
  with its error rather than silently skipped.

Campaigns run on a background thread, so the GUI never blocks. Each
campaign is mirrored into a Mission (missions.py) so long-running batches
show up in the same place as every other long-running objective, and
every item execution publishes to the Event Bus for the Timeline.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

STATUSES = ("draft", "approved", "running", "paused", "completed", "cancelled", "failed")
ITEM_STATUSES = ("pending", "running", "done", "failed", "skipped")

_MAX_ATTEMPTS = 3
_runners: dict[int, object] = {}
_controls: dict[int, dict] = {}   # campaign_id -> {"pause": Event, "cancel": Event}
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS campaigns ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, description TEXT, "
        "status TEXT, batch_size INTEGER, delay_seconds REAL, mission_id INTEGER, "
        "approved_at TEXT, created TEXT, updated TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS campaign_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, seq INTEGER, "
        "label TEXT, tool TEXT, params TEXT, status TEXT, attempts INTEGER DEFAULT 0, "
        "result TEXT, error TEXT, updated TEXT)"
    )
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def create_campaign(name: str, kind: str = "", description: str = "",
                    batch_size: int = 1, delay_seconds: float = 0.0) -> int:
    """New campaign in DRAFT. Nothing can run yet."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO campaigns (name, kind, description, status, batch_size, delay_seconds, "
            "mission_id, approved_at, created, updated) VALUES (?, ?, ?, 'draft', ?, ?, NULL, NULL, ?, ?)",
            (name.strip(), kind.strip(), description.strip(),
             max(1, int(batch_size or 1)), max(0.0, float(delay_seconds or 0)), _now(), _now()),
        )
        return cur.lastrowid


def add_items(campaign_id: int, items: list[dict]) -> tuple[int, list[str]]:
    """Add actions to a draft campaign. Returns (added, rejections).

    Validates tool names NOW rather than at run time, so preview can't
    show an action that was never going to work.
    """
    from reyes_agent.tools import TOOLS

    with _connect() as conn:
        row = conn.execute("SELECT status FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            return 0, [f"No campaign #{campaign_id}."]
        if row[0] != "draft":
            return 0, [f"Campaign #{campaign_id} is '{row[0]}' -- items can only be added while it's a draft."]
        start = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM campaign_items WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()[0]

        added, rejected = 0, []
        for i, item in enumerate(items, start=1):
            tool = str(item.get("tool", "")).strip()
            if tool not in TOOLS:
                rejected.append(f"'{tool}' is not a registered tool -- skipped.")
                continue
            if tool in config.AUTONOMY_NEVER_AUTO_TOOLS:
                rejected.append(f"'{tool}' moves money and can never run unattended -- skipped.")
                continue
            conn.execute(
                "INSERT INTO campaign_items (campaign_id, seq, label, tool, params, status, updated) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (campaign_id, start + i, str(item.get("label", "") or tool), tool,
                 json.dumps(item.get("params", {})), _now()),
            )
            added += 1
        conn.execute("UPDATE campaigns SET updated = ? WHERE id = ?", (_now(), campaign_id))
    return added, rejected


def get_campaign(campaign_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, kind, description, status, batch_size, delay_seconds, mission_id, "
            "approved_at, created FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None
        items = conn.execute(
            "SELECT id, seq, label, tool, params, status, attempts, result, error "
            "FROM campaign_items WHERE campaign_id = ? ORDER BY seq", (campaign_id,)
        ).fetchall()
    return {
        "id": row[0], "name": row[1], "kind": row[2], "description": row[3],
        "status": row[4], "batch_size": row[5], "delay_seconds": row[6],
        "mission_id": row[7], "approved_at": row[8], "created": row[9],
        "items": [
            {"id": i[0], "seq": i[1], "label": i[2], "tool": i[3],
             "params": json.loads(i[4] or "{}"), "status": i[5],
             "attempts": i[6], "result": i[7], "error": i[8]}
            for i in items
        ],
    }


def list_campaigns(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.name, c.status, c.created, "
            "  (SELECT COUNT(*) FROM campaign_items i WHERE i.campaign_id = c.id), "
            "  (SELECT COUNT(*) FROM campaign_items i WHERE i.campaign_id = c.id AND i.status = 'done') "
            "FROM campaigns c ORDER BY c.id DESC LIMIT ?", (max(1, min(100, limit)),)
        ).fetchall()
    return [{"id": r[0], "name": r[1], "status": r[2], "created": r[3],
             "total": r[4], "done": r[5]} for r in rows]


def approve(campaign_id: int) -> tuple[bool, str]:
    """The single confirmation for the whole batch. Recorded with a time."""
    c = get_campaign(campaign_id)
    if c is None:
        return False, f"No campaign #{campaign_id}."
    if c["status"] != "draft":
        return False, f"Campaign #{campaign_id} is already '{c['status']}'."
    if not c["items"]:
        return False, "Nothing to approve -- the campaign has no actions."
    with _connect() as conn:
        conn.execute("UPDATE campaigns SET status = 'approved', approved_at = ?, updated = ? WHERE id = ?",
                     (_now(), _now(), campaign_id))
    return True, f"Campaign #{campaign_id} approved with {len(c['items'])} action(s)."


def _set_status(campaign_id: int, status: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE campaigns SET status = ?, updated = ? WHERE id = ?",
                     (status, _now(), campaign_id))


def _controls_for(campaign_id: int) -> dict:
    with _lock:
        ctl = _controls.get(campaign_id)
        if ctl is None:
            ctl = {"pause": threading.Event(), "cancel": threading.Event()}
            _controls[campaign_id] = ctl
        return ctl


def start(campaign_id: int) -> tuple[bool, str]:
    """Begin (or resume) execution on a background thread."""
    c = get_campaign(campaign_id)
    if c is None:
        return False, f"No campaign #{campaign_id}."
    if c["status"] not in ("approved", "paused"):
        return False, (f"Campaign #{campaign_id} is '{c['status']}'. It must be approved first "
                       "-- preview it, then approve it.")
    with _lock:
        existing = _runners.get(campaign_id)
        if existing is not None and not existing.done:
            return False, f"Campaign #{campaign_id} is already running."
    ctl = _controls_for(campaign_id)
    ctl["pause"].clear()
    ctl["cancel"].clear()

    # Mirror into Missions so a long batch appears with every other
    # long-running objective rather than in a silo of its own.
    if not c["mission_id"]:
        try:
            from reyes_agent.tools.missions import create_mission, list_missions_dicts

            create_mission(name=f"Campaign: {c['name']}",
                           description=c["description"] or f"{len(c['items'])} batched actions",
                           mission_type="campaign", priority="medium")
            latest = list_missions_dicts()
            if latest:
                with _connect() as conn:
                    conn.execute("UPDATE campaigns SET mission_id = ? WHERE id = ?",
                                 (latest[0]["id"], campaign_id))
        except Exception:  # noqa: BLE001 -- mission mirroring must not block the run
            pass

    from reyes_agent.worker_pool import PRIORITY_MISSION, get_worker_pool

    task = get_worker_pool().submit(
        _run_loop, campaign_id, name=f"campaign:{campaign_id}",
        priority=PRIORITY_MISSION,
    )
    with _lock:
        _runners[campaign_id] = task
    _set_status(campaign_id, "running")
    return True, f"Campaign #{campaign_id} started."


def pause(campaign_id: int) -> str:
    _controls_for(campaign_id)["pause"].set()
    _set_status(campaign_id, "paused")
    return f"Campaign #{campaign_id} will pause after the current action."


def resume(campaign_id: int) -> str:
    ok, msg = start(campaign_id)
    return msg if ok else msg


def cancel(campaign_id: int) -> str:
    ctl = _controls_for(campaign_id)
    ctl["cancel"].set()
    ctl["pause"].clear()
    _set_status(campaign_id, "cancelled")
    with _lock:
        task = _runners.get(campaign_id)
    if task is not None:
        task.cancel()
    return f"Campaign #{campaign_id} cancelled -- it will stop after the current action."


def _run_loop(campaign_id: int) -> None:
    from reyes_agent import event_bus
    from reyes_agent.tools import TOOLS, execute_tool

    ctl = _controls_for(campaign_id)
    c = get_campaign(campaign_id)
    if c is None:
        return
    delay = float(c["delay_seconds"] or 0)
    batch_size = int(c["batch_size"] or 1)
    done_in_batch = 0

    event_bus.publish("campaign.started", {"campaign": campaign_id, "name": c["name"],
                                           "items": len(c["items"])}, source="campaigns")

    for item in c["items"]:
        if item["status"] in ("done", "skipped"):
            continue
        if ctl["cancel"].is_set():
            _set_status(campaign_id, "cancelled")
            event_bus.publish("campaign.cancelled", {"campaign": campaign_id}, source="campaigns")
            return
        if ctl["pause"].is_set():
            _set_status(campaign_id, "paused")
            event_bus.publish("campaign.paused", {"campaign": campaign_id}, source="campaigns")
            return

        tool = TOOLS.get(item["tool"])
        if tool is None:
            _update_item(item["id"], "failed", error="tool no longer registered")
            continue
        # Re-checked at execution time, not just at add time.
        if item["tool"] in config.AUTONOMY_NEVER_AUTO_TOOLS:
            _update_item(item["id"], "skipped", error="money-movement tool, never runs unattended")
            continue

        attempts = item["attempts"]
        last_error = ""
        succeeded = False
        while attempts < _MAX_ATTEMPTS and not succeeded:
            if ctl["cancel"].is_set():
                break
            attempts += 1
            _update_item(item["id"], "running", attempts=attempts)
            try:
                result = execute_tool(tool, item["params"])
                if isinstance(result, str) and result.lower().startswith("error"):
                    last_error = result
                    time.sleep(min(2 ** attempts, 8))  # backoff before retry
                    continue
                _update_item(item["id"], "done", result=str(result)[:800], attempts=attempts)
                succeeded = True
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(min(2 ** attempts, 8))

        if not succeeded:
            _update_item(item["id"], "failed", error=last_error[:500], attempts=attempts)

        event_bus.publish(
            "campaign.item",
            {"campaign": campaign_id, "seq": item["seq"], "tool": item["tool"],
             "status": "done" if succeeded else "failed"},
            source="campaigns",
        )

        done_in_batch += 1
        if batch_size > 1 and done_in_batch % batch_size == 0 and delay:
            time.sleep(delay)
        elif delay:
            time.sleep(delay)

    final = get_campaign(campaign_id)
    failed = sum(1 for i in final["items"] if i["status"] == "failed") if final else 0
    status = "completed" if failed == 0 else "failed"
    _set_status(campaign_id, status)
    event_bus.publish("campaign.finished", {"campaign": campaign_id, "status": status,
                                            "failed": failed}, source="campaigns")


def _update_item(item_id: int, status: str, result: str = "", error: str = "",
                 attempts: int | None = None) -> None:
    with _connect() as conn:
        if attempts is None:
            conn.execute(
                "UPDATE campaign_items SET status = ?, result = ?, error = ?, updated = ? WHERE id = ?",
                (status, result, error, _now(), item_id))
        else:
            conn.execute(
                "UPDATE campaign_items SET status = ?, result = ?, error = ?, attempts = ?, updated = ? WHERE id = ?",
                (status, result, error, attempts, _now(), item_id))


def retry_failed(campaign_id: int) -> tuple[int, str]:
    """Reset failed items to pending so `start` picks them up again."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE campaign_items SET status = 'pending', attempts = 0, error = '' "
            "WHERE campaign_id = ? AND status = 'failed'", (campaign_id,))
        n = cur.rowcount
        if n:
            conn.execute("UPDATE campaigns SET status = 'approved', updated = ? WHERE id = ?",
                         (_now(), campaign_id))
    return n, (f"{n} failed action(s) reset to pending -- start the campaign again to retry."
               if n else "No failed actions to retry.")


def report(campaign_id: int) -> dict | None:
    c = get_campaign(campaign_id)
    if c is None:
        return None
    counts: dict[str, int] = {s: 0 for s in ITEM_STATUSES}
    for i in c["items"]:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {
        "id": c["id"], "name": c["name"], "status": c["status"],
        "approved_at": c["approved_at"], "mission_id": c["mission_id"],
        "total": len(c["items"]), "counts": counts,
        "failures": [{"seq": i["seq"], "label": i["label"], "error": i["error"]}
                     for i in c["items"] if i["status"] == "failed"],
    }
