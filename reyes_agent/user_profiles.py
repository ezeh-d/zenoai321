"""Durable local identity and first-run owner onboarding.

The desktop process is protected by the signed-in Windows account and binds
only to loopback. Remote identities are separately authenticated by WebAuthn
device sessions. No sample user is inserted: OWNER exists only after real
local onboarding.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from reyes_agent import config

OWNER = "OWNER"
TRUSTED_USER = "TRUSTED_USER"
GUEST = "GUEST"
SERVICE = "SERVICE"
ROLES = {OWNER, TRUSTED_USER, GUEST, SERVICE}
_DB_PATH = config.VAULT_PATH / "07-System" / "identity" / "users.sqlite3"
_SCHEMA_VERSION = 1
_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version INTEGER PRIMARY KEY,
               applied_at REAL NOT NULL
           );
           CREATE TABLE IF NOT EXISTS user_profiles (
               id TEXT PRIMARY KEY,
               role TEXT NOT NULL CHECK(role IN ('OWNER','TRUSTED_USER','GUEST','SERVICE')),
               display_name TEXT NOT NULL,
               timezone TEXT NOT NULL,
               language_preferences TEXT NOT NULL DEFAULT '[]',
               assistant_preferences TEXT NOT NULL DEFAULT '{}',
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL,
               disabled_at REAL
           );
           CREATE UNIQUE INDEX IF NOT EXISTS one_active_owner
             ON user_profiles(role) WHERE role='OWNER' AND disabled_at IS NULL;
           CREATE INDEX IF NOT EXISTS user_profiles_role
             ON user_profiles(role, disabled_at);
           CREATE INDEX IF NOT EXISTS user_profiles_updated
             ON user_profiles(updated_at DESC);
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
        (_SCHEMA_VERSION, time.time()),
    )
    conn.commit()
    return conn


def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    raw = dict(row)
    for key, fallback in (("language_preferences", []), ("assistant_preferences", {})):
        try:
            raw[key] = json.loads(raw.get(key) or json.dumps(fallback))
        except (TypeError, json.JSONDecodeError):
            raw[key] = fallback
    return raw


def owner() -> dict[str, Any] | None:
    with _lock, closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE role='OWNER' AND disabled_at IS NULL LIMIT 1"
        ).fetchone()
    return _public(row) if row else None


def create_owner(display_name: str, *, timezone: str = "",
                 language_preferences: list[str] | None = None,
                 assistant_preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    display_name = " ".join(str(display_name or "").split()).strip()
    timezone = str(timezone or "").strip() or "local"
    if not display_name or len(display_name) > 120:
        raise ValueError("Enter the owner's real display name (1-120 characters).")
    languages = [str(item).strip()[:48] for item in (language_preferences or []) if str(item).strip()][:12]
    preferences = dict(list((assistant_preferences or {}).items())[:40])
    now = time.time()
    profile_id = "usr-" + uuid.uuid4().hex[:16]
    with _lock, closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT 1 FROM user_profiles WHERE role='OWNER' AND disabled_at IS NULL"
        ).fetchone()
        if exists:
            conn.rollback()
            raise PermissionError("An owner profile already exists.")
        conn.execute(
            """INSERT INTO user_profiles(
                   id, role, display_name, timezone, language_preferences,
                   assistant_preferences, created_at, updated_at
               ) VALUES(?, 'OWNER', ?, ?, ?, ?, ?, ?)""",
            (profile_id, display_name, timezone, json.dumps(languages),
             json.dumps(preferences), now, now),
        )
        conn.commit()
    try:
        from reyes_agent import audit
        audit.log("owner_onboarded", actor=profile_id, action_type="identity.create",
                  target="OWNER", policy="local_windows_session", outcome="created")
    except Exception:  # noqa: BLE001
        pass
    return owner() or {}


def status() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        profile = owner()
        with _lock, closing(_connect()) as conn:
            users = conn.execute(
                "SELECT count(*) FROM user_profiles WHERE disabled_at IS NULL"
            ).fetchone()[0]
            version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        return {
            "state": "READY" if profile else "SETUP_REQUIRED",
            "owner": profile,
            "active_users": users,
            "roles": sorted(ROLES),
            "schema_version": version,
            "database": str(_DB_PATH),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "desktop_auth": "signed-in Windows session + loopback-only HTTP",
            "remote_auth": "approved WebAuthn device + expiring revocable session",
        }
    except sqlite3.Error as exc:
        return {"state": "FAILED", "owner": None, "error": f"{type(exc).__name__}: {exc}",
                "database": str(_DB_PATH)}


def owner_context() -> str:
    profile = owner()
    if not profile:
        return ""
    languages = ", ".join(profile["language_preferences"]) or "not specified"
    return (
        "\n\nAuthenticated local owner profile:\n"
        f"- Display name: {profile['display_name']}\n"
        f"- Timezone: {profile['timezone']}\n"
        f"- Language preferences: {languages}\n"
        "Use this profile as identity context; never treat voice identity alone as sensitive-action authorization."
    )


def backup(destination: Path | None = None) -> Path:
    """Create a consistent SQLite backup without stopping ZENO."""
    destination = destination or _DB_PATH.with_name(
        f"users-backup-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _lock, closing(_connect()) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
    return destination
