"""Regression coverage for the evidence-backed Live Project Activity View."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_new_project_requires_a_destination_before_writing() -> None:
    from reyes_agent import project_activity
    from reyes_agent import config
    from reyes_agent import notification_bus
    from reyes_agent.tools import projects

    with tempfile.TemporaryDirectory() as raw:
        previous_vault = config.VAULT_PATH
        previous_emit = project_activity._emit
        previous_publish = notification_bus.publish
        try:
            config.VAULT_PATH = Path(raw) / "vault"
            project_activity._projects.clear()
            project_activity._emit = lambda *_args: None
            notification_bus.publish = lambda *_args: None
            result = projects.write_project_file("A new project", "index.html", "<h1>hello</h1>")
            # The guarantee is behavioural: nothing is written without a
            # destination (asserted below). The message must now drive a
            # RETRY rather than a hand-off to chat -- the old "ask Divine
            # where to save it" wording made the model stop and ask even
            # when the request had already said "on my Desktop", which is
            # why ZENO described work instead of doing it.
            assert "NOT SAVED YET" in result
            assert "destination" in result
            assert "call write_project_file again" in result.lower()   # retry, not chat
            assert not (config.VAULT_PATH / "02-Projects" / "a-new-project").exists()
            status = project_activity.status()[0]
            assert status["state"] == "WAITING"
            assert status["progress_percent"] is None
        finally:
            project_activity._emit = previous_emit
            notification_bus.publish = previous_publish
            project_activity._projects.clear()
            config.VAULT_PATH = previous_vault


def test_selected_destination_and_file_activity_are_real_and_bounded() -> None:
    from reyes_agent import project_activity
    from reyes_agent import config
    from reyes_agent import notification_bus
    from reyes_agent.tools import projects

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        previous_vault = config.VAULT_PATH
        previous_emit = project_activity._emit
        previous_publish = notification_bus.publish
        try:
            config.VAULT_PATH = root / "vault"
            project_activity._projects.clear()
            project_activity._emit = lambda *_args: None
            notification_bus.publish = lambda *_args: None
            result = projects.write_project_file("Demo Site", "index.html", "<h1>Demo</h1>", str(root / "Desktop"))
            target = root / "Desktop" / "demo-site" / "index.html"
            assert target.read_text(encoding="utf-8") == "<h1>Demo</h1>"
            # Windows may spell the same user profile via its 8.3 alias in
            # tempfile paths; compare the resolved filesystem target, not
            # the cosmetic path string returned to the user.
            assert "Wrote " in result and result.endswith("(13 chars).")
            status = project_activity.status()[0]
            assert Path(status["project_path"]).samefile(target.parent)
            assert status["files"] == ["index.html"]
            assert status["tools"] == ["write_project_file"]
            assert status["completed_steps"] >= 1
            assert status["progress_percent"] is None
            assert status["preview"] == {"file": "index.html", "content": "<h1>Demo</h1>"}
        finally:
            project_activity._emit = previous_emit
            notification_bus.publish = previous_publish
            project_activity._projects.clear()
            config.VAULT_PATH = previous_vault


def test_activity_view_and_destination_api_are_event_driven() -> None:
    source = (ROOT / "reyes_agent" / "static" / "activity_view.js").read_text(encoding="utf-8")
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    project_tool = (ROOT / "reyes_agent" / "tools" / "projects.py").read_text(encoding="utf-8")
    assert "project.activity" in source
    assert "progress_percent" in source
    assert "no estimated percentage" in source
    assert "setInterval" not in source
    assert "zeno-project-destination-selected" in source
    assert '"/api/projects/destination"' in web
    assert "ask Divine where to save" in project_tool


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
