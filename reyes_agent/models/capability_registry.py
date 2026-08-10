"""Truthful model capabilities used for routing decisions."""
from __future__ import annotations

CAPABILITIES = {
    "anthropic": frozenset({"TEXT", "VISION", "CODE", "TOOL_USE", "LONG_CONTEXT"}),
    "openai": frozenset({"TEXT", "VISION", "REALTIME", "CODE", "TOOL_USE", "LONG_CONTEXT"}),
    "gemini": frozenset({"TEXT", "VISION", "CODE", "TOOL_USE", "LONG_CONTEXT", "FAST", "CHEAP"}),
    "xai": frozenset({"TEXT", "CODE", "TOOL_USE", "LONG_CONTEXT"}),
    "ollama": frozenset({"TEXT", "CODE", "LOCAL", "OFFLINE"}),
}


def supports(provider: str, required: set[str] | frozenset[str]) -> bool:
    return set(required).issubset(CAPABILITIES.get(provider, frozenset()))
