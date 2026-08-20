"""OwnerAuthService -- one owner, many devices, no standing secrets in git.

THREAT MODEL
------------
This service exists to stand between the public internet and a machine that
can open applications, read files and speak. The realistic attacks are:

  1. Someone finds the URL and tries passwords.       -> scrypt + lockout
  2. Someone steals a session cookie.                 -> short TTL + revocation
  3. Someone replays a captured login request.        -> nonce + single-use
  4. A malicious page makes the browser POST for you. -> CSRF token + SameSite
  5. Someone reads the repository.                    -> no secret is stored here

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No password is ever stored, logged or returned -- only an scrypt hash and its
salt. No password reset by email, because there is no mail infrastructure to
trust and a broken reset flow is a backdoor. The owner re-provisions from the
desktop, which is the machine that already has full authority.

Biometrics are NOT implemented here and never will be: fingerprint and face
matching belong to the phone's secure enclave. This module speaks WebAuthn to
the browser and stores a public key. It never sees a fingerprint.
"""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

# Sessions are short because this surface is reachable from the internet. A
# refresh token keeps the owner logged in without keeping a long-lived
# credential in the browser where XSS could reach it.
ACCESS_TTL_S = 30 * 60           # 30 minutes
# How long a trusted browser stays signed in WITHOUT re-entering the password.
# Every refresh rotates the token and resets this window, so a phone used even
# occasionally never has to log in again. 90 days by default; the owner can
# shorten it (ZENO_OWNER_REFRESH_DAYS) if they prefer tighter sessions. The
# safety net is unchanged: losing the phone means revoking that device from the
# PC, which kills its sessions instantly regardless of this value.
try:
    _REFRESH_DAYS = max(1, min(365, int(os.environ.get("ZENO_OWNER_REFRESH_DAYS", "90"))))
except ValueError:
    _REFRESH_DAYS = 90
REFRESH_TTL_S = _REFRESH_DAYS * 24 * 3600
MAX_FAILED = 5                   # consecutive failures before lockout
LOCKOUT_S = 900.0                # 15 minutes
CHALLENGE_TTL_S = 300.0
BROWSER_PENDING, BROWSER_APPROVED, BROWSER_BLOCKED, BROWSER_REVOKED = (
    "PENDING", "APPROVED", "BLOCKED", "REVOKED")

# scrypt parameters. n=2**15 costs ~100ms on this machine -- slow enough that
# offline guessing is expensive, fast enough that login does not feel broken.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 15, 8, 1
# OpenSSL enforces its own memory ceiling and raises
# "memory limit exceeded" below 128*N*r bytes. That is 32 MiB at these
# parameters; the ceiling is set above it with room for OpenSSL's overhead,
# because the alternative is weakening the cost factor to fit a default.
_SCRYPT_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * 2

_DB = Path(os.environ.get(
    "ZENO_OWNER_AUTH_DB",
    str(Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) /
        "ZENO" / "auth" / "owner.sqlite")))


