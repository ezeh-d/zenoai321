"""What ZENO's hands are allowed to do unattended.

The threat here is not a malicious model -- it is a confident one. An
agentic loop that can click anything will eventually click "Delete
account", "Confirm payment" or "Disable protection" because the pixels
looked like progress toward the goal.

So risk is decided BEFORE an action runs, from the action and the element
it targets, and the highest tier is not gated behind approval at all: it is
refused outright. Approval is for things the owner might reasonably want;
refusal is for things an autonomous loop should never initiate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# --- tiers ---------------------------------------------------------------
SAFE = "SAFE"              # observe, read, screenshot, focus a window
ORDINARY = "ORDINARY"      # click, type, scroll in a normal app
APPROVAL = "APPROVAL"      # destructive or irreversible -- ask first
REFUSED = "REFUSED"        # never automated, whatever the goal

TIERS = (SAFE, ORDINARY, APPROVAL, REFUSED)

# Never auto-completed by an agentic loop. The brief is explicit that
# financial transactions must not complete automatically.
_REFUSE = (
    r"\b(pay|payment|purchase|buy now|place order|checkout|confirm order)\b",
    r"\b(transfer funds?|send money|wire transfer|withdraw)\b",
    r"\b(subscribe|start (?:free )?trial|upgrade plan)\b",
    r"\b(change|reset|update) (?:my )?password\b",
    r"\b(disable|turn off) (?:the )?(?:firewall|antivirus|defender|protection|security)\b",
    r"\bformat (?:drive|disk|c:)\b",
    r"\bfactory reset\b",
)

# Allowed, but only after the owner explicitly says yes.
_APPROVE = (
    r"\bdelete\b", r"\bremove\b", r"\buninstall\b", r"\bdiscard\b",
    # Throwing away unsaved work. Found by running a real GUI task: the
    # button Windows actually shows says "Don't save", which matched nothing
    # here and was therefore classified as an ordinary click.
    r"\bdon'?t save\b", r"\bwithout saving\b", r"\bno,? don'?t\b",
    r"\bempty (?:the )?(?:trash|recycle bin)\b",
    r"\bsign out\b", r"\blog out\b", r"\brevoke\b",
    r"\bpublish\b", r"\bdeploy\b", r"\bsend\b", r"\bpost\b", r"\bsubmit\b",
    r"\bshare\b", r"\binvite\b", r"\bgrant\b", r"\ballow\b",
    r"\boverwrite\b", r"\breplace\b", r"\brestart\b", r"\bshut ?down\b",
)

_READ_ONLY_ACTIONS = frozenset({"observe", "screenshot", "read", "find", "focus", "list"})


@dataclass(frozen=True)
class Risk:
    tier: str
    reason: str
    matched: str = ""

    @property
    def needs_approval(self) -> bool:
        return self.tier == APPROVAL

    @property
    def refused(self) -> bool:
        return self.tier == REFUSED

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "reason": self.reason, "matched": self.matched}


def assess(action: str, target: str = "", context: str = "") -> Risk:
    """Classify one intended action against the thing it will touch.

    `target` is the element label ("Confirm payment"), `context` the window
    title -- both matter, because "Send" in a text editor and "Send" in a
    banking app are not the same click.
    """
    verb = str(action or "").strip().lower()
    if verb in _READ_ONLY_ACTIONS:
        return Risk(SAFE, "read-only observation")

    haystack = " ".join(p for p in (verb, str(target or ""), str(context or "")) if p).lower()

    for pattern in _REFUSE:
        hit = re.search(pattern, haystack)
        if hit:
            return Risk(REFUSED,
                        "This is a payment, credential or security change -- ZENO does not "
                        "complete these automatically. Use the relevant trusted app yourself; "
                        "a more specific phrasing does not bypass this block.",
                        hit.group(0))

    for pattern in _APPROVE:
        hit = re.search(pattern, haystack)
        if hit:
            return Risk(APPROVAL,
                        f"'{hit.group(0)}' is destructive or irreversible; it needs your "
                        "explicit go-ahead first.", hit.group(0))

    return Risk(ORDINARY, "ordinary interaction")


def gate(action: str, target: str = "", context: str = "",
         *, approved: bool = False) -> tuple[bool, Risk]:
    """(may_run, risk). The single decision point before any input is sent."""
    risk = assess(action, target, context)
    if risk.refused:
        return False, risk
    if risk.needs_approval and not approved:
        # A current authenticated command such as "send Ada hello" is the
        # approval for that exact ordinary outward click.  Reuse the central
        # action policy instead of asking again here. Payments/security are
        # already REFUSED above and destructive clicks remain approval-gated.
        outward = re.search(r"\b(send|post|publish|submit|share|forward|reply)\b",
                            " ".join((str(action), str(target))).casefold())
        if outward:
            try:
                from reyes_agent.action_policy import PolicyEffect, evaluate

                capability = (
                    "social_post"
                    if outward.group(1) in {"post", "publish", "share"}
                    else "messaging_send"
                )
                decision = evaluate(
                    "computer_external_action",
                    {"target": target, "window": context},
                    capability=capability,
                )
                if decision.effect is PolicyEffect.EXECUTE:
                    return True, risk
            except Exception:  # noqa: BLE001 -- safety fails closed
                pass
        return False, risk
    return True, risk
