"""A spoken or typed passphrase that approves a new browser, no PC needed.

WHY THIS EXISTS
---------------
Normally a new browser is PENDING until the owner approves it from the Windows
PC. That is the right default -- a stolen password alone must not let a new
device in. But a free tunnel hands out a new address whenever it reconnects,
and a new address is a new browser, so on this setup the owner was re-approving
constantly.

This adds an OWNER-CHOSEN unlock phrase (e.g. "john unlock"). On a pending
browser the owner types it -- or says it, and the phone's speech recognition
types it for them -- and that browser becomes trusted. It is a second secret,
separate from the login password, so an attacker needs BOTH.

SECURITY
--------
The phrase is stored only as an scrypt hash + salt, exactly like the password.
It is never logged, never returned, and never placed in a URL. Attempts are
rate-limited and an identity that fails too often is locked out, so the phrase
cannot be brute-forced. The owner can change or clear it at any time, and a
lost phone is still handled by revoking that device from the PC.

This is NOT a login bypass: unlocking requires an already-authenticated
(password-verified) session. It only replaces the "walk to the PC" approval
step with "prove you know the phrase".
"""

from __future__ import annotations

import hmac
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.auth.owner import _hash_password, _verify_password

_DB = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "auth" / "unlock.sqlite"

MAX_FAILED = 5
LOCKOUT_S = 900.0
MIN_PHRASE_LEN = 4


import re as _re

_PUNCT = _re.compile(r"[^\w\s]", _re.UNICODE)


def _normalise(phrase: str) -> str:
    """Fold spoken/typed variation to one canonical form, so the same phrase
    matches however it is punctuated. Speech-to-text sprinkles commas and full
    stops ("John, unlock."), and a person types inconsistently -- lower-case,
    strip ALL punctuation, and collapse whitespace so every rendering of
    "john unlock" compares equal."""
    text = _PUNCT.sub(" ", str(phrase or "").lower())
    return " ".join(text.split())


class UnlockPhrase:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS phrase(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    phrase_hash TEXT NOT NULL,
                    phrase_salt TEXT NOT NULL,
                    updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS failures(
                    identity TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0);
                """)

    def configured(self) -> bool:
        with self._connection() as conn:
            return conn.execute("SELECT 1 FROM phrase WHERE id=1").fetchone() is not None

    def set_phrase(self, phrase: str) -> tuple[bool, str]:
        """Set or replace the unlock phrase. Stored only as an scrypt hash."""
        normalised = _normalise(phrase)
        if len(normalised) < MIN_PHRASE_LEN:
            return False, f"The unlock phrase must be at least {MIN_PHRASE_LEN} characters."
        hashed, salt = _hash_password(normalised)
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO phrase(id,phrase_hash,phrase_salt,updated) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET phrase_hash=excluded.phrase_hash, "
                "phrase_salt=excluded.phrase_salt, updated=excluded.updated",
                (hashed, salt, time.time()))
        return True, "Unlock phrase set."

    def clear(self) -> bool:
        with self._connection() as conn:
            changed = conn.execute("DELETE FROM phrase WHERE id=1").rowcount
        return bool(changed)

    def _locked(self, identity: str) -> tuple[bool, float]:
        with self._connection() as conn:
            row = conn.execute("SELECT locked_until FROM failures WHERE identity=?",
                               (identity,)).fetchone()
        if row is None:
            return False, 0.0
        return row["locked_until"] > time.time(), float(row["locked_until"])

    def _record_failure(self, identity: str) -> None:
        now = time.time()
        with self._connection() as conn:
            row = conn.execute("SELECT count FROM failures WHERE identity=?",
                               (identity,)).fetchone()
            count = (row["count"] if row else 0) + 1
            locked = now + LOCKOUT_S if count >= MAX_FAILED else 0.0
            conn.execute(
                "INSERT INTO failures(identity,count,locked_until) VALUES(?,?,?) "
                "ON CONFLICT(identity) DO UPDATE SET count=excluded.count, "
                "locked_until=excluded.locked_until", (identity, count, locked))

    def _clear_failures(self, identity: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM failures WHERE identity=?", (identity,))

    def verify(self, phrase: str, *, identity: str = "unknown") -> tuple[bool, str]:
        """Constant-time check with lockout. Returns (ok, reason)."""
        identity = str(identity or "unknown")[:120]
        locked, until = self._locked(identity)
        if locked:
            return False, f"Too many attempts. Wait {int(until - time.time())}s."
        with self._connection() as conn:
            row = conn.execute("SELECT phrase_hash,phrase_salt FROM phrase WHERE id=1").fetchone()
        if row is None:
            return False, "No unlock phrase is set."
        ok = _verify_password(_normalise(phrase), row["phrase_hash"], row["phrase_salt"])
        if not ok:
            self._record_failure(identity)
            return False, "Incorrect unlock phrase."
        self._clear_failures(identity)
        # hmac.compare_digest already used inside _verify_password.
        return True, ""


_instance: UnlockPhrase | None = None
_instance_lock = threading.Lock()


def get_unlock() -> UnlockPhrase:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = UnlockPhrase()
        return _instance


def reset_for_tests(db_path: Path | None = None) -> UnlockPhrase:
    global _instance
    with _instance_lock:
        _instance = UnlockPhrase(db_path)
        return _instance


def status() -> dict[str, Any]:
    return {"configured": get_unlock().configured()}
