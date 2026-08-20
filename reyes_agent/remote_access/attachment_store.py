"""Encrypted, short-lived attachments for the ZENO Anywhere companion.

Phone camera captures and intentionally selected files must not be embedded in
the bounded JSON command queue.  This store keeps the bytes in a separate
AES-256-GCM encrypted SQLite database and puts only an opaque attachment ID in
the command payload.

An attachment is readable only by the registered Windows device and command
to which it was bound.  The originating browser is recorded from its verified
owner session, never from a client supplied identity field.  Records expire
quickly and can be cryptographically released as soon as processing finishes.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from reyes_agent import config


ALLOWED_MIME_TYPES = frozenset({
    # Camera and gallery images. SVG is intentionally excluded because it can
    # contain active content when rendered by a browser.
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/heic",
    # Explicit document uploads. Macro-enabled Office formats are excluded.
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv", "application/json",
})
ALLOWED_PURPOSES = frozenset({"camera", "file"})
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
DEFAULT_TTL_S = 15 * 60.0
MAX_TTL_S = 60 * 60.0
MAX_RECORDS = 64
MAX_STORED_BYTES = 128 * 1024 * 1024
MAX_FILENAME_CHARS = 160
MAX_ARCHIVE_ENTRIES = 512
MAX_ARCHIVE_EXPANDED_BYTES = 96 * 1024 * 1024

_EXTENSIONS: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
    "image/gif": frozenset({".gif"}),
    "image/heic": frozenset({".heic", ".heif"}),
    "application/pdf": frozenset({".pdf"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        frozenset({".docx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        frozenset({".xlsx"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        frozenset({".pptx"}),
    "text/plain": frozenset({".txt", ".md", ".log"}),
    "text/csv": frozenset({".csv"}),
    "application/json": frozenset({".json"}),
}

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_DB = Path(os.environ.get(
    "ZENO_ATTACHMENT_STORE_DB",
    str(Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) /
        "ZENO" / "auth" / "anywhere-attachments.sqlite"),
))


class AttachmentStoreError(RuntimeError):
    """Base error safe for an API layer to translate without data leakage."""


class AttachmentStoreUnavailable(AttachmentStoreError):
    pass


class AttachmentNotFound(AttachmentStoreError):
    pass


class AttachmentAccessDenied(AttachmentStoreError):
    pass


class AttachmentCapacityExceeded(AttachmentStoreError):
    pass


@dataclass(frozen=True)
class AttachmentBlob:
    data: bytes
    content_type: str
    filename: str
    purpose: str
    expires_at: float


def _decode_key(value: str) -> bytes:
    clean = str(value or "").strip()
    if not clean:
        raise AttachmentStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY is required for Anywhere attachments.")
    try:
        padded = clean + "=" * ((4 - len(clean) % 4) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - stable configuration error
        raise AttachmentStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY must be URL-safe base64.") from exc
    if len(key) != 32:
        raise AttachmentStoreUnavailable(
            "ZENO_MEDIA_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _safe_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not _SAFE_ID.fullmatch(clean):
        raise ValueError(f"Invalid {label}.")
    return clean


def _normalise_mime(value: str) -> str:
    mime = str(value or "").split(";", 1)[0].strip().casefold()
    if mime not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported attachment content type: {mime or 'missing'}")
    return mime


def _safe_filename(value: str) -> str:
    raw = str(value or "").strip()
    # PurePath.name does not treat a Windows backslash as a separator on every
    # host, so reject both separator styles before taking a basename.
    if (not raw or "\x00" in raw or "/" in raw or "\\" in raw or
            raw in {".", ".."} or len(raw) > MAX_FILENAME_CHARS):
        raise ValueError("Invalid attachment filename.")
    name = PurePath(raw).name.strip().rstrip(". ")
    if not name or name in {".", ".."}:
        raise ValueError("Invalid attachment filename.")
    # Keep metadata display-safe; the original device path is never accepted.
    if any(ord(ch) < 32 for ch in name):
        raise ValueError("Invalid attachment filename.")
    return name


def _safe_purpose(value: str) -> str:
    purpose = str(value or "").strip().casefold()
    if purpose not in ALLOWED_PURPOSES:
        raise ValueError("Attachment purpose must be camera or file.")
    return purpose


def _validate_payload(data: bytes, mime: str, filename: str) -> None:
    """Verify content independently of the untrusted browser MIME label."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in _EXTENSIONS[mime]:
        raise ValueError("Attachment filename does not match its content type.")

    valid_image = {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": (len(data) >= 12 and data.startswith(b"RIFF") and
                       data[8:12] == b"WEBP"),
        "image/heic": (len(data) >= 12 and data[4:8] == b"ftyp" and
                       data[8:12] in {b"heic", b"heix", b"hevc", b"hevx",
                                      b"mif1", b"msf1"}),
    }
    if mime in valid_image:
        if not valid_image[mime]:
            raise ValueError("Attachment bytes do not match the image type.")
        return
    if mime == "application/pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("Attachment bytes do not match PDF.")
        return
    if mime in {"text/plain", "text/csv", "application/json"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text attachments must be UTF-8.") from exc
        if mime == "application/json":
            try:
                json.loads(text)
            except (ValueError, TypeError) as exc:
                raise ValueError("JSON attachment is not valid JSON.") from exc
        return

    # OOXML is a ZIP container. Verify the requested Office family without
    # extracting it, reject macros, and cap both entry count and expanded size.
    expected = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            "word/document.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            "ppt/presentation.xml",
    }[mime]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = {item.filename.replace("\\", "/").casefold()
                     for item in infos}
            expanded = sum(max(0, item.file_size) for item in infos)
            if (len(infos) > MAX_ARCHIVE_ENTRIES or
                    expanded > MAX_ARCHIVE_EXPANDED_BYTES):
                raise ValueError("Office attachment exceeds safe archive limits.")
            if expected not in names:
                raise ValueError("Attachment is not the declared Office format.")
            if any("vbaproject.bin" in name or name.endswith(".exe")
                   for name in names):
                raise ValueError("Macro or executable Office content is not allowed.")
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Office attachment is not a valid OOXML document.") from exc


