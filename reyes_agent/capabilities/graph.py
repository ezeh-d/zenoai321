"""What a goal actually requires, so a refusal can name the missing piece.

THE FAILURE THIS REPLACES
-------------------------
    "ZENO, automate my email."
    "I don't currently support email automation."

That answer is useless because it conflates three very different situations:
ZENO does not understand the request; ZENO understands it but lacks a tool;
ZENO has the tool but no permission. Only the second and third are
actionable, and only if the missing piece is NAMED.

So goals map to required capabilities, capabilities map to their
dependencies, and a gap is reported as "you have not connected a mailbox"
rather than as a shrug.

REQUIRED vs OPTIONAL
--------------------
Email automation genuinely cannot happen without a mailbox. It can happen
without a calendar -- worse, but possible. Conflating those produces an
assistant that refuses whole tasks over a nice-to-have, so every edge says
which it is.

The map below is a starting set, not a closed world. `plan()` falls back to
keyword matching over capability descriptions for goals nobody enumerated,
and an unmapped goal returns UNKNOWN rather than a wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reyes_agent.capabilities import registry

# goal -> (required, optional). Names must exist in the capability registry.
GOALS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "email_automation": (("email_provider",), ("calendar", "memory", "skills", "gemini")),
    "calendar_management": (("calendar",), ("memory", "skills")),
    "meeting_preparation": ((), ("calendar", "email_provider", "memory",
                                 "semantic_search", "web_research")),
    "web_research": (("web_research",), ("semantic_search", "memory", "gemini")),
    "document_analysis": (("docling",), ("semantic_search", "gemini")),
    "data_analysis": (("duckdb",), ("pandas", "gemini")),
    "spreadsheet_work": (("pandas",), ("duckdb",)),
    "invoice_reconciliation": (("docling", "duckdb"), ("pandas", "gemini")),
    "code_work": (("python",), ("git", "sandbox", "agents")),
    "repository_work": (("git",), ("github", "agents")),
    "browser_automation": (("playwright",), ("computer_control", "web_research")),
    "desktop_automation": (("computer_control",), ("skills",)),
    "image_work": (("opencv",), ()),
    "media_conversion": (("ffmpeg",), ()),
    "voice_interaction": ((), ("deepgram", "elevenlabs", "ollama")),
    "home_control": (("home_assistant",), ()),
    "long_running_work": (("missions",), ("agents", "skills")),
    "local_ai": (("ollama",), ()),
    "logo_design": ((), ("opencv", "computer_control", "web_research")),
    "business_analysis": ((), ("web_research", "semantic_search", "agents",
                               "duckdb", "gemini")),
    # Pure reasoning. It needs a model and nothing else -- leaving these
    # unmapped made decomposition pessimistic, marking "write the copy" as
    # impossible when it is the one thing an LLM assistant is certain to
    # manage. `reasoning` lists both providers so either satisfies it.
    "content_writing": ((), ("gemini", "openai", "ollama", "semantic_search")),
    "reasoning": ((), ("gemini", "openai", "ollama")),
    "summarisation": ((), ("gemini", "openai", "ollama")),
    "reporting": ((), ("gemini", "openai", "semantic_search")),
}

# Words that point at a goal. Matched against the request, longest first so
# "email automation" beats a bare "email".
_HINTS: dict[str, tuple[str, ...]] = {
    "email_automation": ("email automation", "automate my email", "automate email",
                         "inbox", "my email", "emails", "email"),
    "calendar_management": ("calendar", "schedule a meeting", "my schedule"),
    "meeting_preparation": ("prepare me for", "prepare for tomorrow", "brief me",
                            "meeting prep", "prepare for my meeting"),
    "web_research": ("research", "look up", "find out about", "search the web"),
    "document_analysis": ("this pdf", "this document", "read the document",
                          "docx", "pptx", "contract"),
    "data_analysis": ("analyse the data", "analyze the data", "dataset", "csv",
                      "sales file", "what's wrong with this file"),
    "spreadsheet_work": ("spreadsheet", "excel", "xlsx"),
    "invoice_reconciliation": ("reconcile", "invoice", "invoices", "accounting"),
    "code_work": ("write code", "refactor", "fix the bug", "unit test"),
    "repository_work": ("repository", "repo", "pull request", "github"),
    "browser_automation": ("automate this website", "fill this form", "scrape",
                           "this website"),
    "desktop_automation": ("this application", "this app", "automate the repetitive",
                           "click", "open the app"),
    "image_work": ("image", "screenshot", "picture", "photo"),
    "media_conversion": ("convert video", "convert audio", "transcode", "mp4", "mp3"),
    "voice_interaction": ("speak", "say out loud", "voice"),
    "home_control": ("lights", "thermostat", "smart home"),
    "long_running_work": ("over the next few days", "long running", "keep working on"),
    "local_ai": ("offline model", "local model", "without internet"),
    "logo_design": ("logo", "brand mark", "design a logo"),
    "business_analysis": ("what can we automate", "analyse this business",
                          "analyze this business", "my business"),
    "content_writing": ("write the campaign copy", "write copy", "draft the copy",
                        "write a post", "write an article", "copywriting"),
    "reasoning": ("decide the offer", "decide", "work out", "think through",
                  "choose between"),
    "summarisation": ("summarise", "summarize", "tl;dr", "condense"),
    "reporting": ("prepare a report", "write a report", "produce a report"),
}


@dataclass
class Gap:
    capability: str
    state: str
    why: str
    optional: bool = False
    hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "state": self.state, "why": self.why,
                "optional": self.optional, "hint": self.hint}


@dataclass
class Assessment:
    goal: str
    matched: str = ""
    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    have: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    @property
    def blocking(self) -> list[Gap]:
        return [g for g in self.gaps if not g.optional]

    @property
    def can_do(self) -> bool:
        return bool(self.matched) and not self.blocking

    @property
    def degraded(self) -> bool:
        return self.can_do and any(g.optional for g in self.gaps)

    def as_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "matched": self.matched or None,
                "can_do": self.can_do, "degraded": self.degraded,
                "have": self.have, "gaps": [g.as_dict() for g in self.gaps],
                "blocking": [g.capability for g in self.blocking]}


def identify(request: str) -> str:
    """Which known goal a request is asking for, or "" when unrecognised."""
    text = str(request or "").strip().lower()
    if not text:
        return ""
    best, best_len = "", 0
    for goal, hints in _HINTS.items():
        for hint in hints:
            if hint in text and len(hint) > best_len:
                best, best_len = goal, len(hint)
    return best


def assess(request: str) -> Assessment:
    """What this goal needs, and precisely what is missing."""
    registry.status()          # ensure the registry is seeded
    goal = identify(request)
    result = Assessment(goal=str(request or ""), matched=goal)
    if not goal:
        return result

    required, optional = GOALS.get(goal, ((), ()))
    result.required, result.optional = list(required), list(optional)

    for names, is_optional in ((required, False), (optional, True)):
        for name in names:
            capability = registry.get(name)
            if capability is None:
                result.gaps.append(Gap(name, "UNKNOWN",
                                       "ZENO has no record of this capability",
                                       is_optional))
                continue
            state, why = capability.health()
            if state in registry.USABLE:
                result.have.append(name)
            else:
                result.gaps.append(Gap(name, state, why, is_optional,
                                       capability.install_hint))
    return result


def dependents(name: str) -> list[str]:
    """Which goals become impossible if this capability is missing."""
    return sorted(goal for goal, (required, _optional) in GOALS.items()
                  if name in required)


def status() -> dict[str, Any]:
    registry.status()
    reachable, blocked = [], []
    for goal in GOALS:
        (reachable if assess(goal.replace("_", " ")).can_do else blocked).append(goal)
    return {
        "state": "ONLINE",
        "goals_known": len(GOALS),
        "reachable_now": sorted(reachable),
        "blocked": sorted(blocked),
        "note": ("A blocked goal names the capability that blocks it. "
                 "'I don't support that' is never the answer on its own."),
    }
