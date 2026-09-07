"""Startup must not spend cloud inference quota while the owner is idle."""
from types import SimpleNamespace
from unittest.mock import Mock

from reyes_agent import config, provider, scheduler, warmup


def test_cloud_preload_is_one_shot_and_network_free(monkeypatch):
    jobs = []
    monkeypatch.setattr(config, "MODEL_PROVIDER", "gemini")
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: SimpleNamespace(
        schedule=lambda name, fn, **kw: jobs.append((fn, kw))))
    preload = Mock(return_value={})
    monkeypatch.setattr(provider, "warm", preload)
    inference = Mock(side_effect=AssertionError("Startup attempted inference"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=inference)))
    monkeypatch.setattr(provider, "_get_gemini_client", lambda: client)
    warmup.start_background_keepalive()
    assert len(jobs) == 1
    fn, options = jobs[0]
    assert options.get("interval") is None
    fn()
    preload.assert_called_once()
    inference.assert_not_called()


def test_ollama_keepalive_closes_client_even_on_failure(monkeypatch):
    import openai
    client = Mock()
    client.chat.completions.create.side_effect = RuntimeError("offline")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    warmup._ping()
    client.close.assert_called_once()
