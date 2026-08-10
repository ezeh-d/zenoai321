"""Secrets, read from the strongest store available -- and never echoed.

PRIORITY, AS THE BRIEF SETS IT
------------------------------
    OS credential store  (Windows Credential Manager, via keyring)
        v
    environment / .env   (development)

Reads walk that order and stop at the first hit, so moving a key into the
credential manager takes effect with no code change. `keyring` is installed
on this machine and Windows provides a real backing store, so this is a
working path rather than a seam.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
There is no `get_all()`, no listing of values, and `__repr__` never contains
a secret. `describe()` reports where each key lives and whether it is set --
never what it is. The brief's three rules (never in logs, never in crash
reports, never in prompts) are easiest to keep when the value is hard to
obtain by accident.

Migration is one-way on purpose: `migrate_to_keyring()` copies from the
environment into the credential store and then tells the owner to remove the
plaintext themselves. Deleting someone's .env line is not ZENO's call.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

SERVICE = "ZENO"

KEYRING = "keyring"
ENVIRONMENT = "environment"
MISSING = "missing"

_lock = threading.Lock()
_backend_checked = False
_keyring_available = False

# Keys ZENO knows about. Used for `describe()` so the owner can see what is
# configured and where, without any value being read.
KNOWN_KEYS = (
    "GEMINI_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "NETLIFY_AUTH_TOKEN",
    "HOME_ASSISTANT_TOKEN", "LANGFUSE_SECRET_KEY", "QDRANT_API_KEY",
)


def _keyring():
    """Import lazily; a missing backend must degrade, not crash startup."""
    global _backend_checked, _keyring_available
    try:
        import keyring as module
        from keyring.backends import fail

        with _lock:
            if not _backend_checked:
                backend = module.get_keyring()
                _keyring_available = not isinstance(backend, fail.Keyring)
                _backend_checked = True
        return module if _keyring_available else None
    except Exception:  # noqa: BLE001
        with _lock:
            _backend_checked, _keyring_available = True, False
        return None


@dataclass(frozen=True)
class Source:
    key: str
    where: str

    @property
    def found(self) -> bool:
        return self.where != MISSING


def get(key: str, default: str = "") -> str:
    """The value, from the strongest store that has it."""
    name = str(key or "").strip()
    if not name:
        return default

    module = _keyring()
    if module is not None:
        try:
            value = module.get_password(SERVICE, name)
            if value:
                return value
        except Exception:  # noqa: BLE001
            pass          # a broken credential store falls through, never raises

    return os.environ.get(name) or default


def source_of(key: str) -> Source:
    """Where a key WOULD be read from. Does not return the value."""
    name = str(key or "").strip()
    module = _keyring()
    if module is not None:
        try:
            if module.get_password(SERVICE, name):
                return Source(name, KEYRING)
        except Exception:  # noqa: BLE001
            pass
    return Source(name, ENVIRONMENT if os.environ.get(name) else MISSING)


def put(key: str, value: str) -> tuple[bool, str]:
    """Store a secret in the OS credential manager."""
    module = _keyring()
    if module is None:
        return False, ("No OS credential store is available here, so I have not "
                       "stored it. Keep using the environment file.")
    try:
        module.set_password(SERVICE, str(key), str(value))
    except Exception as exc:  # noqa: BLE001
        return False, f"could not store it: {type(exc).__name__}"
    return True, f"{key} is now in the Windows Credential Manager"


def forget(key: str) -> bool:
    module = _keyring()
    if module is None:
        return False
    try:
        module.delete_password(SERVICE, str(key))
        return True
    except Exception:  # noqa: BLE001
        return False


def migrate_to_keyring(keys: tuple[str, ...] = KNOWN_KEYS) -> dict[str, Any]:
    """Copy secrets out of the environment into the credential store.

    Copies only. Removing the plaintext afterwards is the owner's decision,
    and this reports exactly which lines are now safe to delete.
    """
    moved, skipped, failed = [], [], []
    for key in keys:
        value = os.environ.get(key)
        if not value:
            skipped.append(key)
            continue
        if source_of(key).where == KEYRING:
            skipped.append(key)
            continue
        ok, _reason = put(key, value)
        (moved if ok else failed).append(key)
    return {
        "moved": moved, "skipped": skipped, "failed": failed,
        "next_step": ("These are now in the Windows Credential Manager. You can "
                      f"remove them from .env yourself: {', '.join(moved)}"
                      if moved else "nothing to migrate"),
    }


def describe() -> dict[str, Any]:
    """Which keys are configured and where -- never what they are."""
    module = _keyring()
    entries = []
    for key in KNOWN_KEYS:
        source = source_of(key)
        entries.append({"key": key, "where": source.where, "set": source.found})
    return {
        "state": "ONLINE" if module is not None else "DEGRADED",
        "os_credential_store": module is not None,
        "backend": "Windows Credential Manager via keyring" if module else "environment only",
        "priority": [KEYRING, ENVIRONMENT],
        "configured": sum(1 for e in entries if e["set"]),
        "in_keyring": sum(1 for e in entries if e["where"] == KEYRING),
        "in_environment": sum(1 for e in entries if e["where"] == ENVIRONMENT),
        "keys": entries,
        "note": "Values are never returned by this call, logged, or put in a prompt.",
    }


status = describe
