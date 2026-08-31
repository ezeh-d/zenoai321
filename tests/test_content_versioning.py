"""Content versioning (#17) and verify-on-write save (#18).

The safety contract: an AI edit is always recoverable, the original is never
lost, and a write is never called a success until it is verified.
"""

from __future__ import annotations

import pytest

from reyes_agent.content.versioning import VersionManager
from reyes_agent.content import save as save_mod


@pytest.fixture()
def vm(tmp_path):
    return VersionManager(root=tmp_path / "versions")


# --- versioning: undo / redo / revert ---------------------------------------
def test_checkpoint_and_history(tmp_path, vm):
    f = tmp_path / "doc.txt"; f.write_text("AAA")
    assert vm.checkpoint(f)["ok"]
    h = vm.history(f)
    assert h["ok"] and len(h["versions"]) == 1 and h["versions"][0]["current"]


def test_identical_checkpoint_is_a_noop(tmp_path, vm):
    f = tmp_path / "doc.txt"; f.write_text("AAA")
    vm.checkpoint(f)
    again = vm.checkpoint(f)
    assert again["ok"] and again.get("unchanged")
    assert len(vm.history(f)["versions"]) == 1


def test_undo_restores_previous_content(tmp_path, vm):
    f = tmp_path / "doc.txt"
    f.write_text("AAA"); vm.checkpoint(f)
    f.write_text("BBB"); vm.checkpoint(f)
    assert vm.undo(f)["ok"]
    assert f.read_text() == "AAA"


def test_redo_reapplies(tmp_path, vm):
    f = tmp_path / "doc.txt"
    f.write_text("AAA"); vm.checkpoint(f)
    f.write_text("BBB"); vm.checkpoint(f)
    vm.undo(f)
    assert vm.redo(f)["ok"]
    assert f.read_text() == "BBB"


def test_revert_returns_to_the_original(tmp_path, vm):
    f = tmp_path / "doc.txt"
    f.write_text("ORIGINAL"); vm.checkpoint(f)
    f.write_text("v2"); vm.checkpoint(f)
    f.write_text("v3"); vm.checkpoint(f)
    assert vm.revert(f)["ok"]
    assert f.read_text() == "ORIGINAL"


def test_undo_captures_an_uncheckpointed_edit(tmp_path, vm):
    # edit WITHOUT checkpointing, then undo -> the edit is preserved as redo.
    f = tmp_path / "doc.txt"
    f.write_text("AAA"); vm.checkpoint(f)
    f.write_text("DIRTY")            # ZENO edited but didn't checkpoint
    assert vm.undo(f)["ok"]
    assert f.read_text() == "AAA"    # went back
    assert vm.redo(f)["ok"]
    assert f.read_text() == "DIRTY"  # the edit was not lost


def test_undo_with_no_history_is_honest(tmp_path, vm):
    f = tmp_path / "doc.txt"; f.write_text("x")
    r = vm.undo(f)
    assert r["ok"] is False and "no restore points" in r["error"]


def test_the_original_is_never_destroyed(tmp_path, vm):
    f = tmp_path / "doc.txt"
    f.write_text("KEEP ME"); vm.checkpoint(f)
    for i in range(5):
        f.write_text(f"edit{i}"); vm.checkpoint(f)
    # after many edits, revert still recovers the very first content
    vm.revert(f)
    assert f.read_text() == "KEEP ME"


# --- save: verify-on-write --------------------------------------------------
@pytest.fixture()
def _tmp_vm(tmp_path, monkeypatch):
    from reyes_agent.content import versioning
    mgr = VersionManager(root=tmp_path / "versions")
    monkeypatch.setattr(versioning, "get_version_manager", lambda: mgr)
    return mgr


def test_write_verified_checkpoints_then_verifies(tmp_path, _tmp_vm):
    f = tmp_path / "report.txt"; f.write_text("old content")
    r = save_mod.write_verified(f, "new content 2026", expect_contains="2026")
    assert r["ok"] and r["verified"]["change_present"]
    assert f.read_text() == "new content 2026"
    assert r["checkpoint"] is not None            # a restore point was made
    assert _tmp_vm.undo(f)["ok"] and f.read_text() == "old content"  # recoverable


def test_write_verified_fails_when_change_absent(tmp_path, _tmp_vm):
    f = tmp_path / "report.txt"; f.write_text("old")
    r = save_mod.write_verified(f, "something else", expect_contains="MISSING")
    assert r["ok"] is False and r["verified"]["change_present"] is False
    assert r["recoverable"] is True               # still rolls back


def test_verify_write_checks(tmp_path):
    f = tmp_path / "a.json"; f.write_text('{"ok": true}')
    v = save_mod.verify_write(f, expect_contains="ok", expect_format="json")
    assert v["ok"] and v["checks"]["format_ok"] and v["checks"]["exists"]


def test_verify_write_reports_missing_file(tmp_path):
    v = save_mod.verify_write(tmp_path / "nope.txt")
    assert v["ok"] is False and v["checks"]["exists"] is False


def test_save_intent_classification():
    c = save_mod.classify_save_intent
    assert c("save it") == "SAVE"
    assert c("save another copy on my desktop") == "SAVE_AS"
    assert c("turn this into a pdf") == "EXPORT"
    assert c("replace the original") == "OVERWRITE"


# --- tools registered -------------------------------------------------------
def test_version_tools_registered():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    for name in ("content_undo", "content_history"):
        assert name in TOOLS
