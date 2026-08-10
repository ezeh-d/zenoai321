"""Production-reality regressions: truth, boundaries, persistence and audit."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@contextmanager
def _isolated_runtime_writes():
    """Keep tool telemetry from contaminating the owner's real runtime DB."""
    from reyes_agent import audit, event_bus, intelligence

    original = (audit._LOG_DIR, audit._LOG_PATH, event_bus._DB_PATH, intelligence._DB_PATH)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        try:
            audit._LOG_DIR = root / "audit"
            audit._LOG_PATH = audit._LOG_DIR / "audit.log"
            event_bus._DB_PATH = root / "events.sqlite3"
            intelligence._DB_PATH = root / "intelligence.sqlite3"
            yield
            event_bus.flush(3)
        finally:
            audit._LOG_DIR, audit._LOG_PATH, event_bus._DB_PATH, intelligence._DB_PATH = original


def test_production_rejects_demo_and_mock_backends() -> None:
    from reyes_agent.runtime_environment import report, require_safe_startup

    unsafe = {"ZENO_ENV": "production", "ZENO_DEMO_MODE": "true",
              "ZENO_MOCK_PROVIDER": "1"}
    result = report(unsafe)
    assert result["state"] == "DEGRADED"
    assert result["demo_mode"] is True
    try:
        require_safe_startup(unsafe)
    except RuntimeError as exc:
        assert "Unsafe production configuration" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Production must fail closed when demo/mock flags are active.")


def test_test_environment_uses_separate_runtime_stores() -> None:
    import subprocess

    script = (
        "from reyes_agent import audit,event_bus,intelligence,provider_manager;"
        "print(event_bus._DB_PATH.name);print(intelligence._DB_PATH.name);"
        "print(provider_manager._DB_PATH.name);print(audit._LOG_DIR.name)"
    )
    env = dict(__import__("os").environ)
    env["ZENO_ENV"] = "test"
    result = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), env=env,
                            text=True, capture_output=True, timeout=20, check=True)
    assert result.stdout.splitlines() == [
        "test-state.db", "test-state.db", "test-health.sqlite3", "test-logs",
    ]


def test_failures_are_typed_for_recovery_instead_of_generic() -> None:
    from reyes_agent import failures

    assert failures.classify("rate limited", status_code=429) == failures.PROVIDER_RATE_LIMIT
    assert failures.classify("token expired", status_code=401) == failures.AUTH_EXPIRED
    assert failures.classify("element not found") == failures.ELEMENT_NOT_FOUND
    assert failures.classify("request timed out") == failures.TOOL_TIMEOUT
    assert failures.classify("network offline") == failures.NETWORK_OFFLINE


def test_provider_key_is_configured_until_a_real_probe_succeeds() -> None:
    from reyes_agent import config, provider_manager

    original_key = config.OPENAI_API_KEY
    original_path = provider_manager._DB_PATH
    original_open = provider_manager.urllib.request.urlopen

    class Reply:
        status = 200

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b'{"data":[{"id":"real-model"}]}'

    with tempfile.TemporaryDirectory() as folder:
        try:
            config.OPENAI_API_KEY = "sk-test-provider-reality-1234567890"
            provider_manager._DB_PATH = Path(folder) / "providers.sqlite3"
            provider_manager.urllib.request.urlopen = lambda *_a, **_k: Reply()
            before = provider_manager.status()["providers"]["openai"]
            assert before["state"] == provider_manager.CONFIGURED
            after = provider_manager.validate("openai")
            assert after["state"] == provider_manager.ONLINE
            assert after["validated_at"] and after["latency_ms"] is not None
            assert config.OPENAI_API_KEY.encode() not in provider_manager._DB_PATH.read_bytes()
        finally:
            config.OPENAI_API_KEY = original_key
            provider_manager._DB_PATH = original_path
            provider_manager.urllib.request.urlopen = original_open


def test_synthetic_router_metrics_do_not_validate_a_provider() -> None:
    from reyes_agent import config, model_router, provider_manager

    original_key = config.XAI_API_KEY
    original_path = provider_manager._DB_PATH
    with tempfile.TemporaryDirectory() as folder:
        try:
            config.XAI_API_KEY = "xai-test-not-real-1234567890"
            provider_manager._DB_PATH = Path(folder) / "providers.sqlite3"
            model_router.record("xai", 0.01, ok=True)
            assert provider_manager.status()["providers"]["xai"]["state"] == provider_manager.CONFIGURED
            model_router.record("xai", 0.01, ok=True, validated_runtime=True)
            assert provider_manager.status()["providers"]["xai"]["state"] == provider_manager.ONLINE
        finally:
            model_router.reset("xai")
            config.XAI_API_KEY = original_key
            provider_manager._DB_PATH = original_path


