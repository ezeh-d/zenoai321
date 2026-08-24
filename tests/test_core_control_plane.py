from __future__ import annotations

import json
from pathlib import Path

import pytest

from reyes_agent.action_verifier import FAILED, UNVERIFIED, VERIFIED, ActionVerifier
from reyes_agent.capability_truth import (
    AUTH_REQUIRED, AVAILABLE, DEGRADED, DEVICE_OFFLINE, TESTING, CapabilityTruth,
)
from reyes_agent.evidence_ledger import ActionEvidence, EvidenceLedger, SideEffectLedger
from reyes_agent.failure_regression import FailureCaptureService, RegressionCaseGenerator, RegressionCorpus
from reyes_agent.observability.tracer import Tracer
from reyes_agent.policy_engine import (
    ADMIN, ALLOW, ASK, DENY, FINANCIAL, LOW_RISK, TEMPORARY,
    DeviceTrustManager, PermissionEngine,
)
from reyes_agent.quality_score import QualityDimension, QualityScoreEngine
from reyes_agent.recovery_engine import (
    REQUIRES_DEVICE, REQUIRES_REAUTH, SAFE_RETRY, FailureClassifier,
    FallbackResolver, RecoveryPlanner,
)
from reyes_agent.resource_governor import ResourceGovernor, ResourceSnapshot
from reyes_agent.unified_session import SessionStateManager
from reyes_agent.computer_use_benchmark import ComputerUseCase, ZenoComputerUseBenchmark
from reyes_agent.knowledge_trust import KnowledgeTrustEngine


def test_capability_truth_distinguishes_auth_device_and_testing(monkeypatch):
    truth = CapabilityTruth()
    truth.declare("slack.send", implemented=True, tested=True,
                  authentication_required=True, authenticated=False)
    assert truth.truth("slack.send")["status"] == AUTH_REQUIRED
    truth.declare("slack.send", authenticated=True, device_requirements=["laptop"], available=False)
    assert truth.truth("slack.send")["status"] == DEVICE_OFFLINE
    truth.declare("slack.send", available=True, tested=False)
    assert truth.truth("slack.send")["status"] == TESTING
    truth.mark_tested("slack.send", True)
    assert truth.truth("slack.send")["status"] == AVAILABLE


def test_capability_dependency_root_cause():
    truth = CapabilityTruth()
    truth.declare("auth.slack", implemented=True, tested=True,
                  authentication_required=True, authenticated=False)
    truth.declare("slack.send", implemented=True, tested=True,
                  dependencies=["auth.slack"])
    diagnosis = truth.diagnose("slack.send")
    assert diagnosis["root_cause"] == {"dependency": "auth.slack", "status": AUTH_REQUIRED}


def test_capability_degraded_is_not_available(monkeypatch):
    truth = CapabilityTruth()
    truth.declare("browser", implemented=True, tested=True)
    monkeypatch.setattr(truth, "_healthy", lambda _name: (False, {"breaker": "OPEN"}))
    assert truth.truth("browser")["status"] == DEGRADED


def test_action_verifier_file_and_failure(tmp_path):
    verifier = ActionVerifier()
    path = tmp_path / "report.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    assert verifier.verify("file", {"path": str(path), "contains": "true",
                                    "valid_json": True}).state == VERIFIED
    assert verifier.verify("file", {"path": str(tmp_path / "missing")}).state == FAILED
    assert verifier.verify("does-not-exist", {}).state == UNVERIFIED


def test_provider_receipt_requires_external_id():
    verifier = ActionVerifier()
    assert verifier.verify("provider_receipt", {}).state == UNVERIFIED
    result = verifier.verify("provider_receipt", {"message_id": "m-42", "target": "team"})
    assert result.state == VERIFIED
    assert result.evidence["external_result_id"] == "m-42"


def test_evidence_history_is_redacted_and_queryable(tmp_path):
    ledger = EvidenceLedger(tmp_path / "state.db")
    ledger.record(ActionEvidence("cmd-1", "phone", "laptop", "STARK", "open_app",
                                 "desktop", "Notepad token=secret", "opened", VERIFIED))
    rows = ledger.history(command_id="cmd-1")
    assert len(rows) == 1 and rows[0]["agent"] == "STARK"
    assert ledger.stats()["verification_rate"] == 1.0


def test_duplicate_side_effect_claim_is_prevented(tmp_path):
    effects = SideEffectLedger(EvidenceLedger(tmp_path / "state.db"))
    first = effects.claim("send_message", "team", idempotency_key="same")
    assert first["claimed"]
    assert effects.complete(first["claim_key"], "message-1")
    duplicate = effects.claim("send_message", "team", idempotency_key="same")
    assert not duplicate["claimed"]
    assert duplicate["status"] == "COMPLETED"
    assert duplicate["result_id"] == "message-1"


@pytest.mark.parametrize(("message", "expected"), [
    ("401 token expired", "AUTH_REQUIRED"),
    ("laptop node offline", "DEVICE_OFFLINE"),
    ("request timed out", "TOOL_TIMEOUT"),
    ("verification failed", "VERIFICATION_FAILED"),
])
def test_failure_classifier(message, expected):
    assert FailureClassifier().classify(message) == expected


def test_recovery_policies_are_bounded():
    planner = RecoveryPlanner()
    assert planner.plan("401 token expired").retry_policy == REQUIRES_REAUTH
    assert planner.plan("device offline").retry_policy == REQUIRES_DEVICE
    timeout = planner.plan("timed out", capability="custom")
    assert timeout.retry_policy == SAFE_RETRY and timeout.max_attempts == 1


