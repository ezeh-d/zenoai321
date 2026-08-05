"""
LLM gateway — tries multiple models in order until one answers.

Order: your primary model, then any other cloud providers you have keys for,
then local Ollama (no key needed). Models whose provider key is missing are
skipped, so REYES never wastes a call that would just fail with 401.
"""
from __future__ import annotations

import os

from config import settings
from logger import log


def _ensure_env() -> None:
    """LiteLLM reads keys from env vars, so mirror our settings into os.environ."""
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
    if settings.gemini_api_key:
        os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)


def _provider_key(model: str) -> str | None:
    """Return the API key a model needs, or None if it needs none (Ollama)."""
    m = model.lower()
    if m.startswith("ollama/"):
        return "__none__"  # sentinel: no key required
    if m.startswith(("gemini", "google")):
        return settings.gemini_api_key
    if m.startswith(("claude", "anthropic")):
        return settings.anthropic_api_key
    if m.startswith(("gpt", "openai", "o1", "o3", "o4")):
        return settings.openai_api_key
    # unknown provider — don't block it, just try
    return "__unknown__"


def _build_chain() -> list[str]:
    """Ordered, de-duplicated list of models to attempt."""
    chain: list[str] = []

    def add(model: str) -> None:
        model = (model or "").strip()
        if model and model not in chain:
            chain.append(model)

    # 1) your chosen primary
    add(settings.llm_model)

    # 2) explicit fallbacks from .env (comma-separated), if provided
    for m in (settings.llm_fallback_models or "").split(","):
        add(m)

    # 3) auto-add any other cloud provider you have a key for
    if settings.gemini_api_key:
        add("gemini/gemini-1.5-flash")
    if settings.anthropic_api_key:
        add("claude-3-5-sonnet-latest")
    if settings.openai_api_key:
        add("gpt-4o-mini")

    # 4) always finish with local Ollama (free, offline)
    add(settings.ollama_model)

    # keep only models we can actually authenticate (or that need no key)
    usable = [m for m in chain if _provider_key(m)]
    return usable


class LLM:
    def __init__(self) -> None:
        _ensure_env()
        self.chain = _build_chain()
        self.model = self.chain[0] if self.chain else settings.llm_model

    def complete(self, messages: list[dict]) -> str:
        """Try each model in the chain until one returns a reply."""
        from litellm import completion

        errors: list[str] = []
        for model in self.chain:
            kwargs = dict(model=model, messages=messages, temperature=0.4)
            if model.lower().startswith("ollama/"):
                kwargs["api_base"] = settings.ollama_base_url
            try:
                resp = completion(**kwargs)
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    if model != self.chain[0]:
                        log.info("Answered via fallback model '%s'.", model)
                    return text
                errors.append(f"{model}: empty reply")
            except Exception as e:  # noqa: BLE001
                log.warning("Model '%s' failed: %s", model, e)
                errors.append(f"{model}: {e}")

        detail = " | ".join(errors) if errors else "no models configured"
        return (
            "[REYES could not reach any model. Tried: " + detail + ". "
            "Add a working API key in .env, or install & run Ollama "
            "(ollama.com), then: ollama pull llama3]"
        )
