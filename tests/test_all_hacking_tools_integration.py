from __future__ import annotations

import zipfile

from reyes_agent.security.testing import archive_catalog, authorization


TOOLS_MD = """## Information Gathering
- <a href="https://example.test/whatweb">WhatWeb</a>
- <a href="https://example.test/nmap">AstraNmap</a>
## Web Attack Tools
- <a href="https://example.test/sqlmap">SqlMap</a>
- <a href="https://example.test/Ultra-DDos">Ultra-DDos</a>
## Phishing And IpHack
- <a href="https://example.test/zphisher">Zphisher</a>
- <a href="https://example.test/iphack">IpHack</a>
"""


def _archive(tmp_path, *, traversal: bool = False):
    path = tmp_path / "AllHackingTools-main.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AllHackingTools-main/.github/TOOLS.md", TOOLS_MD)
        archive.writestr("AllHackingTools-main/Files/WebFiles.sh", "git clone example")
        archive.writestr("AllHackingTools-main/Castom/ngrok", b"binary")
        if traversal:
            archive.writestr("../escape.py", "bad")
    return path


def test_archive_is_inventory_only_and_every_reference_is_classified(tmp_path):
    report = archive_catalog.inspect(_archive(tmp_path))
    assert report["available"] is True
    assert report["entry_count"] == 3
    assert report["tool_count"] == 6
    assert sum(report["tool_counts"].values()) == 6
    assert report["entry_counts"][archive_catalog.QUARANTINED_INSTALLER] == 2
    assert "never imported, extracted, installed or executed" in report["execution_policy"]


def test_harmful_archive_tools_are_blocked_not_scope_gated(tmp_path):
    path = _archive(tmp_path)
    for name in ("Ultra-DDos", "Zphisher", "IpHack"):
        result = archive_catalog.route(name, "10.0.0.5", archive_path=path)
        assert result["allowed"] is False
        assert result["state"] == archive_catalog.BLOCKED


def test_authorized_candidate_requires_real_scope_and_archive_never_executes(tmp_path):
    path = _archive(tmp_path)
    scope = authorization.reset_for_tests(tmp_path / "scope.sqlite")
    denied = archive_catalog.route("SqlMap", "10.0.0.5", archive_path=path)
    assert denied["allowed"] is False
    scope.authorize("10.0.0.5", "ctf_or_lab")
    allowed = archive_catalog.route("SqlMap", "10.0.0.5", archive_path=path)
    assert allowed["allowed"] is True
    assert "archive code stays quarantined" in allowed["reason"]


def test_traversal_archive_is_rejected_without_extraction(tmp_path):
    report = archive_catalog.inspect(_archive(tmp_path, traversal=True))
    assert report["available"] is False
    assert "unsafe" in report["reason"].casefold()


def test_ava_owns_the_safe_archive_catalog_tool():
    from reyes_agent.tools import TOOLS
    from reyes_agent.tools.subagents import _SPECIALISTS

    assert "security_archive_catalog" in TOOLS
    assert "security_archive_catalog" in _SPECIALISTS["ava"]["tools"]
    assert TOOLS["security_archive_catalog"].requires_confirmation is False


def test_real_owner_archive_is_bounded_and_classified_when_present():
    report = archive_catalog.inspect()
    if not report.get("available"):
        return
    assert report["entry_count"] <= 2_000
    assert report["tool_count"] > 40
    assert report["tool_counts"][archive_catalog.BLOCKED] > 0
    assert report["tool_counts"][archive_catalog.AUTHORIZED_TESTING] > 0
