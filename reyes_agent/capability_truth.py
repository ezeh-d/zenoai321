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
    implemented: bool = False
    tested: bool = False          # a smoke test actually passed
    has_fallback: bool = False
    observable: bool = False
    documented: bool = False
    available: bool = True        # present on THIS device/node
    owner: str = ""               # responsible component (pack5 #136)


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
            for field_name in ("implemented", "tested", "has_fallback",
                               "observable", "documented", "available"):
                if field_name in facts:
                    setattr(current, field_name, bool(facts[field_name]))
            if "owner" in facts:
                current.owner = str(facts["owner"])
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
        return {
            "name": key,
            "advertised": advertised,
            "implemented": facts.implemented,
            "tested": facts.tested,
            "healthy": healthy,
            "available": facts.available,
            "active": active and facts.available,
            "lifecycle": self._lifecycle(key),
            "owner": facts.owner,
            "health_detail": health_detail,
        }

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
    truth.declare("open_app", implemented=True, tested=True, has_fallback=True,
                  observable=True, documented=True, owner="remote_access")
    # The conversation planner has a passing test suite and a live diagnostics
    # endpoint, but no realtime audio pipeline -- honestly not observable yet.
    truth.declare("conversation_plan", implemented=True, tested=True,
                  observable=False, documented=True, owner="conversation")
    try:
        from reyes_agent import capability_lifecycle as _cl

        life = _cl.get_lifecycle()
        for name in ("open_app", "conversation_plan"):
            life.register(name, criticality=_cl.IMPORTANT, state=_cl.CANARY)
            life.transition(name, _cl.PRODUCTION)
    except Exception:  # noqa: BLE001
        pass
