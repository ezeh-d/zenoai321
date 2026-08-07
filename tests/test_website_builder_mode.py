"""Regression tests for the Website Builder integration seam."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

def test_router_keeps_simple_web_questions_fast_and_builds_deep() -> None:
    from reyes_agent import cognition
    simple = cognition.route("What is a website?")
    assert simple.path == cognition.FAST and cognition.WEBSITE_BUILDER in simple.modes
    build = cognition.route("Build me a professional company website with a homepage and contact form.")
    assert build.path == cognition.DEEP and cognition.WEBSITE_BUILDER in build.modes

def test_metadata_checkpoint_and_static_inspection_are_bounded() -> None:
    from reyes_agent import config, website_builder as wb
    with tempfile.TemporaryDirectory() as raw:
        old = config.VAULT_PATH
        old_emit = wb._emit
        try:
            config.VAULT_PATH = Path(raw) / "vault"; wb._emit = lambda *_a, **_k: None
            site = Path(raw) / "site"; site.mkdir()
            (site / "index.html").write_text('<html><body><img src="hero.png"></body></html>', encoding="utf-8")
            registered = wb.register_build("Demo", site, status="verified", files=["index.html"])
            assert registered and wb.projects()[0]["framework"] == "HTML/CSS/JavaScript"
            saved = wb.checkpoint(site, "before hero redesign")
            assert saved["files"] == ["index.html"] and wb.checkpoints(site)[0]["version"] == saved["version"]
            (site / "index.html").write_text("<html><title>New</title></html>", encoding="utf-8")
            (site / "later.txt").write_text("later", encoding="utf-8")
            restored = wb.restore_checkpoint(site, saved["version"])
            assert "later.txt" in restored["removed"]
            assert "img src" in (site / "index.html").read_text(encoding="utf-8")
            findings = wb.inspect(site)
            assert any("missing page title" in item for item in findings)
            assert any("without alt" in item for item in findings)
            manifest_path = site / ".zeno" / "versions" / saved["version"] / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"] = ["../outside.txt"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            try:
                wb.restore_checkpoint(site, saved["version"])
            except ValueError as exc:
                assert "unsafe" in str(exc)
            else:
                raise AssertionError("checkpoint traversal was accepted")
        finally:
            wb._emit = old_emit; config.VAULT_PATH = old

def test_zeno_core_and_vault_cannot_be_selected_as_website_projects() -> None:
    from reyes_agent import config, website_builder as wb
    for protected in (config.PROJECT_ROOT, config.VAULT_PATH):
        try: wb.safe_project_root(Path(protected))
        except ValueError as exc: assert "refuses" in str(exc)
        else: raise AssertionError("protected ZENO path was accepted")

def test_existing_build_runtime_registers_websites_without_a_second_executor() -> None:
    from reyes_agent.tools import TOOLS
    from reyes_agent import website_builder
    assert "build_project" in TOOLS and "website_project" in TOOLS
    source = (ROOT / "reyes_agent" / "website_builder.py").read_text(encoding="utf-8")
    assert "threading.Thread" not in source and "subprocess" not in source
    assert "build_project/task engine" in source


def test_website_studio_panel_visual_check_and_bounded_history_are_wired() -> None:
    from reyes_agent import config
    page = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    activity = (ROOT / "reyes_agent" / "static" / "activity_view.js").read_text(encoding="utf-8")
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert 'id="website-studio-btn"' in page and "openWebsiteStudio" in activity
    assert '"/api/website/projects"' in web and '"/api/website/visual-inspect"' in web
    assert "visual_inspect" in (ROOT / "reyes_agent" / "tools" / "website.py").read_text(encoding="utf-8")
    assert 150 <= config.WEBSITE_CHECKPOINT_MAX_FILES <= 1_000
    assert 2 <= config.WEBSITE_CHECKPOINT_MAX_MB <= 25

def test_a_capped_checkpoint_never_deletes_files_it_did_not_capture() -> None:
    """The data-loss case, measured 2026-08-07 before the truncation flag.

    A 200-file project checkpoints only 150. The safety backup taken during
    restore caps identically, so deleting "files not in the manifest" would
    destroy the other 50 in BOTH places at once. A capped snapshot must
    therefore copy back without deleting anything.
    """
    from reyes_agent import config, website_builder as wb
    with tempfile.TemporaryDirectory() as raw:
        old, old_emit = config.VAULT_PATH, wb._emit
        try:
            config.VAULT_PATH = Path(raw) / "vault"; wb._emit = lambda *_a, **_k: None
            site = Path(raw) / "big"; site.mkdir()
            for index in range(wb._MAX_SNAPSHOT_FILES + 50):
                (site / f"page{index:03d}.html").write_text(f"<html>{index}</html>", encoding="utf-8")
            before = {p.name for p in site.glob("*.html")}
            saved = wb.checkpoint(site, "full site")
            assert saved["truncated"] is True, "a capped snapshot must say so"
            assert len(saved["files"]) == wb._MAX_SNAPSHOT_FILES

            result = wb.restore_checkpoint(site, saved["version"])
            assert result["complete"] is False, "an incomplete restore must be reported as such"
            assert result["removed"] == [], "nothing may be deleted on a capped snapshot's authority"
            assert {p.name for p in site.glob("*.html")} == before, "no file may be lost"
        finally:
            wb._emit = old_emit; config.VAULT_PATH = old


def test_a_complete_checkpoint_still_performs_a_real_undo() -> None:
    """Safety must not cost the feature: a small project gets a true rewind."""
    from reyes_agent import config, website_builder as wb
    with tempfile.TemporaryDirectory() as raw:
        old, old_emit = config.VAULT_PATH, wb._emit
        try:
            config.VAULT_PATH = Path(raw) / "vault"; wb._emit = lambda *_a, **_k: None
            site = Path(raw) / "small"; site.mkdir()
            (site / "index.html").write_text("<h1>ORIGINAL</h1>", encoding="utf-8")
            saved = wb.checkpoint(site, "before redesign")
            assert saved["truncated"] is False

            (site / "index.html").write_text("<h1>REDESIGNED</h1>", encoding="utf-8")
            (site / "extra.html").write_text("added after", encoding="utf-8")
            result = wb.restore_checkpoint(site, saved["version"])

            assert result["complete"] is True
            assert (site / "index.html").read_text(encoding="utf-8") == "<h1>ORIGINAL</h1>"
            assert "extra.html" in result["removed"] and not (site / "extra.html").exists()
            # ...and the undo is itself undoable.
            backup = site / ".zeno" / "versions" / result["backup"] / "extra.html"
            assert backup.is_file(), "the removed file must survive in the safety checkpoint"


            # "Undo" with no version means the latest DELIBERATE checkpoint,
            # not the automatic backup restore just created.
            assert wb.latest_restorable(site) == saved["version"]
        finally:
            wb._emit = old_emit; config.VAULT_PATH = old


def test_a_variant_leaves_the_original_untouched() -> None:
    from reyes_agent import config, website_builder as wb
    with tempfile.TemporaryDirectory() as raw:
        old, old_emit = config.VAULT_PATH, wb._emit
        try:
            config.VAULT_PATH = Path(raw) / "vault"; wb._emit = lambda *_a, **_k: None
            site = Path(raw) / "restaurant"; site.mkdir()
            (site / "index.html").write_text("<h1>V1</h1>", encoding="utf-8")
            wb.checkpoint(site, "v1")

            item = wb.variant(site, "restaurant bold")
            copy = Path(item["location"])
            # Compare RESOLVED parents: Windows hands back 8.3 short names for
            # temp paths, so the raw strings differ for the same folder.
            assert copy.name == "restaurant-bold"
            assert copy.parent.resolve() == site.parent.resolve()
            assert (copy / "index.html").read_text(encoding="utf-8") == "<h1>V1</h1>"
            assert (site / "index.html").read_text(encoding="utf-8") == "<h1>V1</h1>", "original must not change"
            # A variant starts its own history rather than inheriting one.
            assert not (copy / ".zeno").exists()
            # Editing the variant cannot touch the original.
            (copy / "index.html").write_text("<h1>V2</h1>", encoding="utf-8")
            assert (site / "index.html").read_text(encoding="utf-8") == "<h1>V1</h1>"
            # A clashing name is refused rather than overwriting.
            try:
                wb.variant(site, "restaurant bold")
            except ValueError as exc:
                assert "already exists" in str(exc)
            else:
                raise AssertionError("an existing folder was silently overwritten")
        finally:
            wb._emit = old_emit; config.VAULT_PATH = old


def test_generated_sites_live_outside_the_zeno_installation() -> None:
    from reyes_agent import config
    from reyes_agent.executors import desktop
    workspace = desktop.website_workspace().resolve()
    installation = Path(config.PROJECT_ROOT).resolve()
    try:
        workspace.relative_to(installation)
    except ValueError:
        pass
    else:
        raise AssertionError(f"generated websites would live inside ZENO itself: {workspace}")
    assert desktop.resolve_destination("websites") == desktop.website_workspace()

    # An override pointing into ZENO is refused, not obeyed.
    original = config.WEBSITE_WORKSPACE_PATH
    try:
        config.WEBSITE_WORKSPACE_PATH = installation / "reyes_agent" / "sites"
        fallback = desktop.website_workspace().resolve()
        try:
            fallback.relative_to(installation)
        except ValueError:
            pass
        else:
            raise AssertionError("a workspace override inside ZENO was accepted")
    finally:
        config.WEBSITE_WORKSPACE_PATH = original


def test_stack_selection_prefers_the_smallest_thing_that_works() -> None:
    from reyes_agent import website_builder as wb
    from reyes_agent.executors import terminal

    real = terminal.tool_available
    terminal.tool_available = lambda program: True      # pretend Node exists
    try:
        assert wb.recommend_stack("Build me a modern restaurant website")["stack"] == "static"
        assert wb.recommend_stack("Build a portfolio landing page")["stack"] == "static"
        assert wb.recommend_stack("a site with a customer dashboard and login")["stack"] == "vite-react"
        assert wb.recommend_stack("a shop with a database and stripe payments")["stack"] == "next"
        # Next.js must not be the answer to everything.
        assert wb.recommend_stack("a law firm website with a contact form")["stack"] != "next"
    finally:
        terminal.tool_available = real

    # Without Node.js installed, a build-step stack could not run at all.
    terminal.tool_available = lambda program: False
    try:
        pick = wb.recommend_stack("a site with a database and stripe payments")
        assert pick["stack"] == "static" and "Node.js is not installed" in pick["reason"]
    finally:
        terminal.tool_available = real


def test_project_lookup_offers_candidates_instead_of_guessing() -> None:
    from reyes_agent import config, website_builder as wb
    with tempfile.TemporaryDirectory() as raw:
        old, old_emit = config.VAULT_PATH, wb._emit
        try:
            config.VAULT_PATH = Path(raw) / "vault"; wb._emit = lambda *_a, **_k: None
            for name in ("Restaurant Demo", "Restaurant Bold", "Law Firm Site"):
                folder = Path(raw) / name.lower().replace(" ", "-")
                folder.mkdir()
                (folder / "index.html").write_text("<html></html>", encoding="utf-8")
                wb.register_build(name, folder, status="verified", files=["index.html"])

            matches = wb.find_project("continue my restaurant website")
            assert len(matches) == 2, [m["project_name"] for m in matches]
            assert {m["project_name"] for m in matches} == {"Restaurant Demo", "Restaurant Bold"}
            assert wb.find_project("law firm")[0]["project_name"] == "Law Firm Site"
            assert wb.find_project("bakery") == []
        finally:
            wb._emit = old_emit; config.VAULT_PATH = old


def test_undo_and_variant_are_reachable_as_tools() -> None:
    """A capability the model cannot call is not a capability."""
    from reyes_agent.tools import TOOLS
    assert "website_restore_checkpoint" in TOOLS
    restore = TOOLS["website_restore_checkpoint"]
    assert restore.requires_confirmation, "restoring removes files -- it stays gated"
    assert "version" not in restore.input_schema["required"], "'undo that' must work without an id"
    actions = TOOLS["website_project"].input_schema["properties"]["action"]["enum"]
    for needed in ("checkpoint", "checkpoints", "variant", "find", "list", "inspect"):
        assert needed in actions, f"website_project is missing '{needed}'"


# --- error analyzer ------------------------------------------------------

def test_analyzer_parses_what_the_tools_actually_print() -> None:
    from reyes_agent.executors import diagnostics as dx

    tsc = dx.analyze("src/components/Navbar.tsx(42,15): error TS2304: Cannot find name 'useSate'.")
    assert len(tsc) == 1
    assert tsc[0].category == dx.TYPESCRIPT
    assert tsc[0].file == "src/components/Navbar.tsx" and tsc[0].line == 42 and tsc[0].column == 15
    assert tsc[0].code == "TS2304" and "never imported or declared" in tsc[0].likely_cause

    # esbuild puts the location on the FOLLOWING line -- it must be picked up.
    esbuild = dx.analyze('✘ [ERROR] Could not resolve "./components/Hero"\n    src/App.jsx:3:18:')
    assert len(esbuild) == 1 and esbuild[0].category == dx.IMPORT
    assert esbuild[0].file == "src/App.jsx" and esbuild[0].line == 3

    assert dx.analyze("npm ERR! code ETIMEDOUT")[0].category == dx.NETWORK
    assert dx.analyze('npm error Missing script: "build"')[0].category == dx.CONFIGURATION
    assert dx.analyze("Error: Cannot find module 'react-dom'")[0].category == dx.DEPENDENCY
    assert dx.analyze("Error: Cannot find module './utils/format'")[0].category == dx.IMPORT
    assert dx.analyze("SyntaxError: Unexpected token '}'")[0].category == dx.JAVASCRIPT
    assert dx.analyze("[postcss] src/styles/main.css:12:3: Unknown word")[0].category == dx.CSS
    for error in dx.analyze("src/App.tsx(1,1): error TS1005: ',' expected."):
        assert error.severity == dx.ERROR


def test_analyzer_never_invents_a_file_it_could_not_read() -> None:
    from reyes_agent.executors import diagnostics as dx

    # Clean output produces nothing at all.
    assert dx.analyze("vite v5.0 building for production...\ndone in 412ms") == []
    # An unparseable failure is kept, but with NO guessed location.
    vague = dx.analyze("error: something went badly wrong in the toolchain")
    assert len(vague) == 1
    assert vague[0].file == "" and vague[0].line is None
    assert vague[0].category in dx.CATEGORIES


def test_analyzer_deduplicates_repeated_failures() -> None:
    """Bundlers repeat one missing module per importer.

    Counting those separately makes a good repair look like a regression to
    a loop that compares error counts before and after.
    """
    from reyes_agent.executors import diagnostics as dx

    repeated = "\n".join(["Error: Cannot find module './Nav'"] * 5)
    assert len(dx.analyze(repeated)) == 1


# --- build checker / repair loop -----------------------------------------

def test_checks_are_derived_from_the_project_not_assumed() -> None:
    from reyes_agent.executors import build_check

    with tempfile.TemporaryDirectory() as raw:
        static = Path(raw) / "static"; static.mkdir()
        (static / "index.html").write_text("<html></html>", encoding="utf-8")
        assert build_check.applicable_checks(static) == [], "a static site has no build step"
        assert build_check.dependencies_installed(static) is True

        app = Path(raw) / "app"; app.mkdir()
        (app / "package.json").write_text(
            json.dumps({"name": "x", "scripts": {"build": "vite build", "lint": "eslint ."},
                        "dependencies": {"react": "^18"}}), encoding="utf-8")
        commands = [c.command for c in build_check.applicable_checks(app)]
        assert "npm run build" in commands and "npm run lint" in commands
        assert "npm run typecheck" not in commands, "no typecheck script and no tsconfig"
        # Declared dependencies with no node_modules means "not installed".
        assert build_check.dependencies_installed(app) is False
        (app / "node_modules").mkdir()
        assert build_check.dependencies_installed(app) is True


def test_static_site_defects_are_caught_without_any_build_tooling() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import build_check

    with tempfile.TemporaryDirectory() as raw:
        site = Path(raw) / "site"; site.mkdir()
        (site / "index.html").write_text('<html><body><script src="app.js"></script></body></html>', encoding="utf-8")
        (site / "app.js").write_text("function broken( {", encoding="utf-8")
        task = task_engine.create("check", plan=["Checking the generated code"])
        report = build_check.verify(task.id, site)
        assert report.ok is False, "a broken script must not pass"
        assert report.errors and any("app.js" in (e.file or "") for e in report.errors)
        assert "static" in report.reason.lower() or report.errors


def test_a_real_build_is_run_and_its_errors_are_structured() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import build_check, terminal

    if not terminal.tool_available("node"):
        print("    (node.js absent -- real-build assertions skipped)")
        return
    with tempfile.TemporaryDirectory() as raw:
        app = Path(raw) / "bad"; app.mkdir()
        (app / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
            encoding="utf-8")
        # A build that fails and prints a real tsc-shaped error.
        (app / "build.js").write_text(
            'console.error("src/App.tsx(9,3): error TS2304: Cannot find name \'foo\'.");\n'
            "process.exit(1);", encoding="utf-8")
        task = task_engine.create("failing build", plan=["Checking the generated code"])
        report = build_check.verify(task.id, app)

        assert report.ok is False
        assert any(r.check == "build" and not r.ok for r in report.runs), "the build must really have run"
        typescript = [e for e in report.errors if e.category == "TYPESCRIPT"]
        assert typescript, [e.as_dict() for e in report.errors]
        assert typescript[0].file == "src/App.tsx" and typescript[0].line == 9
        assert report.attempts <= build_check.MAX_ATTEMPTS_CEILING


def test_a_passing_build_is_reported_as_passing() -> None:
    from reyes_agent import task_engine
    from reyes_agent.executors import build_check, terminal

    if not terminal.tool_available("node"):
        print("    (node.js absent -- real-build assertions skipped)")
        return
    with tempfile.TemporaryDirectory() as raw:
        app = Path(raw) / "good"; app.mkdir()
        (app / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
            encoding="utf-8")
        (app / "build.js").write_text('console.log("built ok");', encoding="utf-8")
        task = task_engine.create("passing build", plan=["Checking the generated code"])
        report = build_check.verify(task.id, app)
        assert report.ok is True, report.summary()
        assert any(r.check == "build" and r.ok for r in report.runs)


def test_a_failure_nobody_could_parse_is_still_a_failure() -> None:
    """The honesty case: exit != 0 with unreadable output must not read as ok."""
    from reyes_agent import task_engine
    from reyes_agent.executors import build_check, terminal

    if not terminal.tool_available("node"):
        print("    (node.js absent -- real-build assertions skipped)")
        return
    with tempfile.TemporaryDirectory() as raw:
        app = Path(raw) / "silent"; app.mkdir()
        (app / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
            encoding="utf-8")
        (app / "build.js").write_text("process.exit(2);", encoding="utf-8")   # fails, says nothing
        task = task_engine.create("silent failure", plan=["Checking the generated code"])
        report = build_check.verify(task.id, app)
        assert report.ok is False, "a silent non-zero exit is still a failure"
        assert any("could not interpret" in (e.likely_cause or "") for e in report.errors)


def test_the_repair_loop_is_bounded_and_never_installs_scraped_names() -> None:
    from reyes_agent.executors import build_check
    from reyes_agent import config

    assert build_check.MAX_ATTEMPTS_CEILING == 5
    assert config.WEBSITE_MAX_FIX_ATTEMPTS <= build_check.MAX_ATTEMPTS_CEILING
    source = (ROOT / "reyes_agent" / "executors" / "build_check.py").read_text(encoding="utf-8")
    # The only command repair is a plain `npm install` of DECLARED deps --
    # now started as a background job rather than a blocking call.
    assert 'jobs.start("npm install"' in source
    # The literal string is never built from parsed error text, so a package
    # name scraped out of a message can never be installed.
    assert "npm install {" not in source and 'npm install " +' not in source and \
        'npm install {target}' not in source, \
        "a package name from error text must never be installed"
    import re as _re
    assert not _re.search(r'f"npm install[^"]*\{', source), "no interpolated install command"


def test_the_checker_is_reachable_as_a_tool() -> None:
    from reyes_agent.tools import TOOLS

    assert "website_check" in TOOLS
    schema = TOOLS["website_check"].input_schema
    assert "location" in schema["required"]
    assert "auto_fix" in schema["properties"]


def _run_all() -> int:
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]; failed=0
    for test in tests:
        try: test(); print(f"PASS {test.__name__}")
        except Exception as exc: failed+=1; print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests)-failed} passed, {failed} failed"); return 1 if failed else 0
if __name__ == "__main__": raise SystemExit(_run_all())
