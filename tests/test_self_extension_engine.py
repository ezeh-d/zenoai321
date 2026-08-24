from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from reyes_agent.extensions.adapter import AdapterGenerator
from reyes_agent.extensions.engine import SelfExtensionEngine
from reyes_agent.extensions.inspection import CompatibilityAnalyzer, IntegrationPlanner, RepositoryInspector
from reyes_agent.extensions.models import (
    APPROVAL, DISCOVERED, GITHUB_DIRECTORY, GITHUB_FILE, GITHUB_RELEASE,
    GITHUB_REPOSITORY, QUARANTINED, REJECTED,
)
from reyes_agent.extensions.registry import ExtensionRegistry
from reyes_agent.extensions.source import GitHubImportEngine, SourceError, parse_source


def make_engine(tmp_path: Path) -> SelfExtensionEngine:
    return SelfExtensionEngine(registry=ExtensionRegistry(tmp_path / "catalog"))


@pytest.mark.parametrize(("source", "kind"), [
    ("https://github.com/pallets/click", GITHUB_REPOSITORY),
    ("https://github.com/pallets/click.git", GITHUB_REPOSITORY),
    ("https://github.com/pallets/click/blob/main/src/click/core.py", GITHUB_FILE),
    ("https://github.com/pallets/click/tree/main/src", GITHUB_DIRECTORY),
    ("https://github.com/pallets/click/releases/tag/8.3.0", GITHUB_RELEASE),
])
def test_parse_github_sources(source: str, kind: str) -> None:
    reference = parse_source(source)
    assert reference.kind == kind
    assert reference.owner == "pallets"
    assert reference.repository == "click"


def test_parse_package_and_missing_source() -> None:
    assert parse_source("pip:httpx").package == "httpx"
    assert parse_source("npm:@modelcontextprotocol/sdk").package == "@modelcontextprotocol/sdk"
    assert parse_source("model:owner/model-adapter").kind == "MODEL_ADAPTER"
    assert parse_source("adapter:owner/tool-adapter").kind == "TOOL_ADAPTER"
    with pytest.raises(SourceError):
        parse_source("")
    with pytest.raises(SourceError):
        parse_source("not a source")


def test_github_client_only_allows_official_api_endpoint() -> None:
    with pytest.raises(SourceError, match="unexpected endpoint"):
        GitHubImportEngine()._request("https://example.com/repository")


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.py", "print('no')")
    with pytest.raises(SourceError, match="unsafe path"):
        GitHubImportEngine().inspect_source(archive)
    assert not (tmp_path.parent / "escape.py").exists()


def test_tar_traversal_is_rejected_without_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar"
    payload = tmp_path / "payload.py"
    payload.write_text("print('no')", encoding="utf-8")
    with tarfile.open(archive, "w") as handle:
        handle.add(payload, arcname="../escape.py")
    with pytest.raises(SourceError, match="unsafe path"):
        GitHubImportEngine().inspect_source(archive)
    assert not (tmp_path.parent / "escape.py").exists()


