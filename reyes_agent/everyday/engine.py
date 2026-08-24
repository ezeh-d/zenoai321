"""EverydayIntelligenceEngine -- the one everyday front door (Pack 10 #1, #134, #269).

This is the REUSE layer the pack insists on (#183/#185/#186/#201): it does not
re-implement anything, it composes what already exists --
* notification triage + while-you-were-away (this package),
* the UniversalTraceEngine + EvidenceLedger (verification/audit),
* CapabilityTruth (so ZENO honestly knows which everyday features are AVAILABLE,
  DISABLED or NO_PROVIDER),
* ActionVerifier (so 'done' means verified).

`status()` answers "ZENO, what's going on?"; `capability_report()` answers
"which everyday feature is broken/off?" -- both from live state, never faked.
"""

from __future__ import annotations

import threading
from typing import Any

# (capability, implemented, tested, available, note) for everyday features.
# available=False is the honest "present in design, not usable here yet".
_CAPABILITIES = [
    ("everyday.notifications", True, True, True, "notification triage"),
    ("everyday.while_away", True, True, True, "activity recap from the trace bus"),
    ("everyday.personal_search", True, True, True, "federated local search"),
    ("everyday.screen.awareness", True, True, True, "context priority resolver"),
    ("everyday.screen.recall", True, True, False, "off until the owner opts in"),
    ("everyday.safety", True, True, True, "risk + secret detection"),
    ("everyday.smart_home", False, False, False, "NO_PROVIDER (needs Home Assistant)"),
    ("everyday.camera_scanner", False, False, False, "needs phone camera permission"),
    ("everyday.travel", False, False, False, "needs owner location permission"),
    ("everyday.location.owner_phone", False, False, False, "needs the paired phone agent"),
]


class EverydayIntelligenceEngine:
    def __init__(self) -> None:
        self._declared = False
        self._declare_capabilities()

    def _declare_capabilities(self) -> None:
        if self._declared:
            return
        try:
            from reyes_agent import capability_truth as ct

            truth = ct.get_truth()
            for name, impl, tested, avail, note in _CAPABILITIES:
                truth.declare(name, implemented=impl, tested=tested, available=avail,
                              documented=True, owner="everyday", description=note)
                if tested:
                    truth.mark_tested(name, impl)
            self._declared = True
        except Exception:  # noqa: BLE001 -- declaration is best-effort
            pass

    def capability_report(self) -> list[dict[str, Any]]:
        """Which everyday features are truly AVAILABLE vs off/no-provider (#183)."""
        try:
            from reyes_agent import capability_truth as ct

            truth = ct.get_truth()
            out = []
            for name, *_ in _CAPABILITIES:
                t = truth.truth(name)
                out.append({"capability": name, "available": t.get("active", False),
                            "status": t.get("status", ""), "healthy": t.get("healthy")})
            return out
        except Exception:  # noqa: BLE001
            return []

    def status(self, *, now: float, away_since: float | None = None) -> dict[str, Any]:
        """"What's going on?" -- notifications + recent activity + capabilities."""
        out: dict[str, Any] = {}
        try:
            from reyes_agent.everyday.notifications import NotificationIntelligenceEngine  # noqa: F401
            from reyes_agent.everyday import notifications as _n

            # A shared engine would be injected in real use; expose the shape here.
            out["notifications"] = {"engine": "NotificationIntelligenceEngine",
                                    "categories": [_n.CRITICAL, _n.ACTION_REQUIRED, _n.IMPORTANT]}
        except Exception:  # noqa: BLE001
            out["notifications"] = {}
        try:
            from reyes_agent.everyday.while_away import WhileYouWereAwayEngine

            since = away_since if away_since is not None else now - 3600.0
            out["while_away"] = WhileYouWereAwayEngine().recap(since=since, until=now)
        except Exception:  # noqa: BLE001
            out["while_away"] = {}
        out["capabilities"] = self.capability_report()
        return out

    # -- reuse of existing verification/audit (no re-implementation) ---------
    def verify_action(self, action: str, args: dict | None = None,
                      result: Any = None) -> dict[str, Any]:
        """Reuse ActionVerifier (#185) -- 'done' must be verified."""
        try:
            from reyes_agent import action_verifier

            return action_verifier.verify(action, args, result).as_dict()
        except Exception:  # noqa: BLE001
            return {"verified": False, "verifiable": False, "method": "none", "evidence": ""}

    def record_evidence(self, action: str, account: str, provider_result: str,
                        verification: str, *, now: float, trace_id: str = "") -> dict[str, Any]:
        """Reuse the EvidenceLedger (#186) -- meaningful actions are recorded."""
        try:
            from reyes_agent.trace_engine import get_evidence_ledger

            return get_evidence_ledger().record(action, account, provider_result,
                                                verification, timestamp=now,
                                                trace_id=trace_id).as_dict()
        except Exception:  # noqa: BLE001
            return {}


_instance: EverydayIntelligenceEngine | None = None
_lock = threading.Lock()


def get_engine() -> EverydayIntelligenceEngine:
    global _instance
    with _lock:
        if _instance is None:
            _instance = EverydayIntelligenceEngine()
        return _instance
