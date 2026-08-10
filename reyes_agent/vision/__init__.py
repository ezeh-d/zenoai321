"""ZENO's screen eyes.

Windows UI Automation is the primary backend because it returns
accessibility ground truth in ~0.2s with no model and no GPU; OCR covers
surfaces with no accessibility tree; OmniParser is an optional adapter for
machines that can actually run it. All three return the same `Element`
schema, so the computer controller never cares which one answered.
"""

from __future__ import annotations

from reyes_agent.vision import elements, grounding, parser, scene_state, screen_capture
from reyes_agent.vision.elements import Element, Scene

__all__ = ["Element", "Scene", "elements", "grounding", "parser",
           "scene_state", "screen_capture", "observe", "find"]


def observe(force: bool = False):
    """The current screen, cached briefly."""
    return scene_state.current(force=force)


def find(want: str, **kwargs):
    """Resolve a description to a real on-screen element, or None."""
    return grounding.find(scene_state.current(), want, **kwargs)
