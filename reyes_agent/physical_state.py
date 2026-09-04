"""Bridges the frontend motion engine's physical events (shake/dizzy/settled)
to a genuinely-generated, occasional in-character line -- never a canned
string repeated verbatim, never louder than real work.

WHAT THIS IS NOT: a physics engine. Every velocity/shake/dizziness
CALCULATION happens entirely in the browser (static/motion_engine.js) at
render cadence -- nothing here is on that path, and nothing here is called
per-frame. This module answers exactly one question, at most once per
cooldown window: "is now a reasonable moment for ZENO to say something about
what just happened to the HUD, and if so, what?" That question reaches the
model -- coordinates and velocities never do (see the /api/personality/
physical-event handler in web.py, which sends only a coarse event label plus
0..1 dizziness/shake floats, not raw motion samples).
"""

from __future__ import annotations

import threading
import time

_COOLDOWN_S = 25.0  # personality reactions must not become chatter
_lock = threading.Lock()
_last_reaction_at = 0.0

_VALID_EVENTS = {"shake", "dizzy", "recovered"}

# Guidance only -- see build_context()'s docstring for why these are never
# returned verbatim. Three per event so the model has real variety to draw
# from rather than one phrase it converges on by default.
_TONE_EXAMPLES: dict[str, tuple[str, ...]] = {
    "shake": (
        "Easy there. My stabilizers have feelings.",
        "Whoa -- are we escaping something, or just excited?",
        "Noted. Filing a complaint with whoever's holding the mouse.",
    ),
    "dizzy": (
        "Right... give the room a second to stop orbiting.",
        "Okay, that's enough centrifuge for one afternoon.",
        "I may need a moment. Or a horizon. Either works.",
    ),
    "recovered": (
        "Stabilizers restored.",
        "Okay, world's holding still again. Good.",
        "Back to level. That was a whole thing.",
    ),
}


def _on_cooldown(now: float) -> bool:
    with _lock:
        return (now - _last_reaction_at) < _COOLDOWN_S


def _mark_reacted(now: float) -> None:
    global _last_reaction_at
    with _lock:
        _last_reaction_at = now


def cooldown_remaining_s() -> float:
    with _lock:
        return max(0.0, _COOLDOWN_S - (time.time() - _last_reaction_at))


def _important_work_active() -> bool:
    """Real conversation/voice work in flight overrides a playful aside --
    reuses the SAME operation registry _fast_local_reply and the turn
    supersede logic already check, rather than a second notion of 'busy'."""
    try:
        from reyes_agent.intelligence import get_runtime_control

        return any(op.get("kind") in ("brain", "voice") for op in get_runtime_control().active())
    except Exception:  # noqa: BLE001 -- a broken health check must never force a reaction through
        return True  # fail toward silence, not toward interrupting the owner


def maybe_react(event: str, *, dizziness: float = 0.0, shake_intensity: float = 0.0,
                now: float | None = None) -> dict[str, object]:
    """Decide whether to react, and if so, generate ONE short line.

    Returns {"reacted": False, "reason": str} or {"reacted": True, "text": str,
    "event": str}. `text` is meant to be spoken by the caller through the
    EXISTING /api/tts endpoint (voice_manager.synthesize) -- this function
    never touches audio itself, so there is exactly one TTS code path in
    the whole app, not a second one for personality quips.
    """
    now = time.time() if now is None else now
    event = str(event or "").strip().lower()
    if event not in _VALID_EVENTS:
        return {"reacted": False, "reason": "unknown_event"}
    if _on_cooldown(now):
        return {"reacted": False, "reason": "cooldown"}
    if _important_work_active():
        return {"reacted": False, "reason": "important_work_active"}

    try:
        text = _generate_line(event, dizziness=dizziness, shake_intensity=shake_intensity)
    except Exception:  # noqa: BLE001 -- a failed quip must never surface as an error
        return {"reacted": False, "reason": "generation_failed"}
    if not text:
        return {"reacted": False, "reason": "empty_generation"}

    _mark_reacted(now)
    return {"reacted": True, "text": text, "event": event}


def _generate_line(event: str, *, dizziness: float, shake_intensity: float) -> str:
    """One tiny, fast model call -- reuses provider.run_turn (the SAME
    provider/fallback/circuit-breaker path every real turn uses), not a
    separate LLM-calling mechanism. No tools, no conversation history: this
    is a one-shot aside, never a step in the owner's actual conversation.
    """
    from reyes_agent import config
    from reyes_agent.provider import run_turn

    examples = "; ".join(f'"{line}"' for line in _TONE_EXAMPLES.get(event, ()))
    intensity_note = (
        f" (dizziness {dizziness:.2f}, shake {shake_intensity:.2f} on a 0-1 scale)"
        if event != "recovered" else ""
    )
    system = (
        "You are ZENO reacting, in one short spoken line (under 15 words), to your own HUD "
        f"being physically {event}{intensity_note} on screen. Stay in character: dry, "
        "self-aware, a little playful, never alarmed and never verbose. Generate a genuinely "
        "NEW line in that spirit -- do not just recite one of these examples verbatim, they "
        f"are tone reference only: {examples}. Reply with ONLY the line, no quotes, no preamble."
    )
    turn = run_turn(
        [{"role": "user", "content": "(react now)"}],
        system=system, tools=[], task_kind="general",
    )
    text = (turn.text or "").strip().strip('"').strip()
    return text[:200]
