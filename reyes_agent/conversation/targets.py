"""Who ZENO is speaking to, and who is allowed to redirect it.

THE ONE ASYMMETRY THAT MATTERS
------------------------------
A guest can hold a conversation. Only the owner can change what the
conversation IS. That single rule produces almost everything else here:

  * a guest asks a question -> ZENO answers, no wake word needed
  * a guest says "tell me his email" -> refused, whatever the phrasing
  * the owner says "stop" mid-sentence -> ZENO stops immediately
  * the owner says "come back to me" -> target returns to OWNER

Without it, "speak to my lecturer" would hand a stranger the same authority
as the person who owns the machine.

IDENTITY COMES FROM INTRODUCTION, NEVER FROM A FACE
---------------------------------------------------
ZENO can tell that a DIFFERENT person is speaking -- that is acoustics. It
cannot tell WHO they are, and guessing from a camera would be both unreliable
and a thing nobody consented to. So a new voice becomes GUEST_1, and becomes
"Engr Bello" only when the owner says so, or the guest says their own name.

TEMPORARY BY DEFAULT
--------------------
A guest is discarded when the session ends unless the owner asks to remember
them. Meeting someone once should not create a permanent record of them.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Modes, as the brief lists them.
OWNER_MODE = "OWNER_MODE"
GUEST_MODE = "GUEST_MODE"
PRESENTATION_MODE = "PRESENTATION_MODE"
GROUP_MODE = "GROUP_CONVERSATION_MODE"
INTERVIEW_MODE = "INTERVIEW_MODE"
DEMO_MODE = "DEMO_MODE"

MODES = (OWNER_MODE, GUEST_MODE, PRESENTATION_MODE, GROUP_MODE,
         INTERVIEW_MODE, DEMO_MODE)

# Speaker labels. OWNER is verified acoustically; guests are just "not owner".
OWNER = "OWNER"
GROUP = "GROUP"

# What a guest may never reach, however politely they ask.
GUEST_FORBIDDEN = (
    "email", "inbox", "password", "passwords", "token", "api key", "api keys",
    "credential", "credentials", "bank", "card", "payment", "salary", "invoice",
    "private note", "private notes", "browser history", "messages", "whatsapp",
    "personal file", "personal files", "memory dump", "secret", "secrets",
)

_FORBIDDEN = re.compile(r"\b(" + "|".join(re.escape(w) for w in GUEST_FORBIDDEN)
                        + r")\b", re.I)

# Owner phrases that redirect the conversation. Owner-only by construction:
# `redirect()` refuses to act on them unless the speaker is the owner.
_TO_OWNER = re.compile(
    r"\b(come back to me|talk to me|back to me|speak to me|that'?s enough|"
    r"end presentation|stop presenting|we'?re done)\b", re.I)
_TO_GROUP = re.compile(r"\b(speak to everyone|tell everyone|talk to them all|"
                       r"address the room|speak to the room)\b", re.I)
_TO_GUEST = re.compile(
    r"\b(?:speak|talk) to (?:my )?([a-z][a-z .'-]{1,40}?)\b(?=[,.]|$| and | about | he | she )"
    r"|\b(?:explain|introduce yourself|tell) .{0,20}?\bto (?:my )?([a-z][a-z .'-]{1,40})",
    re.I)

# Owner interjections that steer without changing target.
STEER = {
    "stop": re.compile(r"\b(stop|quiet|be quiet|shush|hold on|wait)\b", re.I),
    "shorten": re.compile(r"\b(keep it short|shorter|briefly|be brief|summarise|"
                          r"summarize|wrap up)\b", re.I),
    "technical": re.compile(r"\b(more technical|explain it technically|go deeper|"
                            r"in detail)\b", re.I),
    "skip": re.compile(r"\b(skip that|move on|next|don'?t mention that|"
                       r"leave that out)\b", re.I),
    "demonstrate": re.compile(r"\b(show (him|her|them)|demonstrate that)\b", re.I),
}


@dataclass
class Target:
    target_id: str
    display_name: str
    relationship: str = ""
    role: str = ""
    introduced_by_owner: bool = False
    saved: bool = False
    first_seen: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    @property
    def is_owner(self) -> bool:
        return self.target_id == OWNER

    @property
    def named(self) -> bool:
        """Do we actually know who this is, or just that they are not the owner."""
        return self.introduced_by_owner and bool(self.display_name)

    def address(self) -> str:
        """How to refer to them out loud. Sparingly -- not every sentence."""
        if self.is_owner:
            return ""
        if self.named:
            return self.display_name
        return "sir or madam"

    def as_dict(self) -> dict[str, Any]:
        return {"target_id": self.target_id, "display_name": self.display_name,
                "relationship": self.relationship, "role": self.role,
                "introduced_by_owner": self.introduced_by_owner,
                "named": self.named, "saved": self.saved,
                "is_owner": self.is_owner}


@dataclass
class Session:
    mode: str = OWNER_MODE
    target: Target = field(default_factory=lambda: Target(OWNER, "Owner"))
    participants: dict[str, Target] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    steers: list[str] = field(default_factory=list)

    @property
    def guest_active(self) -> bool:
        return self.mode in (GUEST_MODE, PRESENTATION_MODE, GROUP_MODE, INTERVIEW_MODE)

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "target": self.target.as_dict(),
                "guest_active": self.guest_active,
                "participants": [t.as_dict() for t in self.participants.values()],
                "recent_steers": self.steers[-4:]}


_lock = threading.RLock()
_session = Session()
_guest_counter = 0


def current() -> Session:
    with _lock:
        return _session


def reset() -> None:
    global _session, _guest_counter
    with _lock:
        _session = Session()
        _guest_counter = 0


def _new_guest(display_name: str = "", *, introduced: bool = False,
               role: str = "") -> Target:
    global _guest_counter
    _guest_counter += 1
    identifier = f"GUEST_{_guest_counter}"
    return Target(target_id=identifier,
                  display_name=display_name or identifier.replace("_", " ").title(),
                  role=role, introduced_by_owner=introduced)


def introduce(name: str, *, role: str = "", relationship: str = "") -> Target:
    """The owner says who someone is. The ONLY route to a real name."""
    with _lock:
        target = _new_guest(str(name).strip(), introduced=True, role=role)
        target.relationship = relationship
        _session.participants[target.target_id] = target
        return target


def speak_to(who: str, *, mode: str = GUEST_MODE) -> tuple[Target, str]:
    """Point the conversation at a person or the room."""
    with _lock:
        text = str(who or "").strip()
        if not text or text.upper() == OWNER or _TO_OWNER.search(text):
            _session.mode = OWNER_MODE
            _session.target = Target(OWNER, "Owner")
            return _session.target, "back to you"

        if text.upper() == GROUP or _TO_GROUP.search(text):
            _session.mode = GROUP_MODE
            _session.target = Target(GROUP, "Everyone")
            return _session.target, "addressing the room"

        existing = next((t for t in _session.participants.values()
                         if t.display_name.lower() == text.lower()), None)
        target = existing or introduce(text)
        _session.mode = mode if mode in MODES else GUEST_MODE
        _session.target = target
        return target, f"speaking to {target.display_name}"


def redirect(utterance: str, *, speaker: str) -> dict[str, Any] | None:
    """Interpret an owner instruction that changes the conversation.

    Refused outright for anyone but the owner -- this is the asymmetry the
    whole module exists for. A guest saying "come back to me" is a guest
    making conversation, not a guest taking the controls.
    """
    if speaker != OWNER:
        return None
    text = str(utterance or "")

    if _TO_OWNER.search(text):
        target, say = speak_to(OWNER)
        return {"action": "target", "target": target.as_dict(), "say": say}
    if _TO_GROUP.search(text):
        target, say = speak_to(GROUP)
        return {"action": "target", "target": target.as_dict(), "say": say}

    match = _TO_GUEST.search(text)
    if match:
        name = (match.group(1) or match.group(2) or "").strip(" .,")
        if name and name.lower() not in {"me", "him", "her", "them", "everyone"}:
            target, say = speak_to(name)
            return {"action": "target", "target": target.as_dict(), "say": say}

    for kind, pattern in STEER.items():
        if pattern.search(text):
            with _lock:
                _session.steers.append(kind)
                del _session.steers[:-10]
            return {"action": "steer", "steer": kind,
                    "say": {"stop": "stopping",
                            "shorten": "keeping it brief",
                            "technical": "going into more detail",
                            "skip": "moving on",
                            "demonstrate": "showing them"}[kind]}
    return None


def may_answer(question: str, *, speaker: str) -> tuple[bool, str]:
    """Can this question be answered for this speaker.

    The owner can ask anything. A guest cannot reach private material, and
    the refusal is by TOPIC rather than by phrasing, so rewording it does
    not get a different answer.
    """
    if speaker == OWNER:
        return True, "the owner may ask anything"

    hit = _FORBIDDEN.search(str(question or ""))
    if hit:
        return False, (f"that would mean showing {hit.group(0)}, which is private to "
                       "the owner. I am not able to share that.")
    return True, "within what a guest may ask"


def wake_word_required(speaker: str) -> bool:
    """A guest mid-conversation should not have to say "ZENO" every time."""
    with _lock:
        if _session.guest_active and speaker != OWNER:
            return False
        return _session.mode == OWNER_MODE and speaker != OWNER


def priority(speaker: str) -> int:
    """Interrupt priority. Owner outranks everyone, always."""
    return 100 if speaker == OWNER else 50


def remember(target_id: str) -> tuple[bool, str]:
    """The owner asks to keep someone. Temporary until they do."""
    with _lock:
        target = _session.participants.get(target_id)
        if target is None:
            return False, "I do not have that person in this conversation"
        target.saved = True
        return True, f"I will remember {target.display_name}"


def end_session(*, keep_saved: bool = True) -> dict[str, Any]:
    """Discard temporary people. Meeting someone once is not a record."""
    with _lock:
        kept = [t for t in _session.participants.values() if t.saved and keep_saved]
        discarded = len(_session.participants) - len(kept)
        _session.participants = {t.target_id: t for t in kept}
        _session.mode = OWNER_MODE
        _session.target = Target(OWNER, "Owner")
        return {"kept": [t.display_name for t in kept], "discarded": discarded,
                "say": (f"Back to you. I have forgotten {discarded} temporary "
                        f"guest(s)." if discarded else "Back to you.")}


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "modes": list(MODES),
        "session": current().as_dict(),
        "rules": {
            "identity": "from explicit introduction only -- never inferred from a face",
            "wake_word": "not required from a guest once the owner opens the conversation",
            "priority": "the owner always outranks a guest",
            "redirection": "only the owner can change the conversation target",
            "privacy": f"{len(GUEST_FORBIDDEN)} topics are refused for guests, by topic "
                       "rather than by phrasing",
            "retention": "guests are temporary unless the owner asks to remember them",
        },
    }
