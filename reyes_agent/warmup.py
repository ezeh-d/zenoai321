"""Prepare provider clients without consuming idle cloud inference quota.

Cloud SDK imports and client construction run once in a managed background
job. DNS/TLS and inference wait for a real request. Explicit Ollama mode keeps
its existing local model keepalive, with bounded requests and closed clients.
"""

from __future__ import annotations

from reyes_agent import config

_PING_INTERVAL_SECONDS = 4 * 60  # inside Ollama's ~5 min default unload window


def _ping() -> None:
    import openai

    client = openai.OpenAI(api_key="ollama", base_url=config.OLLAMA_BASE_URL,
                           timeout=30.0, max_retries=0)
    try:
        client.chat.completions.create(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception:  # noqa: BLE001 -- best-effort keepalive, never fatal
        pass
    finally:
        client.close()


def _warm_cloud() -> None:
    """Preload cached SDK clients; deliberately send no network request."""
    from reyes_agent import provider

    provider.warm()


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
        "cloud-warmup", _warm_cloud, delay=1.0,
        priority=80, timeout=30,
    )