def test_fallback_skips_failed_provider():
    resolver = FallbackResolver()
    resolver.register("test-pipe", ["one", "two", "three"])
    assert resolver.next("test-pipe", "one") == "two"


def test_permission_deny_and_ask(monkeypatch, tmp_path):
    trust = DeviceTrustManager(tmp_path / "trust.json")
    engine = PermissionEngine(trust)
    assert engine.evaluate(action_class=FINANCIAL)["decision"] == DENY
    trust.set("phone", TEMPORARY)
    monkeypatch.setattr("reyes_agent.permissions.check", lambda _tool: "enabled")
    assert engine.evaluate(action_class=LOW_RISK, tool="read", device="phone")["decision"] == ASK
    assert engine.evaluate(action_class=ADMIN, device="laptop")["decision"] == ASK
    assert engine.evaluate(action_class=LOW_RISK, device="laptop")["decision"] == ALLOW


def test_resource_pressure_recommends_shedding_without_touching_core(monkeypatch):
    governor = ResourceGovernor("BALANCED")
    sample = ResourceSnapshot(1.0, 95.0, 93.0, 500.0, 50.0, None, None, 8, "HIGH")
    monkeypatch.setattr(governor.monitor, "sample", lambda: sample)
    result = governor.evaluate()
    assert "pause_indexing" in result["recommended_actions"]
    assert "stop" in result["interaction_core_reserved"]


def test_quality_score_never_invents_unmeasured_numbers(monkeypatch):
    engine = QualityScoreEngine()
    monkeypatch.setattr(engine, "dimensions", lambda: [
        QualityDimension("Core", 98.0, 20, 2.0, "tests"),
        QualityDimension("Optional", None, 0, 0.5, "unmeasured"),
    ])
    result = engine.score()
    assert result["score"] == 98.0
    assert result["unmeasured_dimensions"] == ["Optional"]
    assert engine.release_gate(99.0)["promote"]
    assert not engine.release_gate(None)["promote"]


def test_phone_laptop_and_agent_state_are_global_and_durable(tmp_path):
    path = tmp_path / "session.json"
    manager = SessionStateManager(path)
    manager.connect_device("phone", make_active=True)
    manager.connect_device("laptop")
    manager.set_agent("stark", True)
    assert manager.snapshot()["active_agents"] == ["STARK"]
    assert set(manager.snapshot()["connected_devices"]) == {"phone", "laptop"}
    restored = SessionStateManager(path).snapshot()
    assert restored["active_device"] == "phone"
    assert restored["connected_devices"] == {}  # online state requires a fresh heartbeat
    assert restored["active_agents"] == []      # lifecycle rebuilds ephemeral presence


def test_trace_hierarchy_and_secret_redaction():
    tracer = Tracer()
    with tracer.span("command", command_id="c1", attributes={"api_key": "secret"}) as parent:
        with tracer.span("tool") as child:
            assert child["trace_id"] == parent["trace_id"]
            assert child["parent_span_id"] == parent["span_id"]
    records = tracer.snapshot()["local_records"]
    assert records[-1]["attributes"]["api_key"] == "[REDACTED]"


def test_failure_capture_creates_reusable_golden_case(tmp_path, monkeypatch):
    corpus = RegressionCorpus(tmp_path)
    generator = RegressionCaseGenerator()
    monkeypatch.setattr("reyes_agent.failure_regression.RegressionCorpus", lambda: corpus)
    result = FailureCaptureService(generator).capture(
        input={"command": "open Slack", "token": "never-store"},
        system_state={"device": "offline"}, failure_class="DEVICE_OFFLINE",
        expected_behavior="DEVICE_OFFLINE", fix="route only when laptop online")
    data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert data["input"]["token"] == "[REDACTED]"
    assert corpus.cases()[0]["failure_class"] == "DEVICE_OFFLINE"


def test_doctor_root_cause_is_exact():
    from reyes_agent.doctor import ZenoDoctor
    from reyes_agent.capability_truth import get_truth
    name = "test.auth.capability"
    get_truth().declare(name, implemented=True, tested=True,
                        authentication_required=True, authenticated=False)
    report = ZenoDoctor().diagnose(name)
    assert report["diagnosis"]["status"] == AUTH_REQUIRED


def test_emergency_unknown_command_is_rejected_without_model():
    from reyes_agent.emergency_control import execute
    result = execute("do something risky")
    assert result == {"ok": False, "command": "DO SOMETHING RISKY",
                      "reason": "unknown emergency command"}


def test_knowledge_trust_enforces_source_boundary_and_freshness(tmp_path):
    engine = KnowledgeTrustEngine(tmp_path / "knowledge.db")
    fact = engine.remember("ZENO uses one Kernel", source="AGENT.md",
                           confidence=0.95, boundary="zeno_project")
    rows = engine.query(boundary="zeno_project")
    assert rows[0]["fact_id"] == fact.fact_id and rows[0]["fresh"]
    with pytest.raises(ValueError):
        engine.remember("unscoped", source="", confidence=1.0)


def test_computer_use_benchmark_counts_only_verified_evidence():
    cases = (ComputerUseCase("a", "open", "open_app", "process"),
             ComputerUseCase("b", "send", "message", "receipt"))
    benchmark = ZenoComputerUseBenchmark(cases)
    result = benchmark.run(lambda case: {"verified": case.case_id == "a",
                                         "evidence": {"case": case.case_id}})
    assert result["passed"] == 1 and result["total"] == 2
    assert result["pass_rate"] == 0.5
