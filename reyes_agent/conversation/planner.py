"""ConversationResponsePlanner (pack6 #144-146) -- the capstone.

Composes the social engines into ONE decision for a spoken turn: should ZENO
speak, who to, in what register, at what detail, and what kind of response. It
decides nothing it cannot justify from the words and the explicit context, and
STAY_SILENT is a first-class outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from reyes_agent.conversation.explanation import ExplanationAdapter, UNKNOWN as LEVEL_UNKNOWN
from reyes_agent.conversation.social import (
    AddresseeResolver, SocialRegisterEngine, StayQuietPolicy, ZENO, OWNER, ROOM)

# Response types (pack6 #145).
ANSWER = "ANSWER"
CLARIFY = "CLARIFY"
ASK_NAME = "ASK_NAME"
EXPLAIN = "EXPLAIN"
SUMMARIZE = "SUMMARIZE"
ACKNOWLEDGE = "ACKNOWLEDGE"
CORRECT = "CORRECT"
DEFER = "DEFER"
STAY_SILENT = "STAY_SILENT"

_EXPLAIN = re.compile(r"\b(explain|how does|how do|what is|what are|walk me|"
                      r"break (?:it|this) down|teach|describe)\b", re.IGNORECASE)
_SUMMARIZE = re.compile(r"\b(summar|recap|what did i miss|catch me up|tl;?dr)\b",
                        re.IGNORECASE)
_CORRECTION = re.compile(r"\b(no,? i meant|actually,? i|that'?s not|not that)\b",
                         re.IGNORECASE)


@dataclass
class ConversationPlan:
    should_speak: bool
    addressee: str
    register: str
    detail_level: str
    response_type: str
    reason: str
    explanation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"should_speak": self.should_speak, "addressee": self.addressee,
                "register": self.register, "detail_level": self.detail_level,
                "response_type": self.response_type, "reason": self.reason,
                "explanation": self.explanation}


class ConversationResponsePlanner:
    def __init__(self) -> None:
        self._addressee = AddresseeResolver()
        self._register = SocialRegisterEngine()
        self._quiet = StayQuietPolicy()
        self._explain = ExplanationAdapter()

    def plan(self, text: str, *, mode: str = "normal", relationship: str = "",
             setting: str = "", audience_level: str = LEVEL_UNKNOWN,
             agents: tuple[str, ...] = (), humans: tuple[str, ...] = (),
             zeno_names: tuple[str, ...] = ("zeno",), detail: str = "",
             requested_register: str = "", proactive: bool = False,
             critical: bool = False, ambiguous_reference: bool = False) -> ConversationPlan:
        try:
            addr = self._addressee.resolve(
                text, agents=agents, humans=humans, zeno_names=zeno_names, mode=mode)
            speak = self._quiet.decide(addr, mode=mode, proactive=proactive, critical=critical)
            register = self._register.select(
                relationship=relationship, setting=setting or mode, requested=requested_register)
            strategy = self._explain.strategy(
                audience_level, detail=detail, purpose=relationship or setting)

            if not speak.speak:
                rtype = STAY_SILENT
            elif ambiguous_reference:
                rtype = CLARIFY               # two people fit "tell him" (pack6 #55)
            else:
                rtype = _response_type(text)

            return ConversationPlan(
                should_speak=speak.speak,
                addressee=addr.target,
                register=register,
                detail_level=strategy.detail,
                response_type=rtype,
                reason=(speak.reason if not speak.speak else addr.reason),
                explanation=strategy.as_dict())
        except Exception:  # noqa: BLE001 -- planning must never break a turn
            return ConversationPlan(True, ZENO, "NEUTRAL", "normal", ANSWER,
                                    "fallback plan", {})


def _response_type(text: str) -> str:
    raw = str(text or "")
    if _CORRECTION.search(raw):
        return CORRECT
    if _SUMMARIZE.search(raw):
        return SUMMARIZE
    if _EXPLAIN.search(raw):
        return EXPLAIN
    if raw.strip().endswith("?") or re.match(r"^\s*(who|what|why|how|when|where|"
                                             r"which|can|could|would|should|is|are|do|does|did)\b",
                                             raw, re.IGNORECASE):
        return ANSWER
    return ACKNOWLEDGE


_instance: ConversationResponsePlanner | None = None


def get_planner() -> ConversationResponsePlanner:
    global _instance
    if _instance is None:
        _instance = ConversationResponsePlanner()
    return _instance
