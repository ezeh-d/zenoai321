"""The scope. AVA acts only on targets the owner personally authorized.

THIS IS THE WHOLE SAFETY MODEL
------------------------------
An offensive security agent is a security tool when it operates under rules
of engagement, and malware when it does not. The single line between the two
is: *is this target one the owner is allowed to test, and said so?*

So every active operation asks this module first. A target that is not in the
authorization list gets nothing -- no scan, no probe, no exploit, no command
built against it. The owner adds a target explicitly (through a
confirmation-gated tool), with an attestation that they own it or have written
permission, and an expiry. When the engagement ends, it lapses.

This is exactly how a professional penetration test works: a signed scope,
a target list, a start and end date. It is not a limitation on AVA's
capability -- inside the scope she does the full job -- it is what makes the
capability legitimate.

WHAT IS STORED, AND WHAT IS NOT
-------------------------------
A target string, the owner's attestation, when it was authorized and when it
expires, and an audit trail. No credentials, no captured data, no exploit
output -- this module authorizes work, it does not hold its results.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

_DB = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "security" / "scope.sqlite"

# How the owner attested their right to test the target. Anything weaker than
# these is not an authorization.
ATTESTATIONS = {
    "i_own_it": "The owner states they own this target.",
    "written_permission": "The owner holds written permission to test it.",
    "ctf_or_lab": "A deliberately vulnerable CTF, lab or range meant to be attacked.",
    "bug_bounty_scope": "In scope for a published bug-bounty programme.",
    "sanctioned_public": "A host the target's owner has publicly published as legal to test.",
}

# A default engagement lasts this long, then the target must be re-authorized.
# Scope should not outlive the engagement that justified it.
DEFAULT_TTL_S = 30 * 24 * 3600

# Targets that must never be authorized, whatever the owner types. These are
# not the owner's to grant permission over.
_FORBIDDEN_HOSTS = re.compile(
    r"(?:^|\.)(?:gov|mil|police|"
    r"google|gmail|youtube|microsoft|apple|icloud|amazon|aws|azure|"
    r"facebook|meta|instagram|whatsapp|tiktok|twitter|x|paypal|stripe|"
    r"visa|mastercard|cloudflare|github|openai|anthropic)\."
    r"(?:com|net|org|io|gov|mil)$",
    re.IGNORECASE)

# Ranges that belong to everyone / no one -- authorizing them means authorizing
# other people's machines.
_PUBLIC_INFRA = ("8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9")


@dataclass(frozen=True)
class Target:
    value: str
    kind: str            # ip | cidr | hostname | url | app
    attestation: str
    authorized_at: float
    expires_at: float
    note: str = ""

    @property
    def active(self) -> bool:
        return self.expires_at > time.time()

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.value, "kind": self.kind,
                "attestation": self.attestation, "authorized_at": self.authorized_at,
                "expires_at": self.expires_at, "active": self.active, "note": self.note}


@dataclass(frozen=True)
class ScopeCheck:
    allowed: bool
    reason: str
    target: str = ""
    matched: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason,
                "target": self.target, "matched": self.matched}


def classify(target: str) -> str:
    """What kind of thing is this -- an IP, a range, a URL, a hostname?"""
    value = str(target or "").strip()
    if not value:
        return "empty"
    # Bug-bounty programs scope whole subtrees: *.example.com. A wildcard is a
    # first-class target kind, matched against any subdomain by _covers.
    if value.startswith("*.") and re.match(r"^\*\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value):
        return "wildcard"
    if "/" in value and not value.startswith(("http://", "https://")):
        try:
            ipaddress.ip_network(value, strict=False)
            return "cidr"
        except ValueError:
            pass
    if value.startswith(("http://", "https://")):
        return "url"
    try:
        ipaddress.ip_address(value)
        return "ip"
    except ValueError:
        pass
    if re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value):
        return "hostname"
    if re.match(r"^[a-zA-Z0-9 _.-]{1,64}$", value):
        return "app"          # a locally installed application, for host testing
    return "unknown"


def _host_of(target: str, kind: str) -> str:
    if kind == "url":
        return re.sub(r"^https?://", "", target).split("/", 1)[0].split(":", 1)[0]
    if kind == "wildcard":
        return target[2:]          # the base domain, for grantability checks
    return target


def is_grantable(target: str) -> tuple[bool, str]:
    """Whether the owner is even allowed to authorize this target.

    Refuses third-party infrastructure the owner cannot consent for -- a
    stranger's bank, a public DNS resolver, a major platform. The owner may
    genuinely own a server; they do not own paypal.com.
    """
    value = str(target or "").strip()
    kind = classify(value)
    if kind in ("empty", "unknown"):
        return False, "That does not look like a target I can scope (expected an IP, range, hostname or URL)."

    host = _host_of(value, kind)
    if host in _PUBLIC_INFRA:
        return False, f"{host} is shared public infrastructure, not something you can authorize testing of."
    if _FORBIDDEN_HOSTS.search(host):
        return False, (f"{host} belongs to a third party you cannot grant permission over. "
                       "Authorize your own systems, a lab, or a target you have written permission for.")

    if kind in ("ip", "cidr"):
        try:
            net = ipaddress.ip_network(value if kind == "cidr" else f"{value}/32", strict=False)
        except ValueError:
            return False, "That address does not parse."
        # A giant public range is mass-targeting, not a scoped engagement.
        if net.num_addresses > 1024 and net.is_global:
            return False, ("That range is too large and public to be a scoped engagement. "
                           "Scope the specific hosts you are authorized to test.")
    return True, ""


class ScopeStore:
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
                CREATE TABLE IF NOT EXISTS scope(
                    target TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    attestation TEXT NOT NULL,
                    authorized_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    revoked INTEGER NOT NULL DEFAULT 0);

                CREATE TABLE IF NOT EXISTS scope_audit(
                    at REAL NOT NULL,
                    event TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '');
                """)

    def _audit(self, event: str, target: str = "", **detail: Any) -> None:
        with self._connection() as conn:
            conn.execute("INSERT INTO scope_audit(at,event,target,detail) VALUES(?,?,?,?)",
                         (time.time(), event, target, json.dumps(detail)[:400]))

    def authorize(self, target: str, attestation: str, *, ttl_s: float = DEFAULT_TTL_S,
                  note: str = "") -> tuple[bool, str]:
        """Record that the owner authorizes testing of `target`."""
        value = str(target or "").strip()
        if attestation not in ATTESTATIONS:
            return False, (f"Authorization needs a valid attestation, one of: "
                           f"{', '.join(ATTESTATIONS)}.")
        grantable, why = is_grantable(value)
        if not grantable:
            self._audit("authorize_refused", value, reason=why)
            return False, why

        kind = classify(value)
        now = time.time()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO scope(target,kind,attestation,authorized_at,expires_at,note,revoked) "
                "VALUES(?,?,?,?,?,?,0) ON CONFLICT(target) DO UPDATE SET "
                "attestation=excluded.attestation, authorized_at=excluded.authorized_at, "
                "expires_at=excluded.expires_at, note=excluded.note, revoked=0",
                (value, kind, attestation, now, now + ttl_s, note[:200]))
        self._audit("authorized", value, attestation=attestation, kind=kind)
        return True, (f"Authorized {value} ({kind}) for testing, "
                      f"expiring in {int(ttl_s // 86400)} days. AVA may now operate on it.")

    def revoke(self, target: str) -> bool:
        value = str(target or "").strip()
        with self._connection() as conn:
            changed = conn.execute("UPDATE scope SET revoked=1 WHERE target=?", (value,)).rowcount
        if changed:
            self._audit("revoked", value)
        return bool(changed)

    def clear(self) -> int:
        with self._connection() as conn:
            removed = conn.execute("DELETE FROM scope").rowcount
        self._audit("cleared_all", count=removed)
        return int(removed)

    def targets(self, *, active_only: bool = True) -> list[Target]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scope WHERE revoked=0 ORDER BY authorized_at DESC").fetchall()
        out = [Target(r["target"], r["kind"], r["attestation"], r["authorized_at"],
                      r["expires_at"], r["note"]) for r in rows]
        return [t for t in out if t.active] if active_only else out

    def check(self, target: str) -> ScopeCheck:
        """May AVA operate on `target`? The question every active op asks."""
        value = str(target or "").strip()
        if not value:
            return ScopeCheck(False, "No target was given.")
        kind = classify(value)
        host = _host_of(value, kind)

        for authorized in self.targets(active_only=True):
            if self._covers(authorized, value, host, kind):
                return ScopeCheck(True, "Target is within the owner's authorized scope.",
                                  target=value, matched=authorized.value)

        return ScopeCheck(
            False,
            f"{value} is NOT in the authorized scope. AVA only operates on targets you have "
            f"personally authorized. Add it with security_authorize first.",
            target=value)

    @staticmethod
    def _covers(authorized: Target, target: str, host: str, kind: str) -> bool:
        # Exact match, or a URL/host falling under an authorized host.
        if authorized.value == target:
            return True
        # A wildcard covers its base domain and any subdomain of it.
        if authorized.kind == "wildcard":
            base = authorized.value[2:].casefold()   # strip "*."
            h = host.casefold()
            return h == base or h.endswith("." + base)
        auth_host = _host_of(authorized.value, authorized.kind)
        if auth_host and host and auth_host.casefold() == host.casefold():
            return True
        # An IP inside an authorized CIDR.
        if authorized.kind == "cidr" and kind in ("ip", "url", "hostname"):
            try:
                net = ipaddress.ip_network(authorized.value, strict=False)
                return ipaddress.ip_address(host) in net
            except ValueError:
                return False
        return False

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT at,event,target,detail FROM scope_audit ORDER BY at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),)).fetchall()
        return [dict(r) for r in rows]


_store: ScopeStore | None = None
_store_lock = threading.Lock()


def get_scope() -> ScopeStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ScopeStore()
        return _store


def reset_for_tests(db_path: Path | None = None) -> ScopeStore:
    global _store
    with _store_lock:
        _store = ScopeStore(db_path)
        return _store
