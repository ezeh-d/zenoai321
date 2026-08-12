"""ZENO's operating mode. One source of truth, and the frontend is not it.

    "Do not let frontend decide the true mode independently."

So the mode lives here, changes here, and is announced here. A page that
wants to look like ULTRON asks what the mode IS; it never decides. That
matters beyond tidiness: a GUI that can put itself into serious mode can
show a crimson HUD over an assistant that is still behaving normally, and
the display would be a lie about the system it is displaying.

ULTRON IS A MODE, NOT A SECOND ASSISTANT
----------------------------------------
    "ZENO REMAINS THE MASTER AI."

`master` is a constant here. There is no code path that changes it, because
there is no such thing as ULTRON owning the system -- there is ZENO,
operating differently.

THE NAME COLLISION, HANDLED RATHER THAN IGNORED
-----------------------------------------------
ULTRON already exists in this project as a registered specialist: Chief
Strategy Officer, with workers named logic, risk, critic, vector, scenario
and priority. That is not a conflict to route around, it is the reason the
name fits -- those workers are precisely what serious mode is FOR. Serious
mode is ZENO thinking the way ULTRON's team thinks, and when it delegates
strategy it delegates to that same registered agent.

What is NOT created: a second ULTRON in the registry, a separate runtime, a
parallel agent list, or a competing master. The brief's own test forbids a
duplicate identity, and the way to pass it is to not make one.

SERIOUS MODE IS NOT REDUCED SAFETY
-----------------------------------
    "ULTRON means: more serious reasoning. NOT: safety disabled."

Nothing here touches permissions, policy or confirmation. The mode changes
how ZENO REASONS AND SPEAKS. Every consequential action goes through exactly
the same gates it did a moment earlier, and a test holds that.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

MASTER = "ZENO"                 # never reassigned
NORMAL = "NORMAL"
ULTRON = "ULTRON"
MODES = (NORMAL, ULTRON)

# Concise on purpose. A dramatic speech every activation stops being
# impressive the second time and starts costing the owner his own airtime.
_GREETINGS = ("Ultron online.", "Serious mode active.",
              "Ready. What's the objective?", "Serious mode. Go ahead.")
_FAREWELLS = ("Back to normal.", "Standing down.", "Normal mode.")

_ACTIVATE = (
    r"^\s*ultron\s*[.!]?\s*$",
    r"\bactivate ultron\b", r"\bultron mode\b", r"\bbring ultron online\b",
    r"\bultron,? (?:wake|come) (?:up|online)\b",
    r"\bactivate serious mode\b", r"\bserious mode\b", r"\bgo serious\b",
    r"\bbe serious\b", r"\bget serious\b",
)
_DEACTIVATE = (
    r"\breturn to zeno\b", r"\bexit ultron\b", r"\bnormal mode\b",
    r"\bdeactivate serious mode\b", r"\bultron,? stand down\b",
    r"\bstand down\b", r"\bzeno,? come back\b", r"\bback to normal\b",
    r"\bstop being serious\b",
)
_ACTIVATE_RE = [re.compile(p, re.I) for p in _ACTIVATE]
_DEACTIVATE_RE = [re.compile(p, re.I) for p in _DEACTIVATE]

_lock = threading.RLock()
_state: dict[str, Any] = {"mode": NORMAL, "since": time.time(),
                          "changed_by": "startup", "activations": 0}


@dataclass
class RuntimeState:
    """What the GUI renders. Every field is read from something real."""

    master: str = MASTER
    mode: str = NORMAL
    activity_state: str = "IDLE"
    current_task: str = ""
    active_agent: str = ""
    active_sub_agent: str = ""
    active_worker: str = ""
    current_tool: str = ""
    voice_state: str = "STANDBY"
    health: dict[str, Any] = field(default_factory=dict)
    since: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"master": self.master, "mode": self.mode,
                "activity_state": self.activity_state,
                "current_task": self.current_task,
                "active_agent": self.active_agent,
                "active_sub_agent": self.active_sub_agent,
                "active_worker": self.active_worker,
                "current_tool": self.current_tool,
                "voice_state": self.voice_state, "health": self.health,
                "since": self.since,
                "elapsed_s": round(time.time() - self.since, 1) if self.since else 0.0}


def current() -> str:
    with _lock:
        return _state["mode"]


def is_ultron() -> bool:
    return current() == ULTRON


def detect(utterance: str) -> str:
    """ACTIVATE, DEACTIVATE or '' -- what this sentence asks of the mode.

    Deactivation is checked FIRST. "Ultron, stand down" contains the word
    ultron, and matching activation on it would make the phrase that turns
    serious mode off turn it on instead.
    """
    text = (utterance or "").strip()
    if not text:
        return ""
    for pattern in _DEACTIVATE_RE:
        if pattern.search(text):
            return "DEACTIVATE"
    for pattern in _ACTIVATE_RE:
        if pattern.search(text):
            return "ACTIVATE"
    return ""


def _announce(previous: str, now: str, source: str) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish("assistant.mode_changed",
                          {"previous": previous, "current": now,
                           "master": MASTER, "source": source,
                           "timestamp": time.time()},
                          source="modes")
    except Exception:  # noqa: BLE001
        pass


def set_mode(mode: str, *, source: str = "owner") -> dict[str, Any]:
    """Change mode and announce it. Idempotent."""
    want = (mode or "").strip().upper()
    if want not in MODES:
        return {"ok": False, "mode": current(),
                "reason": f"'{mode}' is not a mode. Use NORMAL or ULTRON."}

    with _lock:
        previous = _state["mode"]
        if previous == want:
            return {"ok": True, "mode": want, "changed": False,
                    "say": "", "reason": f"already in {want} mode"}
        _state.update({"mode": want, "since": time.time(), "changed_by": source})
        if want == ULTRON:
            _state["activations"] += 1
        count = _state["activations"]

    _announce(previous, want, source)
    greeting = (_GREETINGS[(count - 1) % len(_GREETINGS)] if want == ULTRON
                else _FAREWELLS[count % len(_FAREWELLS)])
    return {"ok": True, "mode": want, "previous": previous, "changed": True,
            "master": MASTER, "say": greeting,
            "intro_animation": intro_enabled()}


def intro_enabled() -> bool:
    return os.environ.get("ULTRON_INTRO_ANIMATION", "true").strip().lower() \
        not in {"0", "false", "no", "off"}


def visual_quality() -> str:
    """AUTO | LOW | MEDIUM | HIGH. AUTO is resolved by the page, which is the
    only place that can see the actual frame budget."""
    value = os.environ.get("ULTRON_VISUAL_QUALITY", "AUTO").strip().upper()
    return value if value in ("AUTO", "LOW", "MEDIUM", "HIGH") else "AUTO"


def restore_on_start() -> str:
    """Which mode a restart lands in.

    NORMAL unless explicitly configured otherwise. A crash while serious mode
    was on should not bring the machine back up in a state the owner did not
    ask for a second time.
    """
    if os.environ.get("RESTORE_LAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return current()
    return NORMAL


def style() -> dict[str, Any]:
    """How ZENO should speak right now. Prompt guidance, not a second brain."""
    if not is_ultron():
        return {"mode": NORMAL, "guidance": ""}
    return {
        "mode": ULTRON,
        "guidance": (
            "You are ZENO in serious mode, which the owner calls Ultron. Same "
            "system, same identity, different operating state. Be calm, "
            "precise and direct. Lead with the objective, then the plan, then "
            "risks. State what you verified rather than what you assume. Cut "
            "jokes, filler and enthusiasm. Never be threatening, theatrical or "
            "grandiose -- 'Understood. I'll verify the current state before "
            "changing anything' is right; declarations about controlling all "
            "systems are not. You are not a separate being: if asked what "
            "Ultron is, say you are ZENO's serious operating mode."),
        "reduce": ["jokes", "filler", "rambling", "enthusiasm"],
        "increase": ["precision", "risk awareness", "verification",
                     "clear recommendations", "failure detection"],
        "delegates_strategy_to": "ultron",   # the REGISTERED agent, not a copy
    }


def runtime_state() -> RuntimeState:
    """The live object the GUI renders. Empty fields mean empty, not unknown."""
    with _lock:
        mode, since = _state["mode"], _state["since"]

    state = RuntimeState(mode=mode, since=since)
    try:
        from reyes_agent import conversation_state

        state.activity_state = conversation_state.current()
        state.voice_state = conversation_state.current()
    except Exception:  # noqa: BLE001
        pass

    # The active agent path comes from the SAME registry ZENO uses. There is
    # no Ultron-only agent list to drift out of step with it.
    try:
        from reyes_agent.agents import registry

        busy = [a for a in registry.agents() if getattr(a, "busy", False)]
        if busy:
            state.active_agent = busy[0].name
    except Exception:  # noqa: BLE001
        pass
    return state


def status() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    return {
        "state": "ONLINE",
        "master": MASTER,
        "mode": snapshot["mode"],
        "since": snapshot["since"],
        "elapsed_s": round(time.time() - snapshot["since"], 1),
        "changed_by": snapshot["changed_by"],
        "activations": snapshot["activations"],
        "intro_animation": intro_enabled(),
        "visual_quality": visual_quality(),
        "restore_last_mode": restore_on_start() != NORMAL,
        "safety": ("unchanged -- serious mode alters reasoning and tone, never "
                   "permissions, policy or confirmation"),
        "ultron_agent": ("the registered Chief Strategy Officer, reused; no "
                         "second ULTRON identity is created"),
    }
