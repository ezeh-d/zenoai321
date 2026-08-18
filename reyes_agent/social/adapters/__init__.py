"""Platform adapters.

Imported lazily: neither adapter touches the network on import, and a missing
configuration must never stop ZENO from starting.
"""

from __future__ import annotations

from typing import Any

from reyes_agent.social import store as social_store
from reyes_agent.social.adapters.base import (
    AUTH_REQUIRED, DEGRADED, FAILED, HEALTHY, NOT_CONFIGURED, OFFLINE,
    RATE_LIMITED, AuthState, PublishResult, RateLimitError, SocialAdapter,
)

__all__ = [
    "AuthState", "PublishResult", "RateLimitError", "SocialAdapter",
    "HEALTHY", "DEGRADED", "AUTH_REQUIRED", "RATE_LIMITED", "OFFLINE",
    "FAILED", "NOT_CONFIGURED", "adapter_for", "all_adapters",
]

_CACHE: dict[str, SocialAdapter] = {}


def adapter_for(platform: str) -> SocialAdapter | None:
    """One adapter instance per platform, so rate-limit state is shared."""
    key = (platform or "").strip().lower()
    if key in _CACHE:
        return _CACHE[key]

    if key == social_store.INSTAGRAM:
        from reyes_agent.social.adapters.instagram import InstagramAPIAdapter
        _CACHE[key] = InstagramAPIAdapter()
    elif key == social_store.TIKTOK:
        from reyes_agent.social.adapters.tiktok import TikTokAPIAdapter
        _CACHE[key] = TikTokAPIAdapter()
    else:
        return None
    return _CACHE[key]


def all_adapters() -> dict[str, SocialAdapter]:
    return {platform: adapter for platform in social_store.PLATFORMS
            if (adapter := adapter_for(platform)) is not None}


def reset_adapters_for_tests() -> None:
    _CACHE.clear()


def health() -> list[dict[str, Any]]:
    out = []
    for platform in social_store.PLATFORMS:
        adapter = adapter_for(platform)
        if adapter is None:
            continue
        try:
            out.append(adapter.health())
        except Exception as exc:  # noqa: BLE001
            out.append({"platform": platform, "state": FAILED,
                        "detail": f"{type(exc).__name__}: {exc}"})
    return out
