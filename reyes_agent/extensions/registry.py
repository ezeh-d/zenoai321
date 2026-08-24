"""Atomic, redacted extension catalog and rollback metadata."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent.extensions.models import (
    ACTIVE, APPROVAL, BENCHMARK, BROKEN, CANARY, COMPATIBILITY_REVIEW,
    DISCOVERED, DISABLED, INSPECTING, QUARANTINED, REJECTED, REMOVED,
    SANDBOX_TEST, SECURITY_REVIEW,
)

_ALLOWED: dict[str, set[str]] = {
    DISCOVERED: {INSPECTING, REJECTED, REMOVED},
    INSPECTING: {SECURITY_REVIEW, REJECTED, QUARANTINED, BROKEN},
    SECURITY_REVIEW: {COMPATIBILITY_REVIEW, REJECTED, QUARANTINED},
    COMPATIBILITY_REVIEW: {SANDBOX_TEST, REJECTED, QUARANTINED},
    SANDBOX_TEST: {BENCHMARK, REJECTED, QUARANTINED, BROKEN},
    BENCHMARK: {APPROVAL, REJECTED, QUARANTINED},
    APPROVAL: {CANARY, DISABLED, REJECTED, REMOVED},
    CANARY: {ACTIVE, BROKEN, QUARANTINED, DISABLED},
    ACTIVE: {DISABLED, BROKEN, QUARANTINED, REMOVED},
    DISABLED: {CANARY, REMOVED},
    BROKEN: {QUARANTINED, DISABLED, REMOVED},
    QUARANTINED: {INSPECTING, REMOVED},
    REJECTED: {REMOVED},
    REMOVED: set(),
}
_SENSITIVE = ("password", "passwd", "secret", "token", "api_key", "apikey",
              "cookie", "credential", "private_key", "authorization")


def default_extension_root() -> Path:
    configured = os.environ.get("ZENO_EXTENSION_ROOT", "").strip()
    return (Path(configured).expanduser().resolve() if configured else
            Path(__file__).resolve().parents[2] / "extensions")


def extension_id_for(source: str) -> str:
    digest = hashlib.sha256(str(source).strip().encode("utf-8")).hexdigest()[:16]
    return f"ext_{digest}"


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 7:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(key): ("[REDACTED]" if any(marker in str(key).casefold()
                                                for marker in _SENSITIVE)
                           else _redact(item, depth + 1))
                for key, item in list(value.items())[:300]}
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value[:300]]
    if isinstance(value, str):
        return value[:50_000]
    return value


class ExtensionRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).resolve() if root else default_extension_root().resolve()
        self.path = self.root / "catalog.json"
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"schema": 1, "extensions": {}})

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value.get("extensions"), dict):
                raise ValueError("invalid extension catalog")
            return value
        except FileNotFoundError:
            return {"schema": 1, "extensions": {}}
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"extension catalog is unreadable: {type(exc).__name__}") from exc

    def _write(self, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        temporary.write_text(json.dumps(_redact(value), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def create(self, source: dict[str, Any], *, name: str = "") -> dict[str, Any]:
        original = str(source.get("original") or "")
        extension_id = extension_id_for(original)
        now = time.time()
        with self._lock:
            catalog = self._read()
            existing = catalog["extensions"].get(extension_id)
            if existing and existing.get("state") != REMOVED:
                return copy.deepcopy(existing)
            record = {
                "id": extension_id, "name": name or original, "state": DISCOVERED,
                "source": source, "created_at": now, "updated_at": now,
                "feature_enabled": False, "health": "NOT_TESTED", "version": "",
                "known_good": [], "history": [self._event(DISCOVERED, "source registered")],
            }
            catalog["extensions"][extension_id] = record
            self._write(catalog)
            return copy.deepcopy(record)

    def get(self, extension_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._read()["extensions"].get(str(extension_id))
            return copy.deepcopy(record) if record else None

    def list(self, *, include_removed: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._read()["extensions"].values())
        if not include_removed:
            rows = [row for row in rows if row.get("state") != REMOVED]
        return sorted((copy.deepcopy(row) for row in rows),
                      key=lambda row: float(row.get("updated_at") or 0), reverse=True)

    def transition(self, extension_id: str, state: str, reason: str = "",
                   **updates: Any) -> dict[str, Any]:
        with self._lock:
            catalog = self._read()
            record = catalog["extensions"].get(extension_id)
            if not record:
                raise KeyError(f"unknown extension '{extension_id}'")
            current = str(record.get("state"))
            if state != current and state not in _ALLOWED.get(current, set()):
                raise ValueError(f"invalid extension transition {current} -> {state}")
            record.update(_redact(updates))
            record["state"] = state
            record["updated_at"] = time.time()
            record.setdefault("history", []).append(self._event(state, reason))
            record["history"] = record["history"][-200:]
            self._write(catalog)
            return copy.deepcopy(record)

    def patch(self, extension_id: str, **updates: Any) -> dict[str, Any]:
        record = self.get(extension_id)
        if not record:
            raise KeyError(f"unknown extension '{extension_id}'")
        return self.transition(extension_id, str(record["state"]), "record updated", **updates)

    @staticmethod
    def _event(state: str, reason: str) -> dict[str, Any]:
        return {"state": state, "reason": str(reason)[:2000], "timestamp": time.time()}


class ExtensionRollbackManager:
    def __init__(self, registry: ExtensionRegistry) -> None:
        self.registry = registry

    def rollback(self, extension_id: str) -> dict[str, Any]:
        record = self.registry.get(extension_id)
        if not record:
            raise KeyError(f"unknown extension '{extension_id}'")
        versions = list(record.get("known_good") or [])
        current = str(record.get("version") or "")
        candidates = versions[:-1] if versions and str(versions[-1].get("version") or "") == current else versions
        if not candidates:
            return {"ok": False, "state": record["state"],
                    "reason": "No previous tested known-good version exists."}
        previous = candidates[-1]
        updated = self.registry.transition(extension_id, DISABLED,
                    "rollback selected previous known-good version",
                    version=previous.get("version", ""), feature_enabled=False,
                    health="ROLLBACK_PENDING_CANARY")
        return {"ok": True, "extension": updated, "restored": previous,
                "activation_required": True}
