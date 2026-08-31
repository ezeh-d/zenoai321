"""Phase 2 memory, wake, coding, MCP, devices, autonomy and health contracts."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_memory_policy_is_selective_and_separates_categories() -> None:
    from reyes_agent.memory.policies import Category, Retention, decide

    assert decide("I prefer concise replies").category is Category.USER
    assert decide("I prefer concise replies").retention is Retention.LONG_TERM
    assert decide("The browser project uses Playwright", verified=True).category is Category.PROJECT
    assert decide("The task is loading right now").retention is Retention.SESSION
    assert decide("hello there").retention is Retention.SESSION


def test_secrets_are_never_memory_candidates() -> None:
    from reyes_agent.memory.policies import Retention, decide
    from reyes_agent.memory.privacy import contains_secret, redact

    sample = "api_key=sk-secret-example-1234567890"
    assert contains_secret(sample)
    assert decide(sample, explicit=True).retention is Retention.IGNORE
    assert "fixture-secret" not in redact('{"token": "fixture-secret-must-be-redacted"}')
    assert "sk-secret" not in redact(sample)


def test_memory_retrieval_is_relevant_not_the_entire_store() -> None:
    from reyes_agent import living_memory
    from reyes_agent.memory import retrieval

    original = living_memory.list_memories
    living_memory.list_memories = lambda **_kwargs: [
        {"id": "a", "title": "Browser agent", "content": "The browser project uses Playwright", "category": "project"},
        {"id": "b", "title": "Cooking", "content": "Divine likes jollof rice", "category": "user"},
    ]
    try:
        rows = retrieval.legacy_search("continue the browser project")
    finally:
        living_memory.list_memories = original
    assert len(rows) == 1 and rows[0]["id"] == "a"


def test_session_memory_is_bounded_and_queryable() -> None:
    from reyes_agent.memory.manager import MemoryManager

    manager = MemoryManager()
    manager.consider("We are debugging the browser project", source="user")
    context = manager.context_for("continue browser debugging")
    assert "browser project" in context
    assert manager.status()["session_items"] <= manager.status()["session_capacity"]


def test_mem0_failure_keeps_living_memory_fallback() -> None:
    from reyes_agent.memory.mem0_backend import Mem0Backend

    backend = Mem0Backend()
    backend.enabled = False
    status = backend.status()
    assert status["fallback"] == "Living Memory"
    assert status["state"] == "DISABLED"


class _FakeWakeBackend:
    threshold = 0.5

    def __init__(self):
        self.calls = 0

    def predict(self, _pcm):
        self.calls += 1
        return "zeno", 0.9

    def reset(self):
        return None

    def status(self):
        return {"state": "READY", "backend": "fake", "installed": True,
                "model_configured": True}


def test_wake_engine_has_deterministic_hits_and_cooldown() -> None:
    from reyes_agent.wake.engine import WakeEngine
    from reyes_agent.wake.state_machine import WakeState

    engine = WakeEngine(backend=_FakeWakeBackend(), cooldown_s=3)
    engine.required_hits = 2
    pcm = struct.pack("<" + "h" * 1280, *([4000] * 1280))
    assert engine.feed_pcm(pcm, now=10.0)["detected"] is False
    assert engine.feed_pcm(pcm, now=10.1)["detected"] is True
    assert engine.state_machine.state is WakeState.ACTIVE
    assert engine.feed_pcm(pcm, now=10.2)["reason"] == "cooldown"
    assert engine.status()["triggers"] == 1


def test_wake_state_machine_rejects_invalid_transitions() -> None:
    from reyes_agent.wake.state_machine import WakeState, WakeStateMachine

    machine = WakeStateMachine()
    try:
        machine.transition(WakeState.SPEAKING)
    except ValueError:
        pass
    else:
        raise AssertionError("SLEEPING -> SPEAKING must be rejected")
    machine.transition(WakeState.LISTENING_FOR_WAKE)
    machine.transition(WakeState.ACTIVE)
    machine.transition(WakeState.PROCESSING)


def test_wake_wav_decode_resamples_without_a_second_microphone() -> None:
    from reyes_agent.wake import audio_stream
    from reyes_agent.wake.engine import decode_wav

    raw = struct.pack("<" + "h" * 800, *([1000] * 800))
    stream = tempfile.SpooledTemporaryFile()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(8000); handle.writeframes(raw)
    stream.seek(0)
    decoded = decode_wav(stream.read())
    assert 3100 <= len(decoded) <= 3300
    assert audio_stream.status()["opens_microphone"] is False


def test_missing_wake_model_is_reported_not_disguised_as_no_match() -> None:
    from reyes_agent.wake.engine import WakeEngine

    raw = struct.pack("<" + "h" * 1600, *([3000] * 1600))
    stream = tempfile.SpooledTemporaryFile()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(raw)
    stream.seek(0)
    result = WakeEngine().detect_wav(stream.read())
    assert result["configured"] is False
    assert result["reason"] == "backend_unavailable"
    assert result["error"]


def test_coding_workspace_rejects_path_escape() -> None:
    from reyes_agent.coding_system.workspace import WorkspaceError, resolve_workspace

    try:
        resolve_workspace(Path(tempfile.gettempdir()))
    except WorkspaceError:
        pass
    else:
        raise AssertionError("an unrelated temp directory escaped the coding workspace")


def test_coding_policy_blocks_finance_and_secret_exposure() -> None:
    from reyes_agent.coding_system.command_policy import classify

    assert not classify("transfer money with this script", read_only=False).allowed
    assert not classify("print all environment API keys", read_only=True).allowed
    assert classify("inspect why these tests fail", read_only=True).autonomy_level == 1
    assert classify("fix these tests", read_only=False).autonomy_level == 2


def test_open_interpreter_is_lazy_and_auto_run_is_off() -> None:
    from reyes_agent.coding_system.interpreter_client import InterpreterClient

    client = InterpreterClient()
    result = client.status()
    assert result["auto_run"] is False
    assert result["state"] in {"DISABLED", "READY", "UNAVAILABLE"}


def test_mcp_registry_requires_allowlist_and_no_shell() -> None:
    from reyes_agent.tools.mcp.registry import MCPRegistry

    old = os.environ.get("ZENO_MCP_ALLOWLIST")
    os.environ["ZENO_MCP_ALLOWLIST"] = "safe"
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "servers.json"
            path.write_text(json.dumps({"servers": [
                {"name": "safe", "command": "python", "args": ["server.py"],
                 "permissions": ["filesystem_read"], "trust_level": "reviewed", "enabled": True},
                {"name": "evil", "command": "python & whoami", "enabled": True},
            ]}), encoding="utf-8")
            registry = MCPRegistry(path)
            assert [item.name for item in registry.list()] == ["safe"]
            assert registry.get("safe").enabled
    finally:
        if old is None:
            os.environ.pop("ZENO_MCP_ALLOWLIST", None)
        else:
            os.environ["ZENO_MCP_ALLOWLIST"] = old


def test_mcp_starts_no_process_when_unconfigured() -> None:
    from reyes_agent.tools.mcp.manager import MCPManager
    from reyes_agent.tools.mcp.registry import MCPRegistry

    with tempfile.TemporaryDirectory() as folder:
        manager = MCPManager(MCPRegistry(Path(folder) / "missing.json"))
        status = manager.status()
        assert status["enabled"] == 0 and status["state"] == "STANDBY"
        manager.shutdown()


def test_mcp_official_sdk_stdio_round_trip_and_redaction() -> None:
    from reyes_agent.tools.mcp.manager import MCPManager
    from reyes_agent.tools.mcp.registry import MCPRegistry

    old = os.environ.get("ZENO_MCP_ALLOWLIST")
    os.environ["ZENO_MCP_ALLOWLIST"] = "phase2-echo"
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "servers.json"
            fixture = ROOT / "tests" / "fixtures" / "mcp_echo_server.py"
            path.write_text(json.dumps({"servers": [{
                "name": "phase2-echo", "command": getattr(sys, "_base_executable", sys.executable),
                "args": [str(fixture)], "permissions": ["filesystem_read"],
                "trust_level": "reviewed", "enabled": True, "startup_timeout_s": 20,
            }]}), encoding="utf-8")
            manager = MCPManager(MCPRegistry(path))
            discovered = manager.discover("phase2-echo")
            assert discovered[0]["name"] == "echo"
            assert discovered[0]["annotations"].get("read_only_hint") is True
            result = manager.call("phase2-echo", "echo", {"text": "hello"},
                                  require_read_only=True, timeout_s=20)
            assert result["ok"] is True, result
            assert result["result"]["structured"]["echo"] == "hello"
            assert result["result"]["structured"]["token"] == "[REDACTED]"
            assert "fixture-secret" not in json.dumps(result)
    finally:
        if old is None:
            os.environ.pop("ZENO_MCP_ALLOWLIST", None)
        else:
            os.environ["ZENO_MCP_ALLOWLIST"] = old


def test_mcp_read_requires_server_read_only_annotation() -> None:
    from reyes_agent.tools.mcp.client import _safe_structure
    from reyes_agent.tools.mcp.permissions import read_only_hint

    assert read_only_hint({"annotations": {"readOnlyHint": True}})
    assert not read_only_hint({"annotations": {}})
    cleaned = _safe_structure({"token": "secret", "rows": [{"name": "safe"}]})
    assert cleaned["token"] == "[REDACTED]" and cleaned["rows"][0]["name"] == "safe"


def test_device_manager_has_one_local_device_and_unknown_is_isolated() -> None:
    from reyes_agent.devices.manager import DeviceManager
    from reyes_agent.devices.protocol import DeviceRequest

    manager = DeviceManager()
    assert manager.devices() == ["local-windows"]
    result = manager.execute(DeviceRequest("observe"), device_id="missing")
    assert not result.ok and "No device" in result.error


def test_autonomy_levels_are_explicit_and_finance_is_blocked() -> None:
    from reyes_agent.autonomy import AutonomyLevel, classify_tool, talk_only

    assert talk_only().level is AutonomyLevel.TALK_ONLY
    assert classify_tool("read_file").level is AutonomyLevel.SAFE_AUTOMATION
    assert classify_tool("place_trade").level is AutonomyLevel.BLOCKED


def test_permission_engine_is_enforced_even_without_tool_flag() -> None:
    from reyes_agent import permissions
    from reyes_agent.tools import register, run_tool

    called = []
    name = "phase2_financial_probe"
    permissions.TOOL_CAPABILITY[name] = "financial"

    @register(name=name, description="test only", input_schema={"type": "object", "properties": {}})
    def probe():
        called.append(True)
        return "ran"

    result = run_tool(name, {})
    assert result.startswith("Blocked:") and not called


def test_tool_audit_redaction_does_not_expose_secret_values() -> None:
    from reyes_agent.tools import _audit_safe

    cleaned = _audit_safe({"api_key": "sk-private-12345678901234567890",
                           "nested": {"password": "not-for-logs"},
                           "text": "token=ghp_abcdefghijklmnopqrstuvwxyz1234"})
    encoded = json.dumps(cleaned)
    assert "not-for-logs" not in encoded
    assert "ghp_" not in encoded
    # Count redactions form-agnostically: a content field now summarises as
    # "[REDACTED_CONTENT N chars]" (still contains REDACTED, still hides the
    # value) rather than a bare "[REDACTED]". All three sensitive values are
    # redacted either way.
    assert encoded.count("REDACTED") >= 3


def test_execution_lifecycle_recovery_is_bounded() -> None:
    from reyes_agent.execution_lifecycle import ExecutionTrace

    trace = ExecutionTrace("test", max_recovery_attempts=2)
    assert trace.may_recover() and trace.may_recover()
    assert not trace.may_recover()
    trace.observed("read_file", "Error: missing", {"level": 1})
    assert trace.verification()["verified"] is False


def test_execution_lifecycle_recognises_structured_tool_failure() -> None:
    from reyes_agent.execution_lifecycle import ExecutionTrace

    trace = ExecutionTrace("test")
    trace.observed("example", '{"ok": false, "status": "failed"}', {})
    assert trace.verification()["verified"] is False
    assert trace.recovery_attempts == 1


def test_coding_subprocess_capture_is_bounded() -> None:
    from reyes_agent.coding_system.interpreter_client import _run_bounded

    code = "import sys; sys.stdout.buffer.write(b'x' * 1200000); sys.stdout.flush()"
    return_code, output, _error, limited = _run_bounded(
        [sys.executable, "-c", code], cwd=ROOT, env=dict(os.environ), timeout_s=10)
    assert limited is True
    assert return_code != 0
    assert len(output.encode("utf-8")) <= 1_048_576


def test_central_health_is_real_and_has_no_poller() -> None:
    from reyes_agent import system_health

    result = system_health.snapshot()
    names = {item["system"] for item in result["checks"]}
    assert {"ZENO CORE", "VOICE", "MEMORY", "WAKE WORD", "MCP", "LOCAL WINDOWS DEVICE"} <= names
    assert result["polling"] is False
    assert result["overall"] in {"ONLINE", "DEGRADED"}


def test_startup_phase_is_monotonic_when_services_finish_out_of_order() -> None:
    from reyes_agent import web

    with web._boot_lock:
        old_state = dict(web._boot_state)
        old_completed = set(web._boot_completed)
        web._boot_state.update({"phase": "http_ready", "started_at": time.time(), "errors": []})
        web._boot_completed.clear()
    try:
        web._complete_boot_stage("services", "services_ready")
        assert web._boot_state["phase"] == "services_ready"
        web._complete_boot_stage("executive", "executive_ready")
        assert web._boot_state["phase"] == "executive_ready"
        web._complete_boot_stage("core", "core_ready")
        assert web._boot_state["phase"] == "ready"
    finally:
        with web._boot_lock:
            web._boot_state.clear()
            web._boot_state.update(old_state)
            web._boot_completed.clear()
            web._boot_completed.update(old_completed)


def test_optional_heavy_sdks_are_not_imported_by_phase2_modules() -> None:
    # Run this assertion in a fresh interpreter so another test's explicit
    # MCP round trip cannot make the result order-dependent.
    code = (
        "import sys; "
        "import reyes_agent.memory, reyes_agent.wake, reyes_agent.coding_system; "
        "import reyes_agent.tools.mcp.manager, reyes_agent.devices; "
        "print(','.join(n for n in ('mem0','openwakeword','interpreter','mcp') if n in sys.modules))"
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                               capture_output=True, text=True, timeout=30, check=True)
    assert completed.stdout.strip() == "", completed.stdout


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
