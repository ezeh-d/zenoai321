"""Did the web task actually succeed?

The failure this prevents: reporting "I searched and here are the results"
when the page never loaded, or a consent wall is showing, or the search box
was never filled. A browser action that returns without error is not the
same as a browser action that worked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Pages that look "loaded" but mean the task did not happen.
_BLOCKERS = (
    (r"\b(?:accept|manage)\s+(?:all\s+)?cookies?\b", "a cookie/consent wall is showing"),
    (r"\bverify (?:it'?s )?you\b|\bunusual traffic\b|\bcaptcha\b|\bi'?m not a robot\b",
     "a CAPTCHA or verification challenge is showing"),
    (r"\bsign in\b.{0,30}\bto continue\b|\blog in to continue\b", "a login wall is showing"),
    (r"\b(?:403|404|429|500|502|503)\b.{0,20}\b(?:forbidden|not found|error|unavailable)\b",
     "the page returned an error"),
    (r"\bno results found\b|\bdid not match any\b", "the search returned nothing"),
)


@dataclass
class Verdict:
    ok: bool
    reason: str
    blocker: str = ""
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "blocker": self.blocker,
                "evidence": self.evidence[:300]}


def check(url: str = "", title: str = "", text: str = "",
          expect: str = "") -> Verdict:
    """Judge a page against what the task was trying to achieve."""
    haystack = " ".join(p for p in (title, text) if p).lower()

    if not (url or title or text):
        return Verdict(False, "nothing came back from the browser -- the page was never read")

    for pattern, description in _BLOCKERS:
        if re.search(pattern, haystack, re.I):
            return Verdict(False, f"the page loaded but {description}", blocker=description,
                           evidence=title[:120])

    if expect:
        want = expect.strip().lower()
        if want in haystack:
            return Verdict(True, f"found {expect!r} on the page", evidence=title[:120])
        tokens = [t for t in re.split(r"\W+", want) if len(t) > 3]
        hits = [t for t in tokens if t in haystack]
        if tokens and len(hits) >= max(1, len(tokens) // 2):
            return Verdict(True, f"page matches {expect!r} ({len(hits)}/{len(tokens)} terms)",
                           evidence=title[:120])
        return Verdict(False, f"{expect!r} is not on the page", evidence=title[:120])

    if len(text.strip()) < 40:
        return Verdict(False, "the page has almost no readable text -- it probably did not load",
                       evidence=title[:120])
    return Verdict(True, f"page loaded ({len(text)} chars read)", evidence=title[:120])


def needs_confirmation(task: str) -> tuple[bool, str]:
    """Should the owner see the final action before it commits?

    Anything that submits, sends, buys or posts is shown first. Reading and
    navigating are not.
    """
    text = str(task or "").lower()
    for pattern, why in (
        (r"\b(?:submit|apply|send|post|publish|comment|review)\b",
         "this submits something on your behalf"),
        (r"\b(?:buy|purchase|checkout|order|pay|subscribe)\b",
         "this spends money"),
        (r"\b(?:delete|remove|cancel|close (?:the )?account|unsubscribe)\b",
         "this is destructive and hard to undo"),
    ):
        if re.search(pattern, text):
            return True, why
    return False, ""
