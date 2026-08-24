"""The everyday front-door composes existing engines and declares honest truth."""

from __future__ import annotations

from reyes_agent.everyday.engine import EverydayIntelligenceEngine

NOW = 2_000_000.0


def test_capability_report_is_honest():
    eng = EverydayIntelligenceEngine()
    report = {r["capability"]: r["available"] for r in eng.capability_report()}
    # Built pure-logic features are AVAILABLE...
    assert report["everyday.notifications"] is True
    assert report["everyday.personal_search"] is True
    # ...provider/hardware ones are honestly NOT available yet.
    assert report["everyday.smart_home"] is False
    assert report["everyday.location.owner_phone"] is False


def test_status_composes_sections():
    st = EverydayIntelligenceEngine().status(now=NOW)
    assert "notifications" in st and "while_away" in st and "capabilities" in st
    assert isinstance(st["while_away"], dict)


def test_verify_action_reuses_action_verifier():
    eng = EverydayIntelligenceEngine()
    v = eng.verify_action("send_message", {}, {"ok": True, "evidence": "message id 7"})
    assert v["verified"] is True and v["method"] == "evidence"


def test_record_evidence_reuses_ledger():
    eng = EverydayIntelligenceEngine()
    ev = eng.record_evidence("send email", "gmail:divine", "message id 9", "VERIFIED", now=NOW)
    assert ev.get("action") == "send email" and ev.get("verification") == "VERIFIED"
