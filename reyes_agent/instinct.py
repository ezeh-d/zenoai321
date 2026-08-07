"""ZENO Instinct -- "is there something here worth pointing out?"

THE PROBLEM THIS SOLVES
-----------------------
An assistant that volunteers an opinion on everything becomes noise you
learn to skip. An assistant that never volunteers one is a search box. The
useful behaviour sits between those, and "between" is not a vibe -- it is a
decision that has to be made explicitly, every turn, with a bias toward
silence.

So Instinct scores the moment on five axes the owner named:

    RELEVANCE   -- is this actually about something I can speak to?
    CONFIDENCE  -- do I have grounds, or would I be guessing?
    IMPACT      -- does it matter if he gets this wrong?
    URGENCY     -- does it matter NOW, or can it wait?
    INTERRUPTION COST -- what does saying it cost him right now?

...and combines them into one `weight` (0..1) plus a level. Low weight
means say nothing at all. That is the common case and it is the point.

WHAT IT DOES NOT DO
-------------------
It never generates speech on its own, never queues audio, and never runs on
a timer. It is a pure function called during a turn that is already
happening (see agent.py), so it cannot make ZENO chatty when idle -- the
existing `proactive.py` remains the only thing that speaks unprompted, on
its own bounded 5-minute schedule.

The ADVICE ENGINE below is the same idea for explicit decisions: it supplies
the checklist ZENO reasons through (options, risk, cost, reversibility,
uncertainty, recommendation) as a compact instruction, NOT as headings to
print. The owner asked for advice that sounds like a person, not a form.
"""

from __future__ import annotations

from dataclasses import dataclass

from reyes_agent import cognition, wisdom

# --- levels --------------------------------------------------------------
QUIET = "QUIET"          # say nothing extra
MENTION = "MENTION"      # weave one line into the normal answer
ADVISE = "ADVISE"        # give a clear recommendation
WARN = "WARN"            # say it first, plainly

_LEVEL_AT = ((0.80, WARN), (0.60, ADVISE), (0.40, MENTION))


@dataclass(frozen=True)
class Instinct:
    level: str
    weight: float
    relevance: float
    confidence: float
    impact: float
    urgency: float
    interruption_cost: float
    triggers: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "level": self.level, "weight": self.weight, "relevance": self.relevance,
            "confidence": self.confidence, "impact": self.impact, "urgency": self.urgency,
            "interruption_cost": self.interruption_cost, "triggers": list(self.triggers),
        }


# Situations genuinely worth a word. Each carries its own impact weight --
# "you are about to lose work" is not the same as "there may be a neater way".
_TRIGGERS: dict[str, tuple[float, tuple[str, ...]]] = {
    "possible loss of work": (0.95, (
        "delete everything", "start over", "from scratch", "wipe", "reset everything",
        "rewrite the entire", "rewrite everything", "rebuild everything", "drop the database",
        "format", "uninstall everything",
    )),
    "security risk": (0.95, (
        "hardcode the key", "commit the key", "api key in", "password in the code",
        "disable auth", "turn off authentication", "make it public", "allow all origins",
        "sudo", "run as admin", "disable the firewall",
    )),
    "irreversible step": (0.85, (
        "force push", "delete the branch", "drop table", "overwrite the original",
        "permanently delete", "cancel the subscription", "close the account",
    )),
    "unnecessary spending": (0.75, (
        "buy", "purchase", "subscribe", "upgrade to pro", "paid plan", "pay for",
        "hire someone", "expensive",
    )),
    "likely failure": (0.70, (
        "should work", "probably fine", "it'll be fine", "no need to test",
        "skip the tests", "ship it now", "deploy straight",
    )),
    "unnecessary complexity": (0.60, (
        # Both singular and plural: word-boundary matching means
        # "microservice" does not match "microservices".
        "microservice", "microservices", "kubernetes", "rewrite in",
        "add a framework", "another framework", "another library",
        "custom implementation", "build my own", "roll my own",
    )),
    "missing step": (0.60, (
        "no backup", "without testing", "haven't tested", "not tested",
        "skip verification", "no rollback", "without a backup",
    )),
    "waiting too long": (0.55, (
        "when it's perfect", "when its perfect", "until it's perfect",
        "until its perfect", "everything is perfect", "perfect before",
        "before launching", "before i launch", "not ready yet",
        "still polishing", "one more feature", "keep polishing",
    )),
}


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def evaluate(message: str, decision: cognition.Route, *,
             has_active_task: bool = False) -> Instinct:
    """Score the moment. Pure and fast; no model call, no side effects."""
    text = cognition.normalize(message)

    fired: list[str] = []
    impact = 0.0
    for name, (weight, phrases) in _TRIGGERS.items():
        if cognition._has(text, phrases):
            fired.append(name)
            impact = max(impact, weight)

    # RELEVANCE -- is this a moment where an opinion is even wanted?
    relevance = 0.0
    if cognition.ADVICE in decision.modes:
        relevance = 0.85                    # he asked what to do
    elif fired:
        relevance = 0.70                    # he did not ask, but this matters
    elif decision.path == cognition.DEEP:
        relevance = 0.45
    elif cognition.ACTION in decision.modes:
        relevance = 0.25
    else:
        relevance = 0.10                    # chit-chat

    # CONFIDENCE -- grounds to speak, or guessing? A named trigger phrase is
    # concrete evidence; a vague feeling about a short message is not.
    confidence = 0.80 if fired else (0.55 if cognition.ADVICE in decision.modes else 0.30)
    if len(text.split()) < 4 and not fired:
        confidence = min(confidence, 0.20)  # too little was said to judge

    # URGENCY -- about to happen, or hypothetical?
    imminent = cognition._has(text, (
        "i'm going to", "im going to", "i am going to", "about to", "right now",
        "let's just", "lets just", "i'll just", "ill just", "today", "now",
    ))
    urgency = 0.85 if (fired and imminent) else (0.55 if fired else 0.25)

    # INTERRUPTION COST -- what does speaking up cost him here? Mid-task and
    # mid-casual-chat are both bad moments for unsolicited commentary.
    interruption_cost = 0.20
    if has_active_task and not fired:
        interruption_cost = 0.65
    if cognition.CHAT in decision.modes and not fired:
        interruption_cost = 0.75
    if cognition.ADVICE in decision.modes:
        interruption_cost = 0.05            # he asked; speaking costs nothing

    weight = _clamp(
        (relevance * 0.30) + (confidence * 0.20) + (impact * 0.30) + (urgency * 0.20)
        - (interruption_cost * 0.25)
    )

    level = QUIET
    for threshold, name in _LEVEL_AT:
        if weight >= threshold:
            level = name
            break

    return Instinct(
        level=level, weight=weight, relevance=_clamp(relevance),
        confidence=_clamp(confidence), impact=_clamp(impact), urgency=_clamp(urgency),
        interruption_cost=_clamp(interruption_cost), triggers=tuple(fired),
    )


