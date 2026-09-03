"""Bounded cross-runtime intelligence services for ZENO.

This module is deliberately an integration layer, not another brain, task
runtime, event bus, or scheduler.  It gives the existing Kernel/worker pool
one factual projection of active work, reversible ZENO file writes, current
situation, capability truth, health checks, temporal parsing, and search.

Every persistent record lives in the existing local state database.  All
polling is opt-in: health checks run on demand and situation is updated by
real request/tool/agent events rather than a new background loop.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reyes_agent import config


_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / (
    "test-state.db" if config.ZENO_ENV == "test" else "state.db"
)
_MAX_ACTIONS = 500
_MAX_PREVIOUS_FILE_BYTES = 512 * 1024
_MAX_SEARCH_RESULTS = 20
_SENSITIVE_SUFFIXES = {".env", ".key", ".pem", ".p12", ".pfx", ".secret"}
_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS zeno_action_history ("
            "id TEXT PRIMARY KEY, ts REAL, action TEXT, resource TEXT, result TEXT, "
            "reversible INTEGER, undone INTEGER DEFAULT 0, undo_kind TEXT, undo_data TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zeno_actions_ts ON zeno_action_history(ts DESC)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS zeno_mission_state ("
            "mission_id INTEGER PRIMARY KEY, goal TEXT, plan_json TEXT, completed_json TEXT, "
            "pending_json TEXT, files_json TEXT, agents_json TEXT, decisions_json TEXT, "
            "errors_json TEXT, verification_json TEXT, updated REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS zeno_personal_relationships ("
            "id TEXT PRIMARY KEY, source TEXT, relation TEXT, target TEXT, evidence TEXT, updated REAL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zeno_relationships_lookup "
                     "ON zeno_personal_relationships(source, target, updated DESC)")
    return conn


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret|credential)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)
    return text[:limit]


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="intelligence")
    except Exception:  # noqa: BLE001 -- observability must not break the action
        pass


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relative_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.VAULT_PATH.resolve()))
    except (OSError, ValueError):
        return str(path)


# --- interrupt and correction ------------------------------------------


@dataclass
class ActiveOperation:
    id: str
    label: str
    kind: str
    handle: Any
    started_at: float


class RuntimeControl:
    """Tracks managed task handles so a stop reaches actual work, not just UI."""

    def __init__(self) -> None:
        self._operations: dict[str, ActiveOperation] = {}
        self._control_lock = threading.RLock()

    def register(self, handle: Any, *, label: str, kind: str) -> str:
        operation = ActiveOperation(handle.id, _safe_text(label, 160), kind, handle, time.time())
        with self._control_lock:
            self._operations[operation.id] = operation
        _publish("runtime.operation_started", self.snapshot_operation(operation))
        return operation.id

    def release(self, handle_or_id: Any) -> None:
        operation_id = getattr(handle_or_id, "id", handle_or_id)
        with self._control_lock:
            operation = self._operations.pop(str(operation_id), None)
        if operation is not None:
            _publish("runtime.operation_finished", self.snapshot_operation(operation))

    def supersede(self, *, kinds: tuple[str, ...], keep_id: str = "") -> list[str]:
        """Cancel earlier conversation turns when a newer one supersedes them.

        ZENO serves a single owner and every conversation turn (typed or voice)
        takes the SAME global turn lock, so a slow or abandoned turn makes every
        following command queue behind it (measured: a 2s query waited 87s behind
        stale turns). For an interactive assistant the latest command is the
        intended one, so when a new turn starts we cancel the earlier ones
        instead of letting the newcomer wait out its 90s timeout. Cancellation is
        the existing cooperative kind -- a queued turn spinning on the lock raises
        at its next ``check_cancelled`` and frees the slot at once; one already
        inside a model read frees when that read returns (bounded by the granular
        read timeout), never the full 90s. Only the given ``kinds`` are touched,
        so a workflow or background agent the owner started keeps running.
        """
        wanted = set(kinds)
        cancelled: list[str] = []
        with self._control_lock:
            operations = list(self._operations.values())
        for operation in operations:
            if operation.id == keep_id or operation.kind not in wanted:
                continue
            if getattr(operation.handle, "done", False):
                continue
            if operation.handle.cancel():
                cancelled.append(operation.label)
        return cancelled

    @staticmethod
    def snapshot_operation(operation: ActiveOperation) -> dict[str, Any]:
        snapshot = operation.handle.snapshot() if hasattr(operation.handle, "snapshot") else {}
        return {"id": operation.id, "label": operation.label, "kind": operation.kind,
                "started_at": operation.started_at, "task": snapshot}

    def active(self) -> list[dict[str, Any]]:
        with self._control_lock:
            stale = [oid for oid, op in self._operations.items() if getattr(op.handle, "done", False)]
            for oid in stale:
                self._operations.pop(oid, None)
            return [self.snapshot_operation(op) for op in self._operations.values()]

    def interrupt(self, *, action: str = "cancel", correction: str = "", exclude_id: str = "") -> dict[str, Any]:
        """Cancel managed work and queued specialist work; never claim forced I/O abort."""
        action = (action or "cancel").strip().lower()
        if action not in {"cancel", "pause"}:
            action = "cancel"
        cancelled: list[str] = []
        with self._control_lock:
            operations = list(self._operations.values())
        for operation in operations:
            if operation.id == exclude_id:
                continue
            if getattr(operation.handle, "done", False):
                continue
            if operation.handle.cancel():
                cancelled.append(operation.label)
        workflow_message = ""
        try:
            from reyes_agent.workflow_engine import get_workflow_engine

            workflow_message = (get_workflow_engine().pause_run() if action == "pause"
                                else get_workflow_engine().cancel_run())
        except Exception:  # noqa: BLE001
            pass
        try:
            from reyes_agent import agent_runtime

            cancelled_agents = agent_runtime.cancel_active(reason="owner interruption")
        except Exception:  # noqa: BLE001
            cancelled_agents = 0
        try:
            from reyes_agent import voice_manager

            voice_manager.cancel_current()
        except Exception:  # noqa: BLE001
            pass
        result = {"action": action, "cancelled_operations": cancelled,
                  "cancelled_agent_tasks": cancelled_agents,
                  "workflow": workflow_message, "correction": _safe_text(correction, 500)}
        _publish("runtime.interrupted", result)
        return result

    def classify(self, message: str) -> tuple[str, str]:
        """Return (kind, correction). Exact short commands avoid partial-speech execution."""
        normal = " ".join(str(message or "").casefold().split())
        normal = re.sub(r"^zeno[,:\s]+", "", normal)
        if re.fullmatch(r"(?:stop|cancel|abort|never mind|dont continue|don't continue)(?: (?:that|it|this))?", normal):
            return "cancel", ""
        if re.fullmatch(r"(?:wait|pause|hold on|hold|we'll continue later|we will continue later)(?: (?:that|it|this))?", normal):
            return "pause", ""
        match = re.match(r"(?:no[, ]+)?(?:i meant|change (?:that|the last step) to|not )\s+(.+)", normal)
        if match and match.group(1).strip():
            return "correction", match.group(1).strip()
        return "", ""

    def handle_user_message(self, message: str, *, exclude_id: str = "") -> tuple[str | None, str]:
        kind, correction = self.classify(message)
        if kind == "cancel":
            result = self.interrupt(action="cancel", exclude_id=exclude_id)
            count = len(result["cancelled_operations"])
            return (f"Stopped {count} active ZENO task(s) and cancelled queued work. Completed work was preserved.", "")
        if kind == "pause":
            result = self.interrupt(action="pause", exclude_id=exclude_id)
            return ("Pause requested. ZENO will not start another managed step; completed work is preserved for resume.", "")
        if kind == "correction":
            self.interrupt(action="cancel", correction=correction, exclude_id=exclude_id)
            return (None, correction)
        return None, message


_runtime_control = RuntimeControl()


def get_runtime_control() -> RuntimeControl:
    return _runtime_control


# --- undoable action history -------------------------------------------


def record_tool_execution(action: str, tool_input: dict[str, Any], result: str) -> None:
    """Record a bounded factual entry for every non-specialized tool action."""
    if action == "write_project_file":
        return  # project writes hold real before-state through begin/complete below
    ok = not str(result).casefold().startswith(("error", "couldn't", "queued as request"))
    resource = ""
    for key in ("path", "src", "name_or_path", "project_name", "mission_id", "name"):
        if tool_input.get(key) not in (None, ""):
            resource = _safe_text(tool_input[key], 240)
            break
    action_id = uuid.uuid4().hex[:12]
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO zeno_action_history (id, ts, action, resource, result, reversible, undone, undo_kind, undo_data) "
                    "VALUES (?, ?, ?, ?, ?, 0, 0, '', '')",
                    (action_id, time.time(), action, resource, _safe_text(result, 500)),
                )
                conn.execute(
                    "DELETE FROM zeno_action_history WHERE id IN (SELECT id FROM zeno_action_history "
                    "ORDER BY ts DESC LIMIT -1 OFFSET ?)", (_MAX_ACTIONS,),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return
    _publish("action.recorded", {"id": action_id, "action": action, "resource": resource,
                                   "reversible": False, "ok": ok})


def begin_project_write(target: Path) -> str | None:
    """Capture only safe small project text before one ZENO-owned write."""
    target = target.resolve()
    if target.suffix.casefold() in _SENSITIVE_SUFFIXES:
        return None
    existed = target.is_file()
    undo_kind, undo_data = "", {}
    try:
        if existed:
            size = target.stat().st_size
            if size > _MAX_PREVIOUS_FILE_BYTES:
                return None
            previous = target.read_text(encoding="utf-8")
            # Undo is optional. Do not turn a project write into a local copy
            # of a credential simply to make it reversible.
            if re.search(r"(?i)(api[_-]?key|password|secret|private[_-]?key|credential)\s*[:=]", previous):
                return None
            undo_kind = "restore_file"
            undo_data = {"path": str(target), "previous": previous, "before_hash": _hash_text(previous)}
        else:
            undo_kind = "delete_created_file"
            undo_data = {"path": str(target)}
    except (OSError, UnicodeError):
        return None
    action_id = uuid.uuid4().hex[:12]
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO zeno_action_history (id, ts, action, resource, result, reversible, undone, undo_kind, undo_data) "
                    "VALUES (?, ?, 'write_project_file', ?, 'pending', 1, 0, ?, ?)",
                    (action_id, time.time(), _relative_label(target), undo_kind, json.dumps(undo_data)),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None
    return action_id


def complete_project_write(action_id: str | None, target: Path, result: str) -> None:
    if not action_id:
        return
    try:
        payload = {"after_hash": _hash_text(target.read_text(encoding="utf-8"))}
    except (OSError, UnicodeError):
        payload = {}
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT undo_data FROM zeno_action_history WHERE id = ?", (action_id,)).fetchone()
            prior = json.loads(row[0]) if row and row[0] else {}
            prior.update(payload)
            with conn:
                conn.execute("UPDATE zeno_action_history SET result = ?, undo_data = ? WHERE id = ?",
                             (_safe_text(result, 500), json.dumps(prior), action_id))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return
    # Project Activity already emits the real write completion through the
    # Event Bus. Do not duplicate that event here: duplicate persistence made
    # a direct unit-test/project write keep an otherwise idle writer alive.


def abandon_project_write(action_id: str | None, reason: str) -> None:
    if not action_id:
        return
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute("UPDATE zeno_action_history SET result = ?, reversible = 0 WHERE id = ?",
                             (_safe_text(reason, 500), action_id))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def action_history(limit: int = 10) -> list[dict[str, Any]]:
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, ts, action, resource, result, reversible, undone, undo_kind FROM zeno_action_history "
                "ORDER BY ts DESC LIMIT ?", (max(1, min(100, int(limit))),)
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []
    return [{"id": row[0], "timestamp": row[1], "action": row[2], "resource": row[3],
             "result": row[4], "reversible": bool(row[5]), "undone": bool(row[6]),
             "undo_kind": row[7]} for row in rows]


def undo_last(count: int = 1) -> dict[str, Any]:
    count = max(1, min(10, int(count)))
    actions = [item for item in action_history(100) if item["reversible"] and not item["undone"]][:count]
    if not actions:
        return {"ok": False, "message": "There are no reversible completed ZENO actions to undo.", "undone": []}
    undone, failures = [], []
    # ``action_history`` is newest first, so undo in that same order: the
    # last write is reversed before the write it may have depended on.
    for action in actions:
        try:
            conn = _connect()
            try:
                row = conn.execute("SELECT undo_kind, undo_data, result FROM zeno_action_history WHERE id = ?",
                                   (action["id"],)).fetchone()
            finally:
                conn.close()
            if not row or str(row[2]) == "pending":
                raise RuntimeError("The original write did not complete, so it cannot be safely undone.")
            undo_kind, payload = row[0], json.loads(row[1] or "{}")
            target = Path(str(payload.get("path") or "")).resolve()
            if not str(target):
                raise RuntimeError("The action has no safe resource path.")
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            expected = str(payload.get("after_hash") or "")
            if not expected or _hash_text(current) != expected:
                raise RuntimeError("The file changed after ZENO wrote it; refusing to overwrite newer work.")
            if undo_kind == "restore_file":
                target.write_text(str(payload.get("previous") or ""), encoding="utf-8")
            elif undo_kind == "delete_created_file":
                target.unlink()
            else:
                raise RuntimeError("This action has no implemented inverse.")
            conn = _connect()
            try:
                with conn:
                    conn.execute("UPDATE zeno_action_history SET undone = 1, result = ? WHERE id = ?",
                                 ("undone by owner request", action["id"]))
            finally:
                conn.close()
            undone.append(action["id"])
            _publish("action.undone", {"id": action["id"], "action": action["action"],
                                        "resource": action["resource"]})
        except Exception as exc:  # noqa: BLE001
            failures.append({"id": action["id"], "reason": str(exc)})
    if undone:
        return {"ok": not failures, "message": f"Undid {len(undone)} ZENO file action(s).",
                "undone": undone, "failures": failures}
    return {"ok": False, "message": "No requested action was safely undoable.", "undone": [], "failures": failures}


# --- factual situation and persistent mission state --------------------

_situation: dict[str, Any] = {"updated_at": 0.0, "recent_command": "", "current_task": "",
                              "current_step": "", "active_agents": [], "active_mission": None,
                              "media": "", "notifications": 0}


def update_situation(**values: Any) -> dict[str, Any]:
    with _lock:
        for key, value in values.items():
            if key not in _situation:
                continue
            if isinstance(value, str):
                _situation[key] = _safe_text(value, 500)
            elif key == "active_agents":
                _situation[key] = sorted({str(item)[:64] for item in value}) if value else []
            else:
                _situation[key] = value
        _situation["updated_at"] = time.time()
        snapshot = dict(_situation)
    _publish("situation.updated", snapshot)
    return snapshot


def situation() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_situation)
    try:
        from reyes_agent.activity_monitor import foreground_app

        app, title = foreground_app()
        snapshot["active_application"] = app or None
        snapshot["active_window"] = _safe_text(title, 240) if title else None
    except Exception:  # noqa: BLE001
        snapshot["active_application"] = None
        snapshot["active_window"] = None
    try:
        from reyes_agent.workflow_engine import get_workflow_engine

        workflow = get_workflow_engine().status()
        snapshot["workflow"] = {key: workflow.get(key) for key in ("mode", "name", "index", "total", "prompt", "error")}
    except Exception:  # noqa: BLE001
        snapshot["workflow"] = {}
    try:
        from reyes_agent import agent_runtime

        snapshot["active_agents"] = list(agent_runtime.health().get("working_now", []))
    except Exception:  # noqa: BLE001
        pass
    snapshot["active_operations"] = get_runtime_control().active()
    return snapshot


def resolve_reference(reference: str, *, state: dict[str, Any] | None = None,
                      risk: str = "low") -> dict[str, Any]:
    """Resolve a conversational reference only when observable context is unique.

    Pronouns are never sent to an action as guessed target text. A typed
    category (``that app``, ``this task``, ``the current window``) selects
    only the matching observed field. A bare ``it`` is resolved only when
    exactly one actionable candidate exists across the current projection.
    High-risk resolution still requires the normal permission confirmation;
    reference confidence can never grant authority.
    """
    snapshot = dict(state) if state is not None else situation()
    text = " ".join(str(reference or "").casefold().split())
    risk = str(risk or "low").casefold()
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "medium"

    candidates: list[dict[str, str]] = []

    def add(kind: str, value: Any, evidence: str) -> None:
        value = _safe_text(value, 500).strip()
        if value and all(item["value"].casefold() != value.casefold() for item in candidates):
            candidates.append({"kind": kind, "value": value, "evidence": evidence})

    categories: set[str]
    if re.fullmatch(r"(?:the\s+)?(?:current|active|that|this)?\s*(?:app|application)", text):
        categories = {"application"}
    elif re.fullmatch(r"(?:the\s+)?(?:current|active|that|this)?\s*window", text):
        categories = {"window"}
    elif re.fullmatch(r"(?:the\s+)?(?:current|active|last|that|this)?\s*(?:task|operation|job)", text):
        categories = {"task"}
    elif re.fullmatch(r"(?:the\s+)?(?:current|active|last|that|this)?\s*(?:mission|workflow)", text):
        categories = {"mission"}
    elif text in {"it", "that", "this", "the one", "that one", "this one"}:
        categories = {"application", "window", "task", "mission"}
    else:
        return {
            "resolved": False, "reference": reference,
            "reason": "The phrase is not an ambiguous context reference.",
            "candidates": [], "risk": risk,
            "requires_confirmation": risk in {"high", "critical"},
        }

    if "application" in categories:
        add("application", snapshot.get("active_application"), "observed foreground application")
    if "window" in categories:
        add("window", snapshot.get("active_window"), "observed foreground window")
    if "task" in categories:
        add("task", snapshot.get("current_task"), "current managed task")
        operations = list(snapshot.get("active_operations") or [])
        if len(operations) == 1:
            add("task", operations[0].get("label"), "only active managed operation")
    if "mission" in categories:
        mission = snapshot.get("active_mission")
        if isinstance(mission, dict):
            add("mission", mission.get("title") or mission.get("goal") or mission.get("mission_id"),
                "active durable mission")
        else:
            add("mission", mission, "active durable mission")
        workflow = snapshot.get("workflow")
        if isinstance(workflow, dict) and str(workflow.get("mode") or "").upper() not in {"", "NORMAL"}:
            add("workflow", workflow.get("name") or workflow.get("prompt"), "active workflow")

    if len(candidates) != 1:
        reason = ("No matching observed target exists." if not candidates
                  else "More than one observed target matches; ask which one.")
        return {
            "resolved": False, "reference": reference, "reason": reason,
            "candidates": candidates, "risk": risk,
            "requires_confirmation": risk in {"high", "critical"},
        }
    result = {
        "resolved": True, "reference": reference, "target": candidates[0],
        "confidence": 1.0 if len(categories) == 1 else 0.8,
        "confidence_basis": candidates[0]["evidence"], "risk": risk,
        "requires_confirmation": risk in {"high", "critical"},
    }
    _publish("situation.reference_resolved", {
        "kind": candidates[0]["kind"], "risk": risk,
        "requires_confirmation": result["requires_confirmation"],
    })
    return result


def persist_mission_state(mission_id: int, **state: Any) -> dict[str, Any]:
    """Persist only observable mission state, never model reasoning."""
    current = load_mission_state(mission_id) or {"mission_id": int(mission_id)}
    allowed = {"goal", "plan", "completed", "pending", "files", "agents", "decisions", "errors", "verification"}
    for key, value in state.items():
        if key in allowed:
            current[key] = value
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO zeno_mission_state (mission_id, goal, plan_json, completed_json, pending_json, files_json, "
                    "agents_json, decisions_json, errors_json, verification_json, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(mission_id) DO UPDATE SET goal=excluded.goal, plan_json=excluded.plan_json, "
                    "completed_json=excluded.completed_json, pending_json=excluded.pending_json, files_json=excluded.files_json, "
                    "agents_json=excluded.agents_json, decisions_json=excluded.decisions_json, errors_json=excluded.errors_json, "
                    "verification_json=excluded.verification_json, updated=excluded.updated",
                    (int(mission_id), _safe_text(current.get("goal"), 1000), json.dumps(current.get("plan", [])),
                     json.dumps(current.get("completed", [])), json.dumps(current.get("pending", [])),
                     json.dumps(current.get("files", [])), json.dumps(current.get("agents", [])),
                     json.dumps(current.get("decisions", [])), json.dumps(current.get("errors", [])),
                     json.dumps(current.get("verification", [])), time.time()),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return current
    _publish("mission.state_saved", {"mission_id": int(mission_id), "pending": len(current.get("pending", [])),
                                      "completed": len(current.get("completed", []))})
    return current


def load_mission_state(mission_id: int) -> dict[str, Any] | None:
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT mission_id, goal, plan_json, completed_json, pending_json, files_json, agents_json, "
                               "decisions_json, errors_json, verification_json, updated FROM zeno_mission_state WHERE mission_id = ?",
                               (int(mission_id),)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        labels = ("mission_id", "goal", "plan", "completed", "pending", "files", "agents", "decisions", "errors", "verification", "updated")
        data: dict[str, Any] = {"mission_id": row[0], "goal": row[1], "updated": row[10]}
        for index, label in enumerate(labels[2:-1], start=2):
            try:
                data[label] = json.loads(row[index] or "[]")
            except json.JSONDecodeError:
                data[label] = []
        return data
    except Exception:  # noqa: BLE001
        return None


# --- explicit personal knowledge relationships -------------------------


def add_relationship(source: str, relation: str, target: str, *, evidence: str = "owner-confirmed") -> dict[str, Any]:
    """Store a user-confirmed relationship without replacing the existing note graph."""
    source = _safe_text(source, 160).strip()
    relation = _safe_text(relation, 80).strip().casefold().replace(" ", "_")
    target = _safe_text(target, 160).strip()
    if not source or not relation or not target:
        raise ValueError("A relationship needs a source, relation and target.")
    now = time.time()
    relationship_id = uuid.uuid4().hex[:12]
    try:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT id FROM zeno_personal_relationships WHERE lower(source) = lower(?) "
                "AND relation = ? AND lower(target) = lower(?)", (source, relation, target)
            ).fetchone()
            with conn:
                if existing:
                    relationship_id = existing[0]
                    conn.execute("UPDATE zeno_personal_relationships SET evidence = ?, updated = ? WHERE id = ?",
                                 (_safe_text(evidence, 300), now, relationship_id))
                else:
                    conn.execute("INSERT INTO zeno_personal_relationships (id, source, relation, target, evidence, updated) "
                                 "VALUES (?, ?, ?, ?, ?, ?)",
                                 (relationship_id, source, relation, target, _safe_text(evidence, 300), now))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not save relationship: {exc}") from exc
    item = {"id": relationship_id, "source": source, "relation": relation, "target": target,
            "evidence": _safe_text(evidence, 300), "updated": now}
    _publish("knowledge.relationship_saved", item)
    return item


def relationships(query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(100, int(limit)))
    try:
        conn = _connect()
        try:
            if query.strip():
                term = "%" + query.strip().casefold() + "%"
                rows = conn.execute(
                    "SELECT id, source, relation, target, evidence, updated FROM zeno_personal_relationships "
                    "WHERE lower(source) LIKE ? OR lower(relation) LIKE ? OR lower(target) LIKE ? "
                    "ORDER BY updated DESC LIMIT ?", (term, term, term, limit)
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, source, relation, target, evidence, updated FROM zeno_personal_relationships "
                                    "ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []
    return [{"id": row[0], "source": row[1], "relation": row[2], "target": row[3],
             "evidence": row[4], "updated": row[5]} for row in rows]


def remove_relationship(relationship_id: str) -> bool:
    try:
        conn = _connect()
        try:
            with conn:
                changed = conn.execute("DELETE FROM zeno_personal_relationships WHERE id = ?", (str(relationship_id),)).rowcount
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return False
    if changed:
        _publish("knowledge.relationship_deleted", {"id": str(relationship_id)})
    return bool(changed)


# --- capabilities and health -------------------------------------------

_CAPABILITIES: dict[str, tuple[str, str]] = {
    "voice_input": ("AVAILABLE", "Browser microphone/VAD and Deepgram STT are wired; provider/device availability is checked at use time."),
    "speech_output": ("AVAILABLE", "Voice Manager supports configured ElevenLabs/SAPI paths and cancellation."),
    "browser_automation": ("AVAILABLE", "Playwright is lazy, bounded and reports its own health when started."),
    "desktop_automation": ("AVAILABLE", "Permission-gated desktop tools are registered; exact app state must still be verified."),
    "workflow_replay": ("AVAILABLE", "Owner-approved workflows use guarded replay and explicit visual verification for manual desktop steps."),
    "workflow_semantic_observation": ("DEGRADED", "Accessibility/OCR anchors are used when available; manually demonstrated desktop clicks remain guarded."),
    "voice_identity": ("NOT_CONFIGURED", "Model-backed owner voice evidence is optional and never replaces strong authentication."),
    "audio_recognition": ("NOT_CONFIGURED", "A provider token or local fingerprint database is required for live song names."),
    "video_understanding": ("AVAILABLE", "Explicit bounded frame sampling, temporal change evidence, OCR and optional audio fusion are integrated without a continuous model loop."),
    "knowledge_graph": ("AVAILABLE", "Existing local graph is permission-bound and loaded on demand."),
    "universal_search": ("AVAILABLE", "Bounded search spans permitted memory, notes, projects, workflows and event history."),
    "undo": ("AVAILABLE", "Safe ZENO project text writes up to 512 KiB are hash-verified and reversible; non-reversible actions are labelled before execution."),
    "mission_resume": ("AVAILABLE", "Observable goal, plan, state, files, agents, decisions, blockers and verification persist locally with idempotent mission keys."),
    "safe_simulation": ("AVAILABLE", "Plans can be previewed without executing tools."),
    "proactive_suggestions": ("AVAILABLE", "Quiet opt-in notices and count-backed routine anticipation are integrated without an open-ended provider loop."),
    # Creative Design + Learning uses ZEAL, the existing tool registry and
    # state database. These entries name actual connected paths and their
    # gaps, rather than treating a model instruction as proof of a native
    # design application integration.
    "graphic_design": ("AVAILABLE", "ZEAL provides design direction; real images and text/SVG project assets use the existing tools."),
    "logo_design": ("PARTIAL", "Original logo discovery, critique and SVG/text masters are supported; no native vector-editor integration is claimed."),
    "brand_identity": ("AVAILABLE", "ZEAL can structure original positioning, visual direction and an evidence-backed project asset workflow."),
    "typography": ("AVAILABLE", "Typography teaching and critique policy cover hierarchy, pairing, readability and spacing."),
    "colour_theory": ("AVAILABLE", "Colour, contrast and accessibility guidance are available; cultural/contextual judgement remains a design decision."),
    "layout": ("AVAILABLE", "Hierarchy, alignment, whitespace, grids and composition are covered in design policy and critique."),
    "ui_ux": ("AVAILABLE", "ZEAL can plan and critique user flows, wireframes, components and accessibility; implementation remains project-tool based."),
    "image_editing": ("PARTIAL", "ZENO can generate images and critique visible work, but has no verified native pixel-editor automation."),
    "vector_design": ("PARTIAL", "SVG/text vector masters can be written and verified; no Figma/Illustrator/Inkscape control is claimed."),
    "creative_direction": ("AVAILABLE", "ZEAL can develop distinct, original visual directions and connect them to real design assets."),
    "design_education": ("AVAILABLE", "Learning Mode persists explicit progress locally and supports adaptive, exercise-based paths without an idle tutor runtime."),
    "creator_mode": ("AVAILABLE", "Creator projects reuse the existing agent, project tools, Event Bus and state database; no parallel creative runtime is started."),
    "mastery_coaching": ("AVAILABLE", "Practical mastery records supplied evidence and weak areas; subjective assessment is clearly labelled and never auto-promotes a learner."),
    "foodie_mode": ("AVAILABLE", "Recipe, cooking-coach and food-safety guidance use the existing conversation engine; cooking sessions are optional, bounded and Event-Bus visible."),
    "website_builder": ("AVAILABLE", "Uses the existing managed build, terminal, preview, Activity View and browser paths; website metadata and bounded checkpoints are local and event-driven."),
}


def capabilities() -> list[dict[str, str]]:
    items = []
    for name, (status, detail) in sorted(_CAPABILITIES.items()):
        current = status
        if name == "audio_recognition":
            try:
                from reyes_agent.audio_recognition import providers

                current = "AVAILABLE" if providers() else status
            except Exception:  # noqa: BLE001
                pass
        elif name == "voice_identity":
            try:
                from reyes_agent import speaker_identity

                profile = speaker_identity.enrollment_status()
                backend = profile.get("backend") or {}
                if profile.get("enrolled") and backend.get("state") == "READY":
                    current = "AVAILABLE"
                elif backend.get("state") == "READY":
                    current = "NOT_CONFIGURED"
                else:
                    current = "DEGRADED"
            except Exception:  # noqa: BLE001
                current = "DEGRADED"
        items.append({"capability": name, "status": current, "detail": detail})
    return items


def capability(name: str) -> dict[str, str] | None:
    wanted = str(name or "").strip().casefold().replace(" ", "_")
    return next((item for item in capabilities() if item["capability"] == wanted), None)


def health() -> dict[str, Any]:
    """On-demand, low-cost checks using subsystem truth; no health poller."""
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"system": name, "status": status, "detail": detail})

    try:
        from reyes_agent.kernel import get_kernel

        kernel = get_kernel().diagnostics()
        add("Kernel", "HEALTHY" if not kernel.get("shutting_down") else "DEGRADED", "Lifecycle authority is running." if not kernel.get("shutting_down") else "Shutdown is in progress.")
        workers = kernel.get("workers", {})
        add("Worker pool", "HEALTHY" if workers.get("workers_alive", 0) else "DEGRADED", f"Queue depth: {workers.get('queue_depth', 0)}.")
    except Exception as exc:  # noqa: BLE001
        add("Kernel", "ERROR", _safe_text(exc, 160))
    try:
        from reyes_agent import event_bus

        events = event_bus.runtime_stats()
        add("Event Bus", "DEGRADED" if events.get("persistence_dropped") else "HEALTHY",
            f"Persistence queue: {events.get('persistence_queue_depth', 0)}; dropped: {events.get('persistence_dropped', 0)}.")
    except Exception as exc:  # noqa: BLE001
        add("Event Bus", "ERROR", _safe_text(exc, 160))
    try:
        from reyes_agent import agent_runtime

        agents = agent_runtime.health()
        add("Agents", "HEALTHY" if agents.get("supervisor_alive") else "DEGRADED",
            f"Active workers: {agents.get('agents_active', 0)}; queued: {agents.get('queued_tasks', 0)}.")
    except Exception as exc:  # noqa: BLE001
        add("Agents", "UNAVAILABLE", _safe_text(exc, 160))
    try:
        from reyes_agent import voice_manager

        registry = voice_manager.registry()
        add("Speaker/TTS", "HEALTHY" if registry else "DEGRADED", "Voice registry is available." if registry else "No voice profiles are available.")
    except Exception as exc:  # noqa: BLE001
        add("Speaker/TTS", "UNAVAILABLE", _safe_text(exc, 160))
    try:
        from reyes_agent import browser_controller

        browser = browser_controller.health()
        add("Browser", "HEALTHY" if browser.get("available") else "DISABLED", browser.get("reason", "Browser runtime has not been activated."))
    except Exception:
        add("Browser", "DISABLED", "Browser runtime has not been activated.")
    for item in capabilities():
        if item["capability"] in {"voice_identity", "audio_recognition", "video_understanding"}:
            add(item["capability"], {"AVAILABLE": "HEALTHY", "DEGRADED": "DEGRADED", "NOT_CONFIGURED": "NOT CONFIGURED"}.get(item["status"], item["status"]), item["detail"])
    _publish("health.checked", {"checks": len(checks)})
    return {"checked_at": time.time(), "checks": checks, "active_operations": get_runtime_control().active()}


# --- temporal parsing, search, simulation ------------------------------


def resolve_time(expression: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Resolve common conversational time terms with an explicit timezone."""
    local_now = now or datetime.now().astimezone()
    text = " ".join(str(expression or "").casefold().split())
    result = local_now
    clock_match = re.fullmatch(
        r"(today|tomorrow|yesterday)(?:\s+at\s+(noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?", text,
    )
    if clock_match:
        day_name, clock = clock_match.groups()
        day_delta = {"yesterday": -1, "today": 0, "tomorrow": 1}[day_name]
        result = (local_now + timedelta(days=day_delta)).replace(hour=0, minute=0, second=0, microsecond=0)
        if clock:
            if clock == "noon":
                hour, minute = 12, 0
            elif clock == "midnight":
                hour, minute = 0, 0
            else:
                value = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", clock)
                assert value is not None
                hour, minute, meridiem = int(value.group(1)), int(value.group(2) or 0), value.group(3)
                if minute > 59 or hour > (12 if meridiem else 23) or (meridiem and hour < 1):
                    return {"resolved": False, "expression": expression, "reason": "The requested clock time is invalid."}
                if meridiem:
                    hour = hour % 12 + (12 if meridiem == "pm" else 0)
            result = result.replace(hour=hour, minute=minute)
    elif text == "now":
        result = local_now
    elif text in {"noon", "midnight", "tonight", "this morning", "this afternoon", "this evening"}:
        hour = {"midnight": 0, "this morning": 9, "noon": 12, "this afternoon": 15,
                "tonight": 20, "this evening": 19}[text]
        result = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            year, month, day = (int(value) for value in text.split("-"))
            result = local_now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            return {"resolved": False, "expression": expression, "reason": "The requested calendar date is invalid."}
    else:
        match = re.fullmatch(r"(?:in\s+)?(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks)(?:\s+from\s+now)?", text)
        if match:
            quantity, unit = int(match.group(1)), match.group(2)
            seconds = {"minute": 60, "minutes": 60, "hour": 3600, "hours": 3600,
                       "day": 86400, "days": 86400, "week": 604800, "weeks": 604800}[unit]
            result = local_now + timedelta(seconds=quantity * seconds)
        elif (past := re.fullmatch(r"(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks)\s+ago", text)):
            quantity, unit = int(past.group(1)), past.group(2)
            seconds = {"minute": 60, "minutes": 60, "hour": 3600, "hours": 3600,
                       "day": 86400, "days": 86400, "week": 604800, "weeks": 604800}[unit]
            result = local_now - timedelta(seconds=quantity * seconds)
        elif text.startswith(("last ", "next ", "this ")):
            names = {name: index for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
            direction, weekday = text.split(" ", 1)
            wanted = names.get(weekday)
            if wanted is None:
                return {"resolved": False, "expression": expression, "reason": "Unsupported temporal phrase; ask for a date or time."}
            if direction == "last":
                delta = -((local_now.weekday() - wanted) % 7 or 7)
            elif direction == "next":
                delta = (wanted - local_now.weekday()) % 7 or 7
            else:
                delta = wanted - local_now.weekday()
            result = (local_now + timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            return {"resolved": False, "expression": expression, "reason": "Unsupported temporal phrase; ask for a date or time."}
    return {"resolved": True, "expression": expression, "timestamp": result.timestamp(),
            "iso": result.isoformat(), "timezone": str(result.tzinfo or timezone.utc)}


def universal_search(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Bounded permitted search. Ranking is transparent lexical/recency evidence."""
    words = [word for word in re.findall(r"[\w-]+", str(query).casefold()) if len(word) > 1]
    if not words:
        return []
    limit = max(1, min(_MAX_SEARCH_RESULTS, int(limit)))
    results: list[dict[str, Any]] = []

    def score(text: str, recency: float = 0.0) -> float:
        lower = text.casefold()
        matches = sum(1 for word in words if word in lower)
        return matches * 10 + recency

    try:
        from reyes_agent.tools.memory import search_memories

        response = search_memories(query)
        if not response.startswith("No matching"):
            for line in response.splitlines()[:limit]:
                results.append({"source": "memory", "label": line[:200], "snippet": line[:500], "score": score(line)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.tools.notes import _iter_notes

        for path, title in _iter_notes() or []:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            combined = title + "\n" + text
            base = score(combined)
            if base <= 0:
                continue
            modified = min(5.0, max(0.0, (os.path.getmtime(path) - (time.time() - 30 * 86400)) / (30 * 86400) * 5))
            line = next((item.strip() for item in text.splitlines() if any(word in item.casefold() for word in words)), "")
            results.append({"source": "note", "label": title, "path": str(path), "snippet": line[:500], "score": base + modified})
            if len(results) >= 80:
                break
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent import event_bus

        for event in event_bus.history(limit=100):
            text = f"{event['type']} {event.get('payload', {})}"
            base = score(text)
            if base:
                results.append({"source": "activity", "label": event["type"], "timestamp": event["ts"],
                                "snippet": _safe_text(event.get("payload", {}), 500), "score": base})
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.workflow_engine import get_workflow_engine

        for workflow in get_workflow_engine().list_workflows():
            text = workflow.get("name", "")
            if score(text):
                results.append({"source": "workflow", "label": text, "snippet": f"{workflow.get('steps', 0)} approved step(s)", "score": score(text)})
    except Exception:  # noqa: BLE001
        pass
    for edge in relationships(query, limit=limit):
        text = f"{edge['source']} {edge['relation']} {edge['target']}"
        if score(text):
            results.append({"source": "personal knowledge graph", "label": text,
                            "snippet": edge["evidence"], "score": score(text)})
    for action in action_history(100):
        text = f"{action['action']} {action['resource']} {action['result']}"
        if score(text):
            results.append({"source": "action history", "label": action["action"],
                            "snippet": f"{action['resource']} — {action['result']}", "score": score(text)})
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in results:
        key = (str(item.get("source")), str(item.get("label")))
        if key not in unique or item["score"] > unique[key]["score"]:
            unique[key] = item
    ranked = sorted(unique.values(), key=lambda item: item["score"], reverse=True)[:limit]
    _publish("search.completed", {"query": _safe_text(query, 160), "results": len(ranked)})
    return ranked


def simulate_plan(goal: str, steps: list[str], *, risk: str = "medium", files: list[str] | None = None) -> dict[str, Any]:
    """A non-executing preview. It does not call a tool or alter project state."""
    safe_steps = [_safe_text(step, 300) for step in steps if str(step).strip()][:20]
    risk = risk if risk in {"low", "medium", "high", "critical"} else "medium"
    result = {"mode": "SIMULATION", "goal": _safe_text(goal, 500), "steps": safe_steps,
              "risk": risk, "files_affected": [_safe_text(path, 240) for path in (files or [])][:30],
              "executed": False, "approval_required": risk in {"high", "critical"}}
    _publish("plan.simulated", result)
    return result