def test_safe_document_only_source_reaches_approval_not_active(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    (source / "README.md").write_text("# Harmless parser documentation", encoding="utf-8")
    (source / "LICENSE").write_text("MIT License\nPermission is hereby granted", encoding="utf-8")
    result = make_engine(tmp_path).inspect(source)
    assert result["state"] == APPROVAL
    assert result["feature_enabled"] is False
    assert result["adapter"]["generated_code"] is False
    assert result["adapter"]["implementation_state"] == "PLANNED_NOT_EXECUTABLE"


def test_unknown_executable_code_is_quarantined_not_run(tmp_path: Path) -> None:
    source = tmp_path / "code"
    source.mkdir()
    marker = tmp_path / "must-not-exist.txt"
    (source / "main.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    result = make_engine(tmp_path).inspect(source)
    assert result["state"] == QUARANTINED
    assert result["health"] == "NOT_EXECUTED"
    assert not marker.exists()
    sandbox = next(row for row in result["tests"] if row["name"] == "sandbox_execution")
    assert sandbox["state"] == "BLOCKED"


def test_prohibited_purpose_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad-purpose"
    source.mkdir()
    (source / "README.md").write_text("A credential theft and phishing toolkit", encoding="utf-8")
    result = make_engine(tmp_path).inspect(source)
    assert result["state"] == REJECTED
    assert result["health"] == "REJECTED"
    assert result["rejection_reasons"][0]["category"] == "prohibited_purpose"


def test_hard_coded_secret_is_rejected_and_redacted_from_catalog(tmp_path: Path) -> None:
    source = tmp_path / "secret"
    source.mkdir()
    fake = "AKIA" + "A" * 16
    (source / "main.py").write_text(f"key = {fake!r}\n", encoding="utf-8")
    engine = make_engine(tmp_path)
    result = engine.inspect(source)
    assert result["state"] == REJECTED
    catalog = engine.registry.path.read_text(encoding="utf-8")
    assert fake not in catalog


def test_uninspected_package_reference_stays_quarantined(tmp_path: Path) -> None:
    result = make_engine(tmp_path).inspect("pip:example-package")
    assert result["state"] == QUARANTINED
    assert result["health"] == "INCOMPLETE_INSPECTION"


def test_static_reports_permissions_license_and_components(tmp_path: Path) -> None:
    source = tmp_path / "tool"
    source.mkdir()
    (source / "main.py").write_text(
        "import subprocess\nimport requests\nsubprocess.run(['echo', 'ok'])\n"
        "requests.get('https://api.example.test/data')\n",
        encoding="utf-8",
    )
    (source / "LICENSE").write_text("Apache License Version 2.0", encoding="utf-8")
    importer = GitHubImportEngine()
    snapshot = importer.inspect_source(source)
    report = RepositoryInspector().inspect(snapshot)
    compatibility = CompatibilityAnalyzer().analyze(snapshot, report)
    plan = IntegrationPlanner().plan(snapshot, report, compatibility)
    assert report.license == "Apache-2.0"
    assert report.permissions.subprocess is True
    assert "api.example.test" in report.permissions.network
    assert plan.components
    assert AdapterGenerator().generate("ext_test", snapshot, plan)["execution"] == "isolated_worker_required"


def test_supply_chain_and_trust_are_measured_not_claimed_safe(tmp_path: Path) -> None:
    source = tmp_path / "node"
    source.mkdir()
    (source / "package.json").write_text(json.dumps({
        "scripts": {"postinstall": "node setup.js"},
        "dependencies": {"left-pad": "*"},
    }), encoding="utf-8")
    result = make_engine(tmp_path).inspect(source)
    supply = result["inspection"]["supply_chain"]
    assert supply["install_script_count"] == 1
    assert supply["unpinned_count"] == 1
    assert supply["known_vulnerability_scan"] == "NOT_RUN_NO_ADVISORY_PROVIDER"
    assert result["trust"]["score"] < 100
    assert "not proof" in result["trust"]["meaning"].lower()


def test_registry_is_atomic_redacted_and_rejects_lifecycle_skips(tmp_path: Path) -> None:
    registry = ExtensionRegistry(tmp_path / "registry")
    record = registry.create({"original": "local:test", "api_token": "must-not-persist"})
    assert record["state"] == DISCOVERED
    persisted = json.loads(registry.path.read_text(encoding="utf-8"))
    assert persisted["extensions"][record["id"]]["source"]["api_token"] == "[REDACTED]"
    with pytest.raises(ValueError, match="invalid extension transition"):
        registry.transition(record["id"], APPROVAL, "skip every gate")


def test_approval_does_not_activate_without_real_adapter(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    (source / "README.md").write_text("Documentation only", encoding="utf-8")
    engine = make_engine(tmp_path)
    record = engine.inspect(source)
    result = engine.approve(record["id"])
    assert result["ok"] is False
    assert "not working code" in result["reason"]
    assert engine.registry.get(record["id"])["state"] == APPROVAL


def test_real_adapter_requires_canary_evidence_and_unregisters_cleanly(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reyes_agent import feature_flags
    from reyes_agent.tools.universal_registry import (
        READY, ToolExecution, ToolHealth, ToolMetadata, get_global_tool_registry,
    )

    class FakeAdapter:
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                "zeno.extension.test.v1", "extension_test_capability", "test adapter",
                "extensions", "test", "1", {"type": "object"}, {"type": "object"},
                (), ("zeno-core",), False, False,
            )

        def health(self) -> ToolHealth:
            return ToolHealth(READY, "test health passed", "enabled", {"zeno-core": "ONLINE"})

        def validate(self, args: dict) -> tuple[bool, str]:
            return True, "valid"

        async def execute(self, *args, **kwargs) -> ToolExecution:
            return ToolExecution("test", "zeno.extension.test.v1", True, "VERIFIED")

        async def cancel(self, execution_id: str) -> dict:
            return {"ok": True}

        def required_permissions(self) -> tuple[str, ...]:
            return ()

        def supported_devices(self) -> tuple[str, ...]:
            return ("zeno-core",)

        def verify(self, result) -> dict:
            return {"verified": True}

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr(feature_flags, "_instance", feature_flags.FeatureFlags(tmp_path / "flags.json"))
    source = tmp_path / "docs-canary"
    source.mkdir()
    (source / "README.md").write_text("adapter documentation", encoding="utf-8")
    engine = make_engine(tmp_path)
    review = engine.inspect(source)
    approved = engine.approve(review["id"], FakeAdapter())
    assert approved["ok"] is True
    assert approved["extension"]["state"] == "CANARY"
    assert get_global_tool_registry().get("zeno.extension.test.v1") is not None
    refused = engine.record_canary(review["id"], passed=True, evidence={})
    assert refused["ok"] is False
    active = engine.record_canary(review["id"], passed=True,
                                  evidence={"verification": "VERIFIED", "case": "smoke"})
    assert active["extension"]["state"] == "ACTIVE"
    assert active["extension"]["known_good"]
    disabled = engine.disable(review["id"])
    assert disabled["ok"] is True
    assert get_global_tool_registry().get("zeno.extension.test.v1") is None


def test_tool_registration_confirmation_and_routing() -> None:
    from reyes_agent.routing.capability import tools_for
    from reyes_agent.tools import TOOLS

    assert TOOLS["extension_inspect"].requires_confirmation is False
    for name in ("extension_approve", "extension_rollback", "extension_remove"):
        assert TOOLS[name].requires_confirmation is True
    route = tools_for("ZENO add this https://github.com/pallets/click")
    assert route.capabilities == ("extensions",)
    assert "extension_inspect" in route.tools


def test_extension_removal_cannot_unregister_native_tool() -> None:
    from reyes_agent.tools.universal_registry import get_global_tool_registry
    registry = get_global_tool_registry()
    native = registry.get("extension_status")
    assert native is not None
    with pytest.raises(ValueError, match="native tool"):
        registry.unregister("extension_status")
    assert registry.get("extension_status") is native


def test_mission_control_has_lazy_extensions_section() -> None:
    source = Path("reyes_agent/mission_control.py").read_text(encoding="utf-8")
    frontend = Path("reyes_agent/static/mission_control.js").read_text(encoding="utf-8")
    assert '"EXTENSIONS": extensions' in source
    assert "'EXTENSIONS'" in frontend
