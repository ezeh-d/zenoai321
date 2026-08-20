"""Security core for ZENO's browser-based Phone Companion.

This module deliberately keeps the phone surface separate from the desktop
dashboard API.  It stores only public WebAuthn/device credentials, hashes all
bearer-like values at rest and makes device revocation invalidate sessions
immediately.  A local companion may arrive through Wi-Fi or the laptop
hotspot; its cryptographic key, never its IP address, is its identity.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from webauthn import (generate_authentication_options, generate_registration_options,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, options_to_json
from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from reyes_agent import config

PENDING_APPROVAL = "PENDING_APPROVAL"
TRUSTED, LOCKED, REVOKED, EXPIRED = "TRUSTED", "LOCKED", "REVOKED", "EXPIRED"
OWNER, TRUSTED_USER, GUEST, SERVICE = "OWNER", "TRUSTED_USER", "GUEST", "SERVICE"
DEVICE_ROLES = {OWNER, TRUSTED_USER, GUEST, SERVICE}
REMOTE_AUDIO_SEND = "remote_audio_send"
DEVICE_KEY_AUTH, OWNER_AUTH = "DEVICE_KEY", "OWNER_VERIFIED"
DEFAULT_SCOPES = {
    "status", "talk", "missions", "agents", "saved_routines", REMOTE_AUDIO_SEND,
}
PAIR_TTL_S, CHALLENGE_TTL_S, SESSION_TTL_S = 300, 300, 1800
_DB = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "phone" / "devices.sqlite"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _device_key_jwk(value: dict[str, Any]) -> tuple[str, str]:
    """Validate and canonicalise one browser-generated P-256 public key."""
    if not isinstance(value, dict):
        raise ValueError("A cryptographic device public key is required.")
    clean = {key: str(value.get(key, "")) for key in ("kty", "crv", "x", "y")}
    if clean["kty"] != "EC" or clean["crv"] != "P-256":
        raise ValueError("The companion device key must be ECDSA P-256.")
    try:
        if len(base64url_to_bytes(clean["x"])) != 32 or len(base64url_to_bytes(clean["y"])) != 32:
            raise ValueError
    except Exception as exc:
        raise ValueError("The companion device public key is malformed.") from exc
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    return canonical, _hash(canonical)


class PhoneSecurity:
    """Durable pairing, device and session registry; one instance per process."""
    def __init__(self, db_path: Path = _DB) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _connection(self):
        """Commit and close every SQLite handle (essential on Windows)."""
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS pairs(token_hash TEXT PRIMARY KEY, manual_hash TEXT UNIQUE,
              expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0, cancelled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              credential_id TEXT UNIQUE NOT NULL, public_key BLOB NOT NULL, sign_count INTEGER NOT NULL,
              state TEXT NOT NULL, scopes TEXT NOT NULL, created REAL NOT NULL, last_auth REAL, last_activity REAL,
              revoked_at REAL);
            CREATE TABLE IF NOT EXISTS challenges(challenge_hash TEXT PRIMARY KEY, challenge TEXT NOT NULL,
              purpose TEXT NOT NULL, subject TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, device_id TEXT NOT NULL,
              csrf_hash TEXT NOT NULL, expires REAL NOT NULL, last_activity REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS session_auth(token_hash TEXT PRIMARY KEY,
              auth_level TEXT NOT NULL, FOREIGN KEY(token_hash) REFERENCES sessions(token_hash) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS commands(device_id TEXT NOT NULL, command_id TEXT NOT NULL,
              nonce_hash TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(device_id,command_id), UNIQUE(device_id,nonce_hash));
            CREATE TABLE IF NOT EXISTS audit(ts REAL NOT NULL, event TEXT NOT NULL, device_id TEXT, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_roles(device_id TEXT PRIMARY KEY, role TEXT NOT NULL,
              updated REAL NOT NULL, FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
            CREATE UNIQUE INDEX IF NOT EXISTS one_owner_device ON device_roles(role) WHERE role='OWNER';
            CREATE TABLE IF NOT EXISTS companion_devices(
              device_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
              device_type TEXT NOT NULL, browser TEXT NOT NULL,
              device_public_key TEXT NOT NULL, device_key_hash TEXT UNIQUE NOT NULL,
              pinned INTEGER NOT NULL DEFAULT 0, owner_device INTEGER NOT NULL DEFAULT 0,
              preferred_route TEXT NOT NULL DEFAULT 'AUTO', last_network TEXT NOT NULL DEFAULT '',
              last_ip TEXT NOT NULL DEFAULT '', biometric_enabled INTEGER NOT NULL DEFAULT 0,
              created REAL NOT NULL, last_seen REAL, revoked INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(device_id) REFERENCES devices(device_id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS companion_pinned_first
              ON companion_devices(pinned DESC, created DESC);
            """)
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)",
                         (time.time(),))
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(2,?)",
                         (time.time(),))

    def _audit(self, event: str, device_id: str | None = None, **detail: Any) -> None:
        with self._connection() as conn:
            conn.execute("INSERT INTO audit VALUES(?,?,?,?)", (time.time(), event, device_id, json.dumps(detail)))
        try:
            from reyes_agent import event_bus
            event_bus.publish("phone." + event, {"device_id": device_id, **detail}, source="phone-security")
        except Exception:
            pass

    def create_pair(self) -> dict[str, Any]:
        # The QR keeps the full 256-bit random token. The manual fallback is
        # the six-digit format shown in the companion flow; it remains
        # short-lived, rate-limited and single-use.
        token, manual = secrets.token_urlsafe(32), f"{secrets.randbelow(10**6):06d}"
        expires = time.time() + PAIR_TTL_S
        with self._connection() as conn:
            conn.execute("UPDATE pairs SET cancelled=1 WHERE consumed=0")
            conn.execute("INSERT INTO pairs(token_hash,manual_hash,expires) VALUES(?,?,?)",
                         (_hash(token), _hash(manual), expires))
        self._audit("pair_created", expires=expires)
        return {"token": token, "manual_code": manual, "expires_at": expires}

    def cancel_pair(self, token: str) -> None:
        with self._connection() as conn:
            conn.execute("UPDATE pairs SET cancelled=1 WHERE token_hash=?", (_hash(token),))

    def _valid_pair(self, token: str) -> bool:
        return self._pair_hash(token) is not None

    def _pair_hash(self, token_or_manual_code: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM pairs WHERE token_hash=? OR manual_hash=?",
                               (_hash(token_or_manual_code), _hash(token_or_manual_code))).fetchone()
        if not row or row["consumed"] or row["cancelled"] or row["expires"] <= time.time():
            return None
        return row["token_hash"]

    def registration_options(self, pair_token: str, name: str, rp_id: str) -> dict[str, Any]:
        pair_hash = self._pair_hash(pair_token)
        if pair_hash is None:
            raise PermissionError("Pairing link is invalid, expired, or already used.")
        challenge = secrets.token_bytes(32)
        subject = json.dumps({"pair": pair_hash, "name": name[:64]})
        self._save_challenge(challenge, "registration", subject)
        options = generate_registration_options(
            rp_id=rp_id, rp_name=config.ASSISTANT_NAME, user_name="zeno-phone-" + _hash(pair_token)[:12],
            user_id=secrets.token_bytes(32), user_display_name=name[:64], challenge=challenge,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED),
        )
        return json.loads(options_to_json(options))

    def _save_challenge(self, challenge: bytes, purpose: str, subject: str) -> None:
        with self._connection() as conn:
            conn.execute("INSERT INTO challenges VALUES(?,?,?,?,?,0)",
                         (_hash(_b64(challenge)), _b64(challenge), purpose, subject, time.time() + CHALLENGE_TTL_S))

    def _take_challenge(self, challenge: str, purpose: str) -> sqlite3.Row:
        """Consume a verification challenge exactly once.

        The conditional update is the authority here.  A read followed by an
        unconditional update allowed two concurrent requests to both observe
        the same unused challenge before either one marked it consumed.
        """
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE challenge_hash=? AND purpose=?",
                (_hash(challenge), purpose),
            ).fetchone()
            if not row:
                raise PermissionError("Verification challenge expired or was already used.")
            consumed = conn.execute(
                "UPDATE challenges SET used=1 WHERE challenge_hash=? AND purpose=? "
                "AND used=0 AND expires>?",
                (row["challenge_hash"], purpose, now),
            )
            if consumed.rowcount != 1:
                raise PermissionError("Verification challenge expired or was already used.")
        return row

    def finish_registration(self, credential: dict[str, Any], challenge: str, origin: str, rp_id: str) -> str:
        row = self._take_challenge(challenge, "registration")
        subject = json.loads(row["subject"])
        if not self._valid_pair_hash(subject["pair"]):
            raise PermissionError("Pairing link is no longer valid.")
        verified = verify_registration_response(credential=credential, expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
        device_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute("UPDATE pairs SET consumed=1 WHERE token_hash=?", (subject["pair"],))
            conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                device_id, subject["name"], _b64(verified.credential_id), verified.credential_public_key,
                verified.sign_count, PENDING_APPROVAL, json.dumps(sorted(DEFAULT_SCOPES)), time.time(), None, None, None))
            conn.execute("INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?)",
                         (device_id, TRUSTED_USER, time.time()))
        self._audit("device_pending", device_id, name=subject["name"])
        return device_id

    def _issue_session(self, device_id: str, auth_level: str = DEVICE_KEY_AUTH) -> dict[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        now = time.time()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO sessions(token_hash,device_id,csrf_hash,expires,last_activity) VALUES(?,?,?,?,?)",
                (_hash(token), device_id, _hash(csrf), now + SESSION_TTL_S, now),
            )
            conn.execute("INSERT INTO session_auth(token_hash,auth_level) VALUES(?,?)",
                         (_hash(token), auth_level))
        self._audit("session_created", device_id, auth_level=auth_level,
                    expires=now + SESSION_TTL_S)
        return {"session": token, "csrf": csrf, "device_id": device_id,
                "auth_level": auth_level, "expires_at": str(now + SESSION_TTL_S)}

    # ---- standing microphone key -------------------------------------
    # A headset is paired once and then simply works. The one-time token
    # cannot behave that way: it is designed to die. So the microphone gets a
    # STANDING key -- a code that does not expire and can be scanned by a new
    # phone at any time.
    #
    # WHAT KEEPS "NEVER EXPIRES" FROM MEANING "NEVER SAFE":
    #
    #   * It buys ONE permission, remote_audio_send. Not desktop control, not
    #     files, not shell, not mail, not memory. Identical to the one-time
    #     path -- the key is longer-lived, never wider.
    #   * It is refused from anywhere that is not this machine's own local
    #     network. A photographed QR is useless to someone who is not already
    #     on the owner's Wi-Fi or hotspot.
    #   * It is rotatable in one call, which kills every old QR at once.
    #   * Every use is audited, and each paired phone stays revocable on its
    #     own without disturbing the others.
    #
    # It is stored in plaintext because a QR has to be REGENERATABLE -- the
    # same reason Windows keeps your Wi-Fi password rather than its hash. The
    # file sits in LOCALAPPDATA under the owner's account.
    def mic_key(self) -> str:
        """The standing microphone key, created once on first use."""
        with self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS mic_key("
                         "id INTEGER PRIMARY KEY CHECK(id=1), key TEXT NOT NULL,"
                         " created REAL NOT NULL, rotated REAL)")
            row = conn.execute("SELECT key FROM mic_key WHERE id=1").fetchone()
            if row:
                return str(row["key"])
            key = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO mic_key(id,key,created) VALUES(1,?,?)",
                         (key, time.time()))
        self._audit("mic_key_created")
        return key

    def rotate_mic_key(self) -> str:
        """Issue a new standing key. Every previously printed QR stops working."""
        key = secrets.token_urlsafe(32)
        with self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS mic_key("
                         "id INTEGER PRIMARY KEY CHECK(id=1), key TEXT NOT NULL,"
                         " created REAL NOT NULL, rotated REAL)")
            conn.execute("INSERT INTO mic_key(id,key,created,rotated) VALUES(1,?,?,?) "
                         "ON CONFLICT(id) DO UPDATE SET key=excluded.key,"
                         " rotated=excluded.rotated",
                         (key, time.time(), time.time()))
        self._audit("mic_key_rotated")
        return key

    def guest_mic_key(self) -> str:
        """A SECOND standing key that pairs a listen-only microphone.

        Two keys rather than one key with a flag, because the grant must be
        a property of the CODE and not of the request that presents it. A
        phone holding this code cannot ask for more: there is no parameter to
        change, no field to omit, and nothing the page could send that would
        widen it. Somebody who photographs this QR gets a microphone.

        This is what a visitor's phone should scan. The owner's phone scans
        the other one.
        """
        # Its OWN table. The original mic_key was created with CHECK(id=1),
        # and SQLite cannot alter a CHECK constraint -- widening it would mean
        # rebuilding a table that holds a live credential, which is not a
        # thing to do for tidiness. A separate table also makes the two keys
        # impossible to confuse in a query.
        with self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS guest_mic_key("
                         "id INTEGER PRIMARY KEY CHECK(id=1), key TEXT NOT NULL,"
                         " created REAL NOT NULL, rotated REAL)")
            row = conn.execute("SELECT key FROM guest_mic_key WHERE id=1").fetchone()
            if row:
                return str(row["key"])
            key = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO guest_mic_key(id,key,created) VALUES(1,?,?)",
                         (key, time.time()))
        self._audit("guest_mic_key_created")
        return key

    def refresh_local_scopes(self) -> dict[str, Any]:
        """Bring already-paired phones up to the current grant.

        A phone paired before this grant widened would otherwise keep the
        old audio-only scopes until it was re-paired -- so the owner would
        scan a fresh code to fix something that is not his mistake. Only
        devices paired by the standing microphone key are touched, and every
        change is audited.
        """
        changed: list[str] = []
        want = sorted(DEFAULT_SCOPES)
        with self._connection() as conn:
            rows = conn.execute(
                # BOTH local pairing paths. The first version matched only
                # 'mic-key:%' and left phones paired by the earlier one-time
                # token stuck on audio-only -- the owner would have had to
                # work out which code he had scanned to know why one phone
                # obeyed and another did not.
                "SELECT device_id,name,scopes FROM devices "
                "WHERE state=? AND (credential_id LIKE 'mic-key:%' "
                "                   OR credential_id LIKE 'local-token:%')",
                (TRUSTED,)).fetchall()
            for row in rows:
                if sorted(json.loads(row["scopes"])) == want:
                    continue
                conn.execute("UPDATE devices SET scopes=? WHERE device_id=?",
                             (json.dumps(want), row["device_id"]))
                changed.append(str(row["name"]))
        for name in changed:
            self._audit("local_device_scopes_refreshed", name=name, scopes=want)
        return {"upgraded": len(changed), "devices": changed, "scopes": want}

    def pair_with_mic_key(self, key: str, device_name: str,
                          peer_ip: str = "") -> dict[str, Any]:
        """Pair a phone with the standing key. No expiry, still audio-only.

        `peer_ip` is the address the request genuinely arrived from, and it
        is CHECKED, not recorded. This is what makes a non-expiring code
        acceptable: the key alone is not enough, the phone must also already
        be on a network this laptop is on.
        """
        supplied = (key or "").strip()
        if not supplied:
            raise PermissionError(
                "That microphone code is not valid for this computer. It may "
                "have been replaced -- show the QR code again.")

        # WHICH key was presented decides the grant. The request cannot
        # influence it: a guest code has no path to anything but audio.
        if secrets.compare_digest(supplied, self.mic_key()):
            granted, kind = sorted(DEFAULT_SCOPES), "OWNER"
        elif secrets.compare_digest(supplied, self.guest_mic_key()):
            granted, kind = [REMOTE_AUDIO_SEND], "GUEST"
        else:
            raise PermissionError(
                "That microphone code is not valid for this computer. It may "
                "have been replaced -- show the QR code again.")

        if not self._is_local_peer(peer_ip):
            self._audit("mic_key_rejected_remote", detail=peer_ip[:40])
            raise PermissionError(
                "The microphone code only works from this computer's own "
                "Wi-Fi or hotspot. Connect the phone to one of them first.")

        name = (str(device_name or "").strip() or "Phone")[:60]
        device_id = str(uuid.uuid4())

        # THE PHONE IS A MICROPHONE, NOT A LESSER PRINCIPAL.
        #
        # It first carried REMOTE_AUDIO_SEND alone, and that was right for a
        # pairing credential considered on its own. But it made the remote
        # microphone useless: every sentence was transcribed perfectly and
        # then refused with "this device does not have the 'status' scope" --
        # ZENO could hear the owner and was not allowed to answer him.
        #
        # The owner's voice through his own phone is the owner speaking. The
        # phone is the conduit; the authority belongs to the person. So a
        # locally-paired phone now carries the same scopes a passkey-verified
        # device does.
        #
        # WHAT DOES NOT WIDEN, AND CANNOT: money movement and security or
        # credential changes are refused by CATEGORY in remote_access.policy,
        # before scopes are ever consulted. No scope grants them, so a lost
        # phone still cannot start either one -- which was the actual point
        # of keeping the grant narrow.
        scopes = granted
        now = time.time()
        with self._connection() as conn:
            conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                device_id, name, f"mic-key:{device_id}", b"", 0, TRUSTED,
                json.dumps(scopes), now, None, None, None))
            conn.execute("INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?)",
                         (device_id, TRUSTED_USER, now))
        # The session still expires even though the standing key does not. Use
        # the authoritative session issuer so the base session and its auth
        # level stay consistent after the v2 schema split.
        issued = self._issue_session(device_id, DEVICE_KEY_AUTH)
        self._audit("device_paired_mic_key", device_id, name=name,
                    peer=peer_ip[:40], grant=kind)
        return {"device_id": device_id, "name": name, "state": TRUSTED,
                "scopes": scopes, "method": f"STANDING_MIC_KEY_{kind}",
                "grant": kind,
                "session": issued["session"], "csrf": issued["csrf"]}

    @staticmethod
    def _is_local_peer(peer_ip: str) -> bool:
        """Is this address on one of THIS machine's own local networks.

        Subnet membership against the laptop's live adapters, so it follows
        the machine onto a new Wi-Fi without configuration. Loopback counts:
        that is the owner testing from the desktop itself.
        """
        try:
            from reyes_agent.remote_mic import routes

            # Addresses only -- deliberately NOT the full route list, which
            # shells out to PowerShell for adapter descriptions. That check
            # belongs in a dashboard, not on the pairing path, where it once
            # made this request hang for seconds.
            return routes.is_local_address(peer_ip)
        except Exception:  # noqa: BLE001
            # Fail CLOSED. If the local networks cannot be determined, a
            # never-expiring key is exactly the wrong thing to accept.
            return False

    def pair_local(self, token: str, device_name: str) -> dict[str, Any]:
        """Pair over the LAN with a one-time token instead of WebAuthn.

        WebAuthn cannot work on an http:// origin -- `navigator.credentials`
        needs a secure context, and even behind Chrome's secure-origin flag
        the relying-party checks are built for a real HTTPS host. On the LAN
        that leaves the phone stuck on "Verify this device" forever, which is
        exactly the symptom this exists to remove.

        The token carries the trust instead: it is 32 random URL-safe bytes,
        stored only as a hash, single-use, and expires with PAIR_TTL_S.
        Consuming it is what proves the person holding the phone also had
        physical access to this screen.

        THE SCOPE IS THE POINT. A LAN-paired phone gets REMOTE_AUDIO_SEND and
        NOTHING else -- no desktop control, no filesystem, no shell, no
        memory, no mail. It is a microphone, so it is allowed to be a
        microphone. `finish_registration` grants DEFAULT_SCOPES because it
        proved possession of a hardware credential; this proved possession of
        a QR code, which is a weaker claim and gets a narrower grant.
        """
        pair_hash = self._pair_hash(token)
        if pair_hash is None:
            raise PermissionError(
                "That pairing code has expired or was already used. "
                "Generate a new QR code on the computer.")

        name = (str(device_name or "").strip() or "Phone")[:60]
        device_id = str(uuid.uuid4())
        scopes = [REMOTE_AUDIO_SEND]

        with self._connection() as conn:
            conn.execute("UPDATE pairs SET consumed=1 WHERE token_hash=?", (pair_hash,))
            conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                # `credential_id` and `public_key` are NOT NULL -- the schema
                # was written for WebAuthn, where every device has one. A
                # LAN-paired phone has no credential, so it carries a marked
                # sentinel rather than a null: it keeps the constraint honest
                # AND makes token-paired devices identifiable at a glance,
                # which matters because they are the weaker trust.
                device_id, name, f"local-token:{device_id}", b"", 0, TRUSTED,
                json.dumps(scopes), time.time(), None, None, None))
            conn.execute("INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?)",
                         (device_id, TRUSTED_USER, time.time()))

        # Open the session here rather than making the phone log in again.
        # There is nothing else it COULD log in with: a token-paired device has
        # no passkey, so a second step would only be a second thing to fail.
        # Possession of the one-time token was the proof, and it is now spent.
        issued = self._issue_session(device_id, DEVICE_KEY_AUTH)
        self._audit("device_paired_local", device_id, name=name, scopes=scopes)
        return {"device_id": device_id, "name": name, "state": TRUSTED,
                "scopes": scopes, "method": "ONE_TIME_TOKEN",
                "session": issued["session"], "csrf": issued["csrf"]}

    def pair_companion_local(self, token: str, device_name: str,
                             device_public_key: dict[str, Any],
                             browser: str = "Chrome") -> dict[str, Any]:
        """Register one local browser installation pending desktop approval.

        The one-time QR token proves physical proximity.  The P-256 key is
        the durable device identity used on later reconnects; no IP address,
        canvas value, user-agent fingerprint or biometric material is used.
        Full companion scopes are inactive until the PC owner explicitly
        changes the device from PENDING_APPROVAL to TRUSTED.
        """
        canonical_key, key_hash = _device_key_jwk(device_public_key)
        pair_hash = self._pair_hash(token)
        if pair_hash is None:
            raise PermissionError(
                "That pairing code has expired or was already used. Generate a new QR code on the computer."
            )
        display_name = (str(device_name or "").strip() or "Divine's Redmi 14C")[:64]
        browser_name = (str(browser or "").strip() or "Chrome")[:32]
        now = time.time()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT c.device_id,d.state FROM companion_devices c "
                "JOIN devices d ON d.device_id=c.device_id WHERE c.device_key_hash=?",
                (key_hash,),
            ).fetchone()
            if existing:
                if existing["state"] == REVOKED:
                    raise PermissionError("This companion device was revoked and must be paired again with a new key.")
                conn.execute("UPDATE pairs SET consumed=1 WHERE token_hash=?", (pair_hash,))
                conn.execute(
                    "UPDATE companion_devices SET display_name=?,browser=?,last_seen=? WHERE device_id=?",
                    (display_name, browser_name, now, existing["device_id"]),
                )
                device_id = existing["device_id"]
                state = existing["state"]
            else:
                device_id = str(uuid.uuid4())
                conn.execute("UPDATE pairs SET consumed=1 WHERE token_hash=?", (pair_hash,))
                conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    device_id, display_name, f"device-key:{key_hash}", b"", 0,
                    PENDING_APPROVAL, json.dumps(sorted(DEFAULT_SCOPES)), now,
                    None, None, None))
                owner_exists = conn.execute(
                    "SELECT 1 FROM companion_devices WHERE owner_device=1 AND revoked=0 LIMIT 1"
                ).fetchone()
                pinned, owner_device = (0, 0) if owner_exists else (1, 1)
                conn.execute(
                    "INSERT INTO companion_devices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (device_id, display_name, "ANDROID_PHONE", browser_name,
                     canonical_key, key_hash, pinned, owner_device, "AUTO", "", "",
                     0, now, now, 0),
                )
                role = OWNER if owner_device else TRUSTED_USER
                try:
                    conn.execute("INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?)",
                                 (device_id, role, now))
                except sqlite3.IntegrityError:
                    conn.execute("INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?)",
                                 (device_id, TRUSTED_USER, now))
                state = PENDING_APPROVAL
        self._audit("device_pinned", device_id, name=display_name, state=state,
                    browser=browser_name)
        metadata = self._companion(device_id)
        return {"device_id": device_id, "display_name": display_name,
                "state": state, "pinned": bool(metadata and metadata["pinned"]),
                "owner_device": bool(metadata and metadata["owner_device"]),
                "biometric_enabled": bool(metadata and metadata["biometric_enabled"]),
                "method": "DEVICE_KEY_PENDING_APPROVAL"}

    def _valid_pair_hash(self, token_hash: str) -> bool:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM pairs WHERE token_hash=?", (token_hash,)).fetchone()
        return bool(row and not row["cancelled"] and row["expires"] > time.time())

    def pairing_status(self, device_id: str) -> dict[str, Any]:
        device = self._device(device_id)
        meta = self._companion(device_id)
        return {"device_id": device_id, "state": device["state"],
                "display_name": meta["display_name"] if meta else device["name"],
                "pinned": bool(meta and meta["pinned"]),
                "owner_device": bool(meta and meta["owner_device"]),
                "biometric_enabled": bool(meta and meta["biometric_enabled"])}

    def _companion(self, device_id: str) -> sqlite3.Row | None:
        with self._connection() as conn:
            return conn.execute(
                "SELECT * FROM companion_devices WHERE device_id=?", (device_id,)
            ).fetchone()

    def device_authentication_options(self, device_id: str) -> dict[str, Any]:
        device = self._device(device_id, trusted=True)
        meta = self._companion(device_id)
        if not meta or not meta["device_public_key"] or meta["revoked"]:
            raise PermissionError("This browser has no active companion device credential.")
        challenge = secrets.token_bytes(32)
        self._save_challenge(challenge, "device-authentication", device_id)
        return {"challenge": _b64(challenge), "device_id": device_id,
                "display_name": meta["display_name"],
                "biometric_required": bool(meta["biometric_enabled"]),
                "state": device["state"]}

    @staticmethod
    def _verify_device_signature(public_jwk: str, challenge: str, signature: str) -> None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        jwk = json.loads(public_jwk)
        x = int.from_bytes(base64url_to_bytes(jwk["x"]), "big")
        y = int.from_bytes(base64url_to_bytes(jwk["y"]), "big")
        key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        raw = base64url_to_bytes(signature)
        if len(raw) == 64:  # WebCrypto returns IEEE-P1363 r||s for ECDSA.
            raw = encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                       int.from_bytes(raw[32:], "big"))
        key.verify(raw, challenge.encode("ascii"), ec.ECDSA(hashes.SHA256()))

    def finish_device_authentication(self, device_id: str, challenge: str,
                                     signature: str) -> dict[str, Any]:
        row = self._take_challenge(challenge, "device-authentication")
        if row["subject"] != device_id:
            raise PermissionError("The device authentication challenge does not match this device.")
        self._device(device_id, trusted=True)
        meta = self._companion(device_id)
        if not meta or meta["revoked"]:
            raise PermissionError("This companion device was revoked.")
        try:
            self._verify_device_signature(meta["device_public_key"], challenge, signature)
        except Exception as exc:
            self._audit("auth_failure", device_id, method="DEVICE_KEY")
            raise PermissionError("The companion device signature was invalid.") from exc
        with self._connection() as conn:
            conn.execute("UPDATE companion_devices SET last_seen=? WHERE device_id=?",
                         (time.time(), device_id))
        if meta["biometric_enabled"]:
            self._audit("device_recognized", device_id, biometric_required=True)
            return {"device_id": device_id, "state": "BIOMETRIC_REQUIRED",
                    "biometric_required": True}
        issued = self._issue_session(device_id, DEVICE_KEY_AUTH)
        self._audit("auth_success", device_id, method="DEVICE_KEY",
                    owner_authenticated=False)
        return {**issued, "state": "DEVICE_AUTHENTICATED",
                "biometric_required": False, "owner_authenticated": False}

    def webauthn_enrollment_options(self, device_id: str, rp_id: str) -> dict[str, Any]:
        device = self._device(device_id, trusted=True)
        meta = self._companion(device_id)
        if not meta:
            raise PermissionError("This is not a companion device.")
        challenge = secrets.token_bytes(32)
        self._save_challenge(challenge, "webauthn-enrollment", device_id)
        options = generate_registration_options(
            rp_id=rp_id, rp_name=config.ASSISTANT_NAME,
            user_name="zeno-owner-" + device_id[:12],
            user_id=hashlib.sha256(device_id.encode("utf-8")).digest(),
            user_display_name=meta["display_name"], challenge=challenge,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED),
        )
        return json.loads(options_to_json(options))

    def finish_webauthn_enrollment(self, device_id: str, credential: dict[str, Any],
                                   challenge: str, origin: str, rp_id: str) -> dict[str, Any]:
        row = self._take_challenge(challenge, "webauthn-enrollment")
        if row["subject"] != device_id:
            raise PermissionError("The enrollment challenge does not match this device.")
        self._device(device_id, trusted=True)
        verified = verify_registration_response(
            credential=credential, expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
        with self._connection() as conn:
            conn.execute(
                "UPDATE devices SET credential_id=?,public_key=?,sign_count=? WHERE device_id=?",
                (_b64(verified.credential_id), verified.credential_public_key,
                 verified.sign_count, device_id),
            )
            conn.execute(
                "UPDATE companion_devices SET biometric_enabled=1,last_seen=? WHERE device_id=?",
                (time.time(), device_id),
            )
        self._audit("webauthn_registered", device_id)
        return {"device_id": device_id, "state": "WEBAUTHN_ENROLLED",
                "biometric_enabled": True}

    def authentication_options(self, device_id: str, rp_id: str) -> dict[str, Any]:
        device = self._device(device_id, trusted=True)
        meta = self._companion(device_id)
        if meta and not meta["biometric_enabled"]:
            raise PermissionError("Platform user verification is not enrolled for this device.")
        if str(device["credential_id"]).startswith(("local-token:", "device-key:")):
            raise PermissionError("Platform user verification is not enrolled for this device.")
        challenge = secrets.token_bytes(32)
        self._save_challenge(challenge, "authentication", device_id)
        options = generate_authentication_options(rp_id=rp_id, challenge=challenge,
            allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(device["credential_id"]))],
            user_verification=UserVerificationRequirement.REQUIRED)
        return json.loads(options_to_json(options))

    def finish_authentication(self, credential: dict[str, Any], challenge: str, origin: str, rp_id: str) -> dict[str, str]:
        challenge_row = self._take_challenge(challenge, "authentication")
        device = self._device(challenge_row["subject"], trusted=True)
        verified = verify_authentication_response(credential=credential, expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id, expected_origin=origin, credential_public_key=device["public_key"],
            credential_current_sign_count=device["sign_count"], require_user_verification=True)
        now = time.time()
        with self._connection() as conn:
            conn.execute("UPDATE devices SET sign_count=?,last_auth=?,last_activity=? WHERE device_id=?",
                         (verified.new_sign_count, now, now, device["device_id"]))
        issued = self._issue_session(device["device_id"], OWNER_AUTH)
        self._audit("auth_success", device["device_id"], method="WEBAUTHN",
                    owner_authenticated=True)
        return issued

    def _device(self, device_id: str, trusted: bool = False) -> sqlite3.Row:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row or (trusted and row["state"] != TRUSTED):
            raise PermissionError("This device is not trusted.")
        return row

    def is_device_trusted(self, device_id: str) -> bool:
        """Cheap revocation check used by long-lived media sessions."""
        try:
            self._device(device_id, trusted=True)
            return True
        except PermissionError:
            return False

    def session(self, token: str, csrf: str = "", require_csrf: bool = False) -> sqlite3.Row:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.*,d.state,d.name,d.scopes,COALESCE(r.role,?) AS role,"
                "COALESCE(a.auth_level,?) AS auth_level "
                "FROM sessions s JOIN devices d ON d.device_id=s.device_id "
                "LEFT JOIN device_roles r ON r.device_id=d.device_id "
                "LEFT JOIN session_auth a ON a.token_hash=s.token_hash WHERE s.token_hash=?",
                (TRUSTED_USER, DEVICE_KEY_AUTH, _hash(token)),
            ).fetchone()
            if not row or row["expires"] < time.time() or row["state"] != TRUSTED:
                raise PermissionError("Phone session expired, locked, or revoked.")
            if require_csrf and (not csrf or not secrets.compare_digest(row["csrf_hash"], _hash(csrf))):
                raise PermissionError("Invalid request protection token.")
            conn.execute("UPDATE sessions SET last_activity=? WHERE token_hash=?", (time.time(), _hash(token)))
            conn.execute("UPDATE devices SET last_activity=? WHERE device_id=?", (time.time(), row["device_id"]))
        return row

    def devices(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT d.device_id,COALESCE(c.display_name,d.name) AS name,d.state,d.scopes,"
                "d.created,d.last_auth,d.last_activity,d.revoked_at,COALESCE(r.role,?) AS role,"
                "COALESCE(c.device_type,'PHONE') AS device_type,COALESCE(c.browser,'') AS browser,"
                "COALESCE(c.pinned,0) AS pinned,COALESCE(c.owner_device,0) AS owner_device,"
                "COALESCE(c.preferred_route,'AUTO') AS preferred_route,"
                "COALESCE(c.last_network,'') AS last_network,COALESCE(c.last_ip,'') AS last_ip,"
                "COALESCE(c.biometric_enabled,0) AS biometric_enabled,COALESCE(c.revoked,0) AS companion_revoked "
                "FROM devices d LEFT JOIN device_roles r ON r.device_id=d.device_id "
                "LEFT JOIN companion_devices c ON c.device_id=d.device_id "
                "ORDER BY COALESCE(c.pinned,0) DESC,d.created DESC", (TRUSTED_USER,)
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["scopes"] = json.loads(row["scopes"])
            for key in ("pinned", "owner_device", "biometric_enabled", "companion_revoked"):
                item[key] = bool(item[key])
            item["authentication"] = (
                "WEBAUTHN_ENROLLED" if item["biometric_enabled"] else
                ("DEVICE_KEY" if item["device_type"] == "ANDROID_PHONE" else "PASSKEY_OR_LOCAL_TOKEN")
            )
            output.append(item)
        return output

    def record_connection(self, device_id: str, network: str, ip: str) -> None:
        now = time.time()
        changed = False
        with self._connection() as conn:
            current = conn.execute(
                "SELECT last_network,last_ip FROM companion_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
            changed = bool(current and (
                current["last_network"] != str(network or "")[:32] or
                current["last_ip"] != str(ip or "")[:64]
            ))
            conn.execute(
                "UPDATE companion_devices SET last_network=?,last_ip=?,last_seen=? WHERE device_id=?",
                (str(network or "")[:32], str(ip or "")[:64], now, device_id),
            )
        if changed:
            self._audit("network_changed", device_id, network=str(network or "")[:32])

    def set_preferred_route(self, device_id: str, route: str) -> None:
        value = str(route or "AUTO").strip().upper()
        if value not in {"AUTO", "LAN_WIFI", "LAPTOP_HOTSPOT"}:
            raise ValueError("Preferred route must be AUTO, LAN_WIFI or LAPTOP_HOTSPOT.")
        self._device(device_id, trusted=True)
        with self._connection() as conn:
            updated = conn.execute(
                "UPDATE companion_devices SET preferred_route=? WHERE device_id=?",
                (value, device_id),
            )
            if updated.rowcount != 1:
                raise ValueError("This is not a pinned companion device.")
        self._audit("preferred_route_changed", device_id, route=value)

    def set_role(self, device_id: str, role: str) -> None:
        role = str(role or "").strip().upper()
        if role not in DEVICE_ROLES:
            raise ValueError("Invalid device role")
        self._device(device_id)
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO device_roles(device_id,role,updated) VALUES(?,?,?) "
                    "ON CONFLICT(device_id) DO UPDATE SET role=excluded.role,updated=excluded.updated",
                    (device_id, role, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("An OWNER phone is already assigned; demote it first.") from exc
        self._audit("device_role_changed", device_id, role=role)

    def set_device(self, device_id: str, state: str | None = None, scopes: set[str] | None = None) -> None:
        if state and state not in {TRUSTED, LOCKED, REVOKED, EXPIRED}:
            raise ValueError("Invalid device state")
        with self._connection() as conn:
            if state:
                conn.execute("UPDATE devices SET state=?,revoked_at=? WHERE device_id=?", (state, time.time() if state == REVOKED else None, device_id))
            if scopes is not None:
                conn.execute("UPDATE devices SET scopes=? WHERE device_id=?", (json.dumps(sorted(scopes)), device_id))
            if state in {LOCKED, REVOKED}:
                conn.execute(
                    "DELETE FROM session_auth WHERE token_hash IN "
                    "(SELECT token_hash FROM sessions WHERE device_id=?)", (device_id,))
                conn.execute("DELETE FROM sessions WHERE device_id=?", (device_id,))
            if state == REVOKED:
                conn.execute("UPDATE companion_devices SET revoked=1 WHERE device_id=?", (device_id,))
        self._audit("device_" + (state or "scopes_changed").lower(), device_id)

    def end_sessions(self, device_id: str | None = None) -> None:
        with self._connection() as conn:
            if device_id:
                conn.execute(
                    "DELETE FROM session_auth WHERE token_hash IN "
                    "(SELECT token_hash FROM sessions WHERE device_id=?)", (device_id,))
            else:
                conn.execute("DELETE FROM session_auth")
            conn.execute("DELETE FROM sessions" + (" WHERE device_id=?" if device_id else ""), ((device_id,) if device_id else ()))
        self._audit("sessions_ended", device_id)

    def claim_command(self, device_id: str, command_id: str, nonce: str) -> bool:
        """Atomically reject command-id or nonce replay for the device."""
        try:
            with self._connection() as conn:
                conn.execute("DELETE FROM commands WHERE created<?", (time.time() - 3600,))
                conn.execute("INSERT INTO commands VALUES(?,?,?,?)", (device_id, command_id, _hash(nonce), time.time()))
            return True
        except sqlite3.IntegrityError:
            self._audit("command_replayed", device_id, command_id=command_id)
            return False


_security: PhoneSecurity | None = None
_security_lock = threading.Lock()
def get_phone_security() -> PhoneSecurity:
    global _security
    with _security_lock:
        if _security is None:
            _security = PhoneSecurity()
        return _security
