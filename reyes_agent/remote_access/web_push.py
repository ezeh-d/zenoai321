"""Privacy-preserving native Web Push for the trusted owner PWA.

Push subscriptions contain bearer-like endpoint credentials, so they are
encrypted at rest and never returned by an API.  Delivery is best-effort on
one bounded worker; a slow push service must never hold a gateway request or
grow an unbounded executor queue.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import ipaddress
import json
import os
import queue
import socket
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from reyes_agent import config

_MAX_SUBSCRIPTIONS = 32
_MAX_QUEUE = 128
_MAX_ENDPOINT = 2048
_MAX_KEY = 512
_ALLOWED_PUSH_HOST_SUFFIXES = (
    ".googleapis.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
    ".wns.windows.com",
    ".push.apple.com",
    ".webpush.apple.com",
)


class PushConfigurationError(RuntimeError):
    pass


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value.strip() + "=" * (-len(value.strip()) % 4))
    except Exception as exc:  # noqa: BLE001
        raise PushConfigurationError("invalid push encryption key") from exc
    if len(raw) != 32:
        raise PushConfigurationError("push encryption key must decode to 32 bytes")
    return raw


def _safe_endpoint(endpoint: str) -> str:
    value = str(endpoint or "").strip()
    if not value or len(value) > _MAX_ENDPOINT:
        raise ValueError("invalid push endpoint length")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("push endpoint must be a credential-free HTTPS URL")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and (literal.is_private or literal.is_loopback or
                                literal.is_link_local or literal.is_reserved):
        raise ValueError("local and reserved push endpoints are refused")
    allowed = any(host == suffix[1:] or host.endswith(suffix)
                  for suffix in _ALLOWED_PUSH_HOST_SUFFIXES)
    extra = tuple(
        "." + item.strip().casefold().lstrip(".")
        for item in os.environ.get("ZENO_WEB_PUSH_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    )
    if not allowed and not any(host == suffix[1:] or host.endswith(suffix)
                               for suffix in extra):
        raise ValueError("push service host is not allow-listed")
    # Resolve once to reject a public-looking hostname that currently points
    # at a private network. Delivery libraries resolve again, but a strict
    # service-host allow-list prevents attacker-controlled DNS rebinding.
    try:
        for info in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local:
                raise ValueError("push endpoint resolved to a private address")
    except socket.gaierror as exc:
        raise ValueError("push endpoint host did not resolve") from exc
    return value


class WebPushService:
    def __init__(self, path: str | Path | None = None, *, encryption_key: str | None = None,
                 public_key: str | None = None, private_key: str | None = None,
                 subject: str | None = None) -> None:
        self.path = Path(path or os.environ.get("ZENO_WEB_PUSH_DB", "") or
                         (config.VAULT_PATH / "07-System" / "web_push.sqlite"))
        self._public_key = (public_key if public_key is not None else
                            os.environ.get("ZENO_WEB_PUSH_PUBLIC_KEY", "")).strip()
        self._private_key = (private_key if private_key is not None else
                             os.environ.get("ZENO_WEB_PUSH_PRIVATE_KEY", "")).strip()
        self._subject = (subject if subject is not None else
                         os.environ.get("ZENO_WEB_PUSH_SUBJECT", "")).strip()
        supplied_key = (encryption_key if encryption_key is not None else
                        os.environ.get("ZENO_WEB_PUSH_ENCRYPTION_KEY", "")).strip()
        self._key_error = ""
        try:
            self._cipher = AESGCM(_decode_key(supplied_key)) if supplied_key else None
        except PushConfigurationError as exc:
            self._cipher = None
            self._key_error = str(exc)
        self._queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=_MAX_QUEUE)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS subscriptions(
                    id TEXT PRIMARY KEY,
                    browser_device_id TEXT NOT NULL,
                    encrypted BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    created REAL NOT NULL,
                    last_success REAL,
                    failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_push_browser
                    ON subscriptions(browser_device_id);
            """)

    def status(self) -> dict[str, Any]:
        configured = bool(self._cipher and self._public_key and self._private_key and self._subject)
        detail = self._key_error or ("ready" if configured else
            "Set ZENO_WEB_PUSH_PUBLIC_KEY, ZENO_WEB_PUSH_PRIVATE_KEY, "
            "ZENO_WEB_PUSH_SUBJECT and ZENO_WEB_PUSH_ENCRYPTION_KEY.")
        with self._connection() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0])
        return {"state": "STANDBY" if configured else "NOT_CONFIGURED",
                "configured": configured, "subscriptions": count,
                "public_key": self._public_key if configured else "", "detail": detail}

    def _require_configured(self) -> None:
        if not self.status()["configured"]:
            raise PushConfigurationError("native Web Push is not configured")

    def _encrypt(self, payload: dict[str, Any]) -> tuple[bytes, bytes]:
        self._require_configured()
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._cipher.encrypt(nonce, plaintext, b"zeno-web-push-v1"), nonce

    def _decrypt(self, encrypted: bytes, nonce: bytes) -> dict[str, Any]:
        self._require_configured()
        raw = self._cipher.decrypt(nonce, encrypted, b"zeno-web-push-v1")
        return json.loads(raw)

    def register(self, browser_device_id: str, subscription: dict[str, Any]) -> dict[str, Any]:
        browser = str(browser_device_id or "").strip()[:96]
        if not browser:
            raise ValueError("authenticated browser identity is required")
        endpoint = _safe_endpoint(str(subscription.get("endpoint", "")))
        keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
        p256dh, auth = str(keys.get("p256dh", "")).strip(), str(keys.get("auth", "")).strip()
        if not p256dh or not auth or len(p256dh) > _MAX_KEY or len(auth) > _MAX_KEY:
            raise ValueError("push subscription keys are missing or invalid")
        sealed, nonce = self._encrypt({"endpoint": endpoint,
                                      "keys": {"p256dh": p256dh, "auth": auth}})
        sub_id = hashlib.sha256(f"{browser}|{endpoint}".encode()).hexdigest()[:40]
        with self._lock, self._connection() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0])
            exists = conn.execute("SELECT 1 FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
            if count >= _MAX_SUBSCRIPTIONS and not exists:
                raise ValueError("push subscription limit reached")
            conn.execute(
                "INSERT INTO subscriptions(id,browser_device_id,encrypted,nonce,created) "
                "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET browser_device_id=excluded.browser_device_id,"
                "encrypted=excluded.encrypted,nonce=excluded.nonce,last_error='',failures=0",
                (sub_id, browser, sealed, nonce, time.time()))
        return {"ok": True, "subscription_id": sub_id, "browser_device_id": browser}

    def unregister_browser(self, browser_device_id: str) -> int:
        with self._connection() as conn:
            return int(conn.execute("DELETE FROM subscriptions WHERE browser_device_id=?",
                                    (str(browser_device_id)[:96],)).rowcount)

    def enqueue(self, title: str, body: str, *, kind: str = "update") -> bool:
        # Generic content only: notification surfaces may appear on a locked
        # phone, so chat, memory and command payloads never belong here.
        item = {"title": str(title or "ZENO")[:80], "body": str(body or "")[:160],
                "kind": str(kind or "update")[:32], "url": "/app/"}
        if not self.status()["configured"]:
            return False
        self._ensure_worker()
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="zeno-web-push",
                                            daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._deliver_all(item)
            finally:
                self._queue.task_done()

    def _deliver_all(self, item: dict[str, str]) -> None:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY created").fetchall()
        for row in rows:
            try:
                from pywebpush import WebPushException, webpush

                subscription = self._decrypt(row["encrypted"], row["nonce"])
                webpush(subscription_info=subscription,
                        data=json.dumps(item, separators=(",", ":")),
                        vapid_private_key=self._private_key,
                        vapid_claims={"sub": self._subject}, ttl=120, timeout=8)
            except Exception as exc:  # noqa: BLE001 -- isolated per subscription
                response = getattr(exc, "response", None)
                status_code = int(getattr(response, "status_code", 0) or 0)
                with self._connection() as conn:
                    if status_code in {404, 410}:
                        conn.execute("DELETE FROM subscriptions WHERE id=?", (row["id"],))
                    else:
                        conn.execute(
                            "UPDATE subscriptions SET failures=failures+1,last_error=? WHERE id=?",
                            (f"{type(exc).__name__}:{status_code}"[:160], row["id"]))
            else:
                with self._connection() as conn:
                    conn.execute("UPDATE subscriptions SET last_success=?,failures=0,last_error='' "
                                 "WHERE id=?", (time.time(), row["id"]))

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(0.0, timeout))


_service: WebPushService | None = None
_service_lock = threading.Lock()


def get_service() -> WebPushService:
    global _service
    with _service_lock:
        if _service is None:
            _service = WebPushService()
            atexit.register(_service.shutdown)
        return _service


def shutdown_if_started(timeout: float = 2.0) -> None:
    with _service_lock:
        service = _service
    if service is not None:
        service.shutdown(timeout)


def reset_for_tests(path: str | Path, **kwargs: Any) -> WebPushService:
    global _service
    with _service_lock:
        if _service is not None:
            _service.shutdown()
        _service = WebPushService(path, **kwargs)
        return _service
