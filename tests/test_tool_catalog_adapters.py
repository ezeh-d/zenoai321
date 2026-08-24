from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import install
from reyes_agent import ocr


def test_installer_help_and_unknown_arguments_are_real_argparse_paths() -> None:
    with pytest.raises(SystemExit) as help_exit:
        install._parser().parse_args(["--help"])
    assert help_exit.value.code == 0

    with pytest.raises(SystemExit) as bad_exit:
        install._parser().parse_args(["--definitely-not-a-real-option"])
    assert bad_exit.value.code == 2


def test_installer_dry_run_does_not_execute_subprocesses(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: called.append(args))
    assert install.main(["--minimal", "--dry-run", "--skip-doctor"]) == 0
    assert called == []


def test_catalog_safe_mode_does_not_reinstall_unrelated_runtime_groups(
        monkeypatch: pytest.MonkeyPatch) -> None:
    groups: list[list[str]] = []
    monkeypatch.setattr(install, "ensure_pip", lambda **_kwargs: True)
    monkeypatch.setattr(
        install, "pip_install",
        lambda packages, **_kwargs: groups.append(list(packages)) or True,
    )
    assert install.main([
        "--catalog-safe", "--dry-run", "--skip-browser-download", "--skip-doctor",
    ]) == 0
    assert groups == [install.CATALOG_SAFE]


def test_doctor_runs_under_windows_cp1252_without_unicode_crash() -> None:
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "doctor.py"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "UnicodeEncodeError" not in result.stderr
    assert "REYES doctor" in result.stdout


def test_pdf_reader_extracts_real_text_and_honours_bound(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "ZENO PDF capability works")
    document.save(path)
    document.close()

    result = ocr.extract_document_text(path, max_chars=12)
    assert result.ok
    assert result.engine == "pymupdf"
    assert result.text == "ZENO PDF cap"
    assert result.confidence == 1.0


def test_docx_reader_extracts_paragraphs_and_tables(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    path = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_paragraph("ZENO document paragraph")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "stable"
    table.cell(0, 1).text = "reader"
    document.save(path)

    result = ocr.extract_document_text(path)
    assert result.ok
    assert result.engine == "python-docx"
    assert "ZENO document paragraph" in result.text
    assert "stable\treader" in result.text


def test_xlsx_reader_is_read_only_and_bounded(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Evidence"
    sheet.append(["tool", "state"])
    sheet.append(["browser", "verified"])
    workbook.save(path)
    workbook.close()

    result = ocr.extract_document_text(path)
    assert result.ok
    assert result.engine == "openpyxl"
    assert "[Evidence]" in result.text
    assert "browser\tverified" in result.text


def test_pptx_reader_extracts_slide_text(tmp_path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "sample.pptx"
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "ZENO Presentation"
    slide.placeholders[1].text = "Real structured extraction"
    presentation.save(path)

    result = ocr.extract_document_text(path)
    assert result.ok
    assert result.engine == "python-pptx"
    assert "ZENO Presentation" in result.text
    assert "Real structured extraction" in result.text


def test_document_size_limit_fails_before_parser(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    path = tmp_path / "oversized.pdf"
    path.write_bytes(b"not a real pdf")
    monkeypatch.setattr(ocr, "_MAX_DOCUMENT_BYTES", 4)
    result = ocr.extract_document_text(path)
    assert not result.ok
    assert "maximum is 4 bytes" in result.error


def test_capabilities_report_real_document_adapter_availability() -> None:
    state = ocr.capabilities()
    assert state["document_formats"][".pdf"]["package"] == "PyMuPDF"
    assert state["document_formats"][".docx"]["package"] == "python-docx"
    assert state["document_formats"][".xlsx"]["package"] == "openpyxl"
    assert state["document_formats"][".pptx"]["package"] == "python-pptx"
    assert ".doc" in state["legacy_formats_requiring_conversion"]


def test_global_capability_registry_sees_installed_supported_adapters() -> None:
    from reyes_agent.capabilities import registry

    registry.refresh()
    native_documents = registry.get("native_documents")
    pywinauto = registry.get("pywinauto")
    assert native_documents is not None and native_documents.usable
    assert pywinauto is not None and pywinauto.usable


def test_pywinauto_adapter_stays_lazy_when_feature_flag_is_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from reyes_agent.computer.windows import pywinauto_backend

    monkeypatch.delenv("ZENO_PYWINAUTO_ENABLED", raising=False)
    before = "pywinauto" in sys.modules
    assert pywinauto_backend.windows() == []
    assert pywinauto_backend.status()["loaded"] is False
    assert ("pywinauto" in sys.modules) is before


def test_mcp_discovery_retries_one_transient_startup_timeout(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from reyes_agent.tools.mcp import client
    from reyes_agent.tools.mcp.manager import MCPManager
    from reyes_agent.tools.mcp.registry import MCPRegistry

    registry_path = tmp_path / "servers.json"
    registry_path.write_text(json.dumps({"servers": [{
        "name": "catalog-test", "command": sys.executable, "args": ["fixture.py"],
        "permissions": ["filesystem_read"], "trust_level": "reviewed",
        "enabled": True, "startup_timeout_s": 1,
    }]}), encoding="utf-8")
    monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "catalog-test")
    calls = 0

    def transient(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("transient process startup pressure")
        return [{"name": "read", "description": "read", "input_schema": {}}]

    monkeypatch.setattr(client, "run", transient)
    manager = MCPManager(MCPRegistry(registry_path))
    assert manager.discover("catalog-test")[0]["name"] == "read"
    assert calls == 2
    assert manager.status()["discovery_retries"] == 1


def test_mcp_tool_calls_are_not_retried_after_timeout(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from reyes_agent.tools.mcp import client
    from reyes_agent.tools.mcp.manager import MCPManager
    from reyes_agent.tools.mcp.registry import MCPRegistry

    registry_path = tmp_path / "servers.json"
    registry_path.write_text(json.dumps({"servers": [{
        "name": "catalog-test", "command": sys.executable, "args": ["fixture.py"],
        "permissions": ["filesystem_read"], "trust_level": "reviewed",
        "enabled": True, "startup_timeout_s": 1,
    }]}), encoding="utf-8")
    monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "catalog-test")
    manager = MCPManager(MCPRegistry(registry_path))
    manager.registry.get("catalog-test").tools = [{
        "name": "read", "description": "read", "input_schema": {},
        "annotations": {"readOnlyHint": True},
    }]
    calls = 0

    def timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("tool timed out")

    monkeypatch.setattr(client, "run", timeout)
    result = manager.call("catalog-test", "read", require_read_only=True)
    assert not result["ok"]
    assert calls == 1


def test_trusted_local_sandbox_default_remains_bounded_for_loaded_windows() -> None:
    import inspect

    from reyes_agent.sandbox.manager import SandboxManager

    default = inspect.signature(SandboxManager.execute_python).parameters["timeout_s"].default
    assert 20.0 < default <= 60.0
