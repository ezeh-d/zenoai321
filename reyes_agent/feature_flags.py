"""Feature flags -- the safety valve for adopting new capabilities.

WHY
---
Expansion Pack 3 (#48, #49, #255) is explicit: never bulk-enable experimental
integrations. Each new adapter ships behind a flag, is switched on for a small
slice of traffic (canary), and is rolled back with one call if it misbehaves.
This is that switchboard.

Resolution order for a flag's value (highest wins):

  1. a runtime/persisted override  -- ``enable``/``disable``/``set`` (owner intent)
  2. an environment variable       -- ``ZENO_FF_<NAME>`` (deployment intent)
  3. the flag's registered default -- usually ``False`` for anything experimental

Canary rollout is deterministic: ``in_rollout(name, key)`` hashes the key so a
given task/device is *stably* in or out of the slice, never flickering per call.

Thread-safe, atomic persistence, and never raises into a caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

_STORE = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "feature_flags.json"

_TRUE = {"1", "true", "yes", "on", "enabled"}
_FALSE = {"0", "false", "no", "off", "disabled", ""}


@dataclass(frozen=True)
class Flag:
    name: str
    default: bool
    description: str = ""


# Known flags. Experimental integrations default OFF and are adopted through the
# gated pipeline (#252-#254), not by importing them into core.
_REGISTRY: dict[str, Flag] = {
    f.name: f for f in [
        Flag("enable_omniparser", False, "Visual GUI grounding fallback (#2)."),
        Flag("enable_temporal", False, "Durable long-running workflows (#6)."),
        Flag("enable_meilisearch", False, "Universal typo-tolerant search (#7)."),
        Flag("enable_workflow_learning", False, "Demonstration learning (#3)."),
        Flag("enable_mesh_remote", False, "Private mesh transport, e.g. Tailscale (#55)."),
        Flag("enable_new_memory", False, "Experimental memory backend."),
        Flag("enable_otel_traces", False, "OpenTelemetry tracing (#87)."),
    ]
}


def register(name: str, default: bool = False, description: str = "") -> None:
    """Declare a flag (idempotent). Lets an adapter register its own gate."""
    key = _norm(name)
    if key:
        _REGISTRY[key] = Flag(key, bool(default), description)


class FeatureFlags:
    def __init__(self, store: Path | None = None) -> None:
        self._store = store or _STORE
        self._lock = threading.RLock()
        self._overrides: dict[str, Any] = self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")
            os.replace(tmp, self._store)
        except OSError:
            pass  # a flag that can't persist still works for this process

    # -- queries -------------------------------------------------------------
    def is_enabled(self, name: str, default: bool | None = None) -> bool:
        key = _norm(name)
        with self._lock:
            entry = self._overrides.get(key)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
        env = os.environ.get(f"ZENO_FF_{key.upper()}")
        if env is not None:
            return env.strip().casefold() in _TRUE
        if default is not None:
            return bool(default)
        flag = _REGISTRY.get(key)
        return bool(flag.default) if flag else False

    def rollout_percent(self, name: str) -> int:
        key = _norm(name)
        with self._lock:
            entry = self._overrides.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("rollout"), (int, float)):
            return max(0, min(100, int(entry["rollout"])))
        return 100 if self.is_enabled(key) else 0

    def in_rollout(self, name: str, key: str = "") -> bool:
        """True if this key falls inside the flag's canary slice. Stable per key
        so the same task/device stays in or out instead of flickering."""
        if not self.is_enabled(name):
            return False
        pct = self.rollout_percent(name)
        if pct >= 100:
            return True
        if pct <= 0:
            return False
        digest = hashlib.sha256(f"{_norm(name)}:{key}".encode()).digest()
        bucket = digest[0] % 100          # 0..99, uniform
        return bucket < pct

    # -- mutations -----------------------------------------------------------
    def set(self, name: str, enabled: bool, *, rollout: int | None = None) -> None:
        key = _norm(name)
        if not key:
            return
        with self._lock:
            entry = dict(self._overrides.get(key) or {})
            entry["enabled"] = bool(enabled)
            if rollout is not None:
                entry["rollout"] = max(0, min(100, int(rollout)))
            self._overrides[key] = entry
            self._save()

    def enable(self, name: str, *, rollout: int | None = None) -> None:
        self.set(name, True, rollout=rollout)

    def disable(self, name: str) -> None:
        self.set(name, False)

    def clear_override(self, name: str) -> None:
        """Drop the persisted override so env/default takes over again."""
        key = _norm(name)
        with self._lock:
            if key in self._overrides:
                del self._overrides[key]
                self._save()

    def all_flags(self) -> list[dict[str, Any]]:
        names = set(_REGISTRY) | {_norm(k) for k in self._overrides}
        out = []
        for key in sorted(n for n in names if n):
            flag = _REGISTRY.get(key)
            out.append({
                "name": key,
                "enabled": self.is_enabled(key),
                "rollout_percent": self.rollout_percent(key),
                "default": bool(flag.default) if flag else False,
                "description": flag.description if flag else "",
                "overridden": key in self._overrides,
            })
        return out


def _norm(name: str) -> str:
    return str(name or "").strip().casefold()


_instance: FeatureFlags | None = None
_instance_lock = threading.Lock()


def get_flags() -> FeatureFlags:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = FeatureFlags()
        return _instance


def is_enabled(name: str, default: bool | None = None) -> bool:
    """Module-level convenience for the common single-store case."""
    return get_flags().is_enabled(name, default)


def in_rollout(name: str, key: str = "") -> bool:
    return get_flags().in_rollout(name, key)
