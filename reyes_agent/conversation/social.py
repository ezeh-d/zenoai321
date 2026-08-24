"""Social context: who is addressed, what tone, and whether to speak at all.

All three engines are deterministic and evidence-based -- they read the words
that were actually said and the EXPLICIT relationship/setting, never a guess
about someone's status, mood, or identity (pack6 #23, #34, #291).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# --- registers (pack6 #22) --------------------------------------------------
CASUAL = "CASUAL"
FRIENDLY = "FRIENDLY"
NEUTRAL = "NEUTRAL"
PROFESSIONAL = "PROFESSIONAL"
FORMAL = "FORMAL"
ACADEMIC = "ACADEMIC"
EXECUTIVE = "EXECUTIVE"
TEACHING = "TEACHING"
SUPPORTIVE = "SUPPORTIVE"

# Explicit relationship -> default register. Only ever applied to a relationship
# the owner/speaker STATED; never inferred from a voice.
_RELATIONSHIP_REGISTER = {
    "friend": FRIENDLY, "close friend": FRIENDLY, "classmate": FRIENDLY,
    "lecturer": ACADEMIC, "teacher": ACADEMIC, "professor": ACADEMIC,
    "supervisor": PROFESSIONAL, "manager": EXECUTIVE, "ceo": EXECUTIVE,
    "colleague": PROFESSIONAL, "customer": PROFESSIONAL, "client": PROFESSIONAL,
    "student": TEACHING, "family": FRIENDLY, "official": FORMAL,
    "unknown": NEUTRAL, "": NEUTRAL,
}

# Setting can override the relationship default.
_SETTING_REGISTER = {
    "meeting": PROFESSIONAL, "class": ACADEMIC, "presentation": PROFESSIONAL,
    "formal": FORMAL, "friendly": FRIENDLY, "casual": CASUAL,
}


class SocialRegisterEngine:
    """Pick a tone from EXPLICIT relationship + setting (pack6 #23-27)."""

    def select(self, *, relationship: str = "", setting: str = "",
               requested: str = "") -> str:
        req = str(requested or "").strip().upper()
        if req in ALL_REGISTERS:
            return req                       # the owner asked for a specific tone
        setting_key = str(setting or "").strip().casefold()
        if setting_key in _SETTING_REGISTER:
            return _SETTING_REGISTER[setting_key]
        rel = str(relationship or "").strip().casefold()
        return _RELATIONSHIP_REGISTER.get(rel, NEUTRAL)


ALL_REGISTERS = frozenset({
    CASUAL, FRIENDLY, NEUTRAL, PROFESSIONAL, FORMAL, ACADEMIC, EXECUTIVE,
    TEACHING, SUPPORTIVE})


# --- addressee (pack6 #29, #217) --------------------------------------------
ZENO = "zeno"
OWNER = "owner"
ROOM = "room"
UNKNOWN_ADDRESSEE = "unknown"

_QUESTION = re.compile(r"[?]|^\s*(what|why|how|when|where|who|which|can|could|"
                       r"would|should|is|are|do|does|did|will|explain|tell|show|"
                       r"give|help)\b", re.IGNORECASE)
_NAME_ADDRESS = re.compile(r"^\s*([A-Z][\w.\-']{1,30}(?:\s+[A-Z][\w.\-']{1,30})?)\s*[,:]")


@dataclass
class Addressee:
    target: str          # "zeno" | "agent:<name>" | "human:<name>" | "room" | "unknown"
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "confidence": round(self.confidence, 3),
                "reason": self.reason}


class AddresseeResolver:
    """Decide who a spoken line is aimed at, from explicit cues only."""

    def resolve(self, text: str, *, agents: tuple[str, ...] = (),
                humans: tuple[str, ...] = (), zeno_names: tuple[str, ...] = ("zeno",),
                mode: str = "normal") -> Addressee:
        raw = str(text or "").strip()
        low = raw.casefold()
        agents_l = {a.casefold(): a for a in agents}
        humans_l = {h.casefold(): h for h in humans}
        zeno_l = {z.casefold() for z in zeno_names} or {"zeno"}

        # 1) Leading "Name, ..." address is the strongest explicit signal.
        lead = _NAME_ADDRESS.match(raw)
        if lead:
            name = lead.group(1).strip().casefold()
            if name in zeno_l:
                return Addressee(ZENO, 0.97, "addressed ZENO by name")
            if name in agents_l:
                return Addressee(f"agent:{agents_l[name]}", 0.95, "addressed a sub-agent by name")
            if name in humans_l:
                return Addressee(f"human:{humans_l[name]}", 0.9, "addressed a person by name")

        # 2) ZENO's name anywhere -> ZENO.
        if any(re.search(rf"\b{re.escape(z)}\b", low) for z in zeno_l):
            return Addressee(ZENO, 0.85, "ZENO named in the utterance")

        # 3) A known agent/human named anywhere.
        for name_l, name in agents_l.items():
            if re.search(rf"\b{re.escape(name_l)}\b", low):
                return Addressee(f"agent:{name}", 0.8, "sub-agent named in the utterance")
        for name_l, name in humans_l.items():
            if re.search(rf"\b{re.escape(name_l)}\b", low):
                return Addressee(f"human:{name}", 0.75, "person named in the utterance")

        # 4) No explicit target. In a group/meeting/class ZENO must not assume it
        #    is being addressed; one-to-one/normal, a direct question is for ZENO.
        if mode in {"meeting", "class", "group"}:
            return Addressee(ROOM if _QUESTION.search(raw) else UNKNOWN_ADDRESSEE,
                             0.4, f"no explicit addressee in {mode} mode")
        if _QUESTION.search(raw):
            return Addressee(ZENO, 0.6, "direct question in one-to-one context")
        return Addressee(UNKNOWN_ADDRESSEE, 0.3, "no explicit addressee")


# --- stay-quiet policy (pack6 #31, #85, #146) -------------------------------
@dataclass
class SpeakDecision:
    speak: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"speak": self.speak, "reason": self.reason}


class StayQuietPolicy:
    """Silence is a valid, deliberate response. In meeting/class/group modes ZENO
    stays quiet unless it is clearly wanted."""

    def decide(self, addressee: Addressee, *, mode: str = "normal",
               proactive: bool = False, critical: bool = False) -> SpeakDecision:
        target = addressee.target if addressee else UNKNOWN_ADDRESSEE
        # Never answer for someone else.
        if target.startswith("agent:") or target.startswith("human:"):
            return SpeakDecision(False, "addressed to someone else")
        addressed_to_zeno = target in (ZENO, OWNER)
        if mode in {"meeting", "class", "group"}:
            if addressed_to_zeno:
                return SpeakDecision(True, "explicitly addressed in a group setting")
            if critical:
                return SpeakDecision(True, "critical clarification")
            if proactive and target == ROOM:
                return SpeakDecision(True, "proactive mode permits a brief interjection")
            return SpeakDecision(False, f"staying quiet in {mode} mode")
        # Normal / one-to-one.
        if addressed_to_zeno:
            return SpeakDecision(True, "addressed to ZENO")
        if target == ROOM:
            return SpeakDecision(True, "open question, one-to-one context")
        return SpeakDecision(bool(proactive), "no explicit addressee")
