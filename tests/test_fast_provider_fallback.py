"""A ready fallback should not wait behind repeated failed requests."""
from reyes_agent import model_router, provider


def test_available_fallback_is_tried_without_retry_delay(monkeypatch):
    calls = []
    monkeypatch.setattr(model_router, "chain_for", lambda kind: ["groq", "gemini"])
    monkeypatch.setattr(model_router, "record", lambda *a, **kw: None)

    def limited(*args):
        calls.append("groq")
        raise provider.ProviderError("rate limited", retryable=True)

    def available(*args):
        calls.append("gemini")
        return provider.AgentTurn(text="Ready")

    monkeypatch.setitem(provider._RUNNERS, "groq", limited)
    monkeypatch.setitem(provider._RUNNERS, "gemini", available)
    monkeypatch.setattr(provider.time, "sleep", lambda delay: None)
    result = provider.run_turn([{"role": "user", "content": "Hello"}])
    assert result.text == "Ready"
    assert calls == ["groq", "gemini"]


def test_partial_output_never_restarts_on_fallback(monkeypatch):
    import pytest
    calls = []
    monkeypatch.setattr(model_router, "chain_for", lambda kind: ["groq", "gemini"])
    monkeypatch.setattr(model_router, "record", lambda *a, **kw: None)

    def partial(history, system, tools, on_text):
        on_text("Hello")
        raise provider.ProviderError("connection lost", retryable=True)

    monkeypatch.setitem(provider._RUNNERS, "groq", partial)
    monkeypatch.setitem(provider._RUNNERS, "gemini", lambda *args: calls.append("gemini"))
    with pytest.raises(provider.ProviderError, match="connection lost"):
        provider.run_turn([{"role": "user", "content": "Hello"}])
    assert calls == []
