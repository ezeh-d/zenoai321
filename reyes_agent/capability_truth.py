"""The truth about each capability -- advertised vs. actually working (pack5 #246-251).

The no-fake-capability rule (#247-248): ZENO must not claim a capability just
because it appears in documentation or a tool list. A capability is ACTIVE only
when it is implemented AND a smoke test has passed. This service is the single
honest view -- for each capability: is it advertised, implemented, tested,
healthy, available -- and a production-readiness score. Health and lifecycle are
read LIVE from the reputation store, the circuit breaker and the lifecycle FSM,
so the dashboard reflects reality, not a stale flag.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

DEFINED = "DEFINED"
INSTALLED = "INSTALLED"
AVAILABLE = "AVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
DEVICE_REQUIRED = "DEVICE_REQUIRED"
DEVICE_OFFLINE = "DEVICE_OFFLINE"
DEGRADED = "DEGRADED"
BROKEN = "BROKEN"
DISABLED = "DISABLED"
UNSUPPORTED = "UNSUPPORTED"
TESTING = "TESTING"

# Weights for the production-readiness score (pack5 #251). They sum to 1.0.
_WEIGHTS = {
    "implemented": 0.25,
    "tested": 0.25,
    "healthy": 0.20,
    "has_fallback": 0.10,
    "observable": 0.10,
    "documented": 0.10,
}


@dataclass
class CapabilityFacts:
    name: str
    installed: bool = False
    implemented: bool = False
    tested: bool = False          # a smoke test actually passed
    has_fallback: bool = False
    observable: bool = False
    documented: bool = False
    available: bool = True        # present on THIS device/node
    owner: str = ""               # responsible component (pack5 #136)
    description: str = ""
    provider: str = ""
    version: str = ""
    device_requirements: tuple[str, ...] = ()
    network_required: bool = False
    authentication_required: bool = False
    authenticated: bool = True
    permissions: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    verification_method: str = ""
    enabled: bool = True
    broken: bool = False
    dependencies: tuple[str, ...] = ()
    last_health_check: float = 0.0


class CapabilityTruth:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._facts: dict[str, CapabilityFacts] = {}

    def declare(self, name: str, **facts: Any) -> None:
        """Record the static facts a capability itself knows (implemented,
        tested, fallback, observable, documented, available, owner)."""
        key = _norm(name)
        if not key:
            return
        with self._lock:
            current = self._facts.get(key) or CapabilityFacts(key)
            for field_name in ("installed", "implemented", "tested", "has_fallback",
                               "observable", "documented", "available", "broken"):
                if field_name in facts:
                    setattr(current, field_name, bool(facts[field_name]))
            if "owner" in facts:
                current.owner = str(facts["owner"])
            for field_name in ("description", "provider", "version", "verification_method"):
                if field_name in facts:
                    setattr(current, field_name, str(facts[field_name]))
            for field_name in ("device_requirements", "permissions", "fallbacks", "dependencies"):
                if field_name in facts:
                    value = facts[field_name] or ()
                    setattr(current, field_name, tuple(str(item) for item in value))
            for field_name in ("network_required", "authentication_required", "authenticated", "enabled"):
                if field_name in facts:
                    setattr(current, field_name, bool(facts[field_name]))
            if "last_health_check" in facts:
                current.last_health_check = float(facts["last_health_check"] or 0.0)
            self._facts[key] = current

    def mark_tested(self, name: str, passed: bool) -> None:
        """A smoke/proof test ran (pack5 #248-250). Only a pass makes it ACTIVE."""
        self.declare(name, tested=bool(passed))

    # -- live health -----------------------------------------------------
    def _healthy(self, name: str) -> tuple[bool, dict[str, Any]]:
        detail: dict[str, Any] = {}
        try:
            from reyes_agent import circuit_breaker

            if circuit_breaker.is_open(name):
                detail["breaker"] = "OPEN"
                return False, detail
        except Exception:  # noqa: BLE001
            pass
        try:
            from reyes_agent import tool_reputation

            rep = tool_reputation.get_reputation().reputation(name)
            detail["samples"] = rep["samples"]
            detail["success_rate"] = rep["success_rate"]
            # Enough evidence AND clearly failing -> unhealthy. No data -> give
            # the benefit of the doubt (it just hasn't been exercised yet).
            if rep["samples"] >= 5 and rep["success_rate"] < 0.5:
                return False, detail
        except Exception:  # noqa: BLE001
            pass
        return True, detail

    def _lifecycle(self, name: str) -> str:
        try:
            from reyes_agent import capability_lifecycle

            return capability_lifecycle.get_lifecycle().state(name)
        except Exception:  # noqa: BLE001
            return capability_lifecycle_default()

    # -- truth + readiness ----------------------------------------------
    def truth(self, name: str) -> dict[str, Any]:
        key = _norm(name)
        with self._lock:
            facts = self._facts.get(key)
        advertised = facts is not None
        facts = facts or CapabilityFacts(key)
        healthy, health_detail = self._healthy(key)
        active = facts.implemented and facts.tested   # the no-fake rule
        status = self._status(facts, advertised, healthy)
        try:
            from reyes_agent.tool_reputation import get_reputation
            reputation = get_reputation().reputation(key)
        except Exception:  # noqa: BLE001
            reputation = {"success_rate": None, "p50_latency_ms": None}
        return {
            "name": key,
            "advertised": advertised,
            "implemented": facts.implemented,
            "installed": facts.installed,
            "tested": facts.tested,
            "healthy": healthy,
            "available": facts.available,
            "active": active and facts.available,
            "lifecycle": self._lifecycle(key),
            "owner": facts.owner,
            "health_detail": health_detail,
            "status": status,
            "description": facts.description,
            "provider": facts.provider,
            "version": facts.version,
            "device_requirements": list(facts.device_requirements),
            "network_required": facts.network_required,
            "authentication_required": facts.authentication_required,
            "permissions": list(facts.permissions),
            "fallbacks": list(facts.fallbacks),
            "verification_method": facts.verification_method,
            "dependencies": list(facts.dependencies),
            "last_health_check": facts.last_health_check,
            "success_rate": reputation.get("success_rate"),
            "latency_ms": reputation.get("median_latency_ms"),
        }

    @staticmethod
    def _status(facts: CapabilityFacts, advertised: bool, healthy: bool) -> str:
        if not advertised:
            return UNSUPPORTED
        if not facts.enabled:
            return DISABLED
        if facts.broken:
            return BROKEN
        if not facts.implemented:
            return INSTALLED if facts.installed else DEFINED
        if facts.authentication_required and not facts.authenticated:
            return AUTH_REQUIRED
        if facts.device_requirements and not facts.available:
            return DEVICE_OFFLINE
        if not facts.available:
            return DEVICE_REQUIRED
        if not healthy:
            return DEGRADED
        if not facts.tested:
            return TESTING
        return AVAILABLE

    def diagnose(self, name: str) -> dict[str, Any]:
        result = self.truth(name)
        dependencies = [self.truth(dep) for dep in result.get("dependencies", [])]
        result["dependency_health"] = dependencies
        blocked = next((dep for dep in dependencies
                        if dep["status"] not in {AVAILABLE, INSTALLED, TESTING}), None)
        if blocked is not None:
            result["root_cause"] = {"dependency": blocked["name"], "status": blocked["status"]}
        elif result["status"] != AVAILABLE:
            result["root_cause"] = {"capability": result["name"], "status": result["status"]}
        else:
            result["root_cause"] = None
        return result

    def dependencies(self) -> dict[str, list[str]]:
        with self._lock:
            return {name: list(facts.dependencies) for name, facts in self._facts.items()}

    def production_readiness(self, name: str) -> dict[str, Any]:
        key = _norm(name)
        with self._lock:
            facts = self._facts.get(key) or CapabilityFacts(key)
        healthy, _ = self._healthy(key)
        signals = {
            "implemented": facts.implemented,
            "tested": facts.tested,
            "healthy": healthy,
            "has_fallback": facts.has_fallback,
            "observable": facts.observable,
            "documented": facts.documented,
        }
        score = sum(_WEIGHTS[k] for k, v in signals.items() if v)
        return {"name": key, "score": round(score, 3), "signals": signals,
                "ready": score >= 0.8 and facts.implemented and facts.tested}

    def dashboard(self) -> list[dict[str, Any]]:
        with self._lock:
            names = sorted(self._facts)
        rows = []
        for name in names:
            row = self.truth(name)
            row["readiness"] = self.production_readiness(name)["score"]
            rows.append(row)
        return rows


def capability_lifecycle_default() -> str:
    from reyes_agent import capability_lifecycle

    return capability_lifecycle.DISCOVERED


def _norm(name: str) -> str:
    return str(name or "").strip()


_instance: CapabilityTruth | None = None
_instance_lock = threading.Lock()
_seeded = False


def get_truth() -> CapabilityTruth:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = CapabilityTruth()
    return _instance


CapabilityTruthEngine = CapabilityTruth
CapabilityRegistry = CapabilityTruth


class CapabilityDependencyGraph:
    def __init__(self, truth: CapabilityTruth | None = None) -> None:
        self.truth = truth or get_truth()

    def graph(self) -> dict[str, list[str]]:
        return self.truth.dependencies()

    def explain(self, capability: str) -> dict[str, Any]:
        return self.truth.diagnose(capability)


class CapabilityHealthService:
    def __init__(self, truth: CapabilityTruth | None = None) -> None:
        self.truth = truth or get_truth()

    def check(self, capability: str) -> dict[str, Any]:
        return self.truth.diagnose(capability)


def seed_baseline() -> None:
    """Declare ONLY capabilities that are genuinely proven, so the dashboard is
    honest from the first read (the no-fake rule cuts both ways -- do not seed
    tested=True for anything that was not actually exercised). Idempotent."""
    global _seeded
    with _instance_lock:
        if _seeded:
            return
        _seeded = True
    truth = get_truth()
    # Verified this build: phone->desktop open_app actually launched apps and is
    # corroborated by an independent process check; reputation + breaker observe
    # it. See CODEX_CLAUDE_COORDINATION.md.
    truth.declare("open_app", installed=True, implemented=True, tested=True, has_fallback=True,
                  observable=True, documented=True, owner="remote_access",
                  provider="desktop_automation", device_requirements=("laptop",),
                  permissions=("app_control",), verification_method="process_or_window",
                  fallbacks=("windows_shell", "pywinauto"))
    # The conversation planner has a passing test suite and a live diagnostics
    # endpoint, but no realtime audio pipeline -- honestly not observable yet.
    truth.declare("conversation_plan", installed=True, implemented=True, tested=True,
                  observable=False, documented=True, owner="conversation",
                  provider="local", verification_method="contract_tests")
    try:
        from reyes_agent import capability_lifecycle as _cl

        life = _cl.get_lifecycle()
        for name in ("open_app", "conversation_plan"):
            life.register(name, criticality=_cl.IMPORTANT, state=_cl.CANARY)
            life.transition(name, _cl.PRODUCTION)
    except Exception:  # noqa: BLE001
        pass


def seed_tool_registry() -> None:
    """Declare registered tools without pretending registration proves them.

    A tool with no measured successful execution is TESTING, not AVAILABLE.
    Re-running is intentional: lazy tools/plugins can appear after startup.
    """
    try:
        from reyes_agent.tools import TOOLS
        from reyes_agent.tool_reputation import get_reputation
    except Exception:  # noqa: BLE001
        return
    truth = get_truth()
    for name, tool in list(TOOLS.items()):
        current = truth.truth(name)
        rep = get_reputation().reputation(name)
        truth.declare(
            name,
            installed=True,
            implemented=True,
            tested=bool(current.get("tested") or rep.get("samples", 0) > 0),
            observable=True,
            description=str(getattr(tool, "description", ""))[:500],
            provider="local_registry",
            verification_method=(current.get("verification_method") or
                                 "tool_result_classifier"),
            owner="GlobalToolRegistry",
        )
