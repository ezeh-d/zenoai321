"""The realtime engine wired into the live turn/decision layer:
- continuity rejects bare backchannels and flags syntactically-incomplete turns
- the turn processor feeds the latency recorder
Deterministic; no model, no audio hardware."""

from __future__ import annotations

import time

import pytest

from reyes_agent.voice import continuity as c
from reyes_agent.conversation.latency_metrics import get_latency_recorder


@pytest.fixture(autouse=True)
def _reset():
    c.close("test")
    yield
    c.close("test")


# --- semantic turn detection on the decision --------------------------------
def test_incomplete_turn_is_flagged():
    assert c.consider("open spotify and", wake_matched=True).incomplete is True
    assert c.consider("put it next to", wake_matched=True).incomplete is True


def test_complete_turn_is_not_flagged():
    assert c.consider("open spotify", wake_matched=True).incomplete is False
    assert c.consider("what's using my ram", wake_matched=True).incomplete is False


# --- backchannel rejection inside an open window ----------------------------
def test_bare_backchannel_is_not_answered():
    c.open_window(source="test")
    d = c.consider("okay", wake_matched=False)
    assert d.accept is False and "backchannel" in d.reason


def test_real_followup_is_answered():
    c.open_window(source="test")
    d = c.consider("open chrome now", wake_matched=False)
    assert d.accept is True


def test_wake_word_always_wins_even_if_backchannelish():
    # a named address is never rejected as a backchannel
    d = c.consider("okay", wake_matched=True)
    assert d.accept is True


# --- latency recorder is fed --------------------------------------------------
def test_record_latency_helper_feeds_the_recorder():
    from reyes_agent import web
    rec = get_latency_recorder()
    rec.reset()
    web._record_latency("full_task", time.perf_counter() - 0.02)
    p = rec.percentiles("full_task")
    assert p["count"] == 1 and p["p50"] >= 0


def test_conversation_turn_is_instrumented():
    # structural: the turn processor records the full-task span
    import inspect
    from reyes_agent import web
    src = inspect.getsource(web._conversation_turn)
    assert "_record_latency(\"full_task\"" in src or "_record_latency('full_task'" in src
