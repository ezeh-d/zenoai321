"""The four Website Studio limitations, tested as behaviour.

Each test targets one of the gaps the previous review named:

1. repairs were deterministic-only
2. analyzers did not understand webpack/rollup/vitest
3. `npm run build` blocked the caller for up to 300s
4. rollback did not account for dependency changes

Run: `.venv/Scripts/python.exe tests/test_website_autonomy.py`
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TEMP: list[str] = []


def _tmp() -> Path:
    raw = tempfile.mkdtemp(prefix="zeno-auto-")
    _TEMP.append(raw)
    return Path(raw)


def _cleanup() -> None:
    from reyes_agent.executors import jobs

    jobs.shutdown_all()
    time.sleep(0.4)          # let killed process trees release their cwd
    for raw in _TEMP:
        shutil.rmtree(raw, ignore_errors=True)


def _node() -> bool:
    from reyes_agent.executors import terminal

    return terminal.tool_available("node")


def _quiet_website_builder():
    from reyes_agent import website_builder as wb

    wb._emit = lambda *_a, **_k: None
    return wb


# --- 1. autonomous repair ------------------------------------------------

def test_a_model_patch_is_requested_applied_and_verified_without_a_second_command() -> None:
    from reyes_agent import config, task_engine
    from reyes_agent.executors import build_check

    if not _node():
        print("    (node.js absent -- autonomous repair test skipped)")
        return
    wb = _quiet_website_builder()
    root = _tmp()
    config.VAULT_PATH = root / "vault"
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
        encoding="utf-8")
    # Fails until src/App.js contains FIXED -- an error no deterministic
    # rule knows how to repair.
    (app / "build.js").write_text(
        "const fs=require('fs');\n"
        "const s=fs.readFileSync('src/App.js','utf8');\n"
        "if(!s.includes('FIXED')){console.error(\"src/App.js(3,1): error TS2304: "
        "Cannot find name 'foo'.\");process.exit(1);}\n"
        "console.log('built ok');\n", encoding="utf-8")
    (app / "src" / "App.js").write_text("const a = foo;\n", encoding="utf-8")

    seen: list[dict] = []

    def patcher(request: dict):
        seen.append(request)
        return {"files": [{"path": "src/App.js", "content": "const a = 1; // FIXED\n"}]}

    task = task_engine.create("autorepair", plan=["Checking the generated code"])
    report = build_check.verify(task.id, app, patcher=patcher)

    assert seen, "the model must be asked for a patch automatically"
    request = seen[0]
    assert request["errors"] and request["errors"][0]["file"] == "src/App.js"
    assert "src/App.js" in request["sources"], "the model must receive the real source"
    assert "metadata" in request and "previous_attempts" in request

    assert report.ok is True, report.summary()
    assert report.confidence == build_check.MODEL_GENERATED
    assert report.ledger and report.ledger[0]["confidence"] == build_check.MODEL_GENERATED
    assert report.ledger[0]["checkpoint"], "a checkpoint must exist before a model patch"
    assert "FIXED" in (app / "src" / "App.js").read_text(encoding="utf-8")
    assert wb.checkpoints(app), "the checkpoint must be on disk"


def test_a_model_patch_that_does_not_help_is_rolled_back() -> None:
    from reyes_agent import config, task_engine
    from reyes_agent.executors import build_check

    if not _node():
        print("    (node.js absent -- rollback-on-worse test skipped)")
        return
    _quiet_website_builder()
    root = _tmp()
    config.VAULT_PATH = root / "vault"
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
        encoding="utf-8")
    (app / "build.js").write_text(
        'console.error("src/App.js(1,1): error TS2304: Cannot find name \'foo\'.");'
        "process.exit(1);\n", encoding="utf-8")     # always fails
    (app / "src" / "App.js").write_text("ORIGINAL\n", encoding="utf-8")

    def useless(_request: dict):
        return {"files": [{"path": "src/App.js", "content": "STILL BROKEN\n"}]}

    task = task_engine.create("no-help", plan=["Checking the generated code"])
    report = build_check.verify(task.id, app, patcher=useless)

    assert report.ok is False
    assert report.rolled_back is True, "a patch that did not help must be undone"
    assert (app / "src" / "App.js").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_the_repair_budget_is_finite_and_reports_exhaustion() -> None:
    from reyes_agent import config, task_engine
    from reyes_agent.executors import build_check

    if not _node():
        print("    (node.js absent -- exhaustion test skipped)")
        return
    _quiet_website_builder()
    root = _tmp()
    config.VAULT_PATH = root / "vault"
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
        encoding="utf-8")
    (app / "build.js").write_text(
        'console.error("src/App.js(1,1): error TS2304: nope.");process.exit(1);\n', encoding="utf-8")
    (app / "src" / "App.js").write_text("ORIGINAL\n", encoding="utf-8")

    calls = {"n": 0}

    def always_different(_request: dict):
        calls["n"] += 1
        return {"files": [{"path": "src/App.js", "content": f"attempt {calls['n']}\n"}]}

    task = task_engine.create("exhaust", plan=["Checking the generated code"])
    report = build_check.verify(task.id, app, patcher=always_different, max_attempts=2)
    assert report.ok is False
    assert calls["n"] <= build_check.MAX_ATTEMPTS_CEILING, "the loop must not run forever"
    assert report.attempts <= 2
    assert report.confidence == build_check.MANUAL_REQUIRED


def test_a_patch_touching_unrelated_files_is_rejected_whole() -> None:
    from reyes_agent.executors import patching

    root = _tmp() / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "App.js").write_text("original", encoding="utf-8")
    allowed = {"src/app.js"}

    for name, patch in {
        "unrelated file": [{"path": "src/Other.js", "content": "x"}],
        "path traversal": [{"path": "../../escape.js", "content": "x"}],
        "lockfile": [{"path": "package-lock.json", "content": "{}"}],
        "node_modules": [{"path": "node_modules/react/index.js", "content": "x"}],
        "empty content": [{"path": "src/App.js", "content": "  "}],
        "whole rewrite": [{"path": "src/App.js", "content": "x" * (patching.MAX_FILE_BYTES + 1)}],
        "too many files": [{"path": f"src/f{i}.js", "content": "x"}
                           for i in range(patching.MAX_FILES_PER_PATCH + 2)],
    }.items():
        result = patching.apply(root, patching.coerce(patch), allowed_files=allowed)
        assert not result.ok, f"{name} should have been rejected"
        assert result.reason, "a rejection must explain itself"

    # The original is untouched and nothing escaped the project.
    assert (root / "src" / "App.js").read_text(encoding="utf-8") == "original"
    assert not (root.parent.parent / "escape.js").exists()
    # ...while a legitimate, named, scoped patch still applies.
    ok = patching.apply(root, patching.coerce([{"path": "src/App.js", "content": "fixed"}]),
                        allowed_files=allowed)
    assert ok.ok and (root / "src" / "App.js").read_text(encoding="utf-8") == "fixed"


# --- 2. analyzers --------------------------------------------------------

def test_webpack_output_is_structured() -> None:
    from reyes_agent.executors import analyzers, diagnostics as dx

    output = (
        "ERROR in ./src/App.js 12:4-30\n"
        "Module not found: Error: Can't resolve './components/Missing' in '/app/src'\n"
        "ERROR in ./src/legacy.js\n"
        "Module parse failed: Unexpected token (5:12)\n"
    )
    assert "webpack" in analyzers.claimants(output)
    errors = dx.analyze(output)
    assert len(errors) == 2, [e.as_dict() for e in errors]
    missing = next(e for e in errors if e.category == dx.IMPORT)
    assert missing.file == "./src/App.js" and missing.line == 12 and missing.tool == "webpack"
    assert missing.suggested_action
    parse = next(e for e in errors if e.category == dx.BUILD)
    assert parse.line == 5 and parse.column == 12
    # Raw text is always preserved, even when structured.
    assert all(e.as_dict()["raw_message"] for e in errors)


def test_rollup_output_is_structured() -> None:
    from reyes_agent.executors import analyzers, diagnostics as dx

    output = ('[!] Error: Could not resolve "./missing" from src/main.js\n'
              "src/main.js (3:18)\n"
              "[!] (plugin commonjs) SyntaxError: Unexpected token\n"
              "src/legacy.js (12:4)\n")
    assert "rollup" in analyzers.claimants(output)
    errors = dx.analyze(output)
    assert len(errors) == 2, [e.as_dict() for e in errors]
    resolve = next(e for e in errors if e.category == dx.IMPORT)
    # Rollup's location arrives on the NEXT line and must be captured.
    assert resolve.file == "src/main.js" and resolve.line == 3 and resolve.column == 18
    plugin = next(e for e in errors if e.category == dx.JAVASCRIPT)
    assert plugin.code == "commonjs" and plugin.line == 12

    warned = dx.analyze("[!] Circular dependency: src/a.js -> src/b.js -> src/a.js\n")
    assert warned and warned[0].severity == dx.WARNING


def test_vitest_output_is_structured() -> None:
    from reyes_agent.executors import analyzers, diagnostics as dx

    output = ("FAIL  src/math.test.ts > adds numbers correctly\n"
              "AssertionError: expected 3 to be 4\n"
              "  Expected: 4\n"
              "  Received: 3\n"
              " ❯ src/math.test.ts:12:20\n"
              "FAIL  src/api.test.ts > fetches data\n"
              "Test timed out in 5000ms\n")
    assert "vitest" in analyzers.claimants(output)
    errors = dx.analyze(output)
    assert len(errors) == 2, [e.as_dict() for e in errors]
    assertion = errors[0]
    assert assertion.file == "src/math.test.ts" and assertion.line == 12
    assert assertion.code == "adds numbers correctly", "the failing test must be named"
    assert "expected 4" in assertion.likely_cause and "received 3" in assertion.likely_cause
    timeout = errors[1]
    assert timeout.category == dx.RUNTIME and "5000ms" in timeout.likely_cause


def test_analyzers_are_a_registry_and_unknown_output_keeps_its_text() -> None:
    from reyes_agent.executors import analyzers, diagnostics as dx

    assert {"webpack", "rollup", "vitest"} <= set(analyzers.names())
    # Nothing claims plain prose, and the core parser keeps the raw text
    # rather than inventing a file for it.
    assert analyzers.claimants("everything is fine") == []
    vague = dx.analyze("error: something inscrutable happened")
    assert len(vague) == 1
    assert vague[0].file == "" and vague[0].line is None
    assert vague[0].as_dict()["raw_message"], "UNKNOWN must keep the original output"


# --- 3. non-blocking jobs ------------------------------------------------

def test_a_long_build_does_not_block_the_caller() -> None:
    from reyes_agent.executors import jobs

    if not _node():
        print("    (node.js absent -- job test skipped)")
        return
    app = _tmp() / "app"
    app.mkdir(parents=True)
    (app / "slow.js").write_text(
        "let n=0;const t=setInterval(()=>{console.log('step '+(++n));"
        "if(n>=6){clearInterval(t);process.exit(0);}},300);\n", encoding="utf-8")

    started = time.monotonic()
    job, error = jobs.start("node slow.js", app, project="demo", kind=jobs.BUILD)
    elapsed = time.monotonic() - started
    assert job is not None, error
    assert elapsed < 2.0, f"start() blocked for {elapsed:.1f}s"
    assert job.state in {jobs.STARTING, jobs.RUNNING} and job.pid

    # Status is queryable while it runs, and output accumulates.
    output_deadline = time.monotonic() + 4.0
    while time.monotonic() < output_deadline:
        mid = jobs.get(job.id).as_dict()
        if mid["lines"] >= 1:
            break
        time.sleep(0.1)
    assert mid["state"] in {jobs.RUNNING, jobs.SUCCESS} and mid["lines"] >= 1

    done = jobs.wait(job.id, timeout=20)
    assert done.state == jobs.SUCCESS and done.exit_code == 0
    assert "step 6" in done.output()
    for field_name in ("job_id", "project_id", "command", "cwd", "pid", "exit_code",
                       "started_at", "finished_at", "timeout"):
        assert field_name in done.as_dict()


def test_a_job_times_out_and_cancels_only_its_own_tree() -> None:
    from reyes_agent.executors import jobs

    if not _node():
        print("    (node.js absent -- timeout/cancel test skipped)")
        return
    app = _tmp() / "app"
    app.mkdir(parents=True)
    (app / "forever.js").write_text("setInterval(()=>console.log('tick'),200);\n", encoding="utf-8")

    timed = jobs.start("node forever.js", app, kind=jobs.BUILD, timeout=2)[0]
    finished = jobs.wait(timed.id, timeout=20)
    assert finished.state == jobs.TIMED_OUT and "exceeded" in finished.error
    assert finished._process.process.poll() is not None, "the process must really be dead"

    # An unrelated node process must survive a cancellation.
    bystander = subprocess.Popen([shutil.which("node"), "-e", "setInterval(()=>{},1000)"])
    try:
        time.sleep(0.4)
        running = jobs.start("node forever.js", app, kind=jobs.BUILD, timeout=60)[0]
        time.sleep(0.6)
        assert jobs.cancel(running.id)["state"] == jobs.CANCELLED
        time.sleep(0.8)
        assert running._process.process.poll() is not None
        assert bystander.poll() is None, "an unrelated node process was killed"
    finally:
        bystander.kill()

    # Two identical commands in one folder reuse one job.
    a = jobs.start("node forever.js", app, kind=jobs.BUILD, timeout=30)[0]
    b = jobs.start("node forever.js", app, kind=jobs.BUILD, timeout=30)[0]
    assert a.id == b.id, "a duplicate command must not start a second process"
    jobs.cancel(a.id)


def test_job_timeouts_are_configurable_per_kind() -> None:
    from reyes_agent import config
    from reyes_agent.executors import jobs

    assert jobs.timeout_for(jobs.BUILD) == config.WEB_BUILD_TIMEOUT_SECONDS
    assert jobs.timeout_for(jobs.INSTALL) == config.WEB_INSTALL_TIMEOUT_SECONDS
    assert jobs.timeout_for(jobs.TEST) == config.WEB_TEST_TIMEOUT_SECONDS
    assert jobs.classify("npm install") == jobs.INSTALL
    assert jobs.classify("npm run build") == jobs.BUILD
    assert jobs.classify("npm run test") == jobs.TEST
    assert set(jobs.ALL_STATES) == {"QUEUED", "STARTING", "RUNNING", "SUCCESS",
                                    "FAILED", "TIMED_OUT", "CANCELLED"}


def test_job_output_is_bounded() -> None:
    from reyes_agent.executors import jobs

    job = jobs.Job(id="x", project="p", command="c", cwd=".", kind=jobs.BUILD, timeout=10)
    for index in range(5000):
        job.record(f"line {index}")
    text = job.output()
    assert len(text.splitlines()) < 400, "a chatty build must not be kept in full"
    assert "line 0" in text and "line 4999" in text, "head and tail are what matter"
    assert "omitted" in text, "the gap must be stated, not hidden"


# --- 4. dependency-aware rollback ----------------------------------------

def test_rollback_restores_manifests_and_reconciles_dependencies() -> None:
    from reyes_agent import config

    wb = _quiet_website_builder()
    root = _tmp()
    config.VAULT_PATH = root / "vault"
    app = root / "app"
    app.mkdir()
    (app / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "dependencies": {"left-pad": "^1.3.0"}}),
        encoding="utf-8")
    (app / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "name": "x"}),
                                           encoding="utf-8")
    (app / "index.html").write_text("<html>v1</html>", encoding="utf-8")

    state = wb.dependency_state(app)
    assert state["lockfile"] == "package-lock.json" and "left-pad" in state["dependencies"]

    saved = wb.checkpoint(app, "before adding a dependency")
    assert "package.json" in saved["files"] and "package-lock.json" in saved["files"]

    # A dependency is added -- both manifests change.
    (app / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0",
                    "dependencies": {"left-pad": "^1.3.0", "dayjs": "^1.11.0"}}), encoding="utf-8")
    (app / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "name": "x", "changed": True}), encoding="utf-8")

    result = wb.restore_checkpoint(app, saved["version"])

    restored_manifest = json.loads((app / "package.json").read_text(encoding="utf-8"))
    assert list(restored_manifest["dependencies"]) == ["left-pad"], "package.json must roll back"
    assert "changed" not in json.loads((app / "package-lock.json").read_text(encoding="utf-8")), \
        "the lockfile must roll back too"

    dependencies = result["dependencies"]
    assert dependencies["needed"] is True
    if dependencies.get("started"):
        # npm present: reconciliation runs as a background job, and prefers
        # `npm ci` because a lockfile was restored.
        assert dependencies["command"] == "npm ci"
        assert dependencies["job_id"]
    else:
        assert dependencies["reason"], "a skipped reconciliation must say why"

    # node_modules is NEVER snapshotted -- manifests are the source of truth.
    assert not any("node_modules" in name for name in saved["files"])


def test_a_restore_without_manifests_does_not_reinstall() -> None:
    from reyes_agent import config

    wb = _quiet_website_builder()
    root = _tmp()
    config.VAULT_PATH = root / "vault"
    site = root / "static"
    site.mkdir()
    (site / "index.html").write_text("<html>v1</html>", encoding="utf-8")
    saved = wb.checkpoint(site, "v1")
    (site / "index.html").write_text("<html>v2</html>", encoding="utf-8")

    result = wb.restore_checkpoint(site, saved["version"])
    assert result["dependencies"]["needed"] is False
    assert "no dependency manifest" in result["dependencies"]["reason"]


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    try:
        for test in tests:
            started = time.time()
            try:
                test()
                print(f"PASS {test.__name__} ({time.time() - started:.1f}s)")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    finally:
        _cleanup()
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
