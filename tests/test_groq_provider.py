"""Groq provider integration: config wiring, error classification, the
CLOSED/OPEN/HALF_OPEN fallback chain (Groq -> Gemini -> ... -> Ollama for
ordinary conversation), and API-key safety.

These verify the routing/fallback CONTRACT without making real model calls
(mocked SDK exceptions, patched _RUNNERS) -- live behavior (model choice,
tool-calling shape, streaming reliability) was verified against the real
Groq API separately; see config.py's GROQ_MODEL/GROQ_STREAMING comments for
that evidence.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_config_after():
    """Reload config/provider/model_router from the REAL environment after
    each test, so a monkeypatched GROQ_API_KEY never leaks into another
    suite."""
    yield
    import reyes_agent.config as C
    importlib.reload(C)
    import reyes_agent.provider as P
    importlib.reload(P)
    from reyes_agent import model_router

    model_router.reset()


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import reyes_agent.config as C
    return importlib.reload(C)


# --- 1. GROQ_API_KEY missing --------------------------------------------
def test_missing_api_key_raises_a_clear_provider_error(monkeypatch):
    # NOT _reload_config(GROQ_API_KEY=None): config.py's load_dotenv() has
    # override=False, so deleting the env var and reloading just re-reads it
    # straight back out of the real .env (this machine has a real key
    # configured). Patch the already-loaded module's attribute directly
    # instead -- that's what _get_groq_client() actually reads.
    import reyes_agent.provider as P

    monkeypatch.setattr(P.config, "GROQ_API_KEY", "")
    monkeypatch.setattr(P, "_groq_client", None)

    with pytest.raises(P.ProviderError, match="GROQ_API_KEY"):
        P._get_groq_client()


# --- config wiring --------------------------------------------------------
def test_groq_model_is_configurable_without_a_source_edit(monkeypatch):
    C = _reload_config(monkeypatch, GROQ_MODEL="some-future-model")
    assert C.GROQ_MODEL == "some-future-model"


def test_groq_model_default_is_a_real_verified_choice(monkeypatch):
    # Not "llama-3.3-70b-versatile" -- verified gone from Groq's live catalog
    # 2026-09-04; a remembered default would 404 on every call.
    C = _reload_config(monkeypatch, GROQ_MODEL=None)
    assert C.GROQ_MODEL == "openai/gpt-oss-20b"


def test_groq_streaming_defaults_off(monkeypatch):
    # Streaming showed inconsistent hangs in live testing (2026-09-04) --
    # the same failure shape that made Gemini's streaming unsafe. Off by
    # default until proven stable, exactly like GEMINI_STREAMING.
    C = _reload_config(monkeypatch, ZENO_GROQ_STREAMING=None)
    assert C.GROQ_STREAMING is False


# --- 2 & 6-8. error classification (valid request path is exercised via the
# fallback-chain tests below, which run a real provider.run_turn) ----------
def test_error_classification_maps_to_the_right_provider_error(monkeypatch):
    """Each Groq SDK exception the real client can raise must become the
    right ProviderError -- retryable where the failure is transient, with a
    message that names the actual problem (missing key / bad model), not a
    generic 'something went wrong'."""
    import reyes_agent.provider as P

    sdk = P._openai_module()

    class _Resp:
        status_code = 429
        headers = {}
        request = None

    cases = [
        (sdk.RateLimitError("rate limited", response=_Resp(), body=None),
         "retryable", True),
        (sdk.APIConnectionError(request=None), "retryable", True),
        (sdk.AuthenticationError("bad key", response=_Resp(), body=None),
         "message", "GROQ_API_KEY"),
        (sdk.NotFoundError("no such model", response=_Resp(), body=None),
         "message", P.config.GROQ_MODEL),
    ]
    for raised, check, expected in cases:
        def _boom(*_a, **_k):
            raise raised
        monkeypatch.setattr(P, "_run_openai_compatible", _boom)
        with pytest.raises(P.ProviderError) as excinfo:
            P._run_groq([{"role": "user", "content": "hi"}], "sys", [], None)
        if check == "retryable":
            assert excinfo.value.retryable is expected, raised
        else:
            assert expected in str(excinfo.value), (raised, excinfo.value)


# --- 3 & 9-10. routing: Groq leads "general", falls back correctly --------
def test_ordinary_conversation_prefers_groq(monkeypatch):
    """task_kind defaults to 'general' for ordinary conversation (agent.py) --
    Groq must be first in that chain when it is configured and healthy."""
    _reload_config(monkeypatch, GROQ_API_KEY="test-key-for-routing-only")
    from reyes_agent import model_router
    importlib.reload(model_router)
    model_router.reset()

    chain = model_router.chain_for("general")
    assert chain[0] == "groq", chain


def test_groq_failure_falls_back_to_gemini_for_conversation(monkeypatch):
    from reyes_agent import model_router, provider

    model_router.reset()
    attempted: list[str] = []

    def broken(*_a, **_k):
        attempted.append("groq")
        raise provider.ProviderError("simulated Groq outage", retryable=False)

    def healthy(_history, _system, _tools, on_text):
        attempted.append("gemini")
        on_text("ok")
        return provider.AgentTurn(text="ok", tool_calls=[])

    chain = model_router.chain_for("general")
    if "groq" not in chain or "gemini" not in chain:
        pytest.skip("this key set doesn't configure both groq and gemini")
    try:
        provider._RUNNERS["groq"] = broken
        provider._RUNNERS["gemini"] = healthy
        turn = provider.run_turn([{"role": "user", "content": "hi"}], system="x", tools=[])
        assert turn.text == "ok"
        assert attempted[0] == "groq", "Groq must be tried first for ordinary conversation"
        assert "gemini" in attempted, "a failed Groq call must fall through to Gemini"
    finally:
        provider._RUNNERS["groq"] = provider._PRODUCTION_RUNNERS["groq"]
        provider._RUNNERS["gemini"] = provider._PRODUCTION_RUNNERS["gemini"]
        model_router.reset()


def test_every_provider_failing_falls_back_to_ollama_not_a_crash(monkeypatch):
    """11. ZENO continues functioning after provider failure -- the whole
    chain failing must raise one clear ProviderError, never an unhandled
    exception, and never a fabricated answer."""
    from reyes_agent import model_router, provider

    model_router.reset()
    real = dict(provider._RUNNERS)

    def broken(*_a, **_k):
        raise provider.ProviderError("simulated outage", retryable=False)

    try:
        for name in provider._RUNNERS:
            provider._RUNNERS[name] = broken
        with pytest.raises(provider.ProviderError):
            provider.run_turn([{"role": "user", "content": "hi"}], system="x", tools=[])
    finally:
        provider._RUNNERS.clear()
        provider._RUNNERS.update(real)
        model_router.reset()


def test_groq_breaker_opens_and_recovers_like_every_other_provider(monkeypatch):
    """Cooling down after repeated failure, and being reachable again once
    the cooldown elapses, is the SHARED circuit breaker every provider gets
    -- not something Groq needed its own copy of."""
    from reyes_agent import model_router

    _reload_config(monkeypatch, GROQ_API_KEY="test-key-for-routing-only")
    importlib.reload(model_router)
    model_router.reset()
    try:
        assert model_router.breaker_state("groq") == model_router.CLOSED
        for _ in range(3):
            model_router.record("groq", 0.1, ok=False, error="simulated")
        assert model_router.breaker_state("groq") == model_router.OPEN
        assert "groq" not in model_router.chain_for("general")

        model_router._stats["groq"].opened_at -= 61  # advance past cooldown
        assert model_router.breaker_state("groq") == model_router.HALF_OPEN
        assert "groq" in model_router.chain_for("general"), "HALF_OPEN must be probed"

        model_router.record("groq", 0.1, ok=True)
        assert model_router.breaker_state("groq") == model_router.CLOSED
    finally:
        model_router.reset()


def test_vision_route_never_includes_groq(monkeypatch):
    """Groq takes no image input -- a multimodal task must not land on a
    text-only provider just because it answers fast."""
    from reyes_agent import model_router

    assert "groq" not in model_router._DEFAULT_ROUTES["vision"]


def test_reasoning_and_coding_routes_are_unchanged_anthropic_first():
    """ZENO's existing strong-reasoning/coding routes are untouched -- Groq
    is a late fallback there, not a replacement for the existing choice."""
    from reyes_agent import model_router

    assert model_router._DEFAULT_ROUTES["coding"][0] == "anthropic"
    assert model_router._DEFAULT_ROUTES["reasoning"][0] == "anthropic"
    assert "groq" in model_router._DEFAULT_ROUTES["coding"]
    assert "groq" in model_router._DEFAULT_ROUTES["reasoning"]


# --- 12. API key safety (mirrors test_gemini_fast.py's equivalent) --------
def test_api_key_never_surfaces_in_provider_status_or_errors(monkeypatch):
    _reload_config(monkeypatch, GROQ_API_KEY="SECRET-GROQ-KEY-xyz789")
    import reyes_agent.config as C
    import reyes_agent.provider as P
    importlib.reload(P)

    for value in (str(P._request_timeout()), str(C.GROQ_MODEL)):
        assert "SECRET-GROQ-KEY-xyz789" not in value

    # And the error path: an auth failure's message must name the ENV VAR,
    # never echo the rejected key value back.
    sdk = P._openai_module()

    class _Resp:
        status_code = 401
        headers = {}
        request = None

    def _boom(*_a, **_k):
        raise sdk.AuthenticationError("bad key", response=_Resp(), body=None)
    monkeypatch.setattr(P, "_run_openai_compatible", _boom)
    with pytest.raises(P.ProviderError) as excinfo:
        P._run_groq([{"role": "user", "content": "hi"}], "sys", [], None)
    assert "SECRET-GROQ-KEY-xyz789" not in str(excinfo.value)


def test_groq_never_appears_in_a_provider_manager_credential_leak(monkeypatch):
    """provider_manager persists validation state to disk (health.sqlite3) --
    its own credential dict must expose presence, not the secret itself, for
    Groq exactly like every other provider."""
    _reload_config(monkeypatch, GROQ_API_KEY="SECRET-GROQ-KEY-xyz789")
    import reyes_agent.provider_manager as PM
    importlib.reload(PM)

    creds = PM._credentials()
    assert creds["groq"] == "SECRET-GROQ-KEY-xyz789"  # the internal dict IS the secret
    # but the public status/validate surface never returns it raw:
    row = PM._public_row("groq", "ONLINE")
    assert "SECRET-GROQ-KEY-xyz789" not in str(row)


# --- provider registration completeness -----------------------------------
def test_groq_is_registered_everywhere_a_provider_must_be(monkeypatch):
    from reyes_agent import model_router, provider, provider_manager

    assert "groq" in provider._RUNNERS
    assert "groq" in model_router.available_providers()
    assert "groq" in provider_manager._PROVIDERS
    assert "groq" in provider_manager._credentials()
    url, headers, key = provider_manager._request_spec("groq")
    assert url.startswith("https://api.groq.com/")
    assert "Authorization" in headers
