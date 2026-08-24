"""Contracts for Pack 10 everyday cores: notifications, while-away, safety."""

from __future__ import annotations

from reyes_agent import trace_engine as te
from reyes_agent.everyday import notifications as nb
from reyes_agent.everyday import safety as sf
from reyes_agent.everyday.notifications import Notification, NotificationIntelligenceEngine
from reyes_agent.everyday.while_away import WhileYouWereAwayEngine


# --- notifications ----------------------------------------------------------
def test_classification_by_content():
    assert nb.classify(Notification("1", "bank", "Security alert", "unauthorized login")) == nb.CRITICAL
    assert nb.classify(Notification("2", "mail", "Please reply", "action required")) == nb.ACTION_REQUIRED
    assert nb.classify(Notification("3", "cal", "Team meeting", "at 2pm")) == nb.IMPORTANT
    assert nb.classify(Notification("4", "shop", "Big sale", "50% promo")) == nb.LOW_PRIORITY
    assert nb.classify(Notification("5", "misc", "hello", "just a note")) == nb.INFORMATIONAL


def test_muted_source():
    assert nb.classify(Notification("1", "spam", "Anything"), muted_sources={"spam"}) == nb.MUTED


def test_ingest_dedupes_same_and_similar():
    eng = NotificationIntelligenceEngine()
    assert eng.ingest(Notification("a", "news", "OpenAI ships model", "today", 1.0))
    assert eng.ingest(Notification("b", "app", "OpenAI ships model", "today", 2.0)) == ""   # similar
    assert len(eng.visible()) == 1


def test_quiet_state_lets_only_critical_through():
    eng = NotificationIntelligenceEngine()
    eng.ingest(Notification("a", "bank", "Fraud alert", "urgent", 3.0))
    eng.ingest(Notification("b", "cal", "Team meeting", "later", 2.0))
    eng.set_quiet("MEETING")
    vis = eng.visible()
    assert len(vis) == 1 and vis[0].category == nb.CRITICAL


def test_visible_sorted_by_priority_and_digest():
    eng = NotificationIntelligenceEngine()
    eng.ingest(Notification("a", "shop", "Sale", "promo", 5.0))
    eng.ingest(Notification("b", "bank", "Security alert", "fraud", 4.0))
    eng.ingest(Notification("c", "mail", "Please approve", "action required", 3.0))
    order = [n.category for n in eng.visible()]
    assert order[0] == nb.CRITICAL and order[1] == nb.ACTION_REQUIRED
    d = eng.digest()
    assert d["total"] == 3 and d["needs_attention"] == 2 and d["top"]


# --- while away -------------------------------------------------------------
def test_while_away_filters_noise_and_highlights_security():
    eng = te.UniversalTraceEngine()
    eng.record(te.DEVICE, "heartbeat", timestamp=10.0, event_id="d1", status="ok")   # noise
    eng.record(te.EMAIL, "received", timestamp=20.0, event_id="e1", source="gmail")
    eng.record(te.SECURITY, "new_login", timestamp=30.0, event_id="s1", status="alert")
    eng.record(te.CALL, "missed", timestamp=25.0, event_id="c1", source="phone")
    away = WhileYouWereAwayEngine(eng)
    r = away.recap(since=0.0)
    assert r["total_events"] == 4 and r["meaningful"] == 3          # heartbeat dropped
    assert te.EMAIL in r["by_category"] and te.DEVICE not in r["by_category"]
    assert r["highlights"][0]["category"] == te.SECURITY           # security first


def test_while_away_notable_device_status_included():
    eng = te.UniversalTraceEngine()
    eng.record(te.DEVICE, "state", timestamp=10.0, event_id="d1", status="offline")
    r = WhileYouWereAwayEngine(eng).recap(since=0.0)
    assert r["meaningful"] == 1        # a real state change surfaces


def test_while_away_empty_is_honest():
    eng = te.UniversalTraceEngine()
    r = WhileYouWereAwayEngine(eng).recap(since=0.0)
    assert r["meaningful"] == 0 and "Nothing notable" in r["note"]
    assert "Nothing notable" in WhileYouWereAwayEngine(eng).summary_line(0.0)


def test_while_away_summary_line():
    eng = te.UniversalTraceEngine()
    eng.record(te.EMAIL, "recv", timestamp=1.0, event_id="e1")
    eng.record(te.EMAIL, "recv", timestamp=2.0, event_id="e2")
    line = WhileYouWereAwayEngine(eng).summary_line(0.0)
    assert "2 email" in line


# --- safety -----------------------------------------------------------------
def test_action_risk_levels():
    assert sf.classify_action("enter my password and pay the invoice") == sf.SENSITIVE
    assert sf.classify_action("delete the whole folder") == sf.HIGH
    assert sf.classify_action("send Ayo a message") == sf.MODERATE
    assert sf.classify_action("open the report and read it") == sf.LOW


def test_confirmation_policy():
    assert sf.requires_confirmation(sf.LOW) is False
    for r in (sf.MODERATE, sf.HIGH, sf.SENSITIVE):
        assert sf.requires_confirmation(r) is True


def test_detect_secrets():
    assert sf.detect_sensitive("my api key is sk-ABCDEFGH1234567890")["found"]
    assert "private_key" in sf.detect_sensitive("-----BEGIN RSA PRIVATE KEY-----")["kinds"]
    assert sf.detect_sensitive("password: hunter2secret")["found"]
    assert sf.detect_sensitive("your otp is 483920")["found"]
    assert not sf.detect_sensitive("just some ordinary sentence")["found"]


def test_safe_to_persist():
    assert sf.safe_to_persist("remember to buy milk") is True
    assert sf.safe_to_persist("token=eyJhbGciOiJIUzI1Nitest.payloadpart.signaturepart") is False
