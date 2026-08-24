"""How sure are we the action worked? One honest confidence level.

WHY (pack4 #72, #73)
--------------------
"Done." is a lie when nothing checked. This collapses the evidence -- an
:class:`action_verifier.Verdict`, whether the result reported failure, and
multi-step progress -- into ONE level the assistant can say truthfully:

    VERIFIED         an independent check confirms the effect happened
    HIGH_CONFIDENCE  the tool reported success but nothing could verify it
    PARTIAL          some steps verified, others not
    UNVERIFIED       returned normally, no way to check -- do NOT claim "done"
    FAILED           a check ran (or the tool reported) and it did not happen

Pure, dependency-light, never raises.
"""

from __future__ import annotations

from typing import Any

VERIFIED = "VERIFIED"
HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
PARTIAL = "PARTIAL"
UNVERIFIED = "UNVERIFIED"
FAILED = "FAILED"

LEVELS = (VERIFIED, HIGH_CONFIDENCE, PARTIAL, UNVERIFIED, FAILED)


def assess(verdict: Any = None, *, result_failed: bool = False,
           ok_reported: bool | None = None,
           steps_total: int = 0, steps_verified: int = 0) -> str:
    """Reduce the available evidence to one level. Precedence, strongest signal
    first: an explicit failure, then multi-step progress, then a single
    verdict, then a bare success report, else unverified."""
    try:
        if result_failed:
            return FAILED
        if steps_total and steps_total > 0:
            done = max(0, int(steps_verified))
            if done >= int(steps_total):
                return VERIFIED
            return PARTIAL if done > 0 else UNVERIFIED
        if verdict is not None:
            if getattr(verdict, "verified", False):
                return VERIFIED
            # A check ran and came back negative -> the effect did not happen.
            if getattr(verdict, "verifiable", False) and not getattr(verdict, "verified", False):
                return FAILED
        if ok_reported is True:
            return HIGH_CONFIDENCE      # tool says ok, but unproven -- not VERIFIED
        return UNVERIFIED
    except Exception:  # noqa: BLE001 -- an honest fallback beats a raise
        return UNVERIFIED


def from_action(action: str, args: dict | None = None, result: Any = None) -> dict[str, Any]:
    """Verify an action and label its confidence in one call. Returns
    ``{"confidence": <level>, "verdict": {...}}``. Never raises."""
    try:
        from reyes_agent import process_verifier

        verdict = process_verifier.verify(action, args, result)
        result_failed = (verdict.verifiable and not verdict.verified
                         and verdict.method == "evidence")
        level = assess(verdict, result_failed=result_failed)
        return {"confidence": level, "verdict": verdict.as_dict()}
    except Exception:  # noqa: BLE001
        return {"confidence": UNVERIFIED, "verdict": {}}


def truthful(level: str) -> bool:
    """True when it is honest to tell the user the action succeeded."""
    return level in (VERIFIED, HIGH_CONFIDENCE)
