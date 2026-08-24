"""Replaceable provider adapters -- gated OFF, honest, adopter-ready.

Every capability in this package is a "provider behind a ZENO interface": it is
OFF by default (a feature flag), reports its true readiness (disabled / missing
dependency / not configured / ready), and its operations fail honestly when it
is not available -- never a fake "done" (#91, #105). Turning one on is a matter
of enabling its flag and providing its dependency/credentials; nothing here
installs a heavyweight package or touches hardware on its own.

Two families:
  hardware.*  -- camera, smart home, robotics (explicit opt-in, hardware)
  external.*  -- observability, secrets, compute, model serving, identity,
                 native shell, file sync, message bus, log aggregation

`get_registry().dashboard()` lists every adapter's status, which the capability
snapshot surfaces so ZENO can say, truthfully, "that is available / that needs
setup".
"""

from __future__ import annotations

import threading
from typing import Any

from reyes_agent.adapters.base import ProviderAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        with self._lock:
            self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ProviderAdapter | None:
        with self._lock:
            return self._adapters.get(str(name or "").strip())

    def all(self) -> list[ProviderAdapter]:
        with self._lock:
            return list(self._adapters.values())

    def dashboard(self) -> list[dict[str, Any]]:
        return sorted((a.status().as_dict() for a in self.all()),
                      key=lambda s: (s["category"], s["name"]))

    def available_names(self) -> list[str]:
        return [a.name for a in self.all() if a.available()]


_registry: AdapterRegistry | None = None
_lock = threading.Lock()


def get_registry() -> AdapterRegistry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = AdapterRegistry()
            _register_builtins(_registry)
        return _registry


def _register_builtins(registry: AdapterRegistry) -> None:
    from reyes_agent.adapters import external, hardware

    for adapter in (*hardware.all_adapters(), *external.all_adapters()):
        registry.register(adapter)
