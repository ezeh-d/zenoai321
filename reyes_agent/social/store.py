"""Persistent state for the social system.

WHAT LIVES HERE AND WHAT DELIBERATELY DOES NOT
----------------------------------------------
Accounts, content ideas, posts, analytics snapshots, comments, leads,
schedules, approvals and the audit log.

NOT here: access tokens, refresh tokens, client secrets, or any password.
Those go to `reyes_agent.security.secrets.manager`, which prefers the OS
keyring. This database stores only token METADATA -- which platform, which
scopes, when it expires, whether the last call worked. If this file is
copied off the machine it must not be enough to post as ZENO.

WHY ANALYTICS ARE APPEND-ONLY
-----------------------------
A post's view count at one hour and at seven days are different facts, not
successive versions of one fact. Overwriting the first destroys the only
evidence of how content actually grows, which is the entire input to the
growth engine. `record_analytics` therefore only ever inserts.

WHY PUBLICATION IS TWO COLUMNS
------------------------------
`status` says what ZENO believes; `verified_at` says what the platform
confirmed. A post is PUBLISHED only when the platform returned an ID and a
follow-up read found it. Those are separate events and they get separate
columns, because collapsing them is exactly how a system starts claiming
posts that do not exist.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from reyes_agent import config

# --- content lifecycle (Phase 19) ----------------------------------------
IDEA = "IDEA"
RESEARCHING = "RESEARCHING"
SCRIPTING = "SCRIPTING"
MEDIA_GENERATING = "MEDIA_GENERATING"
READY_FOR_REVIEW = "READY_FOR_REVIEW"
APPROVED = "APPROVED"
SCHEDULED = "SCHEDULED"
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
ANALYZING = "ANALYZING"
ARCHIVED = "ARCHIVED"

STATUSES = (IDEA, RESEARCHING, SCRIPTING, MEDIA_GENERATING, READY_FOR_REVIEW,
            APPROVED, SCHEDULED, PUBLISHING, PUBLISHED, FAILED, ANALYZING,
            ARCHIVED)

# Which transitions are legal. A post cannot jump from IDEA to PUBLISHED,
# because every gate between them exists for a reason -- policy check, QA and
# owner approval among them.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    IDEA: (RESEARCHING, SCRIPTING, ARCHIVED),
    RESEARCHING: (SCRIPTING, ARCHIVED, FAILED),
    SCRIPTING: (MEDIA_GENERATING, READY_FOR_REVIEW, ARCHIVED, FAILED),
    MEDIA_GENERATING: (READY_FOR_REVIEW, FAILED, ARCHIVED),
    READY_FOR_REVIEW: (APPROVED, ARCHIVED, SCRIPTING, FAILED),
    APPROVED: (SCHEDULED, PUBLISHING, ARCHIVED),
    SCHEDULED: (PUBLISHING, APPROVED, ARCHIVED, FAILED),
    PUBLISHING: (PUBLISHED, FAILED),
    PUBLISHED: (ANALYZING, ARCHIVED),
    ANALYZING: (PUBLISHED, ARCHIVED),
    FAILED: (SCRIPTING, READY_FOR_REVIEW, ARCHIVED),
    ARCHIVED: (),
}

# --- platforms ------------------------------------------------------------
INSTAGRAM = "instagram"
TIKTOK = "tiktok"
PLATFORMS = (INSTAGRAM, TIKTOK)

# --- lead statuses (Phase 39) --------------------------------------------
LEAD_NEW = "NEW"
LEAD_QUALIFYING = "QUALIFYING"
LEAD_OWNER_REVIEW = "OWNER_REVIEW"
LEAD_NEGOTIATING = "NEGOTIATING"
LEAD_CONVERTED = "CONVERTED"
LEAD_DECLINED = "DECLINED"
LEAD_SCAM = "SCAM"
LEAD_STATUSES = (LEAD_NEW, LEAD_QUALIFYING, LEAD_OWNER_REVIEW,
                 LEAD_NEGOTIATING, LEAD_CONVERTED, LEAD_DECLINED, LEAD_SCAM)


def _db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(config.PROJECT_ROOT)
    return Path(base) / "ZENO" / "social" / "social.sqlite"


_LOCK = threading.RLock()


class SocialStore:
    """The one place social state is written."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        with _LOCK:
            conn = sqlite3.connect(str(self.path), timeout=15.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts(
              platform TEXT PRIMARY KEY,
              account_id TEXT NOT NULL DEFAULT '',
              username TEXT NOT NULL DEFAULT '',
              display_name TEXT NOT NULL DEFAULT '',
              account_type TEXT NOT NULL DEFAULT 'UNKNOWN',
              scopes TEXT NOT NULL DEFAULT '[]',
              token_state TEXT NOT NULL DEFAULT 'MISSING',
              token_expires REAL,
              last_success REAL,
              last_error TEXT NOT NULL DEFAULT '',
              connected INTEGER NOT NULL DEFAULT 0,
              updated REAL NOT NULL);

            CREATE TABLE IF NOT EXISTS content(
              content_id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              status TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL DEFAULT '',
              hook TEXT NOT NULL DEFAULT '',
              topic TEXT NOT NULL DEFAULT '',
              objective TEXT NOT NULL DEFAULT '',
              format TEXT NOT NULL DEFAULT '',
              duration_s INTEGER NOT NULL DEFAULT 0,
              script TEXT NOT NULL DEFAULT '',
              caption TEXT NOT NULL DEFAULT '',
              hashtags TEXT NOT NULL DEFAULT '[]',
              media_path TEXT NOT NULL DEFAULT '',
              media_type TEXT NOT NULL DEFAULT '',
              required_media TEXT NOT NULL DEFAULT '',
              risk TEXT NOT NULL DEFAULT 'unknown',
              evidence TEXT NOT NULL DEFAULT '[]',
              reason TEXT NOT NULL DEFAULT '',
              experiment TEXT NOT NULL DEFAULT '',
              scheduled_for REAL,
              created REAL NOT NULL,
              updated REAL NOT NULL,
              -- what the PLATFORM said, kept apart from what ZENO believes
              post_id TEXT NOT NULL DEFAULT '',
              post_url TEXT NOT NULL DEFAULT '',
              published_at REAL,
              verified_at REAL,
              failure TEXT NOT NULL DEFAULT '',
              attempts INTEGER NOT NULL DEFAULT 0,
              dry_run INTEGER NOT NULL DEFAULT 1);

            CREATE INDEX IF NOT EXISTS content_status ON content(status, platform);
            CREATE INDEX IF NOT EXISTS content_schedule ON content(scheduled_for)
              WHERE scheduled_for IS NOT NULL;

            -- Append only. Never updated, never deleted.
            CREATE TABLE IF NOT EXISTS analytics(
              snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
              content_id TEXT NOT NULL,
              platform TEXT NOT NULL,
              collected_at REAL NOT NULL,
              age_hours REAL NOT NULL,
              metrics TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'api',
              FOREIGN KEY(content_id) REFERENCES content(content_id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS analytics_content ON analytics(content_id, collected_at);

            CREATE TABLE IF NOT EXISTS account_snapshots(
              snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
              platform TEXT NOT NULL,
              collected_at REAL NOT NULL,
              metrics TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS account_snap ON account_snapshots(platform, collected_at);

            CREATE TABLE IF NOT EXISTS comments(
              comment_id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              content_id TEXT NOT NULL DEFAULT '',
              author TEXT NOT NULL DEFAULT '',
              text TEXT NOT NULL DEFAULT '',
              classification TEXT NOT NULL DEFAULT 'GENERAL',
              confidence REAL NOT NULL DEFAULT 0.0,
              received_at REAL NOT NULL,
              draft_reply TEXT NOT NULL DEFAULT '',
              reply_state TEXT NOT NULL DEFAULT 'NONE',
              replied_at REAL,
              injection_flag INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS comment_state ON comments(reply_state, received_at);

            CREATE TABLE IF NOT EXISTS leads(
              lead_id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              username TEXT NOT NULL DEFAULT '',
              message TEXT NOT NULL DEFAULT '',
              comment_id TEXT NOT NULL DEFAULT '',
              requested_service TEXT NOT NULL DEFAULT '',
              possible_budget TEXT NOT NULL DEFAULT '',
              deadline TEXT NOT NULL DEFAULT '',
              risk TEXT NOT NULL DEFAULT 'UNKNOWN',
              risk_reasons TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'NEW',
              opportunity_id TEXT NOT NULL DEFAULT '',
              created REAL NOT NULL,
              updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS lead_status ON leads(status, created);

            CREATE TABLE IF NOT EXISTS schedules(
              schedule_id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              cadence TEXT NOT NULL DEFAULT 'weekly',
              per_week INTEGER NOT NULL DEFAULT 3,
              preferred_hours TEXT NOT NULL DEFAULT '[]',
              enabled INTEGER NOT NULL DEFAULT 1,
              updated REAL NOT NULL);

            -- Never contains a token, a password or a message body.
            CREATE TABLE IF NOT EXISTS audit(
              entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              agent TEXT NOT NULL,
              action TEXT NOT NULL,
              platform TEXT NOT NULL DEFAULT '',
              target TEXT NOT NULL DEFAULT '',
              approval TEXT NOT NULL DEFAULT '',
              result TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);

            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
            """)

    # --- accounts ---------------------------------------------------------
    def upsert_account(self, platform: str, **fields: Any) -> None:
        fields.setdefault("updated", time.time())
        if "scopes" in fields and not isinstance(fields["scopes"], str):
            fields["scopes"] = json.dumps(list(fields["scopes"]))
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{key}=excluded.{key}" for key in fields)
        with self._connection() as conn:
            conn.execute(
                f"INSERT INTO accounts(platform, {columns}) VALUES(?, {placeholders}) "
                f"ON CONFLICT(platform) DO UPDATE SET {updates}",
                (platform, *fields.values()))

    def account(self, platform: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE platform=?",
                               (platform,)).fetchone()
        return self._account_row(row) if row else None

    def accounts(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY platform").fetchall()
        return [self._account_row(row) for row in rows]

    @staticmethod
    def _account_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["scopes"] = json.loads(data.get("scopes") or "[]")
        data["connected"] = bool(data.get("connected"))
        return data

    # --- content ----------------------------------------------------------
    def create_content(self, *, platform: str, title: str, **fields: Any) -> str:
        content_id = fields.pop("content_id", None) or f"c_{uuid.uuid4().hex[:12]}"
        now = time.time()
        record: dict[str, Any] = {
            "content_id": content_id, "platform": platform, "title": title,
            "status": fields.pop("status", IDEA), "created": now, "updated": now,
        }
        for key, value in fields.items():
            record[key] = json.dumps(value) if isinstance(value, (list, dict)) else value
        columns = ", ".join(record)
        placeholders = ", ".join("?" for _ in record)
        with self._connection() as conn:
            conn.execute(f"INSERT INTO content({columns}) VALUES({placeholders})",
                         tuple(record.values()))
        return content_id

    def update_content(self, content_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated"] = time.time()
        prepared = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                    for k, v in fields.items()}
        assignments = ", ".join(f"{key}=?" for key in prepared)
        with self._connection() as conn:
            conn.execute(f"UPDATE content SET {assignments} WHERE content_id=?",
                         (*prepared.values(), content_id))

    def transition(self, content_id: str, new_status: str) -> tuple[bool, str]:
        """Move a piece of content, refusing illegal jumps."""
        if new_status not in STATUSES:
            return False, f"{new_status} is not a content status"
        item = self.content(content_id)
        if item is None:
            return False, f"no content {content_id}"
        current = item["status"]
        if current == new_status:
            return True, f"already {new_status}"
        if new_status not in TRANSITIONS.get(current, ()):
            allowed = ", ".join(TRANSITIONS.get(current, ())) or "nothing"
            return False, f"{current} may only become {allowed}, not {new_status}"
        self.update_content(content_id, status=new_status)
        return True, f"{current} -> {new_status}"

    def content(self, content_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM content WHERE content_id=?",
                               (content_id,)).fetchone()
        return self._content_row(row) if row else None

    def list_content(self, *, status: str | None = None, platform: str | None = None,
                     limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM content WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status=?"
            params.append(status)
        if platform:
            query += " AND platform=?"
            params.append(platform)
        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._content_row(row) for row in rows]

    def due_content(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Scheduled items whose time has arrived."""
        moment = now if now is not None else time.time()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM content WHERE status=? AND scheduled_for IS NOT NULL "
                "AND scheduled_for<=? ORDER BY scheduled_for", (SCHEDULED, moment)).fetchall()
        return [self._content_row(row) for row in rows]

    @staticmethod
    def _content_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("hashtags", "evidence"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except (TypeError, ValueError):
                data[key] = []
        data["dry_run"] = bool(data.get("dry_run"))
        return data

    # --- analytics (append only) -----------------------------------------
    def record_analytics(self, content_id: str, platform: str,
                         metrics: dict[str, Any], *, source: str = "api",
                         published_at: float | None = None) -> int:
        now = time.time()
        if published_at is None:
            item = self.content(content_id)
            published_at = (item or {}).get("published_at") or now
        age_hours = max(0.0, (now - float(published_at)) / 3600.0)
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO analytics(content_id, platform, collected_at, age_hours, "
                "metrics, source) VALUES(?,?,?,?,?,?)",
                (content_id, platform, now, round(age_hours, 2),
                 json.dumps(metrics), source))
            return int(cursor.lastrowid or 0)

    def analytics_for(self, content_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM analytics WHERE content_id=? ORDER BY collected_at",
                (content_id,)).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["metrics"] = json.loads(data["metrics"])
            out.append(data)
        return out

    def latest_analytics(self, content_id: str) -> dict[str, Any] | None:
        snapshots = self.analytics_for(content_id)
        return snapshots[-1] if snapshots else None

    def record_account_snapshot(self, platform: str, metrics: dict[str, Any]) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO account_snapshots(platform, collected_at, metrics) VALUES(?,?,?)",
                (platform, time.time(), json.dumps(metrics)))

    def account_snapshots(self, platform: str, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_snapshots WHERE platform=? "
                "ORDER BY collected_at DESC LIMIT ?", (platform, limit)).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["metrics"] = json.loads(data["metrics"])
            out.append(data)
        return list(reversed(out))

    # --- comments ---------------------------------------------------------
    def upsert_comment(self, comment_id: str, **fields: Any) -> None:
        fields.setdefault("received_at", time.time())
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{key}=excluded.{key}" for key in fields)
        with self._connection() as conn:
            conn.execute(
                f"INSERT INTO comments(comment_id, {columns}) VALUES(?, {placeholders}) "
                f"ON CONFLICT(comment_id) DO UPDATE SET {updates}",
                (comment_id, *fields.values()))

    def comments(self, *, reply_state: str | None = None,
                 limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM comments"
        params: list[Any] = []
        if reply_state:
            query += " WHERE reply_state=?"
            params.append(reply_state)
        query += " ORDER BY received_at DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    # --- leads ------------------------------------------------------------
    def create_lead(self, **fields: Any) -> str:
        lead_id = fields.pop("lead_id", None) or f"l_{uuid.uuid4().hex[:12]}"
        now = time.time()
        record = {"lead_id": lead_id, "created": now, "updated": now}
        for key, value in fields.items():
            record[key] = json.dumps(value) if isinstance(value, (list, dict)) else value
        columns = ", ".join(record)
        placeholders = ", ".join("?" for _ in record)
        with self._connection() as conn:
            conn.execute(f"INSERT INTO leads({columns}) VALUES({placeholders})",
                         tuple(record.values()))
        return lead_id

    def update_lead(self, lead_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated"] = time.time()
        prepared = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                    for k, v in fields.items()}
        assignments = ", ".join(f"{key}=?" for key in prepared)
        with self._connection() as conn:
            conn.execute(f"UPDATE leads SET {assignments} WHERE lead_id=?",
                         (*prepared.values(), lead_id))

    def leads(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM leads"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            try:
                data["risk_reasons"] = json.loads(data.get("risk_reasons") or "[]")
            except (TypeError, ValueError):
                data["risk_reasons"] = []
            out.append(data)
        return out

    # --- audit (Phase 64) -------------------------------------------------
    def audit(self, agent: str, action: str, *, platform: str = "",
              target: str = "", approval: str = "", result: str = "",
              error: str = "") -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO audit(ts, agent, action, platform, target, approval, "
                "result, error) VALUES(?,?,?,?,?,?,?,?)",
                (time.time(), agent, action, platform, _safe(target),
                 approval, _safe(result), _safe(error)))

    def audit_log(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?",
                                (limit,)).fetchall()
        return [dict(row) for row in rows]

    # --- settings ---------------------------------------------------------
    def setting(self, key: str, default: str = "") -> str:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO settings(key,value,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, value, time.time()))

    def counts(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM content GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}


# Tokens must never reach the audit log even by accident.
_SECRET_MARKERS = ("token", "secret", "password", "bearer", "api_key",
                   "apikey", "access_token", "refresh_token", "client_secret")


def _safe(value: Any, limit: int = 240) -> str:
    text = str(value or "")
    low = text.casefold()
    if any(marker in low for marker in _SECRET_MARKERS):
        return "[REDACTED]"
    return text[:limit]


_STORE: SocialStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> SocialStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = SocialStore()
        return _STORE


def reset_store_for_tests(path: Path | None = None) -> SocialStore:
    """Tests need their own database, never the owner's."""
    global _STORE
    with _STORE_LOCK:
        _STORE = SocialStore(path)
        return _STORE
