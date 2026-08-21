"""Short-lived, one-use pairing for the optional native Android companion.

The QR contains only a temporary high-entropy credential and gateway origin.
The permanent DeviceLink token is created after the credential is consumed,
returned once over HTTPS, and stored by the app in Android Keystore.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode, urlsplit

from reyes_agent import config


PAIR_TTL_S = 5 * 60.0
MAX_ACTIVE_PAIRS = 16
_DB = Path(os.environ.get(
    "ZENO_ANDROID_PAIRING_DB",
    str(Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) /
        "ZENO" / "auth" / "android-pairing.sqlite"),
))


class PairingError(RuntimeError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _gateway_origin(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Android pairing requires a credential-free HTTPS origin.")
    if parsed.path not in {"", "/"}:
        raise ValueError("Android pairing gateway must not contain an extra path.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname}{port}"


def _qr_data_uri(value: str) -> str:
    import qrcode

    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class AndroidPairingStore:
    def __init__(self, path: Path | None = None, *, now=time.time) -> None:
        self.path = Path(path or _DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA secure_delete=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS android_pairings(
                    id TEXT PRIMARY KEY,
                    browser_device TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    code_hash TEXT NOT NULL,
                    created REAL NOT NULL,
                    expires REAL NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0,
                    consumed_at REAL);
                CREATE INDEX IF NOT EXISTS idx_android_pair_code
                    ON android_pairings(code_hash,expires,consumed);
                CREATE INDEX IF NOT EXISTS idx_android_pair_expiry
                    ON android_pairings(expires);
                """
            )

    def create(self, *, browser_device: str, gateway: str) -> dict[str, Any]:
        browser = str(browser_device or "").strip()[:96]
        if not browser:
            raise ValueError("Authenticated browser device is required.")
        origin = _gateway_origin(gateway)
        credential = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(10**6):06d}"
        pair_id = f"and_{uuid.uuid4().hex[:20]}"
        now = float(self._now())
        expires = now + PAIR_TTL_S
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM android_pairings WHERE expires<=?", (now,))
            conn.execute(
                "UPDATE android_pairings SET consumed=1,consumed_at=? "
                "WHERE browser_device=? AND consumed=0",
                (now, browser),
            )
            active = int(conn.execute(
                "SELECT COUNT(*) FROM android_pairings WHERE consumed=0 AND expires>?",
                (now,),
            ).fetchone()[0])
            if active >= MAX_ACTIVE_PAIRS:
                raise PairingError("Too many Android pairings are active.")
            conn.execute(
                "INSERT INTO android_pairings(id,browser_device,token_hash,code_hash,created,expires) "
                "VALUES(?,?,?,?,?,?)",
                (pair_id, browser, _hash(credential), _hash(code), now, expires),
            )
        uri = "zeno://pair?" + urlencode({"gateway": origin, "credential": credential})
        return {
            "id": pair_id,
            "credential": credential,
            "manual_code": code,
            "expires_at": expires,
            "gateway": origin,
            "pairing_uri": uri,
            "qr_png": _qr_data_uri(uri),
        }

    def consume(self, credential: str) -> dict[str, Any]:
        supplied = str(credential or "").strip()
        if not supplied or len(supplied) > 128:
            raise PairingError("Pairing credential is invalid or expired.")
        digest = _hash(supplied)
        now = float(self._now())
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT id,browser_device FROM android_pairings "
                "WHERE (token_hash=? OR code_hash=?) AND consumed=0 AND expires>?",
                (digest, digest, now),
            ).fetchone()
            if row is None:
                raise PairingError("Pairing credential is invalid, expired, or already used.")
            changed = conn.execute(
                "UPDATE android_pairings SET consumed=1,consumed_at=? "
                "WHERE id=? AND consumed=0 AND expires>?",
                (now, row["id"], now),
            ).rowcount
            if changed != 1:
                raise PairingError("Pairing credential was already used.")
        return {"id": row["id"], "browser_device": row["browser_device"]}

    def stats(self) -> dict[str, int]:
        now = float(self._now())
        with self._connection() as conn:
            conn.execute("DELETE FROM android_pairings WHERE expires<=?", (now,))
            row = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN consumed=0 THEN 1 ELSE 0 END) AS active "
                "FROM android_pairings"
            ).fetchone()
        return {"records": int(row["total"] or 0), "active": int(row["active"] or 0)}


_store: AndroidPairingStore | None = None
_store_lock = threading.Lock()


def get_store() -> AndroidPairingStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AndroidPairingStore()
        return _store


def reset_for_tests(path: Path | None = None, *, now=time.time) -> AndroidPairingStore:
    global _store
    with _store_lock:
        _store = AndroidPairingStore(path, now=now)
        return _store
