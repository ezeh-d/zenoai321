"""Shared audio adapters; only WebView2 opens the physical microphone."""

from reyes_agent.audio.manager import get_audio_manager

__all__ = ["get_audio_manager"]