# --- the advice engine ---------------------------------------------------
# The owner's checklist, compressed into an instruction. It is deliberately
# phrased as "work through this, then talk normally" -- printing the headings
# would turn every recommendation into a form to fill in.
_ADVICE_FRAME = (
    "Work this through before answering: what is actually being decided, the real "
    "options, what each costs, what it risks, whether it can be undone, and what is "
    "still uncertain. Then say it as one person talking to another -- your "
    "recommendation and the single next step. Do NOT print those as headings."
)

_NOT_A_YES_MAN = (
    "If you think this is the wrong call, say so plainly and say why, then give the "
    "better option. Agreeing to be agreeable is useless to him. Do not argue past "
    "one clear disagreement -- state it once, then respect his decision."
)

_LEVEL_TEXT = {
    MENTION: "There may be something worth a brief mention here ({triggers}). One line inside your normal answer, only if it genuinely helps.",
    ADVISE: "Something here is worth real advice ({triggers}). Give a clear recommendation.",
    WARN: "Say this first, plainly, before anything else ({triggers}). It matters more than the rest of the reply.",
}


def turn_directive(decision: cognition.Route, message: str,
                   *, has_active_task: bool = False) -> str:
    """The compact per-turn instruction, or "" when there is nothing to add.

    Called once per turn from agent.py. Returning "" is the normal outcome
    and costs nothing -- silence is the default, not a fallback.
    """
    reading = evaluate(message, decision, has_active_task=has_active_task)
    parts: list[str] = []

    if reading.level != QUIET:
        triggers = ", ".join(reading.triggers) if reading.triggers else "judgement asked for"
        parts.append(_LEVEL_TEXT[reading.level].format(triggers=triggers))

    if cognition.ADVICE in decision.modes or reading.level in {ADVISE, WARN}:
        parts.append(_ADVICE_FRAME)
        parts.append(_NOT_A_YES_MAN)

    tone, _reason = wisdom.evaluate(message, decision, weight=reading.weight)
    style = wisdom.directive(tone)
    if style:
        parts.append(style)

    if not parts:
        return ""
    return "[Instinct] " + " ".join(parts)


def explain(message: str, *, has_active_task: bool = False) -> dict:
    """Diagnostics for tests and the dashboard."""
    decision = cognition.route(message, has_active_task=has_active_task)
    reading = evaluate(message, decision, has_active_task=has_active_task)
    tone, reason = wisdom.evaluate(message, decision, weight=reading.weight)
    return {
        "route": decision.as_dict(),
        "instinct": reading.as_dict(),
        "wisdom": {"tone": tone, "reason": reason, "mode": wisdom.mode()},
    }
