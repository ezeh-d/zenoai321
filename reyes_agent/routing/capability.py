"""Deciding which tools the model is even shown.

THE MEASURED PROBLEM
--------------------
105 tool schemas went to the model on every turn. This repository already
measured what that costs -- ~5.4s at 93 schemas against ~1.5s at 5 -- and
"what time is it" was taking 10 seconds. Most of that was not thinking. It
was the model reading a catalogue of things it was never going to use.

WHY CLASSIFICATION IS NOT ANOTHER MODEL CALL
--------------------------------------------
Solving schema overload by adding an LLM call to every request would trade
one latency source for another. So the classifier is deterministic: word
boundaries, a small amount of grammar, and the recent conversation. It runs
in microseconds and is measured in the router telemetry.

THE ASYMMETRY THAT SHAPES EVERYTHING HERE
------------------------------------------
Missing a needed tool costs one extra round -- the model asks, `enable_tools`
widens, the turn continues. Exposing a dangerous tool that was never wanted
costs something that cannot be undone. So the two failures are NOT weighted
equally:

  * A low-confidence match expands to a WIDER set, never to everything.
  * A destructive capability requires an imperative, not a mention.
    "What does deleting a folder mean" is a question about deletion; it does
    not get the tool that deletes folders. That distinction is the whole
    reason this file matches grammar rather than keywords.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Always available: how ZENO asks for more, and how he hands off. Kept
# deliberately tiny -- an "essential" set is where a 105-tool payload grows
# back one well-meaning addition at a time.
ESSENTIAL = ("enable_tools", "delegate")

# Capability -> the tools it owns. Derived from real registered names.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "conversation": (),
    "utility": ("get_datetime", "resolve_time", "system_health", "system_status",
                "read_clipboard", "write_clipboard", "set_volume", "media_control",
                "current_activity", "check_presence"),
    "memory": ("remember", "forget_fact", "search_memories", "list_memories",
               "memory_versions", "compare_memory_versions",
               "restore_memory_version", "write_note", "search_notes",
               "list_notes", "link_notes", "search_vault_semantic",
               "explore_knowledge", "knowledge_graph_stats"),
    "web": ("web_search", "get_news", "website_check", "research_lab"),
    # ZENO's own Instagram and TikTok. Status is the common question, so the
    # read-only tools are first; publishing tools are here too because the
    # owner asks about posting in the same breath as asking about numbers.
    "social": ("social_status", "social_health", "social_content",
               "social_ideas", "social_advance", "social_approval_card",
               "social_approve", "social_schedule", "social_publish",
               "social_leads", "social_comments", "social_classify",
               "social_control", "social_identity", "social_setup"),
    "browser": ("browser_open", "browser_click", "browser_read", "browser_fill",
                "browser_scroll", "browser_extract", "browser_screenshot",
                "browser_close", "browser_vision_click", "web_search"),
    "desktop": ("open_app", "run_command", "list_processes", "lock_screen",
                "read_screen_text", "take_screenshot", "open_path",
                "media_control", "set_volume"),
    "files": ("read_file", "write_project_file", "list_dir", "list_project_files",
              "read_document", "open_path", "move_file"),
    "files_destructive": ("delete_file",),
    "coding": ("write_project_file", "read_file", "list_project_files",
               "build_project", "run_command", "website_project",
               "website_restore_checkpoint"),
    "vision": ("take_screenshot", "read_screen_text", "take_webcam_photo",
               "understand_video", "ocr_capabilities", "recognize_audio"),
    "agents": ("agent_roster", "who_is_agent", "agent_roll_call", "agent_status",
               "agent_introduction", "delegate"),
    "council": ("convene_council", "executive_meeting", "agent_roster"),
    "communication": ("send_message", "send_slack_message",
                      "send_telegram_message", "check_email"),
    "business": ("portfolio_report", "paper_trade", "paper_portfolio",
                 "backtest_strategy", "create_campaign", "campaign_status"),
    "career": ("career_profile_status", "career_profile_read",
               "career_profile_update", "career_profile_fill_field",
               "career_platform_plan",
               "browser_open", "browser_read"),
    "paid_work": ("paid_work_status", "paid_work_scout",
                  "paid_work_ingest_opportunity", "paid_work_opportunities",
                  "paid_work_prepare_application", "paid_work_record_submission",
                  "paid_work_profile_variant", "paid_work_portfolio_list", "paid_work_focus",
                  ),
    "client_work": ("paid_work_status", "paid_work_client_review",
                    "paid_work_client_message",
                    "paid_work_set_pricing", "paid_work_negotiate",
                    "paid_work_contract", "paid_work_project", "paid_work_payment",
                    "paid_work_record_delivery", "paid_work_owner_decision"),
    "builder": ("build_project", "website_project", "write_project_file",
                "list_project_files", "website_restore_checkpoint"),
    "creative": ("creator_project", "design_capabilities", "learning_mode",
                 "mastery_mode", "foodie_mode"),
    "missions": ("create_mission", "list_missions", "simulate_mission",
                 "resume_workspace"),
    "diagnostics": ("system_health", "system_status", "phase3_status",
                    "evolution_report", "awareness_status", "digital_dna",
                    "voice_profile_status", "ocr_capabilities"),
    "presentation": ("siwes_evidence", "prepare_for_visit",
                     "start_visitor_session", "set_serious_mode"),
    "workflow": ("workflow_run", "workflow_teach", "workflow_confirm"),
    "voice": ("learn_my_voice", "voice_profile_status", "set_mic_level"),
}

# What each capability may cost, so a bug cannot quietly reintroduce a
# 105-schema payload. Checked by a regression test.
BUDGETS: dict[str, int] = {
    "conversation": 3, "utility": 12, "memory": 16, "web": 8, "browser": 14,
    "desktop": 12, "files": 10, "files_destructive": 4, "coding": 14,
    "vision": 10, "agents": 8, "council": 6, "communication": 8,
    "business": 10, "career": 10, "paid_work": 10, "client_work": 10,
    "builder": 10, "creative": 8, "missions": 8,
    "social": 15, "diagnostics": 10, "presentation": 8, "workflow": 6, "voice": 6,
}

# Intent patterns. Ordered by specificity: the first match wins, so narrow
# beats broad. These match GRAMMAR, not bare nouns -- see the module note.
_INTENT: tuple[tuple[str, str], ...] = (
    # Destructive: an imperative aimed at a target. A question about deletion
    # is not a request to delete, and must not be given the tool.
    ("files_destructive",
     r"^\s*(?:please\s+)?(?:delete|remove|erase|rm)\s+(?:the\s+|my\s+|this\s+)?\S+"),

    # Social. Matches ZENO's OWN accounts and content operations. "post" alone
    # is far too broad (post a letter, blog post), so every alternative here
    # needs a social object or a possessive referring to ZENO's presence.
    ("social",
     r"\b(?:instagram|tiktok|tik tok|reels?|socials?|"
     r"(?:your|zeno[''‘’]?s?) (?:followers?|posts?|videos?|content|captions?|"
     r"hashtags?|account|audience|engagement)|"
     r"(?:content|posting) (?:idea|ideas|calendar|plan|schedule)|"
     r"(?:publish|schedule|approve|draft) (?:a |the |this |that )?"
     r"(?:post|reel|video|caption|clip)|"
     r"client leads?|potential clients?|social (?:media|dashboard|analytics)|"
     r"(?:check|read|show) (?:your|my) comments|"
     r"(?:your|zeno's) (?:comments|dms?|messages) )\b"),

    ("council", r"\b(?:council|all (?:my |the )?agents|everyone['’]?s view|"
                r"ask (?:them|everyone)|executive meeting)\b"),
    ("agents", r"\b(?:who is|what does|who works under|role ?call|your agents?|"
               r"agent (?:status|roster)|which agent)\b"),
    ("career", r"\b(?:(?:create|complete|update|maintain|optimise|optimize|audit|fix)\s+"
               r"(?:my\s+)?(?:job|career|freelance|indeed|linkedin|upwork|fiverr|freelancer)?\s*profile|"
               r"(?:indeed|linkedin|upwork|fiverr|freelancer)\s+(?:account|profile)|"
               r"(?:my\s+)?(?:career profile|professional profile|cv versions?|cover letter templates?))\b"),
    ("client_work", r"\b(?:client (?:replied|response|message|suspicious|risk|project|paid)|"
                    r"check (?:this|the) client|what should i charge|negotiate (?:this|the)|"
                    r"contract approval|active (?:client )?projects?|project ready|"
                    r"scope creep|revision request|payment (?:due|overdue|reported|verified)|"
                    r"has (?:the )?client paid|needs? my approval|verified revenue)\b"),
    ("paid_work", r"\b(?:find (?:me )?(?:jobs?|work|freelance work|gigs?|clients?)|"
                  r"best opportunities|prepare (?:this|the|my) (?:application|proposal)|"
                  r"which cv|job (?:match|application|platform)|freelance (?:work|project)|"
                  r"online work|application (?:history|status|approval)|"
                  r"focus on .{0,40}(?:jobs?|projects?|work)|paid[- ]work)\b"),
    ("browser", r"\b(?:browse|browser|open (?:chrome|edge|firefox)|go to \S+\.\w|"
                r"search (?:google|youtube|the web|online)|on (?:google|youtube)|"
                r"click (?:the|that|first)|scroll (?:down|up)|this (?:page|site)|"
                r"navigate|url|website)\b"),
    ("desktop", r"\b(?:open|launch|start|close|quit)\s+(?:the\s+)?"
                r"(?:app|application|calculator|notepad|explorer|terminal|"
                r"vs ?code|pycharm|slack|word|excel|settings)\b"
                r"|\block (?:the )?screen\b|\bvolume\b|\bmute\b|\bwhat.*running\b"),
    ("vision", r"\b(?:look at|what.*on (?:my|the) screen|see (?:my|the) screen|"
               r"screenshot|read (?:the )?screen|webcam|camera|this image)\b"),
    ("communication", r"\b(?:send|message|text|email|slack|telegram|whatsapp|"
                      r"tell \w+ (?:that|to)|reply to)\b"),
    # Recall rarely puts the verb next to the question word: "what COLOUR did
    # I tell you", "which NUMBER did I say". Allowing a few words between is
    # the difference between recalling a fact and answering from thin air.
    ("memory", r"\b(?:remember|memorise|memorize|forget|recall|"
               r"(?:what|which|who|where)\s+(?:\w+\s+){0,3}did i (?:say|tell|mention|give)|"
               r"did i (?:say|tell|mention)|"
               r"my notes?|note that|save (?:this|that) (?:for|to)|"
               r"(?:what|which)\s+(?:\w+\s+){0,3}(?:was|is|were) my\b)"),
    ("coding", r"\b(?:fix (?:this|the) (?:bug|error|code)|traceback|stack ?trace|"
               r"exception|refactor|write (?:a )?(?:function|script|class)|"
               r"debug|compile|unit test)\b"),
    ("builder", r"\b(?:build (?:me |the |a )?(?:site|website|app|project)|"
                r"create (?:a |the )?(?:website|web app|landing page))\b"),
    ("business", r"\b(?:portfolio|invest|trade|revenue|business idea|"
                 r"opportunit(?:y|ies)|campaign|market)\b"),
    ("web", r"\b(?:search for|look up|google|find out|latest news|what.*happening|"
            r"research)\b"),
    ("files", r"\b(?:file|folder|directory|read (?:the )?\S+\.\w+|save (?:it |this )?to|"
              r"list (?:the )?(?:files|dir))\b"),
    ("presentation", r"\b(?:siwes|evidence|portfolio|engr bello|visitor|"
                     r"presentation|serious mode|ultron)\b"),
    ("diagnostics", r"\b(?:health|diagnostic|status of|are you (?:ok|working)|"
                    r"system status)\b"),
    ("voice", r"\b(?:learn my voice|my voice|microphone level|mic level)\b"),
    ("workflow", r"\b(?:workflow|routine|do that again|the usual)\b"),
    ("missions", r"\b(?:mission|task list|what.*working on)\b"),
    ("utility", r"\b(?:what time|what.*date|today.*date|clipboard|"
                r"how (?:much|many).*(?:ram|cpu|memory|disk))\b"),
)
_COMPILED = tuple((name, re.compile(pattern, re.I)) for name, pattern in _INTENT)

# Follow-ups that carry no capability of their own and must inherit.
_FOLLOW_UP = re.compile(
    r"^\s*(?:and |then |also |now )?(?:do (?:that|it)|open it|search for it|"
    r"click (?:it|that)|again|the same|that one|there|next one|go back|"
    r"close it|scroll|read it|save (?:it|that))\b", re.I)

# How long a capability stays inherited. Long enough for a real follow-up,
# short enough that an unrelated question later is judged on its own.
CONTEXT_TTL_S = 120.0

_lock = threading.RLock()
_context: dict[str, Any] = {"capabilities": (), "at": 0.0, "source": ""}


@dataclass
class Route:
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    confidence: str = "low"          # clear | inherited | low
    reason: str = ""
    latency_ms: float = 0.0
    considered: int = 0
    exposed: int = 0
    expanded: bool = False
    request_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id,
                "capabilities": list(self.capabilities),
                "tools_exposed": self.exposed, "tools_registered": self.considered,
                "confidence": self.confidence, "reason": self.reason,
                "router_latency_ms": round(self.latency_ms, 3),
                "expanded": self.expanded,
                "tools": list(self.tools)}

    def explain(self) -> str:
        """For 'why did you choose that tool?'. Routing facts, not reasoning."""
        if not self.capabilities:
            return (f"I treated that as ordinary conversation, so I offered "
                    f"{self.exposed} tools instead of {self.considered}.")
        return (f"I read that as {', '.join(self.capabilities)}, so I loaded "
                f"{self.exposed} of {self.considered} tools "
                f"({self.confidence} match: {self.reason}).")


def remember_context(capabilities: tuple[str, ...], *, source: str = "") -> None:
    with _lock:
        _context.update({"capabilities": tuple(capabilities), "at": time.time(),
                         "source": source})


def _inherited() -> tuple[str, ...]:
    with _lock:
        if time.time() - _context["at"] <= CONTEXT_TTL_S:
            return tuple(_context["capabilities"])
    return ()


def clear_context() -> None:
    with _lock:
        _context.update({"capabilities": (), "at": 0.0, "source": "cleared"})


def classify(message: str) -> tuple[tuple[str, ...], str, str]:
    """(capabilities, confidence, reason). Deterministic and fast."""
    text = (message or "").strip()
    if not text:
        return (), "clear", "nothing was said"

    # A follow-up inherits rather than being judged alone. "Search for it"
    # after opening a browser is a browser command; classified on its own it
    # is a web search, and the browser context is lost.
    if _FOLLOW_UP.match(text):
        carried = _inherited()
        if carried:
            return carried, "inherited", "a follow-up to the previous request"

    found: list[str] = []
    for name, pattern in _COMPILED:
        if pattern.search(text):
            found.append(name)
            if len(found) >= 3:      # three capabilities is already generous
                break

    if found:
        return tuple(found), "clear", f"matched {found[0]}"

    # Nothing matched. A question with no capability marker is conversation,
    # which is the common case and the one worth being fastest at.
    if len(text.split()) <= 12:
        return (), "clear", "short conversational turn"
    return ("memory", "web"), "low", "no clear capability; offering a modest set"


def tools_for(message: str, *, expand: bool = False) -> Route:
    """The tool names to expose for this message."""
    from reyes_agent.tools import TOOLS

    started = time.perf_counter()
    request_id = f"r{int(time.time() * 1000) % 10_000_000}"
    capabilities, confidence, reason = classify(message)

    names: list[str] = list(ESSENTIAL)
    for capability in capabilities:
        budget = BUDGETS.get(capability, 12)
        for tool in CAPABILITIES.get(capability, ())[:budget]:
            if tool not in names:
                names.append(tool)

    # Controlled expansion, never "everything". One step wider: the
    # neighbouring capabilities, not the whole registry.
    if expand:
        for extra in ("utility", "memory", "files", "web"):
            for tool in CAPABILITIES.get(extra, ())[:6]:
                if tool not in names:
                    names.append(tool)

    exposed = tuple(n for n in names if n in TOOLS)
    if capabilities:
        remember_context(capabilities, source=message[:40])

    return Route(capabilities=capabilities, tools=exposed, confidence=confidence,
                 reason=reason, latency_ms=(time.perf_counter() - started) * 1000,
                 considered=len(TOOLS), exposed=len(exposed), expanded=expand,
                 request_id=request_id)


def status() -> dict[str, Any]:
    from reyes_agent.tools import TOOLS

    return {
        "state": "ONLINE",
        "registered_tools": len(TOOLS),
        "capabilities": len(CAPABILITIES),
        "essential_always": list(ESSENTIAL),
        "context_ttl_s": CONTEXT_TTL_S,
        "held_context": _inherited(),
        "rule": ("Missing a tool costs one extra round; exposing a dangerous "
                 "one cannot be undone. Destructive capabilities need an "
                 "imperative, not a mention."),
    }
