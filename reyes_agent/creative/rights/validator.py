"""The gate before anything is published, and the alternative when it refuses.

A refusal that ends the conversation is a bad refusal. The brief is specific
about this: when rights are not confirmed, ZENO should not repost the raw
footage AND should offer the rights-compliant way to make what the owner
actually wanted -- review, commentary, criticism, analysis, recap with
original narration.

So `check()` returns a verdict, and a blocked verdict carries a plan.

WHY THE TRANSFORMATION CHECK HAS NUMBERS IN IT
----------------------------------------------
"Transformative" is a legal conclusion nobody's code should claim to reach.
What software CAN check is the shape of the thing: a ten-minute upload with
forty seconds of commentary is republication however it is described, and a
ninety-second clip inside eight minutes of analysis is at least the right
shape. So the thresholds are a floor, they are called a floor, and the
verdict says plainly that it is not legal advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reyes_agent.creative.rights import registry

ALLOWED = "ALLOWED"
NEEDS_DECLARATION = "NEEDS_DECLARATION"
BLOCKED = "BLOCKED"

# What ZENO will help make instead, when raw republication is refused.
_ALTERNATIVES = (
    ("review", "a review: your verdict, with short excerpts only where they "
               "illustrate a point"),
    ("commentary", "commentary or criticism, where your voice carries the video "
                   "and the clips support it"),
    ("analysis", "an analysis or breakdown -- what it does well, how it was made"),
    ("recap", "a recap in your own words, narrated by you, over original visuals"),
    ("original", "an original animation on the same theme, with characters and "
                 "environments ZENO makes from scratch"),
)


@dataclass
class Verdict:
    decision: str
    reason: str = ""
    asset: registry.Asset | None = None
    alternatives: list[str] = field(default_factory=list)
    say: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOWED

    def as_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "allowed": self.allowed,
                "reason": self.reason, "say": self.say,
                "alternatives": self.alternatives,
                "asset": self.asset.as_dict() if self.asset else None}


def check(path: str, *, intent: str = "publish", commercial: bool = False) -> Verdict:
    """May this asset be used for this purpose. UNKNOWN is never yes."""
    asset = registry.classify(path)

    if asset.expired:
        return Verdict(BLOCKED, "the licence on file has expired", asset,
                       say=(f"The licence recorded for that expired. I will not publish "
                            "it until you tell me it has been renewed."))

    if asset.classification in registry.NEEDS_PROOF:
        unknown = asset.classification == registry.UNKNOWN_RIGHTS
        return Verdict(
            NEEDS_DECLARATION if unknown else BLOCKED,
            f"classified {asset.classification}", asset,
            alternatives=[text for _key, text in _ALTERNATIVES],
            say=(("I don't know who owns that, so I am not going to publish it. "
                  "If it is yours, or you have a licence, tell me and I will record "
                  "it. If it is someone else's, I can still help you make something "
                  "of your own about it:")
                 if unknown else
                 ("That is someone else's copyrighted work, so I am not going to "
                  "repost it. What I can help you make instead:")))

    if intent in ("publish", "post", "social") and not asset.social_post_allowed:
        if asset.classification != registry.OWNER_CREATED:
            return Verdict(BLOCKED,
                           "the recorded rights do not include social publication",
                           asset,
                           say=("The rights on file for that do not cover posting it "
                                "publicly. If they do, re-declare it with social "
                                "publication included."))

    if commercial and not asset.commercial_allowed:
        if asset.classification != registry.OWNER_CREATED:
            return Verdict(BLOCKED, "the recorded rights are not commercial", asset,
                           say=("That is licensed for personal use only as recorded. "
                                "Commercial use needs a licence that says so."))

    note = ""
    if asset.attribution_required:
        note = (f" Attribution is required: \"{asset.attribution_text}\" — I will "
                "include it.")
    return Verdict(ALLOWED, f"classified {asset.classification}", asset,
                   say=f"Rights are clear for that ({asset.classification}).{note}")


def check_all(paths: list[str], *, intent: str = "publish",
              commercial: bool = False) -> dict[str, Any]:
    """Every asset in a project. One blocked asset blocks the publication."""
    verdicts = {path: check(path, intent=intent, commercial=commercial)
                for path in paths}
    blocked = [p for p, v in verdicts.items() if not v.allowed]
    return {
        "allowed": not blocked,
        "blocked": blocked,
        "verdicts": {p: v.as_dict() for p, v in verdicts.items()},
        "say": ("Rights are clear for all of it." if not blocked else
                f"{len(blocked)} of {len(paths)} assets are not cleared to publish: "
                + ", ".join(blocked[:3])),
    }


def transformative_plan(*, borrowed_seconds: float, original_seconds: float,
                        kind: str = "commentary") -> dict[str, Any]:
    """Does the SHAPE of this edit read as commentary rather than a repost.

    Deliberately not a legal opinion, and it says so. It checks the one thing
    software honestly can: how much of the runtime is somebody else's.
    """
    total = max(0.001, borrowed_seconds + original_seconds)
    ratio = borrowed_seconds / total
    problems = []
    if ratio > registry.MAX_BORROWED_RATIO:
        problems.append(
            f"{int(ratio * 100)}% of it would be their footage. Under about "
            f"{int(registry.MAX_BORROWED_RATIO * 100)}% starts to look like "
            "commentary; above it looks like a repost with talking over it.")
    if original_seconds < registry.MIN_ORIGINAL_SECONDS:
        problems.append(
            f"only {original_seconds:.0f}s of it would be yours -- that is not "
            "enough for the result to be your work.")

    return {
        "kind": kind,
        "borrowed_seconds": round(borrowed_seconds, 1),
        "original_seconds": round(original_seconds, 1),
        "borrowed_ratio": round(ratio, 3),
        "shape_ok": not problems,
        "problems": problems,
        "suggestions": [text for _key, text in _ALTERNATIVES],
        "disclaimer": ("This is a check on the shape of the edit, not legal advice. "
                       "Fair use and fair dealing depend on where you are, what the "
                       "work is and what you do with it — if there is money or a "
                       "big audience involved, ask someone qualified."),
    }


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "decisions": [ALLOWED, NEEDS_DECLARATION, BLOCKED],
        "alternatives_offered": [key for key, _text in _ALTERNATIVES],
        "max_borrowed_ratio": registry.MAX_BORROWED_RATIO,
        "note": ("A refusal always carries the rights-compliant alternative. "
                 "Blocking someone's project without telling them how to get what "
                 "they wanted is not safety, it is just an obstacle."),
    }
