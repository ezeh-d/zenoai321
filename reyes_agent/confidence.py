"""Evidence-backed confidence and action-risk decisions.

This module deliberately does not manufacture a percentage when an upstream
engine supplied none.  Each signal is either measured (0..1) with a short
source note or explicitly ``unknown``.  Decisions combine the available
signals with action risk; a high-risk action with missing or weak evidence is
sent through ZENO's existing confirmation gate instead of being auto-run.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Mapping


DOMAINS = ("speech", "intent", "entity", "visual", "plan", "verification")
_WEIGHTS = {"speech": 0.25, "intent": 0.25, "entity": 0.15,
            "visual": 0.15, "plan": 0.10, "verification": 0.10}
# Speaker identity is deliberately diagnostic-only.  It must never be folded
# into speech-to-text, intent or action confidence: voice resemblance is not
# a replacement for a confirmation factor.
_RECORDABLE_DOMAINS = frozenset((*DOMAINS, "speaker", "action"))
_HIGH_RISK_CAPABILITIES = {"filesystem_delete", "system_commands", "email_send", "messaging_send", "social_post"}
_MEDIUM_RISK_CAPABILITIES = {"filesystem_write", "desktop_automation", "browser_automation", "vision", "audio_capture", "app_control"}
_lock = threading.Lock()
_recent: deque[dict] = deque(maxlen=120)


@dataclass(frozen=True)
class Decision:
    confidence: float | None
    known_domains: tuple[str, ...]
    unknown_domains: tuple[str, ...]
    risk: str
    requires_confirmation: bool
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _score(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def assess(signals: Mapping[str, float | int | None], *, risk: str = "low") -> Decision:
    """Combine supplied evidence without turning unknown data into a score."""
    known: list[str] = []
    unknown: list[str] = []
    weighted_total = 0.0
    available_weight = 0.0
    for domain in DOMAINS:
        value = _score(signals.get(domain))
        if value is None:
            unknown.append(domain)
            continue
        known.append(domain)
        weight = _WEIGHTS[domain]
        weighted_total += value * weight
        available_weight += weight
    combined = round(weighted_total / available_weight, 3) if available_weight else None
    risk = risk if risk in {"low", "medium", "high", "critical"} else "high"
    high_risk = risk in {"high", "critical"}
    weak = combined is None or combined < 0.70
    requires_confirmation = risk == "critical" or (high_risk and weak)
    if requires_confirmation:
        reason = ("critical action risk" if risk == "critical" else
                  "high action risk with " + ("no measured confidence" if combined is None else f"confidence {combined:.0%}"))
    elif combined is None:
        reason = "low/medium-risk action; confidence is unknown rather than invented"
    else:
        reason = f"measured confidence {combined:.0%} for {risk}-risk action"
    return Decision(combined, tuple(known), tuple(unknown), risk, requires_confirmation, reason)


def risk_for_tool(tool_name: str, *, requires_confirmation: bool = False) -> str:
    """Classify reach from the one Permission Engine capability mapping."""
    try:
        from reyes_agent import permissions

        capability = permissions.capability_for_tool(tool_name)
    except Exception:  # noqa: BLE001 -- diagnostics must not break execution
        capability = None
    if capability == "financial":
        return "critical"
    if requires_confirmation or capability in _HIGH_RISK_CAPABILITIES:
        return "high"
    if capability in _MEDIUM_RISK_CAPABILITIES:
        return "medium"
    return "low"


def decide_tool(
    tool_name: str, *, requires_confirmation: bool = False,
    signals: Mapping[str, float | int | None] | None = None,
) -> Decision:
    """Tool-facing decision. Intent is unknown unless a real caller provides it."""
    decision = assess(signals or {}, risk=risk_for_tool(tool_name, requires_confirmation=requires_confirmation))
    # Tool execution already publishes a durable ``tool.completed`` event.
    # Keep the decision locally bounded rather than doubling Event Bus writes
    # for every low-risk tool call.
    record("action", decision.confidence, f"{tool_name}: {decision.reason}", emit=False)
    return decision


def record(domain: str, value: float | int | None, evidence: str, *, emit: bool = True) -> None:
    """Keep bounded diagnostic evidence only; never record user utterances."""
    if domain not in _RECORDABLE_DOMAINS:
        raise ValueError(f"Unknown confidence domain '{domain}'.")
    score = _score(value)
    item = {"at": time.time(), "domain": domain, "score": score,
            "evidence": str(evidence)[:240], "known": score is not None}
    with _lock:
        _recent.append(item)
    if not emit:
        return
    try:
        from reyes_agent import event_bus

        event_bus.publish("confidence.recorded", item, source="confidence")
    except Exception:  # noqa: BLE001 -- metrics are non-critical
        pass


def record_verification(verified: bool, evidence: str) -> None:
    record("verification", 1.0 if verified else 0.0, evidence)


def snapshot() -> dict:
    with _lock:
        items = list(_recent)
    return {"domains": [*DOMAINS, "speaker (separate; never action authority)"],
            "recent": items[-20:], "retained": len(items),
            "policy": "Unknown confidence is never converted into a positive score; speaker evidence is never merged with STT."}
