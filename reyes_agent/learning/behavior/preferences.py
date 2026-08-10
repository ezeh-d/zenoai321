"""Digital DNA boundary: an observed pattern is not a user preference."""
from __future__ import annotations

from typing import Any


def observed_pattern(description: str, *, occurrences: int, confidence: float) -> dict[str, Any]:
    text = " ".join(str(description or "").split())[:500]
    score = max(0.0, min(1.0, float(confidence)))
    enough = occurrences >= 3 and score >= 0.65
    return {"kind": "OBSERVED_PATTERN", "description": text, "occurrences": max(0, int(occurrences)),
            "confidence": score, "suggest": enough, "confirmed": False,
            "may_change_permissions": False, "may_automate_without_approval": False}


def confirm_preference(description: str, *, actor: str = "user") -> dict[str, Any]:
    if actor != "user":
        return {"ok": False, "reason": "Only the owner can confirm a durable preference."}
    text = " ".join(str(description or "").split())[:1000]
    if not text:
        return {"ok": False, "reason": "Preference is empty."}
    from reyes_agent import living_memory
    record = living_memory.create(text, title="Confirmed preference", memory_type="preference",
                                  category="user", actor="user", reason="Owner confirmed inferred preference",
                                  source="digital_dna", tags=["confirmed-preference"])
    return {"ok": True, "kind": "CONFIRMED_USER_PREFERENCE", "memory_id": record.get("id"),
            "may_change_permissions": False}
