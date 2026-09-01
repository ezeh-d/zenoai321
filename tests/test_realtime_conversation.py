"""Realtime turn-taking: semantic turn detection, partial-intent safety gate,
backchannel classification, micro-acks, latency percentiles. Deterministic."""

from __future__ import annotations

import pytest

from reyes_agent.conversation import realtime as rt
from reyes_agent.conversation.realtime import (
    BACKCHANNEL, CORRECTION, INTERRUPT, NEW_COMMAND, STOP,
    BackchannelDetector, MicroAck, PartialIntentEngine,
)
from reyes_agent.conversation.latency_metrics import LatencyRecorder


@pytest.fixture(autouse=True)
def _fast_router(monkeypatch):
    """Default: no real model in these logic tests. A test that needs a match
    overrides this with its own stub."""
    import reyes_agent.routing.intent_router as ir
    monkeypatch.setattr(ir, "get_intent_router",
                        lambda: type("R", (), {"classify": lambda self, t: None})())


# --- semantic turn detection ------------------------------------------------
def test_dangling_conjunction_is_incomplete():
    assert rt.is_turn_complete("open spotify and")["complete"] is False
    assert rt.is_turn_complete("put it next to")["complete"] is False


def test_terminal_and_syntactic_completeness():
    assert rt.is_turn_complete("open spotify.")["complete"] is True
    assert rt.is_turn_complete("what's using my ram")["complete"] is True


def test_hesitation_is_incomplete():
    assert rt.is_turn_complete("the file is um")["complete"] is False


# --- partial intent + safety gate -------------------------------------------
def test_partial_never_executes():
    p = PartialIntentEngine().consider("open spot")
    assert p.execute is False


def test_dangerous_partial_is_not_prepared():
    # "delete the..." must not be prepared on speculation
    p = PartialIntentEngine().consider("delete the old rep")
    assert p.safe_to_prepare is False and p.prepare == [] and p.execute is False


def test_safe_partial_can_warm_a_handler(monkeypatch):
    # stub the intent router so this is deterministic + model-free
    class _Match:
        intent, capability, confidence = "open_app", "desktop", 0.8
    monkeypatch.setattr(rt, "get_intent_router",
                        lambda: type("R", (), {"classify": lambda self, t: _Match()})(),
                        raising=False)
    import reyes_agent.routing.intent_router as ir
    monkeypatch.setattr(ir, "get_intent_router",
                        lambda: type("R", (), {"classify": lambda self, t: _Match()})())
    p = PartialIntentEngine().consider("open spot")
    assert p.safe_to_prepare is True and p.execute is False
    assert any(x.startswith("warm_capability:desktop") for x in p.prepare)


# --- backchannel / interruption ---------------------------------------------
def test_backchannel_while_speaking_is_not_a_command():
    d = BackchannelDetector()
    r = d.classify("mhm", zeno_speaking=True)
    assert r["type"] == BACKCHANNEL and r["act"] is False


def test_stop_is_always_acted_on():
    d = BackchannelDetector()
    assert d.classify("wait", zeno_speaking=True)["type"] == STOP
    assert d.classify("stop", zeno_speaking=False)["type"] == STOP


def test_correction_is_detected():
    d = BackchannelDetector()
    assert d.classify("no, the other one", zeno_speaking=True)["type"] == CORRECTION
    assert d.classify("actually use the newer one")["type"] == CORRECTION


def test_talking_over_zeno_is_an_interrupt():
    d = BackchannelDetector()
    r = d.classify("show me page five", zeno_speaking=True)
    assert r["type"] == INTERRUPT and r["act"] is True


def test_substantive_utterance_when_idle_is_a_command():
    d = BackchannelDetector()
    assert d.classify("open chrome", zeno_speaking=False)["type"] == NEW_COMMAND


# --- micro-acknowledgements -------------------------------------------------
def test_micro_ack_does_not_repeat_back_to_back():
    m = MicroAck()
    seen = [m.pick("ack") for _ in range(4)]
    assert len(set(seen)) > 1                     # varies
    assert all(s for s in seen)                   # non-empty when no visual


def test_micro_ack_is_silent_when_a_visual_shows():
    assert MicroAck().pick("ack", visual_shown=True) == ""


# --- latency percentiles ----------------------------------------------------
def test_latency_percentiles():
    r = LatencyRecorder()
    for v in range(1, 101):          # 1..100 ms
        r.record("intent", v)
    p = r.percentiles("intent")
    assert p["count"] == 100
    assert 49 <= p["p50"] <= 52 and 94 <= p["p95"] <= 96 and p["p99"] >= 98


def test_latency_ignores_junk_and_reports_empty():
    r = LatencyRecorder()
    r.record("intent", -5); r.record("intent", float("nan")); r.record("intent", "x")
    assert r.percentiles("intent")["count"] == 0


def test_latency_timer_records_a_span():
    r = LatencyRecorder()
    with r.timer("tool_start"):
        pass
    assert r.percentiles("tool_start")["count"] == 1
