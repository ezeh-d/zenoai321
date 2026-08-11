"""Real request, real execution. The rule that overrides every other default.

    OWNER ASKS FOR THE REAL THING  -> DO THE REAL THING
    OWNER ASKS FOR A DEMO          -> DEMO
    OWNER SAYS NOTHING ABOUT IT    -> REAL

WHY THIS IS A MODULE AND NOT A CONVENTION
-----------------------------------------
The dangerous failure is not refusing to act. It is acting *plausibly*:
"Application submitted successfully" when nothing was submitted, a rehearsed
inbox instead of the real one, a green tick for an email that never left.
That failure is worse than an error because it is indistinguishable from
success until it matters -- a job application that was never sent looks
exactly like one that was, right up to the day nobody calls.

So the fallback is removed rather than discouraged. `resolve()` decides REAL
or DEMO from the owner's own words, and `blocked()` produces the honest
outcome for a real request that cannot complete. There is no code path from
"the real thing failed" to "show something that looks like it worked".

WHEN A GUEST IS WATCHING
------------------------
Demo mode never activates because someone is in the room. Presentation Mode
is a real conversational mode: real listening, real answers, real tools. A
guest is a reason to be careful, not a reason to pretend.

SCOPE
-----
Demo is per-task and expires. `demo_for()` is a context manager, so ZENO
cannot get stuck in demo mode after one "just show him" -- the next request
is real again unless it says otherwise.
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

REAL = "REAL"
DEMO = "DEMO"

# Honest outcomes for a real request that could not complete. Every one of
# these is a legitimate answer; "success" is not.
AUTH_REQUIRED = "AUTH_REQUIRED"
USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
FAILED = "FAILED"
OFFLINE = "OFFLINE"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

BLOCKED_STATES = (AUTH_REQUIRED, USER_ACTION_REQUIRED, PERMISSION_REQUIRED,
                  DEPENDENCY_MISSING, FAILED, OFFLINE, NOT_IMPLEMENTED)

# The ONLY phrasings that select demo. Deliberately explicit -- an assistant
# that infers "they probably meant a demo" has re-invented the silent
# fallback this module exists to delete.
_DEMO_PHRASES = (
    r"\bdemo\b", r"\bdemonstrat(e|ion|ing)\b", r"\bsimulate\b", r"\bsimulation\b",
    r"\bpretend\b", r"\bmock\b", r"\bsample data\b", r"\bdry[- ]run\b",
    r"\bwithout (actually |really )?(sending|submitting|posting|applying|buying)\b",
    r"\bdon'?t (actually |really )?(send|submit|post|apply|buy|do) it\b",
    r"\bshow (him|her|them|me) (how|what) .{0,40}\bwould\b",
    r"\bwhat .{0,20}would look like\b",
)

_DEMO = tuple(re.compile(p, re.I) for p in _DEMO_PHRASES)

# Phrases that make it unmistakably real, and win over a stray "show".
_REAL_PHRASES = (
    r"\b(actually|really|for real|properly)\b",
    r"\bsubmit (it|the|this)\b", r"\bsend (it|the|this)\b",
    r"\bapply for\b", r"\bgo ahead\b", r"\bdo it now\b",
)

_REAL = tuple(re.compile(p, re.I) for p in _REAL_PHRASES)

_lock = threading.RLock()
_scoped: list[str] = []


def globally_enabled() -> bool:
    """`ZENO_DEMO_MODE`. Default false, and never set by ZENO itself."""
    return os.environ.get("ZENO_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Mode:
    mode: str
    reason: str
    matched: str = ""

    @property
    def is_demo(self) -> bool:
        return self.mode == DEMO

    @property
    def is_real(self) -> bool:
        return self.mode == REAL

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "reason": self.reason, "matched": self.matched}


def resolve(request: str, *, guest_present: bool = False) -> Mode:
    """REAL or DEMO for this request. `guest_present` is deliberately ignored."""
    text = str(request or "")

    with _lock:
        if _scoped:
            return Mode(DEMO, f"a demo was explicitly scoped for: {_scoped[-1]}")

    if globally_enabled():
        return Mode(DEMO, "ZENO_DEMO_MODE is set in the environment")

    # An explicit real verb beats a stray "show" in the same sentence.
    for pattern in _REAL:
        hit = pattern.search(text)
        if hit:
            return Mode(REAL, "the request says to actually do it", hit.group(0))

    for pattern in _DEMO:
        hit = pattern.search(text)
        if hit:
            return Mode(DEMO, "the request explicitly asked for a demonstration",
                        hit.group(0))

    # The default, and the whole point. A guest in the room changes nothing.
    return Mode(REAL, "nothing asked for a demonstration, so this is the real thing")


@contextmanager
def demo_for(task: str):
    """Scope demo mode to one task. It expires; ZENO cannot get stuck in it."""
    with _lock:
        _scoped.append(str(task or "task"))
    try:
        yield Mode(DEMO, f"scoped demo for: {task}")
    finally:
        with _lock:
            if _scoped:
                _scoped.pop()


@dataclass(frozen=True)
class Blocked:
    state: str
    what: str
    why: str
    owner_action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "completed": False, "what": self.what,
                "why": self.why, "owner_action": self.owner_action,
                "say": self.say()}

    def say(self) -> str:
        base = f"I could not {self.what}: {self.why}"
        return f"{base} {self.owner_action}".strip() if self.owner_action else base


def blocked(state: str, what: str, why: str, *, owner_action: str = "") -> Blocked:
    """The honest outcome for a real request that cannot complete.

    This is the ONLY thing a failed real action may return. There is
    deliberately no `simulate_instead()` next to it.
    """
    if state not in BLOCKED_STATES:
        state = FAILED
    return Blocked(state=state, what=what, why=why, owner_action=owner_action)


def label(result: Any, mode: Mode) -> dict[str, Any]:
    """Mark an outcome so a demo can never be mistaken for a real one."""
    body = result if isinstance(result, dict) else {"result": result}
    if mode.is_demo:
        return {**body, "mode": DEMO, "real": False,
                "notice": "This was a DEMONSTRATION. Nothing was actually sent, "
                          "submitted or changed."}
    return {**body, "mode": REAL, "real": True}


def status() -> dict[str, Any]:
    with _lock:
        scoped = list(_scoped)
    return {
        "state": "ONLINE",
        "default": REAL,
        "global_demo_flag": globally_enabled(),
        "scoped_demos_open": scoped,
        "blocked_states": list(BLOCKED_STATES),
        "rule": ("A real request never silently becomes a demo. If the real thing "
                 "cannot happen, ZENO says which of the blocked states applies and "
                 "why -- it never reports success for work that did not occur."),
        "guest_note": ("A guest in the room does not enable demo mode. Presentation "
                       "Mode is a real conversational mode."),
    }
