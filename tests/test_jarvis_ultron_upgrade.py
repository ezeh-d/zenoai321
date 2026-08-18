from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


FACTORS = {
    "skill_fit": 8,
    "startup_cost": 2,
    "time_to_first_result": 3,
    "market_demand": 7,
    "competition": 5,
    "repeatability": 8,
    "scalability": 6,
    "risk": 2,
    "estimated_effort": 4,
}


def test_opportunity_score_is_transparent_and_costs_are_inverted() -> None:
    from reyes_agent.opportunity import score_factors

    base = score_factors(FACTORS)
    expensive = score_factors({**FACTORS, "startup_cost": 9})
    assert 0 <= base["score"] <= 100
    assert expensive["score"] < base["score"]
    assert sum(base["weights"].values()) == pytest.approx(1.0)
    assert base["scale"].endswith("not income probability")


def test_opportunity_score_refuses_missing_or_unbounded_inputs() -> None:
    from reyes_agent.opportunity import score_factors

    with pytest.raises(ValueError, match="missing opportunity factors"):
        score_factors({"skill_fit": 8})
    with pytest.raises(ValueError, match="market_demand must be between"):
        score_factors({**FACTORS, "market_demand": 11})


def test_opportunity_evidence_keeps_fact_and_assumption_distinct() -> None:
    from reyes_agent.opportunity import FACT, Observation, evidence_state

    with pytest.raises(ValueError, match="require a source"):
        Observation.from_value({"kind": FACT, "summary": "Demand rose."})
    assumptions = [Observation.from_value({"kind": "ASSUMPTION", "summary": "The niche may pay."})]
    assert evidence_state(assumptions) == "ASSUMPTION_ONLY"


def test_opportunity_engine_persists_and_revalidates_expired_market_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reyes_agent import opportunity
    from reyes_agent.opportunity import OpportunityEngine

    engine = OpportunityEngine(tmp_path / "opportunities.sqlite3")
    now = time.time()
    record = engine.assess(
        name="Accessibility review service",
        category="freelancing",
        summary="Audit small-business sites and provide evidence-backed remediation plans.",
        factors=FACTORS,
        observations=[{
            "kind": "FACT", "summary": "A dated market observation.",
            "source": "https://example.com/report?token=must-not-persist",
            "observed_at": now - 10, "expires_at": now + 100,
        }],
        opportunity_id="accessibility-review",
    )
    assert record["evidence_state"] == "LIMITED_EVIDENCE"
    assert record["observations"][0]["source"] == "https://example.com/report"
    monkeypatch.setattr(opportunity.time, "time", lambda: now + 200)
    expired = engine.get("accessibility-review")
    assert expired["evidence_state"] == "ASSUMPTION_ONLY"
    assert expired["expired_observations"] == 1
    assert engine.list(limit=2)[0]["id"] == "accessibility-review"


def test_opportunity_plan_reuses_existing_agents_and_has_no_fake_result() -> None:
    from reyes_agent.opportunity import SPECIALIST_COMPONENTS, research_plan

    plan = research_plan("Find a legitimate service I can offer", ["Python", "design"])
    assert {step["agent"] for step in plan["steps"]} <= {
        "aris", "titan", "kate", "tosin", "oracle",
    }
    assert SPECIALIST_COMPONENTS["ProductBuilderAgent"] == "tosin"
    assert plan["score_after_research"] is True
    encoded = json.dumps(plan).casefold()
    assert "guaranteed" in encoded
    assert "earned" not in plan and "revenue" not in plan


def test_opportunity_tools_are_registered_but_not_in_default_payload() -> None:
    from reyes_agent.tools import TOOLS, tool_definitions

    names = {item["name"] for item in tool_definitions()}
    opportunity = {"opportunity_plan", "opportunity_assess", "opportunity_list",
                   "opportunity_get", "opportunity_delete"}
    assert opportunity <= set(TOOLS)
    assert not opportunity & names
    enabled = {item["name"] for item in tool_definitions(groups={"opportunity"})}
    assert opportunity <= enabled
    assert TOOLS["opportunity_delete"].requires_confirmation is True


def test_opportunity_requests_route_deep_without_starting_a_worker() -> None:
    from reyes_agent import cognition

    decision = cognition.route("What online income opportunity fits my Python skills?")
    assert decision.path == cognition.DEEP
    assert cognition.OPPORTUNITY in decision.modes
    assert "never promise income" in cognition.prompt_directive(decision)


