"""The provider-adapter base: flag-gated, dependency-aware, honest.

Readiness resolves in four honest states:
    DISABLED             -- the feature flag is off (the default)
    DEPENDENCY_MISSING   -- enabled, but the library/binary isn't installed
    NOT_CONFIGURED       -- enabled + present, but required credentials/URL absent
    READY                -- enabled + present + configured (available)

`available()` is READY only. Operations call `require()` first, so an adapter
that is not truly wired raises `AdapterUnavailable` instead of pretending.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any

DISABLED = "DISABLED"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
NOT_CONFIGURED = "NOT_CONFIGURED"
READY = "READY"


@dataclass
class AdapterStatus:
    name: str
    category: str
    flag: str
    enabled: bool
    dependency_present: bool
    configured: bool
    available: bool
    status: str
    requires: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "flag": self.flag,
                "enabled": self.enabled, "dependency_present": self.dependency_present,
                "configured": self.configured, "available": self.available,
                "status": self.status, "requires": list(self.requires),
                "detail": self.detail}


class AdapterUnavailable(RuntimeError):
    def __init__(self, name: str, status: AdapterStatus) -> None:
        super().__init__(f"'{name}' is not available: {status.status}. "
                         f"Needs: {', '.join(status.requires) or 'enablement'}.")
        self.name = name
        self.status = status


class ProviderAdapter:
    """Subclass and set the class attributes; override the checks if needed."""
    name: str = ""
    category: str = "external"        # "hardware" | "external"
    flag: str = ""                    # feature-flag name (default OFF)
    summary: str = ""
    pip: tuple[str, ...] = ()         # python import names the provider needs
    env: tuple[str, ...] = ()         # environment variables it needs
    requires: tuple[str, ...] = ()    # human-readable setup steps

    def enabled(self) -> bool:
        try:
            from reyes_agent import feature_flags

            return feature_flags.is_enabled(self.flag)
        except Exception:  # noqa: BLE001
            return False

    def dependency_present(self) -> bool:
        """True if every declared python dependency can be imported. Adapters
        that depend on a running service (a URL, not a lib) override this True."""
        try:
            return all(importlib.util.find_spec(mod) is not None for mod in self.pip)
        except Exception:  # noqa: BLE001
            return False

    def configured(self) -> bool:
        """True if every required environment variable is set."""
        return all(os.environ.get(var) for var in self.env)

    def available(self) -> bool:
        return self.enabled() and self.dependency_present() and self.configured()

    def _status_str(self) -> str:
        if not self.enabled():
            return DISABLED
        if not self.dependency_present():
            return DEPENDENCY_MISSING
        if not self.configured():
            return NOT_CONFIGURED
        return READY

    def status(self) -> AdapterStatus:
        st = self._status_str()
        detail = {
            DISABLED: f"Off. Enable with feature flag '{self.flag}'.",
            DEPENDENCY_MISSING: f"Enabled, but missing: {', '.join(self.pip) or 'a dependency'}.",
            NOT_CONFIGURED: f"Enabled, but not configured: {', '.join(self.env) or 'credentials'}.",
            READY: "Available.",
        }[st]
        return AdapterStatus(
            name=self.name, category=self.category, flag=self.flag,
            enabled=self.enabled(), dependency_present=self.dependency_present(),
            configured=self.configured(), available=(st == READY), status=st,
            requires=list(self.requires), detail=detail)

    def require(self) -> None:
        """Raise unless the adapter is truly available -- never fake success."""
        if not self.available():
            raise AdapterUnavailable(self.name, self.status())

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "summary": self.summary,
                "status": self.status().as_dict()}
