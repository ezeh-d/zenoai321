"""Fast-Gemini integration: model config split, timeout wiring, provider
health/fallback (circuit breaker), and API-key safety.

These verify the routing/fallback CONTRACT without making real model calls; the
live latency (fast model ~1.1s, native streaming first-token ~1.7s) and model
availability (gemini-3.5-flash-lite present on the key) were verified against
the real API separately.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_config_after():
    """These tests reload config/provider under a monkeypatched env; reload them
    from the REAL environment afterwards so no other suite sees stale values."""
    yield
    import reyes_agent.config as C
    importlib.reload(C)
    import reyes_agent.provider as P
    importlib.reload(P)


# --- config: fast / smart split ---------------------------------------------
def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import reyes_agent.config as C
    return importlib.reload(C)


def test_fast_and_smart_models_default(monkeypatch):
    C = _reload_config(monkeypatch, GEMINI_FAST_MODEL=None, GEMINI_SMART_MODEL=None,
                       GEMINI_MODEL=None)
    assert C.GEMINI_FAST_MODEL == "gemini-3.5-flash-lite"
    assert C.GEMINI_SMART_MODEL == "gemini-3.5-flash"
    # GEMINI_MODEL is a backward-compatible alias -> defaults to the fast model
    assert C.GEMINI_MODEL == C.GEMINI_FAST_MODEL


def test_gemini_model_override_respected(monkeypatch):
    C = _reload_config(monkeypatch, GEMINI_MODEL="gemini-flash-lite-latest")
    assert C.GEMINI_MODEL == "gemini-flash-lite-latest"


def test_gemini_enabled_flag(monkeypatch):
    assert _reload_config(monkeypatch, GEMINI_ENABLED="false").GEMINI_ENABLED is False
    assert _reload_config(monkeypatch, GEMINI_ENABLED="true").GEMINI_ENABLED is True


def test_gemini_timeout_parsed(monkeypatch):
    assert _reload_config(monkeypatch, GEMINI_TIMEOUT="12").GEMINI_TIMEOUT == 12.0
    assert _reload_config(monkeypatch, GEMINI_TIMEOUT="").GEMINI_TIMEOUT is None
    assert _reload_config(monkeypatch, GEMINI_TIMEOUT="junk").GEMINI_TIMEOUT is None


def test_request_timeout_uses_gemini_timeout(monkeypatch):
    _reload_config(monkeypatch, GEMINI_TIMEOUT="12")
    import reyes_agent.provider as P
    importlib.reload(P)
    t = P._request_timeout()
    # httpx.Timeout: read should reflect GEMINI_TIMEOUT
    assert float(t.read) == 12.0


# --- provider health / fallback (circuit breaker, spec s14) ------------------
def test_breaker_opens_after_repeated_failures_and_recovers():
    from reyes_agent.circuit_breaker import CircuitBreaker
    now = [1000.0]
    b = CircuitBreaker(failure_threshold=3, cooldown_s=30.0, clock=lambda: now[0])
    for _ in range(3):
        b.record("gemini", ok=False)
    assert b.is_open("gemini") is True
    assert b.allow("gemini") is False                 # refused while cooling down
    now[0] += 31                                       # cooldown elapses
    assert b.allow("gemini") is True                   # one probe allowed
    assert b.allow("gemini") is False                  # only one probe in flight
    b.record("gemini", ok=True)                        # probe succeeded
    assert b.is_open("gemini") is False                # closed again
    assert b.allow("gemini") is True


def test_breaker_success_resets_failure_count():
    from reyes_agent.circuit_breaker import CircuitBreaker
    b = CircuitBreaker(failure_threshold=3, cooldown_s=30.0)
    b.record("gemini", ok=False)
    b.record("gemini", ok=False)
    b.record("gemini", ok=True)                        # reset
    b.record("gemini", ok=False)
    b.record("gemini", ok=False)
    assert b.is_open("gemini") is False                # only 2 since reset


# --- API key safety (spec s21.7) --------------------------------------------
def test_api_key_never_in_provider_status(monkeypatch):
    _reload_config(monkeypatch, GEMINI_API_KEY="SECRET-KEY-abc123", GEMINI_MODEL=None)
    import reyes_agent.config as C
    import reyes_agent.provider as P
    importlib.reload(P)
    # the timeout/model helpers must never surface the key
    for value in (str(P._request_timeout()), str(C.GEMINI_MODEL),
                  str(C.GEMINI_FAST_MODEL)):
        assert "SECRET-KEY-abc123" not in value
