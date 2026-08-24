from __future__ import annotations

import asyncio
import json
import sys
import threading

import pytest
from starlette.requests import Request


def _request(host: str = "127.0.0.1") -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/tool-library", "raw_path": b"/api/tool-library",
        "query_string": b"", "headers": [], "client": (host, 45678),
        "server": ("127.0.0.1", 8765),
    })


def test_master_catalog_has_every_number_once_and_only_supported_states() -> None:
    from reyes_agent.tools import universal_catalog

    rows = universal_catalog.sections()
    assert [row.number for row in rows] == list(range(1, 149))
    assert len({row.title for row in rows}) == 148
    assert all(row.state in universal_catalog.STATES for row in rows)
    assert all(row.evidence.strip() for row in rows)


def test_optional_provider_inventory_is_lazy_honest_and_secret_free() -> None:
    from reyes_agent.tools import universal_catalog

    forbidden_values = {
        value for key, value in __import__("os").environ.items()
        if value and any(marker in key.casefold() for marker in ("key", "token", "secret", "password"))
    }
    before_threads = threading.active_count()
    optional_before = {name: name in sys.modules for name in (
        "docling", "paddleocr", "langgraph", "crewai", "temporalio",
    )}
    rows = universal_catalog.provider_candidates()

    assert len(rows) >= 50
    assert all(row["state"] in universal_catalog.STATES for row in rows)
    assert all(row["reason"] for row in rows)
    assert all(
        all(secret not in json.dumps(row) for secret in forbidden_values if len(secret) >= 8)
        for row in rows
    )
    assert {name: name in sys.modules for name in optional_before} == optional_before
    assert threading.active_count() == before_threads


def test_every_executable_tool_implements_the_universal_contract() -> None:
    from reyes_agent.tools import TOOLS
    from reyes_agent.tools.universal_registry import (
        contract_status,
        get_global_tool_registry,
    )

    registry = get_global_tool_registry()
    adapters = registry.all()
    status = contract_status()

    assert len(adapters) == len(TOOLS)
    assert len({item.metadata().tool_id for item in adapters}) == len(adapters)
    assert status["state"] == "READY"
    assert status["contract_failures"] == []
    assert registry.health()["duplicate_runtime"] is False
    assert registry.health()["execution_authority"] == "reyes_agent.tools.run_tool"


def test_registry_finds_tool_by_capability_and_device() -> None:
    from reyes_agent.tools.universal_registry import get_global_tool_registry

    registry = get_global_tool_registry()
    assert any(item.metadata().name == "get_datetime"
               for item in registry.find_by_capability("date time"))
    assert any(item.metadata().name == "open_app"
               for item in registry.find_by_device("local-windows"))
    resolution = registry.resolve_best_tool("date time")
    assert resolution is not None
    assert resolution["tool"]["metadata"]["name"] == "get_datetime"
    assert resolution["tool"]["health"]["usable"] is True


def test_permission_engine_can_disable_a_normalized_adapter(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from reyes_agent import permissions
    from reyes_agent.tools.universal_registry import DISABLED, get_global_tool_registry

    adapter = get_global_tool_registry().get("get_datetime")
    assert adapter is not None
    original = permissions.check
    monkeypatch.setattr(
        permissions, "check",
        lambda name: permissions.BLOCKED if name == "get_datetime" else original(name),
    )
    health = adapter.health()
    assert health.state == DISABLED
    assert not health.usable


def test_adapter_validation_and_read_only_execution_are_real() -> None:
    from reyes_agent.tools.universal_registry import get_global_tool_registry

    registry = get_global_tool_registry()
    search = registry.get("universal_tool_catalog")
    assert search is not None
    valid, reason = search.validate({"limit": "not-an-integer"})
    assert not valid
    assert "integer" in reason

    adapter = registry.get("get_datetime")
    assert adapter is not None
    execution = asyncio.run(adapter.execute({}, {"timeout_s": 10}))
    assert execution.ok
    assert execution.result
    assert execution.state == "RETURNED_UNVERIFIED"
    assert execution.verification is not None
    assert execution.verification["verifiable"] is False


def test_catalog_tools_are_read_only_and_remain_out_of_default_payload() -> None:
    from reyes_agent.tools import run_tool, tool_definitions

    default_names = {row["name"] for row in tool_definitions()}
    assert not {"universal_tool_catalog", "universal_tool_health",
                "universal_tool_resolve"} & default_names

    result = json.loads(run_tool("universal_tool_catalog", {"query": "browser", "limit": 8}))
    assert result["section_total"] == 148
    assert result["sections"] or result["providers"]


def test_natural_language_tool_library_request_uses_scoped_diagnostics_route() -> None:
    from reyes_agent.routing.capability import tools_for

    route = tools_for("Open the tool library and show available tools")
    assert route.capabilities == ("diagnostics",)
    assert "universal_tool_catalog" in route.tools
    assert "universal_tool_health" in route.tools
    assert len(route.tools) <= 14  # two essentials + the bounded diagnostic set


def test_tool_library_api_is_loopback_only() -> None:
    from fastapi import HTTPException
    from reyes_agent import web

    result = web.universal_tool_library(_request(), q="voice", limit=5)
    assert result["section_total"] == 148
    assert len(result["sections"]) <= 5
    with pytest.raises(HTTPException) as denied:
        web.universal_tool_library(_request("192.168.1.50"))
    assert denied.value.status_code == 403


def test_dashboard_tool_library_is_on_demand_and_has_no_polling_loop() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "reyes_agent" / "static" / "index.html").read_text(
        encoding="utf-8")
    start = html.index("// --- Universal Capability Library")
    end = html.index("// --- Desktop Companion Mode", start)
    block = html[start:end]
    assert 'id="tool-library-overlay"' in html
    assert "window.zenoToolLibrary" in block
    assert "fetch('/api/tool-library?'" in block
    assert "setInterval" not in block
    assert "toolLibraryRequest.abort()" in block


def test_every_optional_provider_flag_is_registered_and_off_by_default(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from reyes_agent import feature_flags
    from reyes_agent.tools import universal_catalog

    flags = feature_flags.FeatureFlags(tmp_path / "flags.json")
    known = {row["name"]: row for row in flags.all_flags()}
    for provider in universal_catalog.PROVIDERS:
        if provider.feature_flag:
            assert provider.feature_flag in known
            monkeypatch.delenv(f"ZENO_FF_{provider.feature_flag.upper()}", raising=False)
            assert known[provider.feature_flag]["default"] is False
