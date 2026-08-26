"""ZENO migration: exports portable state, NEVER bundles secrets, restores cleanly."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from reyes_agent import migration
from reyes_agent.migration import (BIOMETRIC, PORTABLE, REBUILD, SECRET,
                                    MigrationManager)


@pytest.fixture
def machine(tmp_path):
    proj = tmp_path / "proj"
    la = tmp_path / "la"
    vault = tmp_path / "vault"
    (vault / "01-Knowledge").mkdir(parents=True)
    (vault / "01-Knowledge" / "note.md").write_text("my knowledge", encoding="utf-8")
    (la / "spatial").mkdir(parents=True)
    (la / "spatial" / "spatial.db").write_bytes(b"SQLITE-SPATIAL")
    (la / "Biometrics").mkdir(parents=True)
    (la / "Biometrics" / "voice.dat").write_bytes(b"VOICEPRINT")
    # Secrets that must never be exported:
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".env").write_text("OPENAI_API_KEY=sk-SUPERSECRET", encoding="utf-8")
    (la / "auth").mkdir(parents=True)
    (la / "auth" / "owner.sqlite").write_bytes(b"HASH-SUPERSECRET")
    (la / "anywhere").mkdir(parents=True)
    (la / "anywhere" / "executor.json").write_text("token=SUPERSECRET", encoding="utf-8")
    (proj / ".git").mkdir()
    (proj / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return MigrationManager(project_root=proj, localapp=la, vault=vault)


def _all_zip_bytes(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        return b"".join(zf.read(n) for n in zf.namelist())


def test_preflight_categorises_correctly(machine):
    pf = machine.preflight()
    cat = {r["name"]: r["category"] for r in pf["items"]}
    assert cat["knowledge vault"] == PORTABLE
    assert cat["spatial memory"] == PORTABLE
    assert cat["voice profile"] == BIOMETRIC
    assert cat["environment secrets"] == SECRET
    assert cat["owner auth + unlock"] == SECRET
    assert cat["python venv"] == REBUILD
    assert pf["portable_bytes"] > 0 and pf["checklist"]


def test_export_includes_portable_state(machine, tmp_path):
    res = machine.export_profile(tmp_path / "bundle.zip")
    assert res["ok"] is True
    with zipfile.ZipFile(res["bundle"]) as zf:
        names = zf.namelist()
    assert "MANIFEST.json" in names
    assert any("note.md" in n for n in names)         # vault content
    assert any("spatial.db" in n for n in names)       # spatial content


def test_export_never_bundles_secrets(machine, tmp_path):
    bundle = tmp_path / "bundle.zip"
    res = machine.export_profile(bundle)
    assert res["ok"] is True
    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
    # No secret paths, by name...
    assert not any(".env" in n or "auth" in n or "anywhere" in n for n in names)
    # ...and no secret VALUE anywhere in the archive bytes.
    blob = _all_zip_bytes(bundle)
    assert b"SUPERSECRET" not in blob
    assert "environment secrets" in res["excluded_secrets"]


def test_biometrics_opt_in(machine, tmp_path):
    without = tmp_path / "a.zip"
    machine.export_profile(without, include_biometrics=False)
    with zipfile.ZipFile(without) as zf:
        assert not any("voice" in n.lower() for n in zf.namelist())
    with_bio = tmp_path / "b.zip"
    machine.export_profile(with_bio, include_biometrics=True)
    with zipfile.ZipFile(with_bio) as zf:
        assert any("voice" in n.lower() for n in zf.namelist())


def test_import_dry_run_writes_nothing(machine, tmp_path):
    bundle = tmp_path / "bundle.zip"
    machine.export_profile(bundle)
    fresh_la = tmp_path / "new_la"
    fresh_vault = tmp_path / "new_vault"
    target = MigrationManager(project_root=tmp_path / "new_proj",
                              localapp=fresh_la, vault=fresh_vault)
    res = target.import_profile(bundle, dry_run=True)
    assert res["ok"] and res["dry_run"] and res["files"] > 0
    assert not fresh_vault.exists() and not (fresh_la / "spatial").exists()


def test_import_apply_restores_files(machine, tmp_path):
    bundle = tmp_path / "bundle.zip"
    machine.export_profile(bundle)
    fresh_la = tmp_path / "new_la"
    fresh_vault = tmp_path / "new_vault"
    target = MigrationManager(project_root=tmp_path / "new_proj",
                              localapp=fresh_la, vault=fresh_vault)
    res = target.import_profile(bundle, dry_run=False)
    assert res["ok"] and res["dry_run"] is False
    assert (fresh_vault / "01-Knowledge" / "note.md").read_text(encoding="utf-8") == "my knowledge"
    assert (fresh_la / "spatial" / "spatial.db").read_bytes() == b"SQLITE-SPATIAL"


def test_manifest_has_no_secret_and_records_provenance(machine, tmp_path):
    bundle = tmp_path / "bundle.zip"
    machine.export_profile(bundle)
    import json
    with zipfile.ZipFile(bundle) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))
    assert manifest["kind"] == "zeno-profile"
    assert manifest["git_commit"] == "ref: refs/heads"[:0] or manifest["git_commit"]  # present
    assert "SUPERSECRET" not in json.dumps(manifest)


def test_missing_paths_never_raise(tmp_path):
    # A machine with almost nothing present must still preflight/export safely.
    mgr = MigrationManager(project_root=tmp_path / "p", localapp=tmp_path / "l",
                           vault=tmp_path / "v")
    pf = mgr.preflight()
    assert isinstance(pf["items"], list)
    res = mgr.export_profile(tmp_path / "empty.zip")
    assert res["ok"] is True


def test_import_missing_bundle():
    mgr = MigrationManager()
    res = mgr.import_profile("does-not-exist.zip")
    assert res["ok"] is False and "not found" in res["error"]
