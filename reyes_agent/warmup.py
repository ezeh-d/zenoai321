"""Pays model cold-start costs up front instead of on the user's first turn.

TWO DIFFERENT COLD STARTS
-------------------------
1. OLLAMA unloads a model after ~5 minutes idle, and reloading
   llama3.2:3b from disk takes ~35s vs ~6s warm. That 35s landed on
   whatever message happened to follow a gap, which reads as random,
   severe lag.

2. CLOUD providers were assumed to have no cold start, and the keepalive
   returned immediately for them. That was wrong in a way nobody measured
   until 2026-08-07: the FIRST cloud turn of a session took 6.2s against a
   1.4s warm median. The model is not the cost -- constructing the SDK
   client, resolving DNS and completing the TLS handshake is. It is paid
   once per process, and it was being paid by the owner's first sentence.

So both are warmed now. The cloud ping is deliberately tiny (max_tokens=1,
one word in) so the cost is a handshake, not a conversation, and it is
scheduled rather than blocking so startup is never held hostage to it.
"""

from __future__ import annotations

from reyes_agent import config

_PING_INTERVAL_SECONDS = 4 * 60  # inside Ollama's ~5 min default unload window
# Cloud connections go idle and get closed by the peer too; a quiet
# re-ping keeps the pooled TLS connection usable without being chatty.
_CLOUD_REFRESH_SECONDS = 10 * 60


def _ping() -> None:
    import openai

    client = openai.OpenAI(api_key="ollama", base_url=config.OLLAMA_BASE_URL)
    try:
        client.chat.completions.create(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception:  # noqa: BLE001 -- best-effort keepalive, never fatal
        pass


def _warm_cloud() -> None:
    """Build the real client and complete one real handshake.

    Uses the same `_get_*_client()` the live path uses, so the warmed client
    is the one that actually serves the next turn -- warming a throwaway
    client would prove nothing.
    """
    from reyes_agent import provider

    getters = {
        "gemini": getattr(provider, "_get_gemini_client", None),
        "xai": getattr(provider, "_get_xai_client", None),
        "anthropic": getattr(provider, "_get_anthropic_client", None),
    }
    getter = getters.get(config.MODEL_PROVIDER)
    if getter is None:
        return
    try:
        client = getter()
    except Exception:  # noqa: BLE001 -- a missing key is not a warmup failure
        return
    model = {
        "gemini": config.GEMINI_MODEL, "xai": config.XAI_MODEL,
        "anthropic": config.ANTHROPIC_MODEL,
    }.get(config.MODEL_PROVIDER, "")
    try:
        if config.MODEL_PROVIDER == "anthropic":
            client.messages.create(model=model, max_tokens=1,
                                   messages=[{"role": "user", "content": "hi"}])
        else:
            client.chat.completions.create(model=model, max_tokens=1,
                                           messages=[{"role": "user", "content": "hi"}])
    except Exception:  # noqa: BLE001 -- the TLS/DNS cost is paid either way
        pass


def start_background_keepalive() -> None:
    """Warm whichever provider is actually configured."""
    from reyes_agent.scheduler import get_scheduler

    scheduler = get_scheduler()
    if config.MODEL_PROVIDER == "ollama":
        # A local model warmup is intentionally staged after the panel is ready;
        # it no longer holds startup hostage to a 35-second model load.
        scheduler.schedule(
            "ollama-warmup", _ping, delay=2.0, interval=_PING_INTERVAL_SECONDS,
            priority=80, timeout=60,
        )
        return
    scheduler.schedule(
        "cloud-warmup", _warm_cloud, delay=1.0, interval=_CLOUD_REFRESH_SECONDS,
        priority=80, timeout=30,
    )