def test_injected_provider_runner_cannot_mutate_durable_health() -> None:
    from reyes_agent import config, model_router, provider, provider_manager

    original_key = config.OPENAI_API_KEY
    original_path = provider_manager._DB_PATH
    original_chain = model_router.chain_for
    original_runner = provider._RUNNERS["openai"]
    original_retries = provider._MAX_RETRY_ATTEMPTS
    with tempfile.TemporaryDirectory() as folder:
        try:
            config.OPENAI_API_KEY = "sk-test-injected-runner-not-real"
            provider_manager._DB_PATH = Path(folder) / "providers.sqlite3"
            model_router.chain_for = lambda _kind: ["openai"]
            provider._RUNNERS["openai"] = lambda *_a, **_k: provider.AgentTurn(text="mock")
            provider._MAX_RETRY_ATTEMPTS = 1
            turn = provider.run_turn([{"role": "user", "content": "test"}])
            assert turn.text == "mock"
            assert provider_manager.status()["providers"]["openai"]["state"] == provider_manager.CONFIGURED
        finally:
            config.OPENAI_API_KEY = original_key
            provider_manager._DB_PATH = original_path
            model_router.chain_for = original_chain
            provider._RUNNERS["openai"] = original_runner
            provider._MAX_RETRY_ATTEMPTS = original_retries


def test_error_and_pending_results_never_publish_completed() -> None:
    from reyes_agent import event_bus
    from reyes_agent.tools import Tool, execute_tool

    cases = (
        ('{"ok": false, "error": "provider unavailable"}', "tool.failed"),
        ("Browser error: TimeoutError", "tool.failed"),
        ('{"status": "PENDING", "job_id": "j1"}', "tool.waiting"),
        ("ordinary data returned", "tool.returned"),
        ("Wrote and verified on disk", "tool.completed"),
    )
    with _isolated_runtime_writes():
        subscription = event_bus.subscribe()
        try:
            for index, (value, expected) in enumerate(cases):
                tool = Tool(f"reality_{index}", "test", {"type": "object"}, lambda v=value: v)
                assert execute_tool(tool, {}) == value
                deadline = time.time() + 3
                event = subscription.get(timeout=3)
                while not event.type.startswith("tool.") and time.time() < deadline:
                    event = subscription.get(timeout=max(0.05, deadline - time.time()))
                assert event.type == expected, (value, event.type)
                assert event.payload["verification_state"] == (
                    "verified" if expected == "tool.completed" else
                    "failed" if expected == "tool.failed" else
                    "pending" if expected == "tool.waiting" else "unverified"
                )
        finally:
            event_bus.unsubscribe(subscription)


def test_remote_forwarded_clients_only_reach_the_narrow_surface() -> None:
    from reyes_agent.remote_access.boundary import decision

    headers = {"CF-Connecting-IP": "203.0.113.8"}
    assert decision("/api/chat", headers, enabled=True)[:2] == (False, 403)
    assert decision("/api/phone/admin/devices", headers, enabled=True)[:2] == (False, 403)
    assert decision("/api/v1/status", headers, enabled=True)[:2] == (True, 200)
    assert decision("/api/v1/status", headers, enabled=False)[:2] == (False, 503)
    assert decision("/api/chat", {}, enabled=False)[:2] == (True, 200)


def test_public_status_is_real_and_contains_no_private_runtime_data() -> None:
    from reyes_agent.remote_access.api import remote_public_status

    result = remote_public_status()
    assert result["core"] in {"online", "standby", "degraded"}
    assert isinstance(result["missions_active"], int)
    assert isinstance(result["skills_approved"], int)
    serialized = json.dumps(result).casefold()
    for forbidden in ("provider", "device", "owner", "memory text", "path", "audit"):
        assert forbidden not in serialized


def test_permission_changes_are_durable_and_financial_stays_locked() -> None:
    from reyes_agent import permissions

    original_path = permissions._OVERRIDE_FILE
    with tempfile.TemporaryDirectory() as folder:
        try:
            permissions._OVERRIDE_FILE = Path(folder) / "overrides.json"
            assert permissions.set_state("email_send", "blocked") == permissions.BLOCKED
            assert permissions.state_for("email_send") == permissions.BLOCKED
            saved = json.loads(permissions._OVERRIDE_FILE.read_text(encoding="utf-8"))
            assert saved["capabilities"]["email_send"] == "blocked"
            try:
                permissions.set_state("financial", "enabled")
            except PermissionError:
                pass
            else:  # pragma: no cover
                raise AssertionError("The permission UI must not unlock financial execution.")
        finally:
            permissions._OVERRIDE_FILE = original_path


