"""Semantic intent router (#3): classification logic, graceful degradation, and
the guarded regex-first / semantic-fallback wiring in the capability router.

A deterministic bag-of-words encoder is injected so these run in milliseconds
without loading the real sentence-transformer.
"""

from __future__ import annotations

import numpy as np
import pytest

from reyes_agent.routing.intent_router import IntentRouter, Route


def _bow(texts, dim=512):
    """Stable bag-of-words vectors -- lexical overlap stands in for semantics."""
    out = []
    for t in texts:
        v = np.zeros(dim, dtype=float)
        for w in str(t).lower().split():
            v[sum(ord(c) for c in w) % dim] += 1.0
        out.append(v)
    return out


_ROUTES = (
    Route("open_app", "desktop", ("open chrome", "launch spotify", "start notepad")),
    Route("play_media", "desktop", ("play music", "pause song", "skip track")),
    Route("where_is", "spatial", ("where is my laptop", "find my phone")),
)


@pytest.fixture()
def router(monkeypatch):
    monkeypatch.setenv("ZENO_INTENT_ROUTER", "auto")
    return IntentRouter(_ROUTES, encoder=_bow)


def test_classifies_by_overlap(router):
    assert router.classify("open chrome now").intent == "open_app"
    assert router.classify("play music please").intent == "play_media"
    assert router.classify("where is my laptop").intent == "where_is"


def test_maps_to_a_capability(router):
    assert router.classify("launch spotify").capability == "desktop"
    assert router.suggest_capability("find my phone") == "spatial"


def test_unrelated_message_matches_nothing(router):
    assert router.classify("banana helicopter velvet") is None
    assert router.suggest_capability("banana helicopter velvet") == ""


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ZENO_INTENT_ROUTER", "off")
    r = IntentRouter(_ROUTES, encoder=_bow)
    assert r.available() is False
    assert r.classify("open chrome") is None


def test_a_broken_encoder_degrades_to_none(monkeypatch):
    monkeypatch.setenv("ZENO_INTENT_ROUTER", "auto")

    def boom(_texts):
        raise RuntimeError("encoder exploded")
    r = IntentRouter(_ROUTES, encoder=boom)
    # build fails -> unavailable, classify None. Never raises.
    assert r.available() is False
    assert r.classify("open chrome") is None


def test_threshold_is_respected(monkeypatch):
    monkeypatch.setenv("ZENO_INTENT_ROUTER", "auto")
    strict = (Route("open_app", "desktop", ("open chrome",), threshold=0.99),)
    r = IntentRouter(strict, encoder=_bow)
    # partial overlap can't clear a 0.99 bar
    assert r.classify("please open the settings") is None


# --- the regex-first / semantic-fallback wiring in tools_for ----------------
def test_tools_for_uses_the_semantic_fallback_only_when_regex_finds_nothing(monkeypatch):
    from reyes_agent.routing import capability, intent_router

    # Force the regex classifier to find nothing, so the fallback should run.
    monkeypatch.setattr(capability, "classify", lambda m: ((), 0.0, "no trigger"))

    class _Stub:
        def classify(self, message):
            from reyes_agent.routing.intent_router import IntentMatch
            return IntentMatch("open_app", "desktop", 0.7)
    monkeypatch.setattr(intent_router, "get_intent_router", lambda: _Stub())

    route = capability.tools_for("mystery phrasing the triggers miss")
    assert "desktop" in route.capabilities
    assert "semantic:open_app" in route.reason


def test_tools_for_skips_the_fallback_when_regex_already_matched(monkeypatch):
    from reyes_agent.routing import capability, intent_router

    monkeypatch.setattr(capability, "classify",
                        lambda m: (("desktop",), 0.9, "trigger"))
    called = {"n": 0}

    class _Stub:
        def classify(self, message):
            called["n"] += 1
            return None
    monkeypatch.setattr(intent_router, "get_intent_router", lambda: _Stub())

    capability.tools_for("open chrome")
    assert called["n"] == 0, "the 63ms embed must NOT run when regex already matched"


def test_content_tools_are_routable_via_files_capability():
    import reyes_agent.tools.system  # noqa: F401 -- registers content tools
    from reyes_agent.routing.capability import CAPABILITIES
    assert "content_open" in CAPABILITIES["files"]
