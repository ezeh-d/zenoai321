"""Which services are actually connected, and exactly what they may do.

A connection is not a boolean. "Gmail is connected" is the sentence that
hides everything that matters -- connected by whom, with which scopes, able
to send or only to read, and revocable how.

So a connection records the tier that was GRANTED, and every use is checked
against it. Asking to send from a mailbox connected read-only is refused
here, before any request is built, rather than failing at the provider with
a 403 the owner has to interpret.

WHAT IS NOT STORED
------------------
Tokens. `security/secrets` holds those, under a per-service key, and this
records only that a credential should exist there. A connection registry
that also stores secrets is a single file that leaks an entire digital life.

CONNECTING IS THE OWNER'S ACT
-----------------------------
`begin()` produces instructions. It cannot complete an OAuth flow, and it
must not: consent screens exist so a person reads the scopes, and an
assistant that clicks through them has removed the only checkpoint.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.connectors import catalog

# States a connection moves through.
NOT_CONNECTED = "NOT_CONNECTED"
AWAITING_OWNER = "AWAITING_OWNER"
CONNECTED = "CONNECTED"
EXPIRED = "EXPIRED"
REVOKED = "REVOKED"

STATES = (NOT_CONNECTED, AWAITING_OWNER, CONNECTED, EXPIRED, REVOKED)

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] | None = None


def _path() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "integrations" / "connections.json"


def secret_key(service_key: str) -> str:
    """Where the credential lives in the secret store. Never the value."""
    return f"INTEGRATION_{str(service_key).upper()}_TOKEN"


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _path()
        try:
            _cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            _cache = {}
        return _cache


def _save() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(_load(), handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def begin(service_key: str, *, intent: str = "") -> dict[str, Any]:
    """What the owner has to do to connect this, at the narrowest useful tier."""
    service = catalog.get(service_key)
    if service is None:
        return {"ok": False, "say": f"I don't know a service called '{service_key}'."}

    tier = catalog.minimum_for(intent)
    if tier not in service.scopes:
        tier = next((t for t in reversed(service.tiers())
                     if catalog.TIERS.index(t) <= catalog.TIERS.index(tier)),
                    service.tiers()[0] if service.tiers() else catalog.READ)
    scopes = service.scopes_up_to(tier)

    with _lock:
        _load()[service.key] = {
            "service": service.key, "state": AWAITING_OWNER, "tier": tier,
            "scopes": scopes, "requested_at": time.time(), "connected_at": 0.0,
            "note": intent[:200]}
        _save()

    return {
        "ok": True, "state": AWAITING_OWNER, "service": service.name, "tier": tier,
        "scopes": scopes,
        "say": (f"To do that I need {service.name} connected at '{tier}' level, which "
                f"means these scopes: {', '.join(scopes)}. "
                + (f"Sign in with your {service.provider_hint} and approve exactly "
                   "those — I can't click through a consent screen for you, and you "
                   "should be the one who reads it."
                   if service.auth == "oauth" else
                   f"Create {service.provider_hint} limited to those scopes and store "
                   f"it as {secret_key(service.key)}.")),
        "credential_key": secret_key(service.key),
        "consequential": tier in catalog.CONSEQUENTIAL,
    }


def confirm(service_key: str, *, tier: str = "", by: str = "owner") -> tuple[bool, str]:
    """The owner says the flow is done. Verified against the secret store."""
    service = catalog.get(service_key)
    if service is None:
        return False, f"unknown service '{service_key}'"

    try:
        from reyes_agent.security import secrets

        present = bool(secrets.get(secret_key(service.key)))
    except Exception:  # noqa: BLE001
        present = False
    if not present:
        return False, (f"I can't find a credential for {service.name} yet. Store it as "
                       f"{secret_key(service.key)} and tell me again — I will not "
                       "record a connection I cannot see.")

    with _lock:
        record = _load().get(service.key, {})
        granted = tier or record.get("tier") or catalog.READ
        _load()[service.key] = {
            **record, "service": service.key, "state": CONNECTED,
            "tier": granted, "scopes": service.scopes_up_to(granted),
            "connected_at": time.time(), "connected_by": by}
        _save()
    _refresh_capabilities()
    return True, f"{service.name} is connected at '{granted}' level."


def revoke(service_key: str) -> tuple[bool, str]:
    with _lock:
        record = _load().get(str(service_key).lower())
        if record is None:
            return False, "that was not connected"
        record["state"] = REVOKED
        record["revoked_at"] = time.time()
        _save()
    _refresh_capabilities()
    return True, (f"{service_key} is revoked here. Remove the token from your account's "
                  "settings too — I can forget it, but only you can withdraw it.")


def get(service_key: str) -> dict[str, Any] | None:
    return _load().get(str(service_key or "").strip().lower())


def connected(service_key: str) -> bool:
    record = get(service_key)
    return bool(record and record.get("state") == CONNECTED)


def may(service_key: str, intent: str) -> tuple[bool, str]:
    """Is this intent within the tier that was actually granted."""
    service = catalog.get(service_key)
    record = get(service_key)
    if service is None:
        return False, f"unknown service '{service_key}'"
    if not record or record.get("state") != CONNECTED:
        return False, f"{service.name} is not connected"

    granted = record.get("tier", catalog.READ)
    needed = catalog.minimum_for(intent)
    if catalog.TIERS.index(needed) > catalog.TIERS.index(granted):
        return False, (f"{service.name} is connected at '{granted}' level and that "
                       f"needs '{needed}'. Reconnect at the higher level if you want "
                       "me to do it — I will not quietly use more access than you gave.")
    return True, f"within the '{granted}' access you granted"


def for_capability(capability_name: str) -> dict[str, Any]:
    """Which connection (if any) satisfies a capability the registry wants."""
    options = catalog.for_capability(capability_name)
    live = [s for s in options if connected(s.key)]
    return {"capability": capability_name,
            "satisfied_by": [s.key for s in live],
            "options": [s.as_dict() for s in options],
            "connected": bool(live)}


def _refresh_capabilities() -> None:
    """A new connection can unblock a capability, so re-detect."""
    try:
        from reyes_agent.capabilities import inventory

        inventory.invalidate()
    except Exception:  # noqa: BLE001
        pass


def all_connections() -> list[dict[str, Any]]:
    return sorted(_load().values(), key=lambda r: r.get("service", ""))


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def status() -> dict[str, Any]:
    records = all_connections()
    live = [r for r in records if r.get("state") == CONNECTED]
    return {
        "state": "ONLINE",
        "connected": [r["service"] for r in live],
        "awaiting_owner": [r["service"] for r in records
                           if r.get("state") == AWAITING_OWNER],
        "tiers_granted": {r["service"]: r.get("tier") for r in live},
        "available_to_connect": len(catalog.all_services()),
        "note": ("Tokens live in the secret store, never here. A connection records "
                 "the tier that was granted, and every use is checked against it "
                 "before a request is built."),
    }