class AttachmentStore:
    def __init__(self, db_path: Path | None = None, *, key: bytes | None = None,
                 now=time.time, max_records: int = MAX_RECORDS,
                 max_stored_bytes: int = MAX_STORED_BYTES) -> None:
        self.path = Path(db_path or _DB)
        configured_key = key if key is not None else _decode_key(
            os.environ.get("ZENO_MEDIA_ENCRYPTION_KEY", ""))
        if len(configured_key) != 32:
            raise AttachmentStoreUnavailable(
                "The attachment encryption key must be 32 bytes.")
        self._cipher = AESGCM(bytes(configured_key))
        self._now = now
        self._max_records = max(1, int(max_records))
        self._max_stored_bytes = max(MAX_ATTACHMENT_BYTES,
                                     int(max_stored_bytes))
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
                "CREATE TABLE IF NOT EXISTS attachments ("
                "id TEXT PRIMARY KEY, browser_device TEXT NOT NULL, "
                "target_device TEXT NOT NULL, command_id TEXT NOT NULL DEFAULT '', "
                "purpose TEXT NOT NULL, content_type TEXT NOT NULL, "
                "nonce BLOB NOT NULL, encrypted_data BLOB, "
                "filename_nonce BLOB NOT NULL, encrypted_filename BLOB, "
                "created REAL NOT NULL, expires REAL NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachment_expiry "
                "ON attachments(expires)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachment_command "
                "ON attachments(command_id)")

    @staticmethod
    def _aad(attachment_id: str, field: str, browser_device: str,
             target_device: str, content_type: str, purpose: str) -> bytes:
        return "\x1f".join((attachment_id, field, browser_device,
                             target_device, content_type, purpose)).encode("utf-8")

    def _encrypt(self, data: bytes, *, attachment_id: str, field: str,
                 browser_device: str, target_device: str,
                 content_type: str, purpose: str) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        encrypted = self._cipher.encrypt(
            nonce, data, self._aad(attachment_id, field, browser_device,
                                   target_device, content_type, purpose))
        return nonce, encrypted

    def _decrypt(self, nonce: bytes, encrypted: bytes, *, attachment_id: str,
                 field: str, browser_device: str, target_device: str,
                 content_type: str, purpose: str) -> bytes:
        try:
            return self._cipher.decrypt(
                nonce, encrypted,
                self._aad(attachment_id, field, browser_device, target_device,
                          content_type, purpose))
        except Exception as exc:  # noqa: BLE001 - never expose crypto internals
            raise AttachmentStoreError(
                "Stored attachment failed integrity verification.") from exc

    def _purge_expired(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute(
            "DELETE FROM attachments WHERE expires<=?",
            (float(self._now()),)).rowcount)

    def create(self, *, browser_device: str, target_device: str, data: bytes,
               content_type: str, filename: str, purpose: str,
               ttl_s: float = DEFAULT_TTL_S) -> str:
        browser = _safe_id(browser_device, "browser device id")
        target = _safe_id(target_device, "target device id")
        mime = _normalise_mime(content_type)
        safe_name = _safe_filename(filename)
        safe_purpose = _safe_purpose(purpose)
        payload = bytes(data or b"")
        if not payload:
            raise ValueError("Attachment is empty.")
        if len(payload) > MAX_ATTACHMENT_BYTES:
            raise ValueError(
                f"Attachment exceeds {MAX_ATTACHMENT_BYTES} bytes.")
        if safe_purpose == "camera" and not mime.startswith("image/"):
            raise ValueError("Camera attachments must be images.")
        _validate_payload(payload, mime, safe_name)
        ttl = max(30.0, min(float(ttl_s), MAX_TTL_S))
        now = float(self._now())
        attachment_id = f"att_{secrets.token_hex(16)}"
        nonce, encrypted = self._encrypt(
            payload, attachment_id=attachment_id, field="data",
            browser_device=browser, target_device=target,
            content_type=mime, purpose=safe_purpose)
        name_nonce, encrypted_name = self._encrypt(
            safe_name.encode("utf-8"), attachment_id=attachment_id,
            field="filename", browser_device=browser, target_device=target,
            content_type=mime, purpose=safe_purpose)

        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            usage = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(SUM(COALESCE(LENGTH(encrypted_data),0)+"
                "COALESCE(LENGTH(encrypted_filename),0)),0) AS bytes "
                "FROM attachments").fetchone()
            required = len(encrypted) + len(encrypted_name)
            if int(usage["n"] or 0) >= self._max_records:
                raise AttachmentCapacityExceeded(
                    "Too many attachments are waiting for expiry.")
            if int(usage["bytes"] or 0) + required > self._max_stored_bytes:
                raise AttachmentCapacityExceeded(
                    "The bounded attachment store is full.")
            conn.execute(
                "INSERT INTO attachments("
                "id,browser_device,target_device,purpose,content_type,nonce,"
                "encrypted_data,filename_nonce,encrypted_filename,created,expires"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (attachment_id, browser, target, safe_purpose, mime, nonce,
                 encrypted, name_nonce, encrypted_name, now, now + ttl),
            )
        return attachment_id

    def bind_command(self, attachment_id: str, *, command_id: str,
                     target_device: str) -> bool:
        attachment = _safe_id(attachment_id, "attachment id")
        command = _safe_id(command_id, "command id")
        target = _safe_id(target_device, "target device id")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            changed = conn.execute(
                "UPDATE attachments SET command_id=? WHERE id=? "
                "AND target_device=? AND command_id='' AND expires>?",
                (command, attachment, target, float(self._now())),
            ).rowcount
        return bool(changed)

    def read(self, attachment_id: str, *, target_device: str,
             command_id: str) -> AttachmentBlob:
        attachment = _safe_id(attachment_id, "attachment id")
        target = _safe_id(target_device, "target device id")
        command = _safe_id(command_id, "command id")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = conn.execute(
                "SELECT * FROM attachments WHERE id=?", (attachment,)).fetchone()
            if row is None or float(row["expires"]) <= float(self._now()):
                raise AttachmentNotFound("Attachment is missing or expired.")
            if row["target_device"] != target or row["command_id"] != command:
                raise AttachmentAccessDenied(
                    "Attachment is not bound to this device and command.")
            if not row["encrypted_data"] or not row["encrypted_filename"]:
                raise AttachmentNotFound("Attachment has already been released.")
            common = dict(
                attachment_id=row["id"], browser_device=row["browser_device"],
                target_device=row["target_device"],
                content_type=row["content_type"], purpose=row["purpose"])
            data = self._decrypt(row["nonce"], row["encrypted_data"],
                                 field="data", **common)
            filename = self._decrypt(
                row["filename_nonce"], row["encrypted_filename"],
                field="filename", **common).decode("utf-8")
            return AttachmentBlob(
                data=data, content_type=row["content_type"], filename=filename,
                purpose=row["purpose"], expires_at=float(row["expires"]))

    def release(self, attachment_id: str, *, target_device: str,
                command_id: str) -> bool:
        """Cryptographically discard data and filename after processing."""
        attachment = _safe_id(attachment_id, "attachment id")
        target = _safe_id(target_device, "target device id")
        command = _safe_id(command_id, "command id")
        with self._lock, self._connection() as conn:
            self._purge_expired(conn)
            row = conn.execute(
                "SELECT id,target_device,command_id FROM attachments WHERE id=?",
                (attachment,)).fetchone()
            if row is None:
                raise AttachmentNotFound("Attachment is missing or expired.")
            if row["target_device"] != target or row["command_id"] != command:
                raise AttachmentAccessDenied(
                    "Attachment is not bound to this device and command.")
            changed = conn.execute(
                "UPDATE attachments SET nonce=X'',encrypted_data=NULL,"
                "filename_nonce=X'',encrypted_filename=NULL WHERE id=?",
                (attachment,),
            ).rowcount
        return bool(changed)

    def discard(self, attachment_id: str) -> bool:
        attachment = _safe_id(attachment_id, "attachment id")
        with self._lock, self._connection() as conn:
            return bool(conn.execute(
                "DELETE FROM attachments WHERE id=?", (attachment,)).rowcount)

    def stats(self) -> dict[str, int]:
        with self._lock, self._connection() as conn:
            purged = self._purge_expired(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(SUM(COALESCE(LENGTH(encrypted_data),0)+"
                "COALESCE(LENGTH(encrypted_filename),0)),0) AS bytes "
                "FROM attachments").fetchone()
        return {
            "records": int(row["n"] or 0),
            "encrypted_bytes": int(row["bytes"] or 0),
            "purged": purged,
            "max_records": self._max_records,
            "max_stored_bytes": self._max_stored_bytes,
        }


_store: AttachmentStore | None = None
_store_lock = threading.Lock()


def get_attachment_store() -> AttachmentStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AttachmentStore()
        return _store


def reset_for_tests(db_path: Path | None = None, *, key: bytes | None = None,
                    now=time.time, max_records: int = MAX_RECORDS,
                    max_stored_bytes: int = MAX_STORED_BYTES) -> AttachmentStore:
    global _store
    with _store_lock:
        _store = AttachmentStore(
            db_path, key=key, now=now, max_records=max_records,
            max_stored_bytes=max_stored_bytes)
        return _store
