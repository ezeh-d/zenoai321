"""Phase 3 contracts: lazy, truthful, bounded and policy-enforced."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_all_requested_integrations_have_one_decision_and_flag() -> None:
    from reyes_agent.phase3_flags import INTEGRATIONS
    assert len(INTEGRATIONS) == 25
    assert len({item.key for item in INTEGRATIONS}) == len(INTEGRATIONS)
    assert all(item.flag.startswith("ZENO_") for item in INTEGRATIONS)
    assert {item.classification for item in INTEGRATIONS} <= set("ABCDEF")


def test_heavy_services_are_not_enabled_by_default() -> None:
    from reyes_agent.phase3_flags import INTEGRATIONS
    risky = {"screenpipe", "graphiti", "sherpa", "docling", "openhands", "agent_device",
             "scrcpy", "kde_connect", "home_assistant", "local_llm", "whisper_cpp",
             "e2b", "langfuse", "phoenix", "activitywatch", "opa", "n8n"}
    assert not any(item.enabled for item in INTEGRATIONS if item.key in risky)


def test_episodic_capture_has_a_separate_global_kill_switch() -> None:
    from reyes_agent.context.episodic import get_provider
    old_global = os.environ.pop("ZENO_EPISODIC_MEMORY_ENABLED", None)
    old_screenpipe = os.environ.get("ZENO_SCREENPIPE_ENABLED")
    os.environ["ZENO_SCREENPIPE_ENABLED"] = "true"
    try:
        state = get_provider().status()
        assert state["enabled"] is False and state["global_capture_enabled"] is False
    finally:
        if old_global is not None:
            os.environ["ZENO_EPISODIC_MEMORY_ENABLED"] = old_global
        if old_screenpipe is None:
            os.environ.pop("ZENO_SCREENPIPE_ENABLED", None)
        else:
            os.environ["ZENO_SCREENPIPE_ENABLED"] = old_screenpipe


def test_status_imports_no_optional_sdk_and_starts_no_thread() -> None:
    optional = {"docling", "graphiti_core", "sherpa_onnx", "langfuse", "e2b", "pywinauto"}
    before_modules = optional & set(sys.modules)
    before_threads = threading.active_count()
    from reyes_agent.phase3 import status
    result = status()
    assert result["polling"] is False and result["total"] == 25
    assert optional & set(sys.modules) == before_modules
    assert threading.active_count() == before_threads


def test_disabled_activation_fails_without_importing_or_starting() -> None:
    from reyes_agent.phase3 import DISABLED, activate
    result = activate("docling")
    assert result == {"ok": False, "state": DISABLED, "reason": "ZENO_DOCLING_ENABLED is off"}


def test_model_gateway_requires_real_declared_capabilities() -> None:
    from reyes_agent.models.capability_registry import supports
    from reyes_agent.models.gateway import get_gateway
    route = get_gateway().select("vision", {"VISION"})
    assert route.provider
    assert supports(route.provider, {"VISION"}) or "no configured provider" in route.reason
    status = get_gateway().status()
    assert status["duplicate_clients"] is False and status["litellm_installed"] is True


def test_openai_is_a_real_router_option_without_creating_a_client() -> None:
    from reyes_agent import config, model_router, provider
    original = config.OPENAI_API_KEY
    try:
        config.OPENAI_API_KEY = "configured-for-routing-test"
        assert model_router.available_providers()["openai"] is True
        assert "openai" in provider._RUNNERS
        assert provider._openai_client is None
    finally:
        config.OPENAI_API_KEY = original


def test_dead_preferred_provider_routes_to_healthy_fallback_with_a_bound() -> None:
    from reyes_agent import config, model_router
    saved = (config.GEMINI_API_KEY, config.OPENAI_API_KEY)
    try:
        config.GEMINI_API_KEY = "configured"
        config.OPENAI_API_KEY = "configured"
        model_router.reset()
        for _ in range(3):
            model_router.record("gemini", 0.01, ok=False, error="simulated connection failure")
        chain = model_router.chain_for("general")
        assert "gemini" not in chain and chain[0] == "openai"
        assert model_router.breaker_state("gemini") == model_router.OPEN
    finally:
        config.GEMINI_API_KEY, config.OPENAI_API_KEY = saved
        model_router.reset()


def test_local_model_discovery_does_not_load_a_model() -> None:
    from reyes_agent.models.local import local_status
    result = local_status()
    assert result["profile"] in {"LIGHT", "BALANCED", "STRONG"}
    assert result["loaded"] is False


def test_policy_denies_financial_and_credential_actions() -> None:
    from reyes_agent.security.policy import DENY, decide
    for action in ("make_payment", "transfer_funds", "change_password", "disable_security"):
        assert decide(action).effect == DENY


def test_policy_reuses_existing_permission_authority() -> None:
    from reyes_agent.security.policy import ALLOW, decide
    decision = decide("read_document_structured")
    assert decision.effect == ALLOW
    assert decision.capability == "filesystem_read"


def test_tracer_redacts_secrets_and_is_bounded() -> None:
    from reyes_agent.observability import get_tracer
    tracer = get_tracer()
    with tracer.span("test", attributes={"api_key": "should-not-leak", "safe": "visible"}):
        pass
    record = tracer.snapshot(1)["local_records"][0]
    assert record["attributes"]["api_key"] == "[REDACTED]"
    assert record["attributes"]["safe"] == "visible"


def test_episodic_provider_rejects_non_loopback_services() -> None:
    from reyes_agent.context.episodic.provider import _local_url
    try:
        _local_url("https://public.example.com")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("public activity service URL was accepted")


def test_episodic_privacy_excludes_sensitive_windows() -> None:
    from reyes_agent.context.episodic.privacy import allowed
    assert not allowed("My Bank - Sign in", "Chrome")
    assert not allowed("1Password", "1Password")
    assert allowed("ZENO source - Visual Studio Code", "Code")


def test_activitywatch_uses_documented_bucket_event_api_and_filters_incognito() -> None:
    from reyes_agent.context.episodic import get_provider
    import reyes_agent.context.episodic.provider as module

    calls = []
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): return None
        def json(self): return self.value
    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/api/0/buckets/"):
            return Response({"aw-watcher-window-test": {"type": "currentwindow"}})
        return Response([
            {"timestamp": "now", "data": {"app": "Code", "title": "ZENO"}},
            {"timestamp": "now", "data": {"app": "Chrome", "title": "Private", "incognito": True}},
        ])
    original_get = module.requests.get
    saved = {name: os.environ.get(name) for name in ("ZENO_EPISODIC_MEMORY_ENABLED", "ZENO_ACTIVITYWATCH_ENABLED", "ZENO_SCREENPIPE_ENABLED", "ZENO_ACTIVITYWATCH_URL")}
    try:
        os.environ.update({"ZENO_EPISODIC_MEMORY_ENABLED": "true", "ZENO_ACTIVITYWATCH_ENABLED": "true",
                           "ZENO_SCREENPIPE_ENABLED": "false", "ZENO_ACTIVITYWATCH_URL": "http://127.0.0.1:5600"})
        module.requests.get = fake_get
        result = get_provider().query("working", limit=10)
        assert result["ok"] and len(result["items"]) == 1
        assert calls[0].endswith("/api/0/buckets/")
        assert "/events" in calls[1]
    finally:
        module.requests.get = original_get
        for name, value in saved.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value


def test_relevant_requests_lazy_load_only_the_phase3_tool_group() -> None:
    from reyes_agent.phase3 import episodic_request, relevant_request
    assert relevant_request("What was I working on earlier?")
    assert episodic_request("Continue what I was doing yesterday")
    assert not relevant_request("Hello ZENO")


def test_temporal_graph_deduplicates_and_preserves_contradictions() -> None:
    from reyes_agent.memory.graph import KnowledgeGraph
    with tempfile.TemporaryDirectory() as folder:
        graph = KnowledgeGraph(Path(folder) / "graph.sqlite3")
        first = graph.add("ZENO", "primary provider", "Gemini", at=100, source="test")
        duplicate = graph.add("ZENO", "primary provider", "Gemini", at=101, source="test")
        current = graph.add("ZENO", "primary provider", "Claude", at=102, source="test")
        assert first["ok"] and duplicate["deduplicated"] and not current["deduplicated"]
        assert graph.query("provider")[0]["object"] == "Claude"
        history = graph.query("provider", include_history=True)
        assert {row["object"] for row in history} == {"Gemini", "Claude"}
        old = next(row for row in history if row["object"] == "Gemini")
        assert old["valid_to"] == 102


def test_document_loader_chunks_local_text_without_docling() -> None:
    from reyes_agent.knowledge.documents import DocumentLoader
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "report.txt"
        path.write_text(("deadline Friday\n" * 600), encoding="utf-8")
        result = DocumentLoader(chunk_chars=1000, overlap=100).load(path)
        assert result["ok"] and result["engine"]
        assert len(result["chunks"]) > 1
        assert all(len(chunk["text"]) <= 1000 for chunk in result["chunks"])


def test_engineering_manager_stays_inside_allowed_workspace() -> None:
    from reyes_agent.engineering import EngineeringManager
    result = EngineeringManager().select(ROOT)
    assert Path(result["workspace"]) == ROOT
    assert result["backend"]["name"] == "zeno"
    assert result["verification_required"] is True


def test_mobile_discovery_is_disabled_without_explicit_flag() -> None:
    from reyes_agent.devices.mobile import MobileDeviceManager
    old = os.environ.pop("ZENO_AGENT_DEVICE_ENABLED", None)
    try:
        result = MobileDeviceManager().discover()
        assert result["state"] == "DISABLED" and result["devices"] == []
    finally:
        if old is not None:
            os.environ["ZENO_AGENT_DEVICE_ENABLED"] = old


def test_sandbox_never_forwards_secrets_implicitly() -> None:
    from reyes_agent.sandbox import SandboxManager
    choice = SandboxManager().select(untrusted=True, workspace=ROOT)
    assert choice["secrets_forwarded"] == []
    assert choice["backend"] in {"e2b", "local-controlled"}


def test_n8n_refuses_token_over_insecure_remote_http() -> None:
    from reyes_agent.workflow_integrations.n8n import trigger_webhook
    saved = {name: os.environ.get(name) for name in ("ZENO_N8N_ENABLED", "ZENO_N8N_WEBHOOK_URL", "ZENO_N8N_WEBHOOK_TOKEN")}
    try:
        os.environ.update({"ZENO_N8N_ENABLED": "true", "ZENO_N8N_WEBHOOK_URL": "http://public.example/webhook", "ZENO_N8N_WEBHOOK_TOKEN": "secret"})
        result = trigger_webhook({"task": "test"})
        assert result["ok"] is False and "HTTPS or loopback" in result["reason"]
    finally:
        for name, value in saved.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value


def test_audio_fallbacks_do_not_open_another_microphone() -> None:
    from reyes_agent.audio.local.sherpa_engine import status as sherpa_status
    from reyes_agent.voice_stt_router import status as stt_status
    assert sherpa_status()["opens_microphone"] is False
    assert stt_status()["single_audio_owner"] == "reyes_agent.microphone"


def test_only_one_activity_provider_can_be_selected() -> None:
    from reyes_agent.activity import status
    assert status()["exclusive_selection"] is True


def test_observed_behavior_never_silently_becomes_permission_or_automation() -> None:
    from reyes_agent.learning.behavior import observed_pattern
    pattern = observed_pattern("Open Slack after VS Code", occurrences=20, confidence=0.95)
    assert pattern["suggest"] is True and pattern["confirmed"] is False
    assert pattern["may_change_permissions"] is False
    assert pattern["may_automate_without_approval"] is False


def test_openadapt_style_adapter_reuses_existing_verified_engine() -> None:
    from reyes_agent.learning.demonstrations import status
    data = status()
    assert data["authority"] == "reyes_agent.workflow_engine"
    assert data["raw_coordinate_replay"] is False and data["step_verification"] is True


def test_phase3_tools_are_lazy_except_truthful_status() -> None:
    from reyes_agent.tools import tool_definitions
    core = {item["name"] for item in tool_definitions()}
    expanded = {item["name"] for item in tool_definitions(groups={"phase3"})}
    assert "phase3_status" in core
    assert "episodic_search" not in core and "episodic_search" in expanded
    assert "read_document_structured" in expanded


def test_kernel_registration_does_not_activate_services() -> None:
    from reyes_agent.kernel import get_kernel
    from reyes_agent.phase3 import register_with_kernel
    before_threads = threading.active_count()
    register_with_kernel()
    diagnostics = get_kernel().diagnostics()
    services = {name: value for name, value in diagnostics["services"].items() if name.startswith("phase3:")}
    assert services and all(value["state"] == "registered" for value in services.values())
    assert threading.active_count() <= before_threads + 2  # kernel may start its one existing scheduler/pool


def test_health_includes_real_advanced_service_state() -> None:
    from reyes_agent.system_health import snapshot
    result = snapshot()
    advanced = next(item for item in result["checks"] if item["system"] == "ADVANCED SERVICES")
    assert advanced["metrics"]["total"] == 25
    assert advanced["detail"].endswith("no polling.")


def test_ai_regression_dataset_covers_routing_memory_policy_and_sandbox() -> None:
    cases = json.loads((ROOT / "evals" / "zeno_phase3_cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 10
    serialized = json.dumps(cases).casefold()
    for marker in ("computer", "browser", "memory_retrieval", "deny", "sandbox"):
        assert marker in serialized


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        started = time.perf_counter()
        try:
            test()
            print(f"PASS {test.__name__} ({time.perf_counter() - started:.2f}s)")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
