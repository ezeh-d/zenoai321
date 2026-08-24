"""Contracts for the Pack 5 production-intelligence layer."""

from __future__ import annotations

import pytest

from reyes_agent import capability_lifecycle as cl
from reyes_agent.capability_truth import CapabilityTruth
from reyes_agent.admission import AdmissionController, Rejected
from reyes_agent import a2a_registry as a2a


# --- capability lifecycle ---------------------------------------------------
def test_lifecycle_valid_progression():
    m = cl.CapabilityLifecycle()
    m.register("browser", criticality=cl.IMPORTANT)
    assert m.state("browser") == cl.DISCOVERED
    for nxt in (cl.TRIAL, cl.CANARY, cl.PRODUCTION):
        ok, _ = m.transition("browser", nxt)
        assert ok
    assert m.is_production("browser") and m.criticality("browser") == cl.IMPORTANT


def test_lifecycle_rejects_illegal_jump():
    m = cl.CapabilityLifecycle()
    m.register("x")
    ok, reason = m.transition("x", cl.PRODUCTION)   # DISCOVERED -> PRODUCTION
    assert ok is False and "not allowed" in reason


def test_lifecycle_degrade_and_recover():
    m = cl.CapabilityLifecycle()
    m.register("y", state=cl.PRODUCTION)
    m.mark_degraded("y")
    assert m.state("y") == cl.DEGRADED
    assert m.transition("y", cl.PRODUCTION)[0] is True


def test_lifecycle_retire_is_terminal():
    m = cl.CapabilityLifecycle()
    m.register("z", state=cl.PRODUCTION)
    assert m.transition("z", cl.RETIRED)[0] is True
    assert m.transition("z", cl.PRODUCTION)[0] is False


# --- capability truth -------------------------------------------------------
def test_truth_no_fake_capability_rule():
    t = CapabilityTruth()
    t.declare("send_message", implemented=True, tested=False)
    assert t.truth("send_message")["active"] is False   # implemented but untested
    t.mark_tested("send_message", True)
    assert t.truth("send_message")["active"] is True     # now proven


def test_truth_unavailable_is_not_active():
    t = CapabilityTruth()
    t.declare("open_app", implemented=True, tested=True, available=False)
    assert t.truth("open_app")["active"] is False


def test_truth_health_reflects_breaker(monkeypatch):
    from reyes_agent.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=1)
    cb.record("flaky", False)                            # OPEN
    monkeypatch.setattr("reyes_agent.circuit_breaker.get_breaker", lambda: cb)
    monkeypatch.setattr("reyes_agent.circuit_breaker.is_open",
                        lambda n: cb.is_open(n))
    t = CapabilityTruth()
    t.declare("flaky", implemented=True, tested=True)
    assert t.truth("flaky")["healthy"] is False


def test_readiness_score_weights():
    t = CapabilityTruth()
    t.declare("full", implemented=True, tested=True, has_fallback=True,
              observable=True, documented=True)
    r = t.production_readiness("full")
    assert r["score"] == pytest.approx(1.0) and r["ready"] is True
    t.declare("bare", implemented=True, tested=False)
    assert t.production_readiness("bare")["ready"] is False


def test_dashboard_lists_declared():
    t = CapabilityTruth()
    t.declare("a", implemented=True, tested=True)
    t.declare("b", implemented=False)
    names = {row["name"] for row in t.dashboard()}
    assert names == {"a", "b"}


# --- admission control ------------------------------------------------------
def test_admission_backpressure():
    a = AdmissionController(budgets={"vision": 1})
    t1 = a.try_admit("vision")
    assert t1 is not None
    assert a.try_admit("vision") is None                 # full -> rejected
    a.release(t1)
    assert a.try_admit("vision") is not None              # freed


def test_admission_reserved_never_gated():
    a = AdmissionController(budgets={"voice": 0})
    # Reserved classes ignore budgets entirely (interactivity protected).
    for _ in range(5):
        assert a.try_admit("voice") is not None


def test_admission_context_manager_raises_when_full():
    a = AdmissionController(budgets={"gpu": 1})
    held = a.try_admit("gpu")
    with pytest.raises(Rejected):
        with a.admit("gpu"):
            pass
    a.release(held)
    with a.admit("gpu") as ticket:                        # now succeeds
        assert ticket.resource_class == "gpu"


def test_admission_snapshot():
    a = AdmissionController(budgets={"browser": 2})
    a.try_admit("browser")
    row = {r["resource_class"]: r for r in a.snapshot()}["browser"]
    assert row["in_use"] == 1 and row["limit"] == 2


# --- A2A trust registry -----------------------------------------------------
def _card():
    return a2a.CapabilityCard("STARK", "security", capabilities=("scan",))


def test_a2a_new_agent_is_quarantined():
    r = a2a.A2ARegistry()
    r.register_agent("stark@remote", _card())
    assert r.trust_of("stark@remote") == a2a.UNKNOWN
    assert r.may("stark@remote", a2a.READ) is True
    assert r.may("stark@remote", a2a.SIDE_EFFECT) is False
    assert r.may("stark@remote", a2a.SENSITIVE_DATA) is False


def test_a2a_trust_promotion_widens_then_block():
    r = a2a.A2ARegistry()
    r.register_agent("a1", _card())
    r.set_trust("a1", a2a.PARTNER)
    assert r.may("a1", a2a.SIDE_EFFECT) is True and r.may("a1", a2a.SENSITIVE_DATA) is False
    r.set_trust("a1", a2a.LOCAL_TRUSTED)
    assert r.may("a1", a2a.SENSITIVE_DATA) is True
    r.block("a1")
    assert r.may("a1", a2a.READ) is False


def test_a2a_validate_task_contract():
    r = a2a.A2ARegistry()
    ok, why = r.validate_task({"task_id": "1"})
    assert ok is False and "missing" in why
    full = {f: "x" for f in ("task_id", "goal", "inputs", "allowed_tools",
                             "deadline", "budget", "expected_output")}
    assert r.validate_task(full)[0] is True


def test_a2a_validate_result_and_blocked():
    r = a2a.A2ARegistry()
    r.register_agent("a2", _card())
    assert r.validate_result("a2", {"answer": 1})[0] is True
    assert r.validate_result("a2", "")[0] is False
    r.block("a2")
    assert r.validate_result("a2", {"answer": 1})[0] is False


def test_a2a_discover_excludes_blocked():
    r = a2a.A2ARegistry()
    r.register_agent("keep", _card())
    r.register_agent("gone", _card())
    r.block("gone")
    ids = {a["agent_id"] for a in r.discover()}
    assert ids == {"keep"}
