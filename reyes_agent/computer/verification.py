"""Did the action actually do anything?

An agentic loop without verification reports success because it SENT a
click, not because the click worked. Every check here compares the screen
before with the screen after and reports what genuinely changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reyes_agent.vision.elements import Scene


@dataclass
class Change:
    changed: bool
    window_changed: bool
    appeared: list[str]
    disappeared: list[str]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"changed": self.changed, "window_changed": self.window_changed,
                "appeared": self.appeared[:8], "disappeared": self.disappeared[:8],
                "detail": self.detail}


def _fingerprint(scene: Scene) -> set[str]:
    return {f"{e.type}:{e.label}" for e in scene.elements if e.label}


def compare(before: Scene, after: Scene) -> Change:
    """What actually changed between two observations."""
    window_changed = before.window != after.window
    old, new = _fingerprint(before), _fingerprint(after)
    appeared = sorted(new - old)
    disappeared = sorted(old - new)
    changed = bool(window_changed or appeared or disappeared)
    if window_changed:
        detail = f"window changed: {before.window[:40]!r} -> {after.window[:40]!r}"
    elif changed:
        detail = f"{len(appeared)} appeared, {len(disappeared)} disappeared"
    else:
        detail = "nothing observably changed"
    return Change(changed, window_changed,
                  [a.split(":", 1)[-1] for a in appeared],
                  [d.split(":", 1)[-1] for d in disappeared], detail)


def expects(after: Scene, expectation: str) -> tuple[bool, str]:
    """Check a plain-language expectation against the real screen."""
    want = str(expectation or "").strip().lower()
    if not want:
        return True, "no expectation given"
    haystack = (after.window + " " + " ".join(e.label for e in after.elements)).lower()
    if want in haystack:
        return True, f"found {expectation!r} on screen"
    for token in [t for t in want.split() if len(t) > 3]:
        if token in haystack:
            return True, f"found {token!r} on screen (partial match for {expectation!r})"
    return False, f"{expectation!r} is not visible on screen"
