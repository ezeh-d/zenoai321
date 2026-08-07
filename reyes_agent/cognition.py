"""The Intelligence Router -- one authoritative decision about how hard to think.

WHY THIS IS A HEURISTIC AND NOT A MODEL CALL
--------------------------------------------
The point of routing is to make simple things fast. Asking a model "is this
simple?" costs a full round trip, so a model-based router would add latency
to exactly the requests it exists to speed up, and would make ZENO slower
overall than having no router at all. So this is pure local text analysis:
microseconds, no network, no tokens.

It is deliberately a ROUTER, not a second brain. It decides:

  * PATH   -- FAST (answer now) or DEEP (think, plan, verify)
  * MODES  -- what the turn actually needs: action, memory, research,
              advice, specialists, council
  * BUDGET -- tool rounds and whether specialists may be woken

...and nothing else. It never answers, never calls a tool, and never
overrides the model's own judgement mid-turn. `agent.py` uses the budget;
`provider.py` uses the model kind; `instinct.py` uses the modes.

HONESTY
-------
Heuristics misclassify. Every decision carries `reasons` naming the signals
that fired, and the FAST path is deliberately *not* a cap on thinking: a
FAST turn that turns out to need tools still gets them, it just starts with
a smaller budget. Misrouting costs a little speed, never correctness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# --- paths ---------------------------------------------------------------
FAST = "FAST"
DEEP = "DEEP"

# --- modes (a turn can carry several) ------------------------------------
CHAT = "CHAT"
ACTION = "ACTION"
MEMORY = "MEMORY"
RESEARCH = "RESEARCH"
ADVICE = "ADVICE"
SPECIALIST = "SPECIALIST"
COUNCIL = "COUNCIL"
CREATOR = "CREATOR"
LEARNING = "LEARNING"
MASTERY = "MASTERY"
FOODIE = "FOODIE"
WEBSITE_BUILDER = "WEBSITE_BUILDER"

# Tool-round budgets. FAST keeps the loop short so a greeting cannot spend
# eight rounds; DEEP gets the existing full budget.
FAST_ROUNDS = 3
DEEP_ROUNDS = 8


@dataclass(frozen=True)
class Route:
    path: str
    modes: tuple[str, ...]
    reasons: tuple[str, ...]
    complexity: float          # 0..1, from the signals below
    model_kind: str            # feeds model_router.route()
    max_tool_rounds: int
    allow_specialists: bool
    normalized: str = ""       # informal/Pidgin resolved, for diagnostics
    signals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "path": self.path, "modes": list(self.modes), "reasons": list(self.reasons),
            "complexity": self.complexity, "model_kind": self.model_kind,
            "max_tool_rounds": self.max_tool_rounds,
            "allow_specialists": self.allow_specialists, "signals": self.signals,
        }


# --- informal / Nigerian English normalisation ---------------------------
# ZENO must UNDERSTAND these, never correct them. This map exists only so
# the router's keyword signals fire on Pidgin the same way they fire on
# standard English -- the user's own words are what reach the model.
_PIDGIN = {
    r"\babeg\b": "please", r"\bwetin\b": "what", r"\bwahala\b": "problem",
    r"\bdey\b": "is", r"\bdon\b": "has", r"\bnaw?\b": "is",
    r"\bcomot\b": "remove", r"\bgo?ff\b": "off", r"\bmake i\b": "let me",
    r"\bmake you\b": "please", r"\bno be\b": "is not", r"\bshey\b": "is it that",
    r"\bhow far\b": "what is the status", r"\bsabi\b": "know",
    r"\bvex\b": "angry", r"\bfix am\b": "fix it", r"\bcheck am\b": "check it",
    r"\bdo am\b": "do it", r"\bopen am\b": "open it", r"\bshow me am\b": "show it",
    r"\bpikin\b": "child", r"\bchop\b": "eat", r"\bgist\b": "news",
    r"\bjare\b": "", r"\bsha\b": "", r"\bo{2,}\b": "",
}

_FILLERS = (
    "um", "uh", "erm", "eh", "ehm", "hmm", "like", "you know", "i mean",
    "sort of", "kind of", "basically", "actually", "well",
)


# One alternation instead of ~30 sequential passes. Measured 2026-08-07:
# looping the substitutions cost 2.4ms per route; a single compiled pass
# costs a fraction of that. Routing runs on every turn, so its own cost has
# to stay far below the thing it is optimising.
_PIDGIN_RE = re.compile("|".join(f"(?P<g{i}>{p})" for i, p in enumerate(_PIDGIN)))
_PIDGIN_BY_GROUP = {f"g{i}": r for i, r in enumerate(_PIDGIN.values())}


def normalize(text: str) -> str:
    """Lower-cased, informal-resolved copy used ONLY for signal matching."""
    lowered = " ".join(str(text or "").lower().split())
    replaced = _PIDGIN_RE.sub(
        lambda m: _PIDGIN_BY_GROUP.get(m.lastgroup, ""), lowered)
    return " ".join(replaced.split())


# --- signal vocabularies -------------------------------------------------
# Deliberately small and specific. A big fuzzy keyword list produces
# confident nonsense; these are words that genuinely change what a turn needs.

_ACTION_VERBS = (
    "create", "build", "make", "generate", "set up", "setup", "save", "write",
    "open", "launch", "start", "run", "execute", "install", "edit", "change",
    "modify", "update", "move", "rename", "delete", "remove", "preview",
    "test", "deploy", "fix", "repair", "download", "upload", "send", "close",
)

_DEEP_MARKERS = (
    "why", "analyse", "analyze", "architecture", "design", "debug",
    "investigate", "diagnose", "root cause", "compare", "trade-off", "tradeoff",
    "strategy", "optimise", "optimize", "refactor", "migrate", "scale",
    "unstable", "keeps failing", "keeps breaking", "intermittent", "race condition",
    "memory leak", "deadlock", "bottleneck", "performance", "security",
    "best way", "pros and cons", "implications", "long term", "long-term",
    # Failure language. Diagnosing why something breaks is depth work even
    # when the sentence is short -- "why does this keep crashing" is not a
    # quick answer, it is an investigation.
    "crash", "crashes", "crashing", "hang", "hangs", "hanging", "freeze",
    "freezes", "stuck", "broken", "not working", "doesn't work", "fails",
    "rewrite", "rebuild", "from scratch", "start over", "overhaul",
)

# Something is broken. Working out WHY is an investigation, never a quick
# answer, so any of these alone is enough to earn the deep path -- the
# sentence reporting a crash is usually short, which is exactly why a
# length-based score would misread it.
_FAILURE_MARKERS = (
    "crash", "crashes", "crashing", "hang", "hangs", "hanging", "freeze",
    "freezes", "stuck", "broken", "not working", "doesn't work", "fails",
    "keeps failing", "keeps breaking", "unstable", "intermittent",
    "memory leak", "deadlock", "race condition",
)

_ADVICE_MARKERS = (
    "should i", "should we", "worth it", "recommend", "do you think",
    "is it better", "better to", "thinking about", "planning to", "about to",
    "good idea", "bad idea", "advise", "advice", "what would you do",
    "am i right", "does it make sense",
    # Stated intentions. These are the moments where advice is most useful
    # and most often unasked-for -- "I'm going to rewrite everything" wants
    # a considered response, not agreement.
    "i'm going to", "im going to", "i am going to", "i'll just", "ill just",
    "i want to rewrite", "i plan to", "i'm thinking of", "im thinking of",
    "i think i should",
)

_RESEARCH_MARKERS = (
    "research", "look up", "find out", "search for", "latest", "news",
    "what's happening", "whats happening", "current price", "who is",
    "documentation", "docs for",
)

_MEMORY_MARKERS = (
    "remember", "we discussed", "we talked", "earlier", "last time",
    "you said", "we decided", "what was", "remind me", "previously",
    "before", "our conversation",
)

_COUNCIL_MARKERS = (
    "council", "convene", "every perspective", "all perspectives",
    "different angles", "debate", "executive meeting", "roll call",
)

_SPECIALIST_HINTS = {
    "coding": ("code", "function", "bug", "stack trace", "traceback", "compile",
               "typescript", "python", "javascript", "api", "database", "sql",
               "regex", "async", "thread", "exception"),
    "research": ("research", "paper", "study", "evidence", "sources"),
    "reasoning": ("strategy", "decision", "trade-off", "tradeoff", "risk",
                  "architecture", "plan", "roadmap", "business", "invest"),
    "vision": ("screenshot", "image", "photo", "screen", "webcam", "picture"),
}

# Design teaching and a full identity are meaningfully different from a
# one-line definition such as "what is kerning?".  The latter remains FAST;
# these signals only deepen requests that need discovery, a learning path, or
# a coherent multi-part visual system.
_DESIGN_MARKERS = (
    "graphic design", "logo design", "brand identity", "branding", "creative direction",
    "typography", "colour theory", "color theory", "ui ux", "ui/ux", "design system",
    "flyer", "poster", "vector design",
)
_LEARNING_MARKERS = (
    "teach me", "teach us", "learning path", "from zero", "beginner path", "continue my lesson",
    "continue learning", "study plan", "learn by doing",
)
_CREATOR_MARKERS = ("creator mode", "create something", "i have an idea", "build a brand", "start a brand", "food business")
_MASTERY_MARKERS = ("master", "mastery", "professional level", "final assessment", "client-style project")
_FOODIE_MARKERS = ("foodie mode", "what should we cook", "recipe", "cook together", "jollof", "egusi", "meal plan", "ingredients", "too salty", "too watery", "mushy rice", "baking", "egg", "eggs", "boil")
_WEBSITE_MARKERS = ("website mode", "web builder", "build me a website", "create a website", "company website", "restaurant website", "portfolio website", "landing page", "homepage", "hero section", "mobile layout", "dark mode", "preview the website", "website")
_DESIGN_DEEP_MARKERS = (
    "complete brand identity", "full brand identity", "full identity", "brand strategy",
    "full ui system", "design system", "five competitors", "design a full", "logo design process",
)

# Follow-ups that refer to whatever is already happening. These are FAST and
# strongly imply the active task rather than a new one -- "make it darker"
# must edit the running project, not start a second.
_FOLLOWUP_MARKERS = (
    "how far", "what is the status", "status", "how's it going", "hows it going",
    "make it", "change it", "open it", "show it", "darker", "lighter", "bigger",
    "smaller", "instead", "also add", "and add", "as well", "same thing",
)

_PRONOUN_ONLY = re.compile(r"^\s*(it|that|this|them|those|he|she|they)\b", re.I)

_GREETINGS = (
    "hi", "hey", "hello", "yo", "morning", "good morning", "good afternoon",
    "good evening", "how are you", "how you dey", "wassup", "what's up",
    "thanks", "thank you", "ok", "okay", "cool", "nice", "great", "lol",
    "haha", "bye", "goodnight", "good night",
)

_SENSITIVE = (
    "died", "death", "passed away", "funeral", "grief", "cancer", "diagnosis",
    "hospital", "emergency", "suicide", "self harm", "self-harm", "abuse",
    "assault", "lost my job", "fired", "divorce", "miscarriage", "overdose",
)


_vocab_cache: dict[tuple, re.Pattern] = {}


def _compiled(needles: tuple) -> re.Pattern:
    """One alternation per vocabulary, built once.

    Searching ~200 needles as ~200 separate regexes cost 2.4ms per route
    (measured). One compiled alternation per vocabulary scans the text once.
    Needles are sorted longest-first because Python's alternation is
    leftmost-FIRST, not leftmost-longest: without it "i am going to" would
    lose to a shorter overlapping entry.
    """
    pattern = _vocab_cache.get(needles)
    if pattern is None:
        ordered = sorted(needles, key=len, reverse=True)
        pattern = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(n) for n in ordered) + r")(?!\w)")
        _vocab_cache[needles] = pattern
    return pattern


def _has(text: str, needles) -> list[str]:
    """Word-boundary matching, not substring.

    Substring matching looked fine until it didn't: "rewrite" contains the
    action verb "write", and "latest" contains "test", so "should we rewrite
    this?" was classified as an ACTION and "what's the latest news" wanted
    to run a test. Boundaries make a keyword mean the word.
    """
    if not isinstance(needles, tuple):
        needles = tuple(needles)
    return list(dict.fromkeys(_compiled(needles).findall(text)))


def _clause_count(text: str) -> int:
    parts = re.split(r"[.!?;]+|\band\b|\bthen\b|\bbut\b|\bbecause\b|\bafter\b", text)
    return sum(1 for p in parts if len(p.strip().split()) >= 2)


def is_sensitive(text: str) -> bool:
    """Topics where humour and cleverness are never appropriate."""
    return bool(_has(normalize(text), _SENSITIVE))


# --- the router ----------------------------------------------------------

def _route_uncached(message: str, *, has_active_task: bool = False,
                    recent_turns: int = 0, explicit_deep: bool = False) -> Route:
    """Decide how hard this turn should think. Pure, fast, no side effects.

    `has_active_task` matters a great deal: with a build running, "how far?"
    and "make it darker" are follow-ups on that task rather than new work,
    which is what stops ZENO creating a duplicate project.
    """
    raw = str(message or "").strip()
    text = normalize(raw)
    words = text.split()
    word_count = len(words)

    modes: list[str] = []
    reasons: list[str] = []
    signals: dict = {"words": word_count}

    # --- explicit overrides come first -----------------------------------
    if explicit_deep or any(m in text for m in ("think deeply", "think hard", "take your time")):
        reasons.append("deep thinking explicitly requested")

    council_hits = _has(text, _COUNCIL_MARKERS)
    if council_hits:
        modes.append(COUNCIL)
        reasons.append(f"council explicitly invoked ({council_hits[0]})")

    # --- mode detection ---------------------------------------------------
    action_hits = _has(text, _ACTION_VERBS)
    if action_hits:
        modes.append(ACTION)
        reasons.append(f"action verb: {', '.join(action_hits[:3])}")

    memory_hits = _has(text, _MEMORY_MARKERS)
    if memory_hits:
        modes.append(MEMORY)
        reasons.append(f"refers to earlier context: {memory_hits[0]}")

    research_hits = _has(text, _RESEARCH_MARKERS)
    if research_hits:
        modes.append(RESEARCH)
        reasons.append(f"needs external lookup: {research_hits[0]}")

    advice_hits = _has(text, _ADVICE_MARKERS)
    if advice_hits:
        modes.append(ADVICE)
        reasons.append(f"asking for judgement: {advice_hits[0]}")

    deep_hits = _has(text, _DEEP_MARKERS)
    design_hits = _has(text, _DESIGN_MARKERS)
    learning_hits = _has(text, _LEARNING_MARKERS)
    design_deep_hits = _has(text, _DESIGN_DEEP_MARKERS)
    creator_hits = _has(text, _CREATOR_MARKERS)
    mastery_hits = _has(text, _MASTERY_MARKERS)
    foodie_hits = _has(text, _FOODIE_MARKERS)
    website_hits = _has(text, _WEBSITE_MARKERS)
    if creator_hits:
        modes.append(CREATOR)
        reasons.append(f"creator request: {creator_hits[0]}")
    if learning_hits:
        modes.append(LEARNING)
    if mastery_hits:
        modes.append(MASTERY)
        reasons.append(f"mastery request: {mastery_hits[0]}")
    if foodie_hits:
        modes.append(FOODIE)
        reasons.append(f"food request: {foodie_hits[0]}")
    if website_hits:
        modes.append(WEBSITE_BUILDER)
        reasons.append(f"website builder request: {website_hits[0]}")
    followup_hits = _has(text, _FOLLOWUP_MARKERS)
    is_followup = bool(followup_hits) or bool(_PRONOUN_ONLY.match(raw))
    if is_followup and has_active_task:
        modes.append(MEMORY)
        reasons.append("follow-up on the active task, not new work")

    greeting = word_count <= 6 and any(text == g or text.startswith(g + " ") or text == g + "?"
                                       for g in _GREETINGS)
    if greeting:
        reasons.append("greeting or acknowledgement")

    # --- complexity score -------------------------------------------------
    clauses = _clause_count(text)
    signals.update({
        "clauses": clauses, "deep_markers": len(deep_hits),
        "action_verbs": len(action_hits), "advice_markers": len(advice_hits),
        "question_marks": raw.count("?"), "followup": is_followup,
        "design_markers": len(design_hits), "learning_markers": len(learning_hits),
        "creator_markers": len(creator_hits), "mastery_markers": len(mastery_hits), "foodie_markers": len(foodie_hits),
        "website_markers": len(website_hits),
    })

    complexity = 0.0
    if not greeting:
        complexity += min(word_count / 60.0, 0.30)          # length
        complexity += min(clauses * 0.08, 0.24)             # multi-step
        complexity += min(len(deep_hits) * 0.16, 0.32)      # genuine depth words
        complexity += min(len(advice_hits) * 0.10, 0.20)    # judgement asked for
        if len(action_hits) >= 2:
            complexity += 0.10                              # several actions
        if research_hits:
            complexity += 0.08
    if is_followup and has_active_task:
        complexity *= 0.5                                   # follow-ups stay cheap
    if greeting:
        complexity = 0.0
    complexity = round(min(complexity, 1.0), 3)
    signals["complexity_raw"] = complexity

    # --- path decision ----------------------------------------------------
    deep = False
    if explicit_deep or "deep thinking explicitly requested" in reasons:
        deep = True
    elif COUNCIL in modes:
        deep = True
        reasons.append("council work is always deep")
    elif complexity >= 0.45:
        deep = True
        reasons.append(f"complexity {complexity:.2f} >= 0.45")
    elif len(deep_hits) >= 2:
        deep = True
        reasons.append("multiple depth signals")
    elif deep_hits and clauses >= 2:
        deep = True
        reasons.append("depth signal in a multi-clause request")
    elif _has(text, _FAILURE_MARKERS):
        deep = True
        reasons.append("something is reported broken -- diagnosing needs the deep path")
    elif learning_hits and design_hits:
        deep = True
        reasons.append("design learning path needs a structured lesson")
    elif design_deep_hits:
        deep = True
        reasons.append("coherent design system or identity needs a structured process")
    elif creator_hits or mastery_hits or (foodie_hits and ("meal plan" in text or len(action_hits) >= 2)):
        deep = True
        reasons.append("multi-step creator, mastery, or meal-planning work needs a structured process")
    elif website_hits and (bool(action_hits) or len(website_hits) > 1):
        deep = True
        reasons.append("website build or modification needs a structured project path")

    # --- specialists ------------------------------------------------------
    # Never for a greeting or a simple action. "Ultra-smart" must not mean
    # waking thirteen agents to answer "what is Node.js".
    allow_specialists = deep and not greeting
    model_kind = "general"
    if deep:
        for kind, hints in _SPECIALIST_HINTS.items():
            if _has(text, hints):
                model_kind = kind
                if kind != "vision":
                    modes.append(SPECIALIST)
                    reasons.append(f"{kind} expertise is relevant")
                break
        else:
            model_kind = "reasoning"
        if design_hits and SPECIALIST not in modes:
            # ZEAL is an existing, registered specialist; this tag merely
            # lets the main brain decide whether its focused review is worth
            # waking. It does not create a duplicate creative agent.
            modes.append(SPECIALIST)
            reasons.append("creative/design expertise is relevant")
        elif CREATOR in modes and SPECIALIST not in modes:
            modes.append(SPECIALIST)
            reasons.append("creator project can use the existing creative specialist")
    elif ACTION in modes:
        model_kind = "general"

    # CHAT last, so it only appears when nothing else did -- a turn is never
    # both "ordinary conversation" and "needs a specialist".
    if not modes:
        modes.append(CHAT)
        if not reasons:
            reasons.append("ordinary conversation")

    return Route(
        path=DEEP if deep else FAST,
        modes=tuple(dict.fromkeys(modes)),
        reasons=tuple(reasons),
        complexity=complexity,
        model_kind=model_kind,
        max_tool_rounds=DEEP_ROUNDS if deep else FAST_ROUNDS,
        allow_specialists=allow_specialists,
        normalized=text,
        signals=signals,
    )


@lru_cache(maxsize=512)
def _cached_route(message: str, has_active_task: bool, recent_turns: int,
                  explicit_deep: bool) -> Route:
    """Bound repeated local routing without sharing mutable diagnostics."""
    return _route_uncached(message, has_active_task=has_active_task,
                           recent_turns=recent_turns, explicit_deep=explicit_deep)


def route(message: str, *, has_active_task: bool = False,
          recent_turns: int = 0, explicit_deep: bool = False) -> Route:
    """Decide how hard this turn should think, with a bounded exact-message cache.

    A cache hit still returns a fresh `Route` diagnostic map. Callers are
    therefore free to annotate their own copy without leaking state into a
    later conversation, while recurring wake/status phrases remain nearly
    free on the GUI/voice path.
    """
    result = _cached_route(str(message or ""), bool(has_active_task), int(recent_turns), bool(explicit_deep))
    return Route(path=result.path, modes=result.modes, reasons=result.reasons,
                 complexity=result.complexity, model_kind=result.model_kind,
                 max_tool_rounds=result.max_tool_rounds,
                 allow_specialists=result.allow_specialists,
                 normalized=result.normalized, signals=dict(result.signals))


def prompt_directive(decision: Route) -> str:
    """A SHORT per-turn instruction. Length here is latency, so it stays tight."""
    if decision.path == FAST:
        line = ("[Routing: FAST. Answer directly and briefly. Do not delegate, do not "
                "convene specialists, do not over-explain.")
        if ACTION in decision.modes:
            line += " This is an ACTION -- call the tool, then report in one line."
        if MEMORY in decision.modes:
            line += " This refers to something already in progress -- continue it, do not start a new one."
        return line + "]"
    line = ("[Routing: DEEP. This needs real thought: work out what is actually being "
            "asked, consider what could go wrong, and check your answer before sending.")
    if ADVICE in decision.modes:
        line += " Give a clear recommendation, not a list of options."
    if SPECIALIST in decision.modes:
        line += " One specialist may be worth delegating to; do not convene the whole council."
    if COUNCIL in decision.modes:
        line += " The council was explicitly requested."
    if CREATOR in decision.modes:
        line += " Keep one coherent creator project rather than unrelated ideas."
    if LEARNING in decision.modes or MASTERY in decision.modes:
        line += " Teach/practice in small evidence-based steps."
    if FOODIE in decision.modes:
        line += " Keep food guidance practical and safety-aware."
    if WEBSITE_BUILDER in decision.modes:
        line += " Reuse the managed website build path and verification evidence."
    return line + "]"


def explain(message: str, **kwargs) -> dict:
    """Diagnostics for the dashboard and tests."""
    return route(message, **kwargs).as_dict()
