"""Encrypted, bounded media exchange for ZENO Anywhere voice turns.

The command queue deliberately accepts small JSON objects only.  Voice audio
therefore travels through this separate store and a command carries only an
opaque ``media_id``.  Every blob is bound to all three principals involved:

* the approved browser device that recorded it;
* the registered Windows device that may read it; and
* the command that caused the read/write.

Raw audio is encrypted with AES-256-GCM before SQLite sees it.  Production
must provide ``ZENO_MEDIA_ENCRYPTION_KEY`` as a URL-safe base64 encoded
32-byte key.  There is intentionally no machine-derived fallback: silently
using a predictable key would only make encrypted-at-rest a label.
"""

from __future__ import annotations

import base64
import contextlib
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from reyes_agent import config

INPUT_MIME_TYPES = frozenset({
    "audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav",
})
OUTPUT_MIME_TYPES = frozenset({"audio/mpeg", "audio/mp3", "audio/ogg"})
MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_TTL_S = 15 * 60.0
MAX_TTL_S = 60 * 60.0
MAX_RECORDS = 128
MAX_STORED_BYTES = 128 * 1024 * 1024

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DB = Path(os.environ.get(
    "ZENO_MEDIA_STORE_DB", os.environ.get("ZENO_MEDIA_DB",
    str(Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) /
        "ZENO" / "auth" / "anywhere-media.sqlite"),
)))


class MediaStoreError(RuntimeError):
    """Base error safe for an API layer to translate without leaking data."""


class MediaStoreUnavailable(MediaStoreError):
    pass


class MediaNotFound(MediaStoreError):
    pass


class MediaAccessDenied(MediaStoreError):
    pass


class MediaCapacityExceeded(MediaStoreError):
    pass


@dataclass(frozen=True)
class MediaBlob:
    data: bytes
    content_type: str
    expires_at: float


