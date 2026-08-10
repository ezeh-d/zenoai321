"""Turn "the Send button" into a real element with real coordinates.

This is the step that stops a computer-use agent from clicking at invented
pixel positions: a description is resolved against elements the screen
actually reported, and if nothing matches well enough the answer is None
rather than a best guess.
"""

from __future__ import annotations

import re

from reyes_agent.vision.elements import Element, Scene

# Below this, a match is not trustworthy enough to click.
MIN_SCORE = 0.45


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


def score(element: Element, want: str, kind: str = "") -> float:
    """How well one element matches a description. 0..1."""
    label = _normalise(element.label)
    target = _normalise(want)
    if not target:
        return 0.0

    if kind and element.type != kind:
        return 0.0

    if label == target:
        base = 1.0
    elif target and label.startswith(target):
        base = 0.85
    elif target and target in label:
        base = 0.7
    elif label and label in target:
        base = 0.6
    else:
        wanted = set(target.split())
        have = set(label.split())
        if not wanted or not have:
            return 0.0
        overlap = len(wanted & have) / len(wanted)
        if overlap == 0:
            return 0.0
        base = 0.3 + (overlap * 0.35)

    # Interactive elements win ties: "Send" the button beats "Send" the
    # label next to it, because an action wants something actionable.
    if element.interactive:
        base += 0.08
    if not element.enabled:
        base -= 0.35
    return max(0.0, min(1.0, base))


def find(scene: Scene, want: str, *, kind: str = "",
         interactive_only: bool = True) -> Element | None:
    """Best match, or None when nothing is confident enough."""
    candidates = scene.interactive if interactive_only else scene.elements
    if not candidates:
        candidates = scene.elements
    ranked = sorted(((score(e, want, kind), e) for e in candidates),
                    key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] < MIN_SCORE:
        return None
    return ranked[0][1]


def candidates(scene: Scene, want: str, limit: int = 5) -> list[tuple[float, Element]]:
    """Ranked alternatives -- used when a match is ambiguous and ZENO should
    ask rather than pick."""
    ranked = sorted(((score(e, want), e) for e in scene.elements),
                    key=lambda pair: pair[0], reverse=True)
    return [(round(s, 3), e) for s, e in ranked[:limit] if s > 0]


def ambiguous(scene: Scene, want: str) -> bool:
    """True when the top two matches are too close to choose between."""
    ranked = candidates(scene, want, limit=2)
    if len(ranked) < 2 or ranked[0][0] < MIN_SCORE:
        return False
    return (ranked[0][0] - ranked[1][0]) < 0.12
