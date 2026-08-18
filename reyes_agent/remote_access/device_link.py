"""Command queue between ZENO's online surface and the Windows agent.

THE SHAPE, AND WHY
------------------
The Windows machine NEVER listens on a public port. It dials out, holds the
connection, and pulls work. Every arrow points from the desktop outward:

    phone -> gateway.enqueue(...)          owner asks for something
    desktop -> claim(device_id)            agent pulls, marks IN_FLIGHT
    desktop -> acknowledge(...)            "I have it" -- proves delivery
    desktop -> complete(..., result)       "here is what happened"
    phone -> await_result(command_id)      owner sees the real outcome

There is no path that lets the internet reach into the machine. If the queue
service vanishes, the desktop simply fails to poll; nothing is exposed.

WHY A QUEUE AND NOT A DIRECT CALL
---------------------------------
The phone is on a train and the laptop is asleep. A direct call has to fail.
A queue lets the request wait, and -- more importantly -- lets ZENO tell the
owner the truth: QUEUED is not DELIVERED, and DELIVERED is not DONE. Those
are three different states and collapsing them is how "it said it opened
Chrome" happens when nothing opened.

DUPLICATE PREVENTION
--------------------
A phone on a flaky connection retries. Retrying "open Chrome" is harmless;
retrying "delete the folder" is not. Every command carries an idempotency key
and the second insert with the same key returns the FIRST command rather than
creating another.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

# A command nobody claims within this window is dead: the desktop was offline
# or the agent died holding it. Reported as TIMEOUT, never as success.
CLAIM_TIMEOUT_S = 15 * 60.0
# Once claimed, the agent has this long to report a result before the command
# is considered lost.
RESULT_TIMEOUT_S = 180.0
# A device that has not sent a heartbeat in this long is OFFLINE.
HEARTBEAT_GRACE_S = 45.0

QUEUED, WAITING_FOR_DEVICE, PENDING_APPROVAL, IN_FLIGHT, ACKNOWLEDGED = (
    "QUEUED", "WAITING_FOR_DEVICE", "PENDING_APPROVAL", "IN_FLIGHT", "ACKNOWLEDGED")
DONE, FAILED, CANCELLED, EXPIRED, TIMEOUT, REJECTED = (
    "DONE", "FAILED", "CANCELLED", "EXPIRED", "TIMEOUT", "REJECTED")

ONLINE, OFFLINE, BUSY, DEGRADED = "ONLINE", "OFFLINE", "BUSY", "DEGRADED"
PENDING_DEVICE, APPROVED_DEVICE, BLOCKED_DEVICE, REVOKED_DEVICE = (
    "PENDING", "APPROVED", "BLOCKED", "REVOKED")

# The store enforces this allow-list independently of the API.  A future route
# that forgets its own validation still cannot turn network text into a new
# executable action.
ACTION_CATEGORIES = {
    "ask": "READ_ONLY",
    "status": "READ_ONLY",
    "memory_recall": "READ_ONLY",
    "agent_status": "READ_ONLY",
    "task_status": "READ_ONLY",
    "conversation_snapshot": "READ_ONLY",
    "open_app": "STANDARD_DEVICE",
    "close_app": "SENSITIVE_DEVICE",
    "run_automation": "SENSITIVE_DEVICE",
}

APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_DENIED = (
    "pending", "approved", "denied")
APPROVAL_EXPIRED, APPROVAL_CANCELLED, APPROVAL_EXECUTED, APPROVAL_FAILED = (
    "expired", "cancelled", "executed", "failed")

_DB = Path(os.environ.get(
    "ZENO_DEVICE_LINK_DB",
    str(Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) /
        "ZENO" / "auth" / "devices.sqlite")))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Command:
    id: str
    device_id: str
    action: str
    payload: dict[str, Any]
    status: str
    category: str
    created: float
    result: dict[str, Any] | None = None
    expires: float = 0.0
    approval_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        body = {"id": self.id, "device_id": self.device_id, "action": self.action,
                "payload": self.payload, "status": self.status,
                "category": self.category, "created": self.created,
                "expires": self.expires, "approval_id": self.approval_id}
        if self.result is not None:
            body["result"] = self.result
        return body


class DeviceLink:
    """Device registry plus the command queue that serves it."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices(
                    device_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    token_hash TEXT NOT NULL,
                    registered REAL NOT NULL,
                    last_heartbeat REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'OFFLINE',
                    detail TEXT NOT NULL DEFAULT '',
                    revoked INTEGER NOT NULL DEFAULT 0,
                    approval_state TEXT NOT NULL DEFAULT 'PENDING',
                    approved REAL,
                    scopes TEXT NOT NULL DEFAULT '[]',
                    protocol_version TEXT NOT NULL DEFAULT '1.0.0');

                CREATE TABLE IF NOT EXISTS commands(
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    idempotency_key TEXT,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    category TEXT NOT NULL DEFAULT 'SAFE',
                    status TEXT NOT NULL DEFAULT 'QUEUED',
                    created REAL NOT NULL,
                    claimed REAL,
                    acknowledged REAL,
                    finished REAL,
                    result TEXT,
                    error TEXT,
                    expires REAL NOT NULL DEFAULT 0,
                    approval_id TEXT NOT NULL DEFAULT '');

                CREATE UNIQUE INDEX IF NOT EXISTS commands_idem
                    ON commands(device_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;

                CREATE INDEX IF NOT EXISTS commands_pending
                    ON commands(device_id, status, created);

                CREATE TABLE IF NOT EXISTS approvals(
                    id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE,
                    requesting_device TEXT NOT NULL DEFAULT '',
                    target_device TEXT NOT NULL,
                    action TEXT NOT NULL,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'pending',
                    created REAL NOT NULL,
                    expires REAL NOT NULL,
                    decided REAL,
                    decision_evidence TEXT NOT NULL DEFAULT '');

                CREATE INDEX IF NOT EXISTS approvals_state
                    ON approvals(state, expires, created);

                CREATE TABLE IF NOT EXISTS activity(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at REAL NOT NULL,
                    event TEXT NOT NULL,
                    requesting_device TEXT NOT NULL DEFAULT '',
                    target_device TEXT NOT NULL DEFAULT '',
                    command_id TEXT NOT NULL DEFAULT '',
                    agent TEXT NOT NULL DEFAULT 'ZENO',
                    permission_level TEXT NOT NULL DEFAULT '',
                    approval_result TEXT NOT NULL DEFAULT '',
                    execution_result TEXT NOT NULL DEFAULT '',
                    failure_reason TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '');

                CREATE TABLE IF NOT EXISTS settings(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated REAL NOT NULL);
                """
            )
            # Databases created by Claude's first draft predate the additional
            # trust/expiry columns.  Migrate in place without deleting devices
            # or commands that may already exist.
            self._ensure_column(conn, "devices", "approval_state",
                                "TEXT NOT NULL DEFAULT 'PENDING'")
            self._ensure_column(conn, "devices", "approved", "REAL")
            self._ensure_column(conn, "devices", "scopes",
                                "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "devices", "protocol_version",
                                "TEXT NOT NULL DEFAULT '1.0.0'")
            self._ensure_column(conn, "commands", "expires",
                                "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "commands", "approval_id",
                                "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated) VALUES('remote_control','1',?)",
                (time.time(),))

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str,
                       declaration: str) -> None:
        existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def _clean(value: Any, limit: int = 240) -> str:
        text = " ".join(str(value or "").split())[:limit]
        lowered = text.casefold()
        if any(marker in lowered for marker in (
                "password=", "token=", "api_key=", "apikey=", "authorization:",
                "bearer ", "private key", "refresh=")):
            return "[REDACTED]"
        return text

    @classmethod
    def _has_sensitive_data(cls, value: Any, *, depth: int = 0) -> bool:
        if depth > 6:
            return True
        markers = ("password", "token", "secret", "api_key", "apikey", "cookie",
                   "authorization", "private_key", "otp", "mfa", "passkey")
        if isinstance(value, dict):
            return any(any(marker in str(key).casefold() for marker in markers) or
                       cls._has_sensitive_data(item, depth=depth + 1)
                       for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(cls._has_sensitive_data(item, depth=depth + 1) for item in value)
        if isinstance(value, str):
            lowered = value.casefold()
            return any(pattern in lowered for pattern in (
                "bearer ", "-----begin private key", "ghp_", "sk-ant-", "sk-proj-"))
        return False

    def _activity(self, event: str, *, requesting_device: str = "",
                  target_device: str = "", command_id: str = "", agent: str = "ZENO",
                  permission_level: str = "", approval_result: str = "",
                  execution_result: str = "", failure_reason: str = "",
                  summary: str = "") -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO activity(at,event,requesting_device,target_device,command_id,"
                "agent,permission_level,approval_result,execution_result,failure_reason,summary) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), self._clean(event, 80), self._clean(requesting_device, 80),
                 self._clean(target_device, 80), self._clean(command_id, 80),
                 self._clean(agent, 80), self._clean(permission_level, 40),
                 self._clean(approval_result, 40), self._clean(execution_result, 80),
                 self._clean(failure_reason, 240), self._clean(summary, 240)))

    def activity(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),)).fetchall()
        return [dict(row) for row in rows]

    def remote_control_enabled(self) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='remote_control'").fetchone()
        return row is not None and row["value"] == "1"

    def set_remote_control(self, enabled: bool, *, requesting_device: str = "") -> dict[str, Any]:
        now = time.time()
        cancelled = 0
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO settings(key,value,updated) VALUES('remote_control',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                ("1" if enabled else "0", now))
            if not enabled:
                cancelled = conn.execute(
                    "UPDATE commands SET status=?,finished=?,error=? WHERE status IN (?,?,?)",
                    (CANCELLED, now, "remote control disabled", QUEUED,
                     WAITING_FOR_DEVICE, PENDING_APPROVAL)).rowcount
                conn.execute(
                    "UPDATE approvals SET state=?,decided=?,decision_evidence=? "
                    "WHERE state=?",
                    (APPROVAL_CANCELLED, now, "remote control disabled", APPROVAL_PENDING))
        self._activity("remote_control_enabled" if enabled else "remote_control_disabled",
                       requesting_device=requesting_device,
                       execution_result="enabled" if enabled else "disabled",
                       summary=f"cancelled queued commands: {cancelled}")
        return {"enabled": bool(enabled), "cancelled_commands": int(cancelled)}

    # ---- device registration -------------------------------------------
    def register(self, *, label: str, platform: str = "windows",
                 device_id: str = "", approved: bool = False,
                 scopes: list[str] | None = None,
                 protocol_version: str = "1.0.0") -> dict[str, str]:
        """Register a device and return its id and a one-time secret.

        The secret is returned ONCE and stored only as a hash. If it is lost,
        the device re-registers -- there is no recovery path, because a
        recovery path is a second way in.
        """
        device_id = (device_id or f"dev_{uuid.uuid4().hex[:16]}")[:64]
        token = secrets.token_urlsafe(32)
        approval_state = APPROVED_DEVICE if approved else PENDING_DEVICE
        approved_at = time.time() if approved else None
        safe_scopes = sorted({str(item)[:64] for item in (scopes or []) if str(item).strip()})
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO devices(device_id,label,platform,token_hash,registered,state,"
                "approval_state,approved,scopes,protocol_version) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET "
                "label=excluded.label, platform=excluded.platform, token_hash=excluded.token_hash, "
                "state=excluded.state, revoked=0, approval_state=excluded.approval_state, "
                "approved=excluded.approved, scopes=excluded.scopes, "
                "protocol_version=excluded.protocol_version",
                (device_id, label[:80], platform[:32], _hash(token), time.time(), OFFLINE,
                 approval_state, approved_at, json.dumps(safe_scopes),
                 str(protocol_version or "")[:32]))
        self._activity("device_registered", target_device=device_id,
                       execution_result=approval_state, summary=label[:120])
        return {"device_id": device_id, "token": token,
                "approval_state": approval_state}

    def authenticate(self, device_id: str, token: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT token_hash,revoked,approval_state FROM devices WHERE device_id=?",
                (device_id or "",)).fetchone()
        if (row is None or row["revoked"] or
                row["approval_state"] != APPROVED_DEVICE):
            return False
        return secrets.compare_digest(row["token_hash"], _hash(token or ""))

    def approve_device(self, device_id: str, *, scopes: list[str] | None = None) -> bool:
        safe_scopes = sorted({str(item)[:64] for item in (scopes or []) if str(item).strip()})
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE devices SET approval_state=?,approved=?,revoked=0,scopes=? "
                "WHERE device_id=? AND approval_state NOT IN (?,?)",
                (APPROVED_DEVICE, time.time(), json.dumps(safe_scopes), device_id,
                 BLOCKED_DEVICE, REVOKED_DEVICE)).rowcount
        if changed:
            self._activity("device_approved", target_device=device_id,
                           execution_result="approved")
        return bool(changed)

    def rename_device(self, device_id: str, label: str) -> bool:
        clean = " ".join(str(label or "").split())[:80]
        if not clean:
            return False
        with self._connection() as conn:
            changed = conn.execute("UPDATE devices SET label=? WHERE device_id=?",
                                   (clean, device_id)).rowcount
        return bool(changed)

    def block_device(self, device_id: str) -> bool:
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE devices SET approval_state=?,state=? WHERE device_id=? AND revoked=0",
                (BLOCKED_DEVICE, OFFLINE, device_id)).rowcount
            conn.execute(
                "UPDATE commands SET status=?,error=?,finished=? WHERE device_id=? "
                "AND status IN (?,?,?)",
                (CANCELLED, "device blocked", time.time(), device_id,
                 QUEUED, WAITING_FOR_DEVICE, PENDING_APPROVAL))
        if changed:
            self._activity("device_blocked", target_device=device_id,
                           execution_result="blocked")
        return bool(changed)

    def revoke_device(self, device_id: str) -> bool:
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE devices SET revoked=1,approval_state=?,state=? WHERE device_id=?",
                (REVOKED_DEVICE, OFFLINE, device_id)).rowcount
            # A revoked device must not be handed work it will never run.
            conn.execute(
                "UPDATE commands SET status=?, error=?, finished=? "
                "WHERE device_id=? AND status IN (?,?,?,?,?)",
                (REJECTED, "device revoked", time.time(), device_id, QUEUED,
                 WAITING_FOR_DEVICE, PENDING_APPROVAL, IN_FLIGHT, ACKNOWLEDGED))
        if changed:
            self._activity("device_revoked", target_device=device_id,
                           execution_result="revoked")
        return bool(changed)

    # ---- heartbeat ------------------------------------------------------
    def heartbeat(self, device_id: str, *, state: str = ONLINE,
                  detail: str = "") -> bool:
        if state not in (ONLINE, OFFLINE, BUSY, DEGRADED):
            state = DEGRADED
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE devices SET last_heartbeat=?, state=?, detail=? "
                "WHERE device_id=? AND revoked=0 AND approval_state=?",
                (time.time(), state, detail[:200], device_id, APPROVED_DEVICE)).rowcount
        return bool(changed)

    def device_state(self, device_id: str) -> dict[str, Any]:
        """Live state. A stale heartbeat reads OFFLINE regardless of the
        last value the device wrote -- an agent that dies mid-command cannot
        leave itself looking ONLINE forever."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT device_id,label,platform,last_heartbeat,state,detail,revoked,registered,"
                "approval_state,approved,scopes,protocol_version "
                "FROM devices WHERE device_id=?", (device_id or "",)).fetchone()
        if row is None:
            return {"known": False, "state": OFFLINE, "reason": "not registered"}
        age = time.time() - row["last_heartbeat"]
        stale = row["last_heartbeat"] <= 0 or age > HEARTBEAT_GRACE_S
        trusted = row["approval_state"] == APPROVED_DEVICE and not row["revoked"]
        state = OFFLINE if (stale or not trusted) else row["state"]
        try:
            scopes = json.loads(row["scopes"] or "[]")
        except json.JSONDecodeError:
            scopes = []
        return {
            "known": True, "device_id": row["device_id"], "label": row["label"],
            "platform": row["platform"], "state": state, "detail": row["detail"],
            "revoked": bool(row["revoked"]), "registered": row["registered"],
            "approval_state": row["approval_state"], "approved": row["approved"],
            "scopes": scopes, "protocol_version": row["protocol_version"],
            "last_heartbeat": row["last_heartbeat"],
            "seconds_since_heartbeat": round(age, 1) if row["last_heartbeat"] else None,
        }

    def devices(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT device_id FROM devices ORDER BY registered DESC").fetchall()
        return [self.device_state(row["device_id"]) for row in rows]

    # ---- queue ----------------------------------------------------------
    def enqueue(self, device_id: str, action: str, payload: dict[str, Any] | None = None,
                *, category: str = "", idempotency_key: str = "",
                requesting_device: str = "", requires_approval: bool = False,
                expires_in_s: float = CLAIM_TIMEOUT_S) -> Command:
        """Queue one command. Re-queuing the same idempotency key is a no-op.

        Returns the EXISTING command when the key repeats, so a retry from a
        phone on a bad connection cannot run an action twice.
        """
        self._expire_stale()
        if not self.remote_control_enabled():
            raise PermissionError("Remote control is disabled.")
        action = str(action or "").strip()
        if action not in ACTION_CATEGORIES:
            raise ValueError(f"Unregistered remote action: {action!r}")
        expected_category = ACTION_CATEGORIES[action]
        if category and str(category) not in {expected_category, "SAFE", "CONTROL"}:
            raise ValueError("The supplied permission category does not match the action.")
        category = expected_category
        device = self.device_state(device_id)
        if not device.get("known"):
            raise KeyError("Unknown target device.")
        if device.get("approval_state") != APPROVED_DEVICE or device.get("revoked"):
            raise PermissionError("Target device is not approved.")
        payload = payload or {}
        if not isinstance(payload, dict):
            raise TypeError("Command payload must be an object.")
        payload_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(payload_text.encode("utf-8")) > 64 * 1024:
            raise ValueError("Command payload exceeds 64 KiB.")
        if self._has_sensitive_data(payload):
            raise ValueError("Secrets and credentials cannot be queued as command payloads.")
        key = (idempotency_key or "").strip() or None
        now = time.time()
        expires = now + max(30.0, min(float(expires_in_s), 24 * 3600.0))
        command_id = f"cmd_{uuid.uuid4().hex[:20]}"
        approval_id = f"apr_{uuid.uuid4().hex[:20]}" if requires_approval else ""
        initial_status = (PENDING_APPROVAL if requires_approval else
                          (QUEUED if device.get("state") != OFFLINE else WAITING_FOR_DEVICE))

        with self._connection() as conn:
            if key is not None:
                existing = conn.execute(
                    "SELECT id FROM commands WHERE device_id=? AND idempotency_key=?",
                    (device_id, key)).fetchone()
                if existing is not None:
                    return self.command(existing["id"])
            try:
                conn.execute(
                    "INSERT INTO commands(id,device_id,idempotency_key,action,payload,"
                    "category,status,created,expires,approval_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (command_id, device_id, key, action[:120],
                     payload_text, category, initial_status, now, expires, approval_id))
                if requires_approval:
                    conn.execute(
                        "INSERT INTO approvals(id,command_id,requesting_device,target_device,"
                        "action,category,summary,state,created,expires) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (approval_id, command_id, requesting_device[:80], device_id, action,
                         category, self._clean(payload.get("summary") or action, 240),
                         APPROVAL_PENDING, now, expires))
            except sqlite3.IntegrityError:
                # Lost a race against a concurrent identical enqueue.
                existing = conn.execute(
                    "SELECT id FROM commands WHERE device_id=? AND idempotency_key=?",
                    (device_id, key)).fetchone()
                if existing is not None:
                    return self.command(existing["id"])
                raise
        self._activity("command_created", requesting_device=requesting_device,
                       target_device=device_id, command_id=command_id,
                       permission_level=category,
                       approval_result=APPROVAL_PENDING if requires_approval else "not_required",
                       execution_result=initial_status, summary=action)
        return Command(id=command_id, device_id=device_id, action=action,
                       payload=payload, status=initial_status, category=category, created=now,
                       expires=expires, approval_id=approval_id)

    def claim(self, device_id: str, *, limit: int = 5) -> list[Command]:
        """The agent pulls its queued work and marks it IN_FLIGHT."""
        self._expire_stale()
        if not self.remote_control_enabled():
            return []
        device = self.device_state(device_id)
        if (not device.get("known") or device.get("approval_state") != APPROVED_DEVICE or
                device.get("revoked")):
            return []
        now = time.time()
        claimed: list[Command] = []
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT id FROM commands WHERE device_id=? AND status IN (?,?) "
                "ORDER BY created LIMIT ?",
                (device_id, QUEUED, WAITING_FOR_DEVICE,
                 max(1, min(int(limit), 25)))).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE commands SET status=?, claimed=? WHERE id=? AND status IN (?,?)",
                    (IN_FLIGHT, now, row["id"], QUEUED, WAITING_FOR_DEVICE))
        for row in rows:
            command = self.command(row["id"])
            if command is not None:
                claimed.append(command)
        return claimed

    def acknowledge(self, command_id: str, device_id: str) -> bool:
        """The agent confirms receipt. This is DELIVERY, not completion."""
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE commands SET status=?, acknowledged=? "
                "WHERE id=? AND device_id=? AND status=?",
                (ACKNOWLEDGED, time.time(), command_id, device_id, IN_FLIGHT)).rowcount
        if changed:
            self._activity("command_acknowledged", target_device=device_id,
                           command_id=command_id, execution_result=ACKNOWLEDGED)
        return bool(changed)

    def complete(self, command_id: str, device_id: str, *, ok: bool,
                 result: dict[str, Any] | None = None, error: str = "") -> bool:
        """The agent reports what actually happened."""
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE commands SET status=?, finished=?, result=?, error=? "
                "WHERE id=? AND device_id=? AND status IN (?,?)",
                (DONE if ok else FAILED, time.time(),
                 json.dumps(result or {})[:16000], (error or "")[:1000],
                 command_id, device_id, IN_FLIGHT, ACKNOWLEDGED)).rowcount
            if changed:
                conn.execute(
                    "UPDATE approvals SET state=?,decided=? WHERE command_id=? AND state=?",
                    (APPROVAL_EXECUTED if ok else APPROVAL_FAILED, time.time(),
                     command_id, APPROVAL_APPROVED))
        if changed:
            self._activity("command_completed" if ok else "command_failed",
                           target_device=device_id, command_id=command_id,
                           execution_result=DONE if ok else FAILED,
                           failure_reason="" if ok else error)
        return bool(changed)

    def command(self, command_id: str) -> Command | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
        if row is None:
            return None
        result: dict[str, Any] | None = None
        if row["result"]:
            try:
                result = json.loads(row["result"])
            except json.JSONDecodeError:
                result = {"raw": row["result"][:500]}
        if row["error"]:
            result = dict(result or {})
            result["error"] = row["error"]
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            payload = {}
        return Command(id=row["id"], device_id=row["device_id"], action=row["action"],
                       payload=payload, status=row["status"], category=row["category"],
                       created=row["created"], result=result,
                       expires=float(row["expires"] or 0),
                       approval_id=str(row["approval_id"] or ""))

    def cancel(self, command_id: str, *, requesting_device: str = "") -> bool:
        now = time.time()
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE commands SET status=?,finished=?,error=? WHERE id=? "
                "AND status IN (?,?,?)",
                (CANCELLED, now, "cancelled by owner", command_id,
                 QUEUED, WAITING_FOR_DEVICE, PENDING_APPROVAL)).rowcount
            if changed:
                conn.execute(
                    "UPDATE approvals SET state=?,decided=?,decision_evidence=? "
                    "WHERE command_id=? AND state=?",
                    (APPROVAL_CANCELLED, now, "owner cancelled", command_id,
                     APPROVAL_PENDING))
        if changed:
            self._activity("command_cancelled", requesting_device=requesting_device,
                           command_id=command_id, execution_result=CANCELLED)
        return bool(changed)

    def approvals(self, *, state: str = "", limit: int = 100) -> list[dict[str, Any]]:
        self._expire_stale()
        query = "SELECT * FROM approvals"
        args: list[Any] = []
        if state:
            query += " WHERE state=?"
            args.append(str(state).casefold())
        query += " ORDER BY created DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self._connection() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [dict(row) for row in rows]

    def decide_approval(self, approval_id: str, *, approve: bool,
                        requesting_device: str = "", evidence: str = "") -> bool:
        self._expire_stale()
        now = time.time()
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if row is None or row["state"] != APPROVAL_PENDING or row["expires"] <= now:
                return False
            decision = APPROVAL_APPROVED if approve else APPROVAL_DENIED
            conn.execute(
                "UPDATE approvals SET state=?,decided=?,decision_evidence=? WHERE id=?",
                (decision, now, self._clean(evidence or "owner decision", 200), approval_id))
            if approve:
                device = conn.execute(
                    "SELECT last_heartbeat,revoked,approval_state FROM devices WHERE device_id=?",
                    (row["target_device"],)).fetchone()
                online = bool(device and not device["revoked"] and
                              device["approval_state"] == APPROVED_DEVICE and
                              device["last_heartbeat"] > now - HEARTBEAT_GRACE_S)
                next_status = QUEUED if online else WAITING_FOR_DEVICE
                conn.execute(
                    "UPDATE commands SET status=? WHERE id=? AND status=?",
                    (next_status, row["command_id"], PENDING_APPROVAL))
            else:
                conn.execute(
                    "UPDATE commands SET status=?,finished=?,error=? WHERE id=? AND status=?",
                    (REJECTED, now, "owner denied approval", row["command_id"],
                     PENDING_APPROVAL))
        self._activity("approval_decided", requesting_device=requesting_device,
                       target_device=row["target_device"], command_id=row["command_id"],
                       permission_level=row["category"], approval_result=decision,
                       execution_result="released" if approve else REJECTED,
                       summary=row["action"])
        return True

    def recent(self, device_id: str = "", limit: int = 25) -> list[dict[str, Any]]:
        query = ("SELECT id FROM commands " +
                 ("WHERE device_id=? " if device_id else "") +
                 "ORDER BY created DESC LIMIT ?")
        safe_limit = max(1, min(int(limit), 500))
        args: tuple = (device_id, safe_limit) if device_id else (safe_limit,)
        with self._connection() as conn:
            rows = conn.execute(query, args).fetchall()
        out = []
        for row in rows:
            command = self.command(row["id"])
            if command is not None:
                out.append(command.as_dict())
        return out

    def _expire_stale(self) -> int:
        """Time out commands nobody claimed or nobody finished.

        A laptop may legitimately be asleep longer than the old 90-second
        claim timeout. Commands therefore carry an explicit owner-visible
        expiry; they wait for the device until that point, then become EXPIRED.
        """
        now = time.time()
        with self._connection() as conn:
            expired = conn.execute(
                "UPDATE commands SET status=?, finished=?, error=? "
                "WHERE status IN (?,?,?) AND expires > 0 AND expires <= ?",
                (EXPIRED, now, "command expired before execution", QUEUED,
                 WAITING_FOR_DEVICE, PENDING_APPROVAL, now)).rowcount
            conn.execute(
                "UPDATE approvals SET state=?,decided=?,decision_evidence=? "
                "WHERE state=? AND expires <= ?",
                (APPROVAL_EXPIRED, now, "approval expired", APPROVAL_PENDING, now))
            expired += conn.execute(
                "UPDATE commands SET status=?, finished=?, error=? "
                "WHERE status IN (?,?) AND claimed < ?",
                (TIMEOUT, now, "device claimed but never reported a result",
                 IN_FLIGHT, ACKNOWLEDGED, now - RESULT_TIMEOUT_S)).rowcount
        return int(expired)

    def stats(self) -> dict[str, Any]:
        self._expire_stale()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM commands GROUP BY status").fetchall()
        return {"by_status": {r["status"]: r["n"] for r in rows},
                "devices": len(self.devices()),
                "remote_control_enabled": self.remote_control_enabled(),
                "pending_approvals": len(self.approvals(state=APPROVAL_PENDING))}


_link: DeviceLink | None = None
_link_lock = threading.Lock()


def get_link() -> DeviceLink:
    global _link
    with _link_lock:
        if _link is None:
            _link = DeviceLink()
        return _link


def reset_for_tests(db_path: Path | None = None) -> DeviceLink:
    global _link
    with _link_lock:
        _link = DeviceLink(db_path)
        return _link