def generate_key() -> str:
    """Return a configuration-ready random key without persisting it."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _decode_key(value: str) -> bytes:
    clean = str(value or "").strip()
    if not clean:
        raise MediaStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY is required for Anywhere voice media.")
    try:
        padded = clean + "=" * ((4 - len(clean) % 4) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - one stable configuration error
        raise MediaStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY must be URL-safe base64.") from exc
    if len(key) != 32:
        raise MediaStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _normalise_mime(value: str, allowed: frozenset[str]) -> str:
    mime = str(value or "").split(";", 1)[0].strip().casefold()
    if mime not in allowed:
        raise ValueError(f"Unsupported audio content type: {mime or 'missing'}")
    return mime


def _safe_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not _SAFE_ID.fullmatch(clean):
        raise ValueError(f"Invalid {label}.")
    return clean


class MediaStore:
    def __init__(self, db_path: Path | None = None, *, key: bytes | None = None,
                 now=time.time, max_records: int = MAX_RECORDS,
                 max_stored_bytes: int = MAX_STORED_BYTES) -> None:
        self.path = Path(db_path or _DB)
        configured_key = key if key is not None else _decode_key(
            os.environ.get("ZENO_MEDIA_ENCRYPTION_KEY", ""))
        if len(configured_key) != 32:
            raise MediaStoreUnavailable("The media encryption key must be 32 bytes.")
        self._cipher = AESGCM(bytes(configured_key))
        self._now = now
        self._max_records = max(1, int(max_records))
        self._max_stored_bytes = max(MAX_INPUT_BYTES, int(max_stored_bytes))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
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

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS media ("
                "id TEXT PRIMARY KEY, browser_device TEXT NOT NULL, "
                "target_device TEXT NOT NULL, command_id TEXT NOT NULL DEFAULT '', "
                "input_mime TEXT NOT NULL, input_nonce BLOB, input_data BLOB, "
                "output_mime TEXT NOT NULL DEFAULT '', output_nonce BLOB, output_data BLOB, "
                "created REAL NOT NULL, expires REAL NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_expiry ON media(expires)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_command ON media(command_id)")

    @staticmethod
    def _aad(media_id: str, direction: str, browser_device: str,
             target_device: str, mime: str) -> bytes:
        return "\x1f".join((media_id, direction, browser_device,
                             target_device, mime)).encode("utf-8")

    def _encrypt(self, data: bytes, *, media_id: str, direction: str,
                 browser_device: str, target_device: str,
                 mime: str) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        encrypted = self._cipher.encrypt(
            nonce, data,
            self._aad(media_id, direction, browser_device, target_device, mime),
        )
        return nonce, encrypted

    def _decrypt(self, nonce: bytes, encrypted: bytes, *, media_id: str,
                 direction: str, browser_device: str, target_device: str,
                 mime: str) -> bytes:
        try:
            return self._cipher.decrypt(
                nonce, encrypted,
                self._aad(media_id, direction, browser_device, target_device, mime),
            )
        except Exception as exc:  # noqa: BLE001 - never expose crypto internals
            raise MediaStoreError("Stored media failed integrity verification.") from exc

    def _purge_expired(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute(
            "DELETE FROM media WHERE expires<=?", (float(self._now()),)).rowcount)

    @staticmethod
    def _row_size(row: sqlite3.Row) -> int:
        return len(row["input_data"] or b"") + len(row["output_data"] or b"")

    def create_input(self, *, browser_device: str, target_device: str,
                     data: bytes, content_type: str,
                     ttl_s: float = DEFAULT_TTL_S) -> str:
        browser = _safe_id(browser_device, "browser device id")
        target = _safe_id(target_device, "target device id")
        mime = _normalise_mime(content_type, INPUT_MIME_TYPES)
        payload = bytes(data or b"")
        if not payload:
            raise ValueError("Voice audio is empty.")
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError(f"Voice audio exceeds {MAX_INPUT_BYTES} bytes.")
        ttl = max(30.0, min(float(ttl_s), MAX_TTL_S))
        now = float(self._now())
        media_id = f"med_{secrets.token_hex(16)}"
        nonce, encrypted = self._encrypt(
            payload, media_id=media_id, direction="input",
            browser_device=browser, target_device=target, mime=mime)

        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            usage = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(COALESCE(LENGTH(input_data),0)+"
                "COALESCE(LENGTH(output_data),0)),0) AS bytes FROM media").fetchone()
            if int(usage["n"] or 0) >= self._max_records:
                raise MediaCapacityExceeded("Too many voice clips are waiting for expiry.")
            if int(usage["bytes"] or 0) + len(encrypted) > self._max_stored_bytes:
                raise MediaCapacityExceeded("The bounded voice media store is full.")
            conn.execute(
                "INSERT INTO media(id,browser_device,target_device,input_mime,"
                "input_nonce,input_data,created,expires) VALUES(?,?,?,?,?,?,?,?)",
                (media_id, browser, target, mime, nonce, encrypted, now, now + ttl),
            )
        return media_id

    def bind_command(self, media_id: str, *, command_id: str,
                     target_device: str) -> bool:
        media = _safe_id(media_id, "media id")
        command = _safe_id(command_id, "command id")
        target = _safe_id(target_device, "target device id")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            changed = conn.execute(
                "UPDATE media SET command_id=? WHERE id=? AND target_device=? "
                "AND command_id='' AND expires>?",
                (command, media, target, float(self._now())),
            ).rowcount
        return bool(changed)

    def _bound_row(self, conn: sqlite3.Connection, media_id: str, *,
                   target_device: str, command_id: str) -> sqlite3.Row:
        media = _safe_id(media_id, "media id")
        target = _safe_id(target_device, "target device id")
        command = _safe_id(command_id, "command id")
        row = conn.execute("SELECT * FROM media WHERE id=?", (media,)).fetchone()
        if row is None or float(row["expires"]) <= float(self._now()):
            raise MediaNotFound("Voice media is missing or expired.")
        if row["target_device"] != target or row["command_id"] != command:
            raise MediaAccessDenied("Voice media is not bound to this device and command.")
        return row

    def read_input(self, media_id: str, *, target_device: str,
                   command_id: str) -> MediaBlob:
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = self._bound_row(conn, media_id, target_device=target_device,
                                  command_id=command_id)
            if not row["input_data"]:
                raise MediaNotFound("Input audio has already been released.")
            data = self._decrypt(
                row["input_nonce"], row["input_data"], media_id=row["id"],
                direction="input", browser_device=row["browser_device"],
                target_device=row["target_device"], mime=row["input_mime"])
            return MediaBlob(data, row["input_mime"], float(row["expires"]))

    def write_output(self, media_id: str, *, target_device: str,
                     command_id: str, data: bytes, content_type: str) -> None:
        mime = _normalise_mime(content_type, OUTPUT_MIME_TYPES)
        payload = bytes(data or b"")
        if not payload:
            raise ValueError("Synthesized voice audio is empty.")
        if len(payload) > MAX_OUTPUT_BYTES:
            raise ValueError(f"Synthesized voice exceeds {MAX_OUTPUT_BYTES} bytes.")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = self._bound_row(conn, media_id, target_device=target_device,
                                  command_id=command_id)
            nonce, encrypted = self._encrypt(
                payload, media_id=row["id"], direction="output",
                browser_device=row["browser_device"],
                target_device=row["target_device"], mime=mime)
            old_size = self._row_size(row)
            usage = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(LENGTH(input_data),0)+"
                "COALESCE(LENGTH(output_data),0)),0) "
                "AS bytes FROM media").fetchone()
            if int(usage["bytes"] or 0) - old_size + len(row["input_data"] or b"") + len(encrypted) > self._max_stored_bytes:
                raise MediaCapacityExceeded("The bounded voice media store is full.")
            conn.execute(
                "UPDATE media SET output_mime=?,output_nonce=?,output_data=? WHERE id=?",
                (mime, nonce, encrypted, row["id"]),
            )

    def read_output(self, media_id: str, *, browser_device: str) -> MediaBlob:
        media = _safe_id(media_id, "media id")
        browser = _safe_id(browser_device, "browser device id")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = conn.execute("SELECT * FROM media WHERE id=?", (media,)).fetchone()
            if row is None or float(row["expires"]) <= float(self._now()):
                raise MediaNotFound("Voice response is missing or expired.")
            if row["browser_device"] != browser:
                raise MediaAccessDenied("Voice response belongs to another browser device.")
            if not row["output_data"]:
                raise MediaNotFound("Voice response audio is not ready.")
            data = self._decrypt(
                row["output_nonce"], row["output_data"], media_id=row["id"],
                direction="output", browser_device=row["browser_device"],
                target_device=row["target_device"], mime=row["output_mime"])
            return MediaBlob(data, row["output_mime"], float(row["expires"]))

    def release_input(self, media_id: str, *, target_device: str,
                      command_id: str) -> bool:
        """Cryptographically discard raw input after terminal completion."""
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = self._bound_row(conn, media_id, target_device=target_device,
                                  command_id=command_id)
            changed = conn.execute(
                "UPDATE media SET input_nonce=NULL,input_data=NULL WHERE id=?",
                (row["id"],),
            ).rowcount
        return bool(changed)

    def discard(self, media_id: str) -> bool:
        media = _safe_id(media_id, "media id")
        with self._lock, self._connection() as conn:
            return bool(conn.execute("DELETE FROM media WHERE id=?", (media,)).rowcount)

    def stats(self) -> dict[str, int]:
        with self._lock, self._connection() as conn:
            purged = self._purge_expired(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(COALESCE(LENGTH(input_data),0)+"
                "COALESCE(LENGTH(output_data),0)),0) AS bytes FROM media").fetchone()
        return {"records": int(row["n"] or 0),
                "encrypted_bytes": int(row["bytes"] or 0), "purged": purged,
                "max_records": self._max_records,
                "max_stored_bytes": self._max_stored_bytes}


_store: MediaStore | None = None
_store_lock = threading.Lock()


def get_media_store() -> MediaStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = MediaStore()
        return _store


def reset_for_tests(db_path: Path | None = None, *, key: bytes | None = None,
                    now=time.time, max_records: int = MAX_RECORDS,
                    max_stored_bytes: int = MAX_STORED_BYTES) -> MediaStore:
    global _store
    with _store_lock:
        _store = MediaStore(db_path, key=key, now=now,
                            max_records=max_records,
                            max_stored_bytes=max_stored_bytes)
        return _store
