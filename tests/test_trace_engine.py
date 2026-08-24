"""Contracts for the universal trace engine, evidence ledger, and asset registry."""

from __future__ import annotations

from reyes_agent import connected_assets as ca
from reyes_agent import trace_engine as te


# --- trace engine -----------------------------------------------------------
def test_record_and_query():
    eng = te.UniversalTraceEngine()
    eng.record(te.EMAIL, "message_received", timestamp=100.0, event_id="e1",
               account_id="gmail:divine", status="ok")
    got = eng.query(category=te.EMAIL)
    assert len(got) == 1 and got[0]["account_id"] == "gmail:divine"


def test_deduplicates_same_event_id():
    eng = te.UniversalTraceEngine()
    eng.record(te.EMAIL, "recv", timestamp=1.0, event_id="dup")
    eng.record(te.EMAIL, "recv", timestamp=1.0, event_id="dup")   # same event, two devices
    assert len(eng) == 1


def test_secrets_are_redacted_from_metadata():
    eng = te.UniversalTraceEngine()
    eng.record(te.ACCOUNT, "auth", timestamp=1.0, event_id="s1",
               metadata={"api_key": "sk-123", "note": "ok",
                         "nested": {"refresh_token": "rt-xyz", "user": "divine"}})
    md = eng.query(category=te.ACCOUNT)[0]["metadata"]
    assert md["api_key"] == "[REDACTED]" and md["note"] == "ok"
    assert md["nested"]["refresh_token"] == "[REDACTED]" and md["nested"]["user"] == "divine"


def test_timeline_is_chronological():
    eng = te.UniversalTraceEngine()
    eng.record(te.DEVICE, "b", timestamp=200.0, event_id="b")
    eng.record(te.DEVICE, "a", timestamp=100.0, event_id="a")
    tl = eng.timeline()
    assert [e["event_type"] for e in tl] == ["a", "b"]


def test_query_filters_and_search():
    eng = te.UniversalTraceEngine()
    eng.record(te.DEVICE, "hb", timestamp=100.0, event_id="d1", device_id="phone")
    eng.record(te.EMAIL, "recv", timestamp=110.0, event_id="e1", account_id="gmail")
    assert len(eng.query(device_id="phone")) == 1
    assert len(eng.query(since=105.0)) == 1
    assert len(eng.search("recv")) == 1
    assert eng.search("") == []


def test_delete_category_and_clear():
    eng = te.UniversalTraceEngine()
    eng.record(te.EMAIL, "x", timestamp=1.0, event_id="e1")
    eng.record(te.DEVICE, "y", timestamp=2.0, event_id="d1")
    assert eng.delete_category(te.EMAIL) == 1 and len(eng) == 1
    eng.clear()
    assert len(eng) == 0


def test_retention_bound_and_seen_set_consistency():
    eng = te.UniversalTraceEngine(max_events=3)
    for i in range(5):
        eng.record(te.SYSTEM, "e", timestamp=float(i), event_id=f"e{i}")
    assert len(eng) == 3
    # The oldest ids were evicted, so their ids can be reused (seen-set trimmed).
    assert eng.record(te.SYSTEM, "again", timestamp=9.0, event_id="e0") is not None


def test_record_never_raises_on_bad_input():
    eng = te.UniversalTraceEngine()
    assert eng.record(te.EMAIL, "x", timestamp=1.0, event_id="") is None
    assert eng.record("BOGUS_CAT", "x", timestamp=1.0, event_id="ok") is not None  # -> SYSTEM


# --- evidence ledger --------------------------------------------------------
def test_evidence_ledger_records_and_filters():
    ledger = te.EvidenceLedger()
    ledger.record("send email", "gmail:divine", "message id 42", "VERIFIED", timestamp=1.0)
    ledger.record("send slack", "slack:t21", "no ack", "FAILED", timestamp=2.0)
    assert len(ledger) == 2
    assert len(ledger.verified_only()) == 1
    assert ledger.for_account("gmail:divine")[0]["provider_result"] == "message id 42"


def test_evidence_ledger_redacts_secret_result():
    ledger = te.EvidenceLedger()
    ev = ledger.record("auth", "acct", "token=sk-secret", "VERIFIED", timestamp=1.0)
    assert ev.provider_result == "[REDACTED]"


# --- connected asset registry (capability truth) ----------------------------
def test_phone_can_expose_location_when_authorized():
    reg = ca.ConnectedAssetRegistry()
    reg.register("phone1", ca.PHONE, authorized=True, capabilities=["location", "battery"])
    assert reg.can_expose("phone1", "location") is True
    assert reg.can_expose("phone1", "battery") is True


def test_gmail_cannot_expose_location_ever():
    reg = ca.ConnectedAssetRegistry()
    # Even if a caller tries to declare 'location' on Gmail, it is dropped and refused.
    reg.register("gmail1", ca.GMAIL_ACCOUNT, authorized=True,
                 capabilities=["messages", "send", "location"])
    assert reg.can_expose("gmail1", "location") is False
    assert reg.can_expose("gmail1", "gps") is False
    assert reg.can_expose("gmail1", "messages") is True


def test_unauthorized_asset_exposes_nothing():
    reg = ca.ConnectedAssetRegistry()
    reg.register("phone2", ca.PHONE, authorized=False, capabilities=["location"])
    assert reg.can_expose("phone2", "location") is False


def test_dashboard_shows_cannot_expose():
    reg = ca.ConnectedAssetRegistry()
    reg.register("gmail1", ca.GMAIL_ACCOUNT, authorized=True, capabilities=["messages"])
    card = reg.get("gmail1")
    assert "location" in card["cannot_expose"] and "messages" in card["can_expose"]


def test_presence_health_and_forget():
    reg = ca.ConnectedAssetRegistry()
    reg.register("phone1", ca.PHONE, authorized=True)
    assert reg.update_presence("phone1", connection_status=ca.ONLINE, last_seen=123.0)
    assert reg.set_health("phone1", ca.DEGRADED)
    assert reg.get("phone1")["health"] == ca.DEGRADED
    assert reg.forget("phone1") and reg.get("phone1") is None
