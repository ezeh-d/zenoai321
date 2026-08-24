"""Contracts for the OS-process post-condition verifier (process_verifier)."""

from __future__ import annotations

import os

from reyes_agent import process_verifier as av


# --- explicit evidence wins -------------------------------------------------
def test_explicit_evidence_ok_plus_evidence_is_verified():
    v = av.verify("send_message", {}, {"ok": True, "evidence": "message id 42"})
    assert v.verified and v.verifiable and v.method == "evidence"
    assert "42" in v.evidence


def test_reported_failure_is_verifiable_not_verified():
    v = av.verify("open_app", {"app": "slack"}, {"ok": False, "error": "boom"})
    assert v.verifiable is True and v.verified is False and v.method == "evidence"


def test_verification_state_string_counts_as_evidence():
    v = av.verify("build", {}, {"verification_state": "verified"})
    assert v.verified is True


# --- process check (uses THIS running python process) -----------------------
def test_app_is_running_true_for_current_interpreter():
    running, why = av.app_is_running("python")
    assert running is True and "running" in why


def test_app_is_running_false_for_nonsense():
    running, _ = av.app_is_running("definitelynotarealapp_zzz")
    assert running is False


def test_open_app_verified_when_process_present():
    v = av.verify("open_app", {"app": "python"}, "Launched it.")
    assert v.verified is True and v.method == "process"


def test_open_app_not_verified_when_absent():
    v = av.verify("desktop.open_app", {"app": "definitelynotarealapp_zzz"}, "Opened.")
    assert v.verifiable is True and v.verified is False and v.method == "process"


def test_open_app_reads_app_from_result_text():
    # No arg supplied; the app name is recovered from "Opened python".
    v = av.verify("open_app", {}, "Opened python")
    assert v.verified is True


# --- path check -------------------------------------------------------------
def test_create_file_verified_when_path_exists(tmp_path):
    p = tmp_path / "made.txt"
    p.write_text("hi", encoding="utf-8")
    v = av.verify("create_file", {"path": str(p)}, "done")
    assert v.verified is True and v.method == "path" and "exists" in v.evidence


def test_create_file_not_verified_when_missing(tmp_path):
    p = tmp_path / "missing.txt"
    v = av.verify("write_file", {"path": str(p)}, "done")
    assert v.verifiable is True and v.verified is False and "missing" in v.evidence


# --- unknown / safety -------------------------------------------------------
def test_unknown_action_is_unverifiable_not_a_pass():
    v = av.verify("whisper_sweet_nothings", {"x": 1}, "sure did")
    assert v.verifiable is False and v.verified is False and v.method == "none"


def test_verify_never_raises_on_garbage():
    for bad in [None, 123, object(), b"bytes", {"path": 5}]:
        v = av.verify("open_app", bad if isinstance(bad, dict) else None, bad)
        assert isinstance(v, av.Verdict) and v.verified in (True, False)


def test_register_adds_a_checker():
    av.register("teleport", lambda args, result: av.Verdict(True, True, "process", "beamed"))
    v = av.verify("teleport", {}, "zap")
    assert v.verified is True and v.evidence == "beamed"


def test_as_dict_shape():
    d = av.verify("noop", {}, "x").as_dict()
    assert set(d) == {"verified", "verifiable", "method", "evidence"}
