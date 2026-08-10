"""Which browser strategy a web task should use.

    known site / clear DOM target  -> DETERMINISTIC (Playwright)
    unfamiliar / visual / vague    -> AGENTIC (browser-use)

The split matters for the same reason it matters on the desktop: a
deterministic `page.click("#submit")` is milliseconds and cannot
hallucinate, while an agentic loop costs model calls per step. Reaching for
the agent when a selector would do is slow and less reliable, not smarter.

ZENO already has `browser_controller` and `browser_runtime` driving
Playwright with a bounded, owner-facing session. This module ROUTES to
those rather than opening a second browser stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DETERMINISTIC, AGENTIC = "DETERMINISTIC", "AGENTIC"

# A task naming a concrete, mechanical operation on a page ZENO can address
# directly. These do not need a reasoning loop.
_DETERMINISTIC_MARKERS = (
    r"\b(?:go to|open|visit|navigate to)\s+(?:https?://|www\.)\S+",
    r"\bscreenshot\b", r"\bread (?:the )?page\b", r"\bextract\b",
    r"\bcurrent url\b", r"\bpage title\b", r"\bscroll\b",
    r"\bclick (?:the )?(?:#|\.)\S+",           # an actual selector
)

# Language that means "I don't know the layout, work it out".
_AGENTIC_MARKERS = (
    r"\bfind\b", r"\bsearch for\b", r"\blook for\b", r"\bfigure out\b",
    r"\bcompare\b", r"\bbook\b", r"\bsign up\b", r"\bcheckout\b",
    r"\bnavigate (?:the|through)\b", r"\bwork out\b", r"\bbrowse\b",
    r"\bwherever\b", r"\bsomewhere\b", r"\bif you can\b",
)

# Never automated in bulk. The brief forbids uncontrolled mass submission.
_MASS_SUBMISSION = (
    r"\b(?:all|every|each|bulk|mass)\b.{0,40}\b(?:appl(?:y|ication)s?|submit|send|post|message|email)\b",
    r"\b(?:appl(?:y|ication)s?|submit|send|post|message)\b.{0,30}\b(?:to (?:all|every)|in bulk|automatically)\b",
    r"\bspam\b", r"\bscrape (?:all|every)\b",
)


@dataclass(frozen=True)
class Route:
    strategy: str
    reason: str
    refused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"strategy": self.strategy, "reason": self.reason, "refused": self.refused}


def _hit(text: str, patterns) -> str:
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found:
            return found.group(0)
    return ""


def choose(task: str) -> Route:
    """Pick a strategy, or refuse."""
    text = " ".join(str(task or "").strip().split())
    if not text:
        return Route(DETERMINISTIC, "empty task", refused=True)

    mass = _hit(text, _MASS_SUBMISSION)
    if mass:
        return Route(AGENTIC,
                     f"Refused: '{mass}' reads as bulk submission. ZENO does not mass-apply, "
                     "mass-message or mass-post -- platform terms ban it and it can get the "
                     "owner's accounts banned. One at a time, with the final submit his.",
                     refused=True)

    agentic = _hit(text, _AGENTIC_MARKERS)
    deterministic = _hit(text, _DETERMINISTIC_MARKERS)

    # A concrete URL plus exploratory language is still exploration: "go to
    # site X and find the pricing" needs eyes once it lands.
    if agentic and deterministic:
        return Route(AGENTIC, f"starts deterministic ('{deterministic}') but needs "
                              f"exploration ('{agentic}')")
    if agentic:
        return Route(AGENTIC, f"exploratory: '{agentic}'")
    if deterministic:
        return Route(DETERMINISTIC, f"concrete operation: '{deterministic}'")
    return Route(AGENTIC, "no concrete target named; treat as exploratory")


def available() -> dict[str, Any]:
    """What each strategy can actually do on this machine right now."""
    from reyes_agent import integrations

    return {
        "deterministic": {
            "backend": "playwright (via browser_controller/browser_runtime)",
            "installed": integrations.available("playwright"),
            "ready": integrations.available("playwright"),
        },
        "agentic": {
            "backend": "browser-use",
            "installed": integrations.available("browser_use"),
            "enabled": integrations.BROWSER_AGENT_ENABLED,
            "ready": integrations.BROWSER_AGENT_ENABLED and integrations.available("browser_use"),
            "fallback": ("Playwright + ZENO's own vision/grounding loop, which handles "
                         "most navigation without a second agent framework"),
        },
    }
