"""Keeps the local Ollama model loaded so replies don't pay a cold-start cost.

Root cause of the worst lag: Ollama unloads a model after ~5 minutes idle,
and reloading llama3.2:3b from disk takes ~35s -- vs ~6s for an
already-loaded model. That 35s was landing on whatever message happened to
be the next one after a gap, which reads as random, severe lag.

Fix: fire a trivial completion at startup (pays the 35s once, up front,
instead of on a real user turn) and again periodically before the idle
timeout would kick the model out. Only relevant for the Ollama provider --
cloud providers have no load/unload cost.
"""

from __future__ import annotations

from reyes_agent import config

_PING_INTERVAL_SECONDS = 4 * 60  # inside Ollama's ~5 min default unload window


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


def start_background_keepalive() -> None:
    """No-op for non-Ollama providers -- they don't have this problem."""
    if config.MODEL_PROVIDER != "ollama":
        return
    from reyes_agent.scheduler import get_scheduler

    # A local model warmup is intentionally staged after the panel is ready;
    # it no longer holds startup hostage to a 35-second model load.
    get_scheduler().schedule(
        "ollama-warmup", _ping, delay=2.0, interval=_PING_INTERVAL_SECONDS,
        priority=80, timeout=60,
    )