def _hash(value: str) -> str:
    """SHA-256 for TOKENS ONLY.

    Tokens are 256-bit random values, so there is nothing to brute-force and a
    fast hash is correct. Passwords use scrypt -- see `_hash_password`.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                             n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=64,
                             maxmem=_SCRYPT_MAXMEM)
    return derived.hex(), salt.hex()


def _verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    try:
        candidate, _ = _hash_password(password, bytes.fromhex(stored_salt))
    except (ValueError, TypeError):
        return False
    # Constant time: a timing difference here leaks the hash prefix.
    return hmac.compare_digest(candidate, stored_hash)


@dataclass(frozen=True)
class Session:
    token: str
    csrf: str
    refresh: str
    expires_at: float
    device_label: str = ""
    device_id: str = ""
    device_state: str = "PENDING"

    def as_dict(self) -> dict[str, Any]:
        """Safe to send to the client. Contains the tokens it must hold."""
        return {"session": self.token, "csrf": self.csrf,
                "refresh": self.refresh, "expires_at": self.expires_at,
                "device": self.device_label, "device_id": self.device_id,
                "device_state": self.device_state}


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    reason: str = ""
    session: Session | None = None
    retry_after: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"ok": self.ok}
        if self.reason:
            body["reason"] = self.reason
        if self.retry_after:
            body["retry_after"] = round(self.retry_after, 1)
        if self.session is not None:
            body.update(self.session.as_dict())
        return body


class OwnerAuthService:
    """Single-owner authentication with sessions, refresh and revocation."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ---- storage --------------------------------------------------------
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
                CREATE TABLE IF NOT EXISTS owner(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL);

                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY,
                    csrf_hash TEXT NOT NULL,
                    refresh_hash TEXT NOT NULL,
                    device_label TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL,
                    expires REAL NOT NULL,
                    refresh_expires REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    device_id TEXT NOT NULL DEFAULT '');

                CREATE TABLE IF NOT EXISTS browser_devices(
                    device_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'PENDING',
                    approved_at REAL,
                    revoked_at REAL);

                CREATE TABLE IF NOT EXISTS failures(
                    identity TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0);

                CREATE TABLE IF NOT EXISTS credentials(
                    credential_id TEXT PRIMARY KEY,
                    public_key TEXT NOT NULL,
                    sign_count INTEGER NOT NULL DEFAULT 0,
                    label TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL,
                    last_used REAL,
                    revoked INTEGER NOT NULL DEFAULT 0);

                CREATE TABLE IF NOT EXISTS used_nonces(
                    nonce TEXT PRIMARY KEY,
                    seen REAL NOT NULL);

                CREATE TABLE IF NOT EXISTS challenges(
                    challenge_hash TEXT PRIMARY KEY,
                    challenge TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    created REAL NOT NULL,
                    expires REAL NOT NULL);

                CREATE TABLE IF NOT EXISTS audit(
                    at REAL NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '');
                """
            )
            session_columns = {str(row[1]) for row in conn.execute(
                "PRAGMA table_info(sessions)")}
            if "device_id" not in session_columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN device_id TEXT NOT NULL DEFAULT ''")

    def _audit(self, event: str, **detail: Any) -> None:
        """Never called with a password, token or CSRF value. See `_scrub`."""
        with self._connection() as conn:
            conn.execute("INSERT INTO audit(at,event,detail) VALUES(?,?,?)",
                         (time.time(), event, json.dumps(_scrub(detail))[:600]))

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT at,event,detail FROM audit ORDER BY at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),)).fetchall()
        return [dict(row) for row in rows]

    # ---- provisioning ---------------------------------------------------
    def is_provisioned(self) -> bool:
        with self._connection() as conn:
            return conn.execute("SELECT 1 FROM owner WHERE id=1").fetchone() is not None

    def provision(self, email: str, password: str) -> tuple[bool, str]:
        """Create or replace the owner credential. DESKTOP ONLY.

        The route that calls this is not remotely reachable -- the fail-closed
        boundary refuses it -- so provisioning always happens at the machine
        that already has full authority. That is the only place where setting
        a password without knowing the old one is safe.
        """
        password = (password or "").strip()
        if len(password) < 12:
            return False, "Password must be at least 12 characters."
        if password.lower() in _WEAK:
            return False, "That password is one of the most common in use. Choose another."
        email = (email or "").strip().lower()
        if "@" not in email:
            return False, "A valid email address is required."

        hashed, salt = _hash_password(password)
        now = time.time()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO owner(id,email,password_hash,password_salt,created,updated) "
                "VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "email=excluded.email, password_hash=excluded.password_hash, "
                "password_salt=excluded.password_salt, updated=excluded.updated",
                (email, hashed, salt, now, now))
        # A new password invalidates every existing session. If the password
        # was changed because it leaked, leaving old sessions alive would
        # defeat the point of changing it.
        self.revoke_all(reason="password_changed")
        self._audit("owner_provisioned", email=email)
        return True, "Owner credential set. All existing sessions were revoked."

    # ---- login ----------------------------------------------------------
    def login(self, email: str, password: str, *, identity: str = "unknown",
              device_label: str = "", user_agent: str = "",
              nonce: str = "", device_id: str = "") -> AuthResult:
        """Verify the owner's password and issue a session."""
        from reyes_agent.remote_access import policy

        identity = str(identity or "unknown")[:120]

        # Replay protection: every public login request must have a fresh,
        # client-generated nonce. Optional replay protection is no protection.
        if len(str(nonce or "")) < 16:
            return AuthResult(False, "A fresh login nonce is required.")
        if not self._consume_nonce(nonce):
            self._audit("login_replay_rejected", identity=identity)
            return AuthResult(False, "This request was already used.")

        rate = policy.check_rate("login", identity)
        if not rate.allowed:
            self._audit("login_rate_limited", identity=identity)
            return AuthResult(False, "Too many attempts. Wait and try again.",
                              retry_after=rate.retry_after)

        locked, until = self._lockout_state(identity)
        if locked:
            return AuthResult(False, "Locked after repeated failures.",
                              retry_after=max(0.0, until - time.time()))

        if not self.is_provisioned():
            return AuthResult(False, "No owner is provisioned. Run setup at the desktop.")

        with self._connection() as conn:
            row = conn.execute("SELECT email,password_hash,password_salt FROM owner WHERE id=1").fetchone()

        email_ok = hmac.compare_digest((email or "").strip().lower(), row["email"])
        # Verify the password even when the email is wrong, so that a wrong
        # email and a wrong password take the same time. Otherwise the
        # response time tells an attacker which half they got right.
        password_ok = _verify_password(password or "", row["password_hash"], row["password_salt"])

        if not (email_ok and password_ok):
            remaining = self._record_failure(identity)
            policy.check_rate("auth_failure", identity)
            self._audit("login_failed", identity=identity, remaining=remaining)
            return AuthResult(False, "Incorrect email or password.")

        self._clear_failures(identity)
        session = self._issue(device_label=device_label, user_agent=user_agent,
                              address=identity, device_id=device_id)
        self._audit("login_ok", identity=identity, device=device_label)
        return AuthResult(True, session=session)

    # ---- sessions -------------------------------------------------------
    def _touch_browser_device(self, *, device_id: str, label: str,
                              user_agent: str) -> dict[str, Any]:
        clean_id = str(device_id or "").strip()[:96]
        if (len(clean_id) < 16 or
                any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." 
                    for ch in clean_id)):
            clean_id = "browser_" + secrets.token_hex(16)
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT state FROM browser_devices WHERE device_id=?", (clean_id,)).fetchone()
            if row is None:
                state = BROWSER_PENDING
                conn.execute(
                    "INSERT INTO browser_devices(device_id,label,user_agent,created,last_seen,state) "
                    "VALUES(?,?,?,?,?,?)",
                    (clean_id, str(label or "New browser")[:80], user_agent[:200],
                     now, now, state))
            else:
                state = str(row["state"])
                conn.execute(
                    "UPDATE browser_devices SET label=?,user_agent=?,last_seen=? WHERE device_id=?",
                    (str(label or "Browser")[:80], user_agent[:200], now, clean_id))
        return {"device_id": clean_id, "state": state}

    def _issue(self, *, device_label: str = "", user_agent: str = "",
               address: str = "", device_id: str = "") -> Session:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        refresh = secrets.token_urlsafe(40)
        now = time.time()
        browser = self._touch_browser_device(device_id=device_id,
                                             label=device_label,
                                             user_agent=user_agent)
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO sessions(token_hash,csrf_hash,refresh_hash,device_label,"
                "user_agent,address,created,expires,refresh_expires,last_seen,device_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (_hash(token), _hash(csrf), _hash(refresh), device_label[:80],
                 user_agent[:200], address[:80], now, now + ACCESS_TTL_S,
                 now + REFRESH_TTL_S, now, browser["device_id"]))
        return Session(token=token, csrf=csrf, refresh=refresh,
                       expires_at=now + ACCESS_TTL_S, device_label=device_label,
                       device_id=browser["device_id"], device_state=browser["state"])

    def verify(self, token: str, *, csrf: str = "",
               require_csrf: bool = False) -> tuple[bool, str]:
        """Validate a session token. Returns (ok, reason)."""
        if not token:
            return False, "No session."
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.expires,s.revoked,s.csrf_hash,s.device_id,"
                "COALESCE(d.state,'PENDING') AS device_state "
                "FROM sessions s LEFT JOIN browser_devices d ON d.device_id=s.device_id "
                "WHERE s.token_hash=?",
                (_hash(token),)).fetchone()
            if row is None:
                return False, "Unknown session."
            if row["revoked"]:
                return False, "Session was revoked."
            if row["device_state"] in {BROWSER_BLOCKED, BROWSER_REVOKED}:
                return False, "Browser device was blocked or revoked."
            if row["expires"] <= time.time():
                return False, "Session expired."
            if require_csrf and not hmac.compare_digest(_hash(csrf or ""), row["csrf_hash"]):
                return False, "CSRF token mismatch."
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (time.time(), _hash(token)))
        return True, ""

    def session_info(self, token: str) -> dict[str, Any] | None:
        ok, _reason = self.verify(token)
        if not ok:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.device_id,s.device_label,s.created,s.expires,s.last_seen,"
                "COALESCE(d.state,'PENDING') AS device_state "
                "FROM sessions s LEFT JOIN browser_devices d ON d.device_id=s.device_id "
                "WHERE s.token_hash=?", (_hash(token),)).fetchone()
        if row is None:
            return None
        return {"device_id": row["device_id"], "device": row["device_label"],
                "created": row["created"], "expires": row["expires"],
                "last_seen": row["last_seen"], "device_state": row["device_state"],
                "trusted": row["device_state"] == BROWSER_APPROVED}

    def refresh_session(self, refresh_token: str, *,
                        identity: str = "unknown") -> AuthResult:
        """Exchange a refresh token for a new session. Single use."""
        from reyes_agent.remote_access import policy

        rate = policy.check_rate("login", identity)
        if not rate.allowed:
            return AuthResult(False, "Too many attempts.", retry_after=rate.retry_after)

        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT token_hash,device_label,user_agent,address,refresh_expires,revoked,device_id "
                "FROM sessions WHERE refresh_hash=?", (_hash(refresh_token or ""),)).fetchone()
            if row is None:
                self._audit("refresh_unknown", identity=identity)
                return AuthResult(False, "Unknown refresh token.")
            if row["revoked"]:
                return AuthResult(False, "Session was revoked.")
            if row["refresh_expires"] <= now:
                return AuthResult(False, "Refresh token expired. Sign in again.")
            # Rotate: the old row dies so a stolen refresh token is usable at
            # most once, and reuse of an already-spent token finds nothing.
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))

        session = self._issue(device_label=row["device_label"],
                              user_agent=row["user_agent"], address=row["address"],
                              device_id=row["device_id"])
        self._audit("refresh_ok", identity=identity, device=row["device_label"])
        return AuthResult(True, session=session)

    def logout(self, token: str) -> bool:
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE sessions SET revoked=1 WHERE token_hash=? AND revoked=0",
                (_hash(token or ""),)).rowcount
        if changed:
            self._audit("logout")
        return bool(changed)

    def sessions(self) -> list[dict[str, Any]]:
        """Every live session, for the device-management screen.

        Returns no token, no CSRF value and no refresh token -- only what the
        owner needs in order to recognise a device and revoke it.
        """
        now = time.time()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT s.token_hash,s.device_label,s.user_agent,s.address,s.created,s.expires,"
                "s.last_seen,s.revoked,s.device_id,COALESCE(d.state,'PENDING') AS device_state "
                "FROM sessions s LEFT JOIN browser_devices d ON d.device_id=s.device_id "
                "ORDER BY s.last_seen DESC LIMIT 100").fetchall()
        out = []
        for row in rows:
            out.append({
                # A short, non-reversible handle: enough to revoke by, useless
                # as a credential.
                "id": row["token_hash"][:16],
                "device": row["device_label"] or "unknown device",
                "user_agent": row["user_agent"][:120],
                "address": row["address"],
                "device_id": row["device_id"],
                "device_state": row["device_state"],
                "created": row["created"],
                "last_seen": row["last_seen"],
                "expired": row["expires"] <= now,
                "revoked": bool(row["revoked"]),
                "active": (not row["revoked"]) and row["expires"] > now,
            })
        return out

    def revoke(self, session_id: str) -> bool:
        """Revoke one session by the short handle from `sessions()`."""
        handle = (session_id or "").strip()[:16]
        if len(handle) < 8:
            return False
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE sessions SET revoked=1 WHERE substr(token_hash,1,16)=? AND revoked=0",
                (handle,)).rowcount
        if changed:
            self._audit("session_revoked", session=handle)
        return bool(changed)

    def browser_devices(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT device_id,label,user_agent,created,last_seen,state,approved_at,revoked_at "
                "FROM browser_devices ORDER BY last_seen DESC LIMIT 200").fetchall()
        return [dict(row) for row in rows]

    def approve_browser_device(self, device_id: str) -> bool:
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE browser_devices SET state=?,approved_at=?,revoked_at=NULL "
                "WHERE device_id=? AND state=?",
                (BROWSER_APPROVED, time.time(), device_id, BROWSER_PENDING)).rowcount
        if changed:
            self._audit("browser_device_approved", device_id=device_id)
        return bool(changed)

    def rename_browser_device(self, device_id: str, label: str) -> bool:
        clean = " ".join(str(label or "").split())[:80]
        if not clean:
            return False
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE browser_devices SET label=? WHERE device_id=?",
                (clean, device_id)).rowcount
        return bool(changed)

    def set_browser_device_state(self, device_id: str, state: str) -> bool:
        wanted = str(state or "").upper()
        if wanted not in {BROWSER_PENDING, BROWSER_APPROVED,
                           BROWSER_BLOCKED, BROWSER_REVOKED}:
            return False
        now = time.time()
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE browser_devices SET state=?,approved_at=CASE WHEN ?='APPROVED' "
                "THEN COALESCE(approved_at,?) ELSE approved_at END,revoked_at=CASE WHEN ? "
                "IN ('BLOCKED','REVOKED') THEN ? ELSE NULL END WHERE device_id=?",
                (wanted, wanted, now, wanted, now, device_id)).rowcount
            if changed and wanted in {BROWSER_BLOCKED, BROWSER_REVOKED}:
                conn.execute(
                    "UPDATE sessions SET revoked=1 WHERE device_id=?", (device_id,))
        if changed:
            self._audit("browser_device_state", device_id=device_id, state=wanted)
        return bool(changed)

    def revoke_all(self, *, reason: str = "owner_request") -> int:
        with self._connection() as conn:
            changed = conn.execute("UPDATE sessions SET revoked=1 WHERE revoked=0").rowcount
        if changed:
            self._audit("all_sessions_revoked", reason=reason, count=changed)
        return int(changed)

    # ---- lockout --------------------------------------------------------
    def _lockout_state(self, identity: str) -> tuple[bool, float]:
        with self._connection() as conn:
            row = conn.execute("SELECT locked_until FROM failures WHERE identity=?",
                               (identity,)).fetchone()
        if row is None:
            return False, 0.0
        return (row["locked_until"] > time.time()), float(row["locked_until"])

    def _record_failure(self, identity: str) -> int:
        now = time.time()
        with self._connection() as conn:
            row = conn.execute("SELECT count,locked_until FROM failures WHERE identity=?",
                               (identity,)).fetchone()
            count = (row["count"] if row else 0) + 1
            locked_until = now + LOCKOUT_S if count >= MAX_FAILED else 0.0
            conn.execute(
                "INSERT INTO failures(identity,count,locked_until) VALUES(?,?,?) "
                "ON CONFLICT(identity) DO UPDATE SET count=excluded.count, "
                "locked_until=excluded.locked_until",
                (identity, count, locked_until))
        if locked_until:
            self._audit("account_locked", identity=identity, until=locked_until)
        return max(0, MAX_FAILED - count)

    def _clear_failures(self, identity: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM failures WHERE identity=?", (identity,))

    # ---- replay ---------------------------------------------------------
    def _consume_nonce(self, nonce: str) -> bool:
        """True the first time a nonce is seen, False afterwards."""
        nonce = str(nonce)[:120]
        cutoff = time.time() - 3600
        with self._connection() as conn:
            conn.execute("DELETE FROM used_nonces WHERE seen < ?", (cutoff,))
            try:
                conn.execute("INSERT INTO used_nonces(nonce,seen) VALUES(?,?)",
                             (nonce, time.time()))
            except sqlite3.IntegrityError:
                return False
        return True

    # ---- passkeys -------------------------------------------------------
    def passkey_credentials(self) -> list[dict[str, Any]]:
        """Registered passkeys. Public keys only -- never a biometric."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT credential_id,label,created,last_used,revoked FROM credentials "
                "WHERE revoked=0 ORDER BY created DESC").fetchall()
        return [{"id": r["credential_id"][:16], "label": r["label"],
                 "created": r["created"], "last_used": r["last_used"]} for r in rows]

    def register_passkey(self, credential_id: str, public_key: str,
                         label: str = "") -> bool:
        """Refuse unverified key insertion.

        Claude's first draft accepted arbitrary browser strings here.  That
        creates a credential without a WebAuthn challenge, origin, RP-ID or
        user-verification check.  Registration now goes exclusively through
        ``finish_passkey_registration`` below.
        """
        del credential_id, public_key, label
        return False

    def _save_challenge(self, challenge: bytes, purpose: str) -> str:
        encoded = _b64(challenge)
        now = time.time()
        with self._connection() as conn:
            conn.execute("DELETE FROM challenges WHERE expires<=?", (now,))
            conn.execute(
                "INSERT INTO challenges(challenge_hash,challenge,purpose,created,expires) "
                "VALUES(?,?,?,?,?)",
                (_hash(encoded), encoded, purpose, now, now + CHALLENGE_TTL_S))
        return encoded

    def _take_challenge(self, encoded: str, purpose: str) -> str:
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT challenge,purpose,expires FROM challenges WHERE challenge_hash=?",
                (_hash(encoded or ""),)).fetchone()
            if row is None or row["purpose"] != purpose or row["expires"] <= now:
                raise PermissionError("WebAuthn challenge is invalid or expired.")
            conn.execute("DELETE FROM challenges WHERE challenge_hash=?",
                         (_hash(encoded),))
        return str(row["challenge"])

    def passkey_registration_options(self, *, rp_id: str,
                                     label: str = "Owner passkey") -> dict[str, Any]:
        if not self.is_provisioned():
            raise PermissionError("Provision the owner at the Windows desktop first.")
        from webauthn import generate_registration_options
        from webauthn.helpers import options_to_json
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria, ResidentKeyRequirement,
            UserVerificationRequirement,
        )

        with self._connection() as conn:
            row = conn.execute("SELECT email FROM owner WHERE id=1").fetchone()
        challenge = secrets.token_bytes(32)
        self._save_challenge(challenge, "passkey-registration")
        options = generate_registration_options(
            rp_id=str(rp_id), rp_name=config.ASSISTANT_NAME,
            user_name=str(row["email"]),
            user_id=hashlib.sha256(str(row["email"]).encode("utf-8")).digest(),
            user_display_name=str(label or "ZENO owner")[:80], challenge=challenge,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED),
        )
        return json.loads(options_to_json(options))

    def finish_passkey_registration(self, credential: dict[str, Any], *,
                                    challenge: str, origin: str, rp_id: str,
                                    label: str = "") -> dict[str, Any]:
        from webauthn import verify_registration_response
        from webauthn.helpers import base64url_to_bytes

        expected = self._take_challenge(challenge, "passkey-registration")
        verified = verify_registration_response(
            credential=credential, expected_challenge=base64url_to_bytes(expected),
            expected_rp_id=rp_id, expected_origin=origin,
            require_user_verification=True)
        credential_id = _b64(verified.credential_id)
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO credentials(credential_id,public_key,sign_count,label,created,revoked) "
                "VALUES(?,?,?,?,?,0) ON CONFLICT(credential_id) DO UPDATE SET "
                "public_key=excluded.public_key,sign_count=excluded.sign_count,"
                "label=excluded.label,revoked=0",
                (credential_id, verified.credential_public_key, verified.sign_count,
                 str(label or "Owner passkey")[:80], time.time()))
        self._audit("passkey_registered", label=label)
        return {"ok": True, "credential_id": credential_id[:16],
                "label": str(label or "Owner passkey")[:80]}

    def passkey_authentication_options(self, *, rp_id: str) -> dict[str, Any]:
        from webauthn import generate_authentication_options
        from webauthn.helpers import base64url_to_bytes, options_to_json
        from webauthn.helpers.structs import (PublicKeyCredentialDescriptor,
                                              UserVerificationRequirement)

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT credential_id FROM credentials WHERE revoked=0 "
                "ORDER BY created DESC LIMIT 20").fetchall()
        if not rows:
            raise PermissionError("No active owner passkey is registered.")
        challenge = secrets.token_bytes(32)
        self._save_challenge(challenge, "passkey-authentication")
        options = generate_authentication_options(
            rp_id=rp_id, challenge=challenge,
            allow_credentials=[PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(row["credential_id"])) for row in rows],
            user_verification=UserVerificationRequirement.REQUIRED)
        return json.loads(options_to_json(options))

    def finish_passkey_authentication(self, credential: dict[str, Any], *,
                                      challenge: str, origin: str, rp_id: str,
                                      identity: str = "unknown", device_label: str = "",
                                      user_agent: str = "", device_id: str = "") -> AuthResult:
        from webauthn import verify_authentication_response
        from webauthn.helpers import base64url_to_bytes

        expected = self._take_challenge(challenge, "passkey-authentication")
        credential_id = str(credential.get("id") or credential.get("rawId") or "")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT credential_id,public_key,sign_count FROM credentials "
                "WHERE credential_id=? AND revoked=0", (credential_id,)).fetchone()
        if row is None:
            self._audit("passkey_login_failed", identity=identity)
            return AuthResult(False, "Unknown or revoked passkey.")
        try:
            verified = verify_authentication_response(
                credential=credential, expected_challenge=base64url_to_bytes(expected),
                expected_rp_id=rp_id, expected_origin=origin,
                credential_public_key=row["public_key"],
                credential_current_sign_count=row["sign_count"],
                require_user_verification=True)
        except Exception:  # no credential detail in logs or response
            self._audit("passkey_login_failed", identity=identity)
            return AuthResult(False, "Passkey verification failed.")
        with self._connection() as conn:
            conn.execute(
                "UPDATE credentials SET sign_count=?,last_used=? WHERE credential_id=?",
                (verified.new_sign_count, time.time(), credential_id))
        session = self._issue(device_label=device_label, user_agent=user_agent,
                              address=identity, device_id=device_id)
        self._audit("passkey_login_ok", identity=identity, device=device_label)
        return AuthResult(True, session=session)

    def revoke_passkey(self, credential_id: str) -> bool:
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE credentials SET revoked=1 WHERE substr(credential_id,1,16)=?",
                ((credential_id or "")[:16],)).rowcount
        if changed:
            self._audit("passkey_revoked")
        return bool(changed)

    # ---- status ---------------------------------------------------------
    def status(self) -> dict[str, Any]:
        live = [s for s in self.sessions() if s["active"]]
        devices = self.browser_devices()
        return {
            "provisioned": self.is_provisioned(),
            "active_sessions": len(live),
            "passkeys": len(self.passkey_credentials()),
            "browser_devices": len(devices),
            "pending_devices": sum(1 for item in devices if item["state"] == BROWSER_PENDING),
            "approved_devices": sum(1 for item in devices if item["state"] == BROWSER_APPROVED),
            "access_ttl_s": ACCESS_TTL_S,
            "refresh_ttl_s": REFRESH_TTL_S,
            "lockout_after": MAX_FAILED,
        }


# Values that appear in every breach corpus. Not a substitute for length --
# the 12-character minimum does the real work -- but refusing these costs
# nothing and stops the most common single mistake.
# Every entry MUST be at least 12 characters. A shorter one is dead code: the
# length check rejects it first, so it can never be reached. "password123"
# was in the first version of this set and could never have matched.
_WEAK = {
    "password1234", "passw0rd1234", "123456789012", "qwertyuiop12",
    "letmeinplease", "iloveyou1234", "administrator", "zenozenozeno",
    "changemenow12", "passwordpassword", "qwerty123456", "welcome12345",
}

_SENSITIVE_KEYS = ("password", "token", "secret", "csrf", "refresh", "session",
                   "key", "credential", "otp", "code")


def _scrub(detail: dict[str, Any]) -> dict[str, Any]:
    """Remove anything that must never reach the audit table."""
    clean: dict[str, Any] = {}
    for key, value in detail.items():
        if any(marker in key.lower() for marker in _SENSITIVE_KEYS):
            clean[key] = "[redacted]"
        else:
            clean[key] = str(value)[:160]
    return clean


_service: OwnerAuthService | None = None
_service_lock = threading.Lock()


def get_owner_auth() -> OwnerAuthService:
    global _service
    with _service_lock:
        if _service is None:
            _service = OwnerAuthService()
        return _service


def reset_for_tests(db_path: Path | None = None) -> OwnerAuthService:
    global _service
    with _service_lock:
        _service = OwnerAuthService(db_path)
        return _service
