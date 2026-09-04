"""Local, consent-scoped playful Ragebait state for ZENO.

This is intentionally a policy/state module, not a second chat runtime.  It
does no I/O, provider work, or continuous processing.  The normal ZENO turn
may request a short directive from it after the owner explicitly enables it.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent import cognition

MAX_INTENSITY = 5
MAX_ROUNDS = 5
_RECENT_CAPACITY = 8
_MOTION_COOLDOWN_S = 12.0

_STOP = ("stop", "enough", "turn it off", "normal mode", "serious mode", "don't joke", "dont joke")
_ACTIVATE = ("ragebait me", "turn on ragebait", "ragebait mode", "try to annoy me", "make me mad")
_BATTLE = ("ragebait battle", "battle ragebait")
_UP = ("go harder", "harder", "that's weak", "that is weak", "stronger")
_DOWN = ("tone it down", "light ragebait", "go easy", "less ragebait")
_SERIOUS = ("emergency", "medical", "security incident", "financial", "destructive", "serious system failure")


@dataclass
class _Battle:
    active: bool = False
    round: int = 0
    maximum_rounds: int = MAX_ROUNDS
    user_score: float = 0.0
    zeno_score: float = 0.0
    combo_count: int = 0


@dataclass
class _State:
    enabled: bool = False
    intensity: int = 0
    battle: _Battle = field(default_factory=_Battle)
    recent: deque[str] = field(default_factory=lambda: deque(maxlen=_RECENT_CAPACITY))
    last_motion_at: float = 0.0


_lock = threading.RLock()
_state = _State()


def _default_publish(name: str, payload: dict[str, Any]) -> None:
    from reyes_agent import event_bus

    event_bus.publish(name, payload, source="ragebait")


_publish: Callable[[str, dict[str, Any]], None] = _default_publish


def configure_for_test(*, publish: Callable[[str, dict[str, Any]], None] | None = None) -> None:
    """Inject a publisher for tests; production callers never need this."""
    global _publish
    with _lock:
        _publish = publish or _default_publish


def _normalized(text: str) -> str:
    return cognition.normalize(text or "")


def _matches(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _stop(text: str) -> bool:
    return _matches(text, _STOP)


def _serious(text: str, explicit: bool) -> bool:
    return explicit or cognition.is_sensitive(text) or _matches(text, _SERIOUS)


def _snapshot_locked() -> dict[str, Any]:
    battle = _state.battle
    return {
        "enabled": _state.enabled,
        "intensity": _state.intensity,
        "recent_lines": len(_state.recent),
        "battle": {
            "active": battle.active,
            "round": battle.round,
            "maximum_rounds": battle.maximum_rounds,
            "user_score": battle.user_score,
            "zeno_score": battle.zeno_score,
            "combo_count": battle.combo_count,
        },
    }


def _emit(name: str, snapshot: dict[str, Any], *, reason: str = "") -> None:
    payload = {
        "enabled": bool(snapshot["enabled"]),
        "intensity": int(snapshot["intensity"]),
        "battle": dict(snapshot["battle"]),
        "reason": reason[:40],
    }
    try:
        _publish(name, payload)
    except Exception:
        pass


def status() -> dict[str, Any]:
    with _lock:
        return _snapshot_locked()


def reset() -> None:
    """Return to normal state. Restart policy is always Ragebait-off."""
    global _state
    with _lock:
        _state = _State()


def _disable(reason: str) -> dict[str, Any]:
    with _lock:
        was_active = _state.enabled or _state.battle.active
        _state.enabled = False
        _state.intensity = 0
        _state.battle = _Battle()
        snapshot = _snapshot_locked()
    if was_active:
        _emit("ragebait.disabled", snapshot, reason=reason)
    return snapshot


def _enable() -> dict[str, Any]:
    with _lock:
        changed = not _state.enabled
        _state.enabled = True
        if _state.intensity == 0:
            _state.intensity = 1
        snapshot = _snapshot_locked()
    if changed:
        _emit("ragebait.enabled", snapshot)
    return snapshot


def _change_intensity(delta: int) -> dict[str, Any]:
    with _lock:
        if not _state.enabled:
            return _snapshot_locked()
        before = _state.intensity
        _state.intensity = max(0, min(MAX_INTENSITY, _state.intensity + delta))
        if _state.intensity == 0:
            _state.enabled = False
            _state.battle = _Battle()
        snapshot = _snapshot_locked()
    if before != snapshot["intensity"]:
        _emit("ragebait.intensity_changed" if snapshot["enabled"] else "ragebait.disabled", snapshot, reason="intensity")
    return snapshot


def _start_battle() -> dict[str, Any]:
    _enable()
    with _lock:
        _state.battle = _Battle(active=True)
        snapshot = _snapshot_locked()
    _emit("ragebait.battle_started", snapshot)
    return snapshot


def handle(message: str, *, serious: bool = False, now: float | None = None) -> dict[str, Any]:
    """Apply an owner utterance to state; all state work is synchronous/local."""
    del now
    text = _normalized(message)
    if not text:
        return status()
    if _stop(text):
        return _disable("stop")
    if _serious(text, serious):
        return _disable("serious")
    if _matches(text, _BATTLE):
        return _start_battle()
    if _matches(text, _ACTIVATE):
        return _enable()
    if _matches(text, _UP):
        return _change_intensity(1)
    if _matches(text, _DOWN):
        return _change_intensity(-1)
    return status()


def directive(message: str, *, audience: str, serious: bool = False, now: float | None = None) -> str:
    """Return a compact prompt instruction, never an actual generated reply."""
    if audience != "owner_conversation":
        return ""
    text = _normalized(message)
    if _stop(text) or _serious(text, serious):
        handle(message, serious=serious, now=now)
        return ""
    snapshot = status()
    if not snapshot["enabled"]:
        return ""
    recent = ""
    with _lock:
        if _state.recent:
            recent = " Avoid repeating recent banter: " + " | ".join(list(_state.recent)[-3:]) + "."
    battle = snapshot["battle"]
    battle_note = " Continue the current battle round." if battle["active"] else ""
    return (
        f"[Ragebait: consensual owner-to-ZENO playful banter, intensity {snapshot['intensity']}/5. "
        "Be clever and brief; no abuse, threats, identity/appearance/trauma/financial-vulnerability attacks, "
        "or third-party targets. Never delay real assistance.]" + battle_note + recent
    )


def record_reply(reply: str) -> None:
    clean = re.sub(r"\s+", " ", str(reply or "")).strip()
    if not clean:
        return
    fingerprint = clean.casefold()[:160]
    with _lock:
        if not _state.enabled or fingerprint in _state.recent:
            return
        _state.recent.append(fingerprint)
        if _state.battle.active:
            _state.battle.round += 1
            _state.battle.zeno_score = round(_state.battle.zeno_score + 1.0, 1)
            _state.battle.combo_count += 1
            finished = _state.battle.round >= _state.battle.maximum_rounds
            if finished:
                _state.battle.active = False
            snapshot = _snapshot_locked()
        else:
            snapshot = None
            finished = False
    if snapshot:
        _emit("ragebait.battle_finished" if finished else "ragebait.round_completed", snapshot)


def on_motion(event_name: str, *, now: float | None = None) -> dict[str, Any] | None:
    """Return at most one local reaction per cooldown; never calls a model."""
    if event_name not in {"motion.shake", "motion.dizzy", "motion.recovered"}:
        return None
    tick = time.monotonic() if now is None else now
    with _lock:
        if not _state.enabled or tick - _state.last_motion_at < _MOTION_COOLDOWN_S:
            return None
        _state.last_motion_at = tick
        snapshot = _snapshot_locked()
    _emit("ragebait.reaction", snapshot, reason=event_name)
    return {"emotion": "skeptical" if event_name == "motion.shake" else "curious", "state": snapshot}
