"""Contracts for outcome-confidence assessment."""

from __future__ import annotations

from reyes_agent import outcome_confidence as oc
from reyes_agent.action_verifier import Verdict


def test_result_failed_is_failed():
    assert oc.assess(result_failed=True) == oc.FAILED


def test_verified_verdict():
    v = Verdict(True, True, "process", "running")
    assert oc.assess(v) == oc.VERIFIED


def test_negative_check_is_failed():
    # A check ran (verifiable) and came back negative.
    v = Verdict(False, True, "process", "not running")
    assert oc.assess(v) == oc.FAILED


def test_unverifiable_but_ok_reported_is_high_confidence():
    v = Verdict(False, False, "none", "")
    assert oc.assess(v, ok_reported=True) == oc.HIGH_CONFIDENCE


def test_unverifiable_and_silent_is_unverified():
    v = Verdict(False, False, "none", "")
    assert oc.assess(v) == oc.UNVERIFIED


def test_no_verdict_defaults_unverified():
    assert oc.assess() == oc.UNVERIFIED
    assert oc.assess(ok_reported=True) == oc.HIGH_CONFIDENCE


def test_multistep_levels():
    assert oc.assess(steps_total=3, steps_verified=3) == oc.VERIFIED
    assert oc.assess(steps_total=3, steps_verified=1) == oc.PARTIAL
    assert oc.assess(steps_total=3, steps_verified=0) == oc.UNVERIFIED


def test_failure_beats_multistep():
    assert oc.assess(result_failed=True, steps_total=3, steps_verified=3) == oc.FAILED


def test_truthful_helper():
    assert oc.truthful(oc.VERIFIED) is True
    assert oc.truthful(oc.HIGH_CONFIDENCE) is True
    assert oc.truthful(oc.UNVERIFIED) is False
    assert oc.truthful(oc.FAILED) is False


def test_from_action_composes_with_verifier():
    # Real process check: this interpreter is running.
    good = oc.from_action("open_app", {"app": "python"}, "Opened python")
    assert good["confidence"] == oc.VERIFIED and good["verdict"]["verified"] is True
    # Explicit failure evidence in the result.
    bad = oc.from_action("send_message", {}, {"ok": False, "error": "x"})
    assert bad["confidence"] == oc.FAILED


def test_from_action_never_raises():
    out = oc.from_action("whatever", None, object())
    assert out["confidence"] in oc.LEVELS
