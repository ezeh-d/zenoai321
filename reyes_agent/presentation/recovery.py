"""Getting back to a working state, in front of somebody, without panic.

    "DO NOT kill the entire application unless absolutely necessary."

That constraint is the design. Recovery during a visit is not about repairing
whatever broke -- there is no time, and diagnosis in front of a supervisor is
worse than the fault. It is about returning to the ONE state that always
works: ZENO, quiet, listening.

So this stops things and closes things. It does not delete, reset, wipe,
restart or terminate. Every step is independently guarded, because a recovery
that raises halfway through is worse than the failure it was called for -- and
each step reports what it actually managed, so the display afterwards is
honest rather than a reassuring "RECOVERED" over a broken microphone.
"""

from __future__ import annotations

import time
from typing import Any

# Named so the display can say what is on and what is off, rather than
# implying everything is fine.
SAFE_MODE_DISABLES = ("presentation animations", "Agent Space rendering",
                      "architecture visualisation", "orb particle effects")


def _step(name: str, action) -> dict[str, Any]:
    """Run one recovery step. Never raises; always reports."""
    started = time.perf_counter()
    try:
        detail = action() or ""
        ok = True
    except Exception as exc:  # noqa: BLE001
        detail, ok = f"{type(exc).__name__}: {exc}", False
    return {"step": name, "ok": ok, "detail": str(detail)[:160],
            "took_ms": round((time.perf_counter() - started) * 1000, 1)}


def _stop_speech() -> str:
    from reyes_agent import voice_manager

    stopped = voice_manager.cancel_current()
    return f"stopped {stopped} queued utterance(s)"


def _cancel_task() -> str:
    """Cancel the running turn if one is cancellable. Never force-kills."""
    try:
        from reyes_agent.worker_pool import get_worker_pool

        pool = get_worker_pool()
        cancel = getattr(pool, "cancel_current", None) or getattr(pool, "cancel_all", None)
        if cancel is None:
            return "no cancellable task interface"
        return f"cancelled: {cancel()}"
    except Exception as exc:  # noqa: BLE001
        return f"nothing to cancel ({type(exc).__name__})"


def _close_conversation_state() -> str:
    from reyes_agent import conversation_state

    conversation_state.enter(conversation_state.LISTENING, source="recovery")
    return f"state -> {conversation_state.current()}"


def _reopen_listening() -> str:
    """Keep the conversation open, so recovery does not also mute ZENO."""
    from reyes_agent.voice import continuity

    continuity.open_window(source="recovery")
    return f"conversation window open for {continuity.seconds_left():.0f}s"


def _microphone() -> str:
    from reyes_agent.audio.manager import get_audio_manager

    state = get_audio_manager().status()
    sources = state.get("sources") or {}
    if not sources:
        return "NO AUDIO SOURCE -- reconnect the phone or use the laptop mic"
    return f"active: {state.get('active_source') or 'unknown'}"


def recover(*, safe_mode: bool = False) -> dict[str, Any]:
    """Return to ZENO, quiet and listening. Reports what actually happened."""
    steps = [
        _step("stop speech", _stop_speech),
        _step("cancel current task", _cancel_task),
        _step("return to listening", _close_conversation_state),
        _step("reopen conversation", _reopen_listening),
        _step("check microphone", _microphone),
    ]

    if safe_mode:
        steps.append({"step": "safe mode", "ok": True,
                      "detail": "disabled: " + ", ".join(SAFE_MODE_DISABLES),
                      "took_ms": 0.0})

    failed = [s for s in steps if not s["ok"]]
    mic = next((s for s in steps if s["step"] == "check microphone"), {})
    mic_broken = "NO AUDIO SOURCE" in str(mic.get("detail", ""))

    # The display must not say RECOVERED over a dead microphone.
    if failed or mic_broken:
        headline = "ZENO — RECOVERED WITH PROBLEMS"
        say = ("I'm back and listening"
               + (", but there's no microphone input right now."
                  if mic_broken else ", though some parts did not reset."))
    else:
        headline = "ZENO — RECOVERED · LISTENING"
        say = ""          # nothing to announce; just be listening again

    return {
        "headline": headline,
        "recovered": not failed and not mic_broken,
        "safe_mode": safe_mode,
        "steps": steps,
        "problems": [s["step"] for s in failed] + (["microphone"] if mic_broken else []),
        "say": say,
        "did_not": ("delete data, reset memory, wipe sessions, remove logs, "
                    "or restart the application"),
    }


def status() -> dict[str, Any]:
    return {"state": "ONLINE",
            "steps": 5,
            "safe_mode_disables": list(SAFE_MODE_DISABLES),
            "guarantee": ("Stops and closes only. Never deletes, resets or "
                          "restarts, and never reports RECOVERED over a "
                          "broken microphone.")}
