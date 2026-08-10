"""Microphone noise suppression, before VAD, skipped on a clean mic."""

from __future__ import annotations

from reyes_agent.audio.noise import suppressor

__all__ = ["suppressor", "suppress", "enabled", "status"]

suppress = suppressor.suppress
enabled = suppressor.enabled
status = suppressor.status