def test_audit_redacts_secrets_and_keeps_structured_outcome() -> None:
    from reyes_agent import audit

    original_dir, original_path = audit._LOG_DIR, audit._LOG_PATH
    with tempfile.TemporaryDirectory() as folder:
        try:
            audit._LOG_DIR = Path(folder)
            audit._LOG_PATH = Path(folder) / "audit.log"
            secret = "sk-super-secret-provider-value-123456789"
            audit.log("test", actor="owner", action_type="provider.validate",
                      outcome="failed", api_key=secret,
                      detail=f"api_key={secret}")
            raw = audit._LOG_PATH.read_text(encoding="utf-8")
            row = json.loads(raw)
            assert secret not in raw
            assert row["api_key"] == "[REDACTED]"
            assert row["outcome"] == "failed" and row["actor"] == "owner"
            assert row["ts_epoch"] <= time.time()
        finally:
            audit._LOG_DIR, audit._LOG_PATH = original_dir, original_path


def test_living_memory_health_is_a_real_non_record_probe() -> None:
    from reyes_agent import living_memory

    result = living_memory.health()
    assert result["state"] in {"ONLINE", "DEGRADED"}, result
    assert result["readable"] is True and result["writable"] is True
    assert not (living_memory.ROOT / ".healthcheck.json").exists()


def test_first_run_creates_no_fake_user_and_owner_survives_reopen() -> None:
    from reyes_agent import audit, user_profiles

    original_path = user_profiles._DB_PATH
    original_audit_dir, original_audit_path = audit._LOG_DIR, audit._LOG_PATH
    with tempfile.TemporaryDirectory() as folder:
        try:
            user_profiles._DB_PATH = Path(folder) / "identity.sqlite3"
            audit._LOG_DIR = Path(folder) / "audit"
            audit._LOG_PATH = audit._LOG_DIR / "audit.log"
            assert user_profiles.status()["state"] == "SETUP_REQUIRED"
            assert user_profiles.owner() is None
            created = user_profiles.create_owner(
                "Divine", timezone="Africa/Lagos", language_preferences=["English", "Pidgin"]
            )
            assert created["role"] == user_profiles.OWNER
            # Every call opens a fresh SQLite connection: this is a restart-like
            # persistence check, not an in-memory object assertion.
            reopened = user_profiles.owner()
            assert reopened and reopened["display_name"] == "Divine"
            assert reopened["language_preferences"] == ["English", "Pidgin"]
            assert user_profiles.status()["schema_version"] == 1
        finally:
            user_profiles._DB_PATH = original_path
            audit._LOG_DIR, audit._LOG_PATH = original_audit_dir, original_audit_path


def test_onboarding_status_uses_live_subsystems() -> None:
    from reyes_agent import microphone
    from reyes_agent.web import onboarding_status

    result = onboarding_status()
    assert result["steps"]["owner"] in {"READY", "REQUIRED"}
    assert result["steps"]["microphone"] in microphone._KNOWN_STATUSES
    assert result["steps"]["ai_provider"] in {
        "ONLINE", "CONFIGURED", "FAILED", "NOT_CONFIGURED",
    }


def test_individually_scheduled_core_service_advances_kernel_stage() -> None:
    from reyes_agent.kernel import STAGE_CORE, ZenoKernel

    kernel = ZenoKernel()
    try:
        kernel.register_service("reality-core", stage=STAGE_CORE, start=lambda: None)
        kernel.start_service("reality-core")
        assert kernel.diagnostics()["stage"] == STAGE_CORE
    finally:
        kernel.shutdown()


def test_skill_step_requires_verified_tool_evidence() -> None:
    from reyes_agent.skills.executor import _call_tool
    from reyes_agent.tools import TOOLS, Tool

    ordinary = Tool("reality_skill_unverified", "test", {"type": "object"},
                    lambda: "ordinary data returned")
    verified = Tool("reality_skill_verified", "test", {"type": "object"},
                    lambda: "postcondition verified")
    with _isolated_runtime_writes():
        TOOLS[ordinary.name] = ordinary
        TOOLS[verified.name] = verified
        try:
            assert _call_tool(ordinary.name, {})[0] is False
            assert _call_tool(verified.name, {})[0] is True
        finally:
            TOOLS.pop(ordinary.name, None)
            TOOLS.pop(verified.name, None)


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
