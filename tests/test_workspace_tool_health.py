from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from reyes_agent.workspace import get_workspace_service
from reyes_agent.workspace.manager import RevisionClock
from reyes_agent.workspace.models import ToolHealthState
from reyes_agent.workspace.registry import HealthProbe, HealthProbeRegistry
from reyes_agent.workspace.service import WorkspaceService
from reyes_agent.workspace.tool_health import ToolHealthManager


@dataclass
class _Metadata:
    name: str
    category: str = "communication"
    description: str = "Test capability"
    permissions: tuple[str, ...] = ("communication",)
    supported_devices: tuple[str, ...] = ("zeno-core",)


@dataclass
class _AdapterHealth:
    state: str = "READY"
    reason: str = "registered"
    permission_state: str = "enabled"


class _Adapter:
    def __init__(self, name: str, *, state: str = "READY",
                 permission: str = "enabled", category: str = "communication") -> None:
        self._metadata = _Metadata(name, category)
        self._health = _AdapterHealth(state, "adapter status", permission)

    def metadata(self):
        return self._metadata

    def health(self):
        return self._health

    def required_permissions(self):
        return self._metadata.permissions


def _probes(name: str, check, *, timeout_s: float = 0.2) -> HealthProbeRegistry:
    registry = HealthProbeRegistry()
    registry.register(HealthProbe(
        name=name,
        category="communication",
        check=check,
        supported_operations=("status",),
        dependencies=("client",),
        permissions_required=("communication",),
        timeout_s=timeout_s,
    ))
    return registry


def test_registration_without_probe_or_execution_is_degraded_not_available() -> None:
    manager = ToolHealthManager(adapters=[_Adapter("slack")], clock=lambda: 10.0)
    try:
        result = manager.check("slack")
    finally:
        manager.close()

    assert result.status is ToolHealthState.DEGRADED
    assert result.available is False
    assert result.initialized is False
    assert result.evidence_source == "registration_only"


@pytest.mark.parametrize(("probe_value", "expected"), [
    ({"ok": True, "initialized": True, "latency_ms": 12}, ToolHealthState.AVAILABLE),
    ({"ok": False, "auth_required": True}, ToolHealthState.AUTH_REQUIRED),
    ({"ok": False, "dependency_missing": "client"}, ToolHealthState.DEPENDENCY_MISSING),
    ({"ok": False, "disconnected": True}, ToolHealthState.DISCONNECTED),
    ({"ok": False, "unavailable": True}, ToolHealthState.UNAVAILABLE),
    ({"ok": False, "error": "bad response"}, ToolHealthState.ERROR),
])
def test_real_probe_maps_specific_public_states(probe_value, expected) -> None:
    manager = ToolHealthManager(probes=_probes("browser", lambda: probe_value))
    try:
        result = manager.check("browser", force=True)
    finally:
        manager.close()

    assert result.status is expected
    assert result.available is (expected is ToolHealthState.AVAILABLE)


def test_concurrent_forced_checks_share_one_inflight_probe() -> None:
    calls = 0
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def probe():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.08)
        return {"ok": True}

    manager = ToolHealthManager(probes=_probes("files", probe))

    def check(_):
        barrier.wait()
        return manager.check("files", force=True)

    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            rows = list(pool.map(check, range(20)))
    finally:
        manager.close()

    assert calls == 1
    assert all(row.status is ToolHealthState.AVAILABLE for row in rows)
    assert len({row.revision for row in rows}) == 1


def test_ttl_cache_avoids_rechecking_until_expired() -> None:
    now = [10.0]
    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return {"ok": True}

    manager = ToolHealthManager(
        probes=_probes("files", probe), ttl_s=30, clock=lambda: now[0])
    try:
        first = manager.check("files")
        second = manager.check("files")
        now[0] = 41.0
        third = manager.check("files")
    finally:
        manager.close()

    assert calls == 2
    assert first.revision == second.revision
    assert third.revision > second.revision


def test_probe_timeout_is_bounded_and_secret_error_is_redacted() -> None:
    def slow_probe():
        time.sleep(0.3)
        return {"ok": False, "error": "token=supersecret"}

    manager = ToolHealthManager(probes=_probes("slow", slow_probe, timeout_s=0.03))
    started = time.perf_counter()
    try:
        result = manager.check("slow", force=True)
    finally:
        manager.close()

    assert time.perf_counter() - started < 0.2
    assert result.status is ToolHealthState.ERROR
    assert "supersecret" not in repr(result.as_dict())


def test_verified_execution_becomes_available_evidence_and_failure_is_retained() -> None:
    now = [20.0]
    manager = ToolHealthManager(adapters=[_Adapter("search_files", category="files")],
                                clock=lambda: now[0])
    try:
        success = manager.observe_execution("search_files", True, 14)
        now[0] = 21.0
        failed = manager.observe_execution("search_files", False, 20, "NETWORK_OFFLINE")
    finally:
        manager.close()

    assert success.status is ToolHealthState.AVAILABLE
    assert success.last_success == 20.0
    assert failed.status is ToolHealthState.DEGRADED
    assert failed.last_success == 20.0 and failed.last_failure == 21.0
    assert failed.last_error_code == "NETWORK_OFFLINE"


def test_capability_summary_uses_matching_live_tool_state() -> None:
    manager = ToolHealthManager(adapters=[_Adapter("slack_send", category="communication")])
    try:
        manager.observe_execution("slack_send", True, 8)
        summary = manager.capability_summary("Slack messages")
    finally:
        manager.close()

    assert summary["capability"] == "Slack messages"
    assert summary["status"] == "AVAILABLE"
    assert summary["tools"][0]["name"] == "slack_send"


def test_public_workspace_service_accessor_is_lazy_singleton() -> None:
    first = get_workspace_service()
    second = get_workspace_service()
    assert first is second
    assert first.running is False


def test_capability_status_tool_prefers_dynamic_health(monkeypatch) -> None:
    from reyes_agent.workspace import service as service_module

    service = WorkspaceService()
    service.health.close()
    service.health = ToolHealthManager(adapters=[_Adapter("slack_send")])
    service.health.observe_execution("slack_send", True, 7)
    monkeypatch.setattr(service_module, "_service", service)
    from reyes_agent.tools.intelligence_tools import capability_status

    try:
        result = json.loads(capability_status("slack"))
    finally:
        service.health.close()

    assert result["status"] == "AVAILABLE"
    assert result["tools"][0]["name"] == "slack_send"