def test_execution_trace_does_not_promote_plain_return_to_verified() -> None:
    from reyes_agent.execution_lifecycle import ExecutionTrace

    trace = ExecutionTrace("check a thing")
    trace.observed("plain_lookup", "Here is some data", {})
    check = trace.verification()
    assert check["verified"] is False
    assert check["unverified"] == ["plain_lookup"]

    verified = ExecutionTrace("write a thing")
    verified.observed(
        "writer",
        json.dumps({"ok": True, "evidence": {"path": "x"}, "verification_state": "verified"}),
        {},
    )
    assert verified.verification()["verified"] is True


def test_plugin_loading_is_explicit_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    import reyes_agent.tools as tools

    calls: list[bool] = []
    monkeypatch.setattr(tools, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(tools, "_LOADED_PLUGINS", [])
    monkeypatch.setattr(tools, "load_plugins", lambda: calls.append(True) or ["approved"])
    assert tools.ensure_plugins_loaded() == ["approved"]
    assert tools.ensure_plugins_loaded() == ["approved"]
    assert calls == [True]


def test_approved_skill_context_reaches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from reyes_agent import agent, config
    from reyes_agent.skills import manager as skill_manager

    captured: dict[str, str] = {}
    skill = SimpleNamespace(name="Morning report", skill_id="morning-report")
    monkeypatch.setattr(skill_manager, "find_for", lambda _text: skill)
    monkeypatch.setattr(config, "MODEL_PROVIDER", "gemini")
    monkeypatch.setattr(agent, "tool_definitions", lambda **_kwargs: [])

    def fake_turn(_history, *, system, **_kwargs):
        captured["system"] = system
        return SimpleNamespace(wants_tool=False, text="Ready.")

    monkeypatch.setattr(agent, "run_turn", fake_turn)
    history = [{"role": "user", "content": "Run my morning report workflow"}]
    agent.run_agent(history)
    assert "Morning report (morning-report)" in captured["system"]
    assert history[-1]["content"] == "Ready."


def test_opportunity_capability_is_detected_without_network() -> None:
    from reyes_agent.capabilities import registry

    registry.status()
    capability = registry.get("opportunity_intelligence")
    assert capability is not None
    assert capability.usable is True
    assert capability.network is False


def test_notification_runtime_submission_does_not_park_the_calling_worker() -> None:
    from reyes_agent import notification_listener as listener

    completed = threading.Event()
    outcome: dict[str, object] = {}

    async def probe() -> str:
        import asyncio

        await asyncio.sleep(0.1)
        return "done"

    def on_done(result, error) -> None:
        outcome.update(result=result, error=error)
        completed.set()

    try:
        async def warm() -> None:
            return None

        listener._run_on_runtime(warm)
        started = time.perf_counter()
        listener._submit_on_runtime(probe, on_done)
        returned_ms = (time.perf_counter() - started) * 1000
        assert returned_ms < 80
        assert completed.wait(2.0)
        assert outcome == {"result": "done", "error": None}
    finally:
        listener.shutdown_background()


def test_job_cancel_claims_state_before_slow_process_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watchdog exit observation must not overwrite an explicit cancel."""
    from reyes_agent.executors import jobs

    class Process:
        def poll(self):
            return 1

    class Background:
        process = Process()

        def stop(self):
            # Reproduce the old race deterministically: the watchdog tries to
            # record the non-zero exit while cancel() is stopping the process.
            jobs._finish(job, jobs.FAILED, exit_code=1)

    job = jobs.Job(
        id="cancel-race", project="test", command="node test.js", cwd=".",
        kind=jobs.BUILD, timeout=30, state=jobs.RUNNING,
        started_at=time.time(), _started_monotonic=time.monotonic(),
    )
    job._process = Background()
    monkeypatch.setitem(jobs._jobs, job.id, job)

    result = jobs.cancel(job.id)

    assert result is not None
    assert result["state"] == jobs.CANCELLED
    assert job.state == jobs.CANCELLED
    assert "cancelled on request" in job.error


def test_idle_pcm_bus_is_lazy_when_no_local_wake_model_is_configured() -> None:
    root = Path(__file__).resolve().parents[1] / "reyes_agent" / "static"
    vad = (root / "vad.js").read_text(encoding="utf-8")
    mini = (root / "mini.html").read_text(encoding="utf-8")
    dashboard = (root / "audio_frames.js").read_text(encoding="utf-8")

    assert "export function setFrameBusActive(on)" in vad
    assert "if (!frameBusActive) teardownPcmBus()" in vad
    assert "status.backend?.state!=='READY'" in mini
    assert "status.backend?.state !== 'READY'" in dashboard
