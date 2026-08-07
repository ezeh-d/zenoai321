"""`build_project` -- the tool that makes an action request actually happen.

WHY ONE BIG TOOL INSTEAD OF SIX SMALL ONES
------------------------------------------
The obvious design is granular: start_task, write_file, run_command,
preview, verify, finish. It was rejected for a measured reason -- the agent
core stops after MAX_TOOL_ROUNDS (8) tool rounds. A real website is a plan
plus five files plus an install plus a server plus a browser plus
verification, which is more rounds than exist, so the build would be cut
off partway and the model would fall back to explaining the rest. That is
the failure this change is meant to remove, not reproduce.

So the model contributes what only it can -- the plan and the file
contents -- in one call, and this module runs the actual pipeline:
resolve the Desktop, create the folder, write and verify every file, check
the code, run project commands, start a server, open the browser, verify
the page really responded, and report the real path. Each stage emits a
step to the Live Activity panel as it happens (see task_engine), so the
owner watches genuine progress rather than a narration of it.

`build_add_files` exists for projects too large for one call, and continues
the SAME task rather than starting a second one.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from reyes_agent import task_engine
from reyes_agent.executors import application, coding, desktop, filesystem, preview, terminal
from reyes_agent.tools import register

# Plan labels used verbatim in the panel, so what the owner reads matches
# what the executor is doing.
STEP_LOCATE = "Locating destination folder"
STEP_FOLDER = "Creating project folder"
STEP_CHECK = "Checking the generated code"
STEP_DEPS = "Installing required packages"
STEP_SERVER = "Starting development server"
STEP_BROWSER = "Opening browser preview"
STEP_VERIFY = "Verifying the finished project"
STEP_REVEAL = "Showing the project folder"


def _slug(name: str) -> str:
    keep = re.sub(r"[^\w\s-]", "", str(name or "")).strip()
    return re.sub(r"\s+", "-", keep) or "project"


def _coerce_files(files: Any) -> list[tuple[str, str]]:
    """Accept the two shapes models actually emit: a list of {path, content}
    objects, or a {path: content} mapping."""
    out: list[tuple[str, str]] = []
    if isinstance(files, dict):
        for path, content in files.items():
            out.append((str(path), str(content)))
        return out
    if not isinstance(files, list):
        return out
    for entry in files:
        if isinstance(entry, dict):
            path = entry.get("path") or entry.get("filename") or entry.get("name") or ""
            content = entry.get("content") or entry.get("body") or ""
            if str(path).strip():
                out.append((str(path), str(content)))
    return out


def _secret_output_reason(filename: str) -> str:
    """Keep generated websites from receiving actual local credentials.

    A model can safely create a documented `.env.example`, but it must never
    manufacture or overwrite the owner's real dotenv/credential/key file.
    Those values belong in the owner's local setup, outside the tool call and
    outside Live Activity events.
    """
    name = Path(str(filename).replace("\\", "/")).name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "Refused secret-bearing dotenv file; create .env.example with placeholders instead."
    if name in {"credentials.json", "secrets.json"} or name.endswith((".key", ".pem", ".p12", ".pfx")):
        return "Refused secret-bearing credential/key file; do not put private credentials in a generated project."
    return ""


def _publish_workspace(project_name: str, project_dir: Path, filename: str, content: str) -> None:
    """Feed the existing code-workspace overlay, unchanged, alongside the panel."""
    try:
        from reyes_agent import notification_bus

        notification_bus.publish({
            "type": "workspace_code",
            "project": project_name,
            "file": filename,
            "content": content[:6000],
            "files": filesystem.list_files(project_dir),
        })
    except Exception:  # noqa: BLE001 -- no browser tab open is not an error
        pass


# --- pipeline stages -----------------------------------------------------

def _write_files(task_id: str, project_name: str, project_dir: Path,
                 files: list[tuple[str, str]]) -> list[str]:
    """Write each file, verify it landed, and retry only the ones that fail."""
    failures: list[str] = []
    for filename, content in files:
        task_engine.check_cancelled(task_id)
        label = f"Creating {filename}"
        task_engine.begin_step(task_id, label)
        secret_reason = _secret_output_reason(filename)
        if secret_reason:
            task_engine.fail_step(task_id, label, secret_reason)
            failures.append(f"{filename}: {secret_reason}")
            continue
        task_engine.record_file(task_id, filename)
        result = filesystem.write_file(project_dir, filename, content)
        attempt = 1
        while not result.ok and attempt < task_engine.MAX_STEP_ATTEMPTS:
            # Retry only this file. Nothing already written is touched.
            task_engine.fail_step(task_id, label, result.message)
            attempt += 1
            task_engine.begin_step(task_id, label)
            time.sleep(0.2)
            result = filesystem.write_file(project_dir, filename, content)
        if result.ok:
            task_engine.complete_step(task_id, label, f"{result.bytes_written} bytes, verified on disk")
            _publish_workspace(project_name, project_dir, filename, content)
        else:
            task_engine.fail_step(task_id, label, result.message)
            failures.append(f"{filename}: {result.message}")
    return failures


def _check_code(task_id: str, project_dir: Path) -> tuple[list[coding.Issue], list[str]]:
    task_engine.check_cancelled(task_id)
    task_engine.begin_step(task_id, STEP_CHECK)
    repair = coding.repair_project(project_dir)
    issues = repair.issues
    fixed = repair.applied
    if fixed:
        for note in fixed:
            task_engine.record_terminal(task_id, f"[fixed] {note}")
    task_engine.record_terminal(
        task_id,
        "[website-check] " + ", ".join(f"{kind}={count}" for kind, count in sorted(repair.categories.items()))
        + (f"; attempts={repair.attempts}" if repair.attempts else "; no automatic repair")
        + ("; rollback applied" if repair.rolled_back else ""),
    )
    safety = coding.demo_safety_issues(project_dir)
    issues = issues + safety
    blocking = [i for i in issues if i.kind in {"syntax", "invalid_json", "empty_file", "unsafe_form"}]
    for issue in issues:
        if issue not in blocking:
            task_engine.record_warning(task_id, f"{issue.file}: {issue.detail}")
    if blocking:
        task_engine.fail_step(task_id, STEP_CHECK, coding.summarize(blocking))
    else:
        task_engine.complete_step(task_id, STEP_CHECK,
                                  f"{len(fixed)} correction(s), {len(issues)} note(s)")
    return issues, fixed


def _run_commands(task_id: str, project_dir: Path, commands: list[str]) -> list[str]:
    problems: list[str] = []
    for command in commands:
        command = str(command or "").strip()
        if not command:
            continue
        task_engine.check_cancelled(task_id)
        label = STEP_DEPS if re.search(r"\b(install|ci)\b", command) else f"Running {command}"
        task_engine.begin_step(task_id, label)
        result = terminal.run(task_id, command, project_dir)
        if result.blocked:
            # Not a failure of the build -- a boundary. Named plainly so the
            # owner can approve it themselves rather than being told it ran.
            task_engine.skip_step(task_id, label, result.reason)
            problems.append(f"`{command}` was not run automatically: {result.reason}")
            continue
        if result.ok:
            task_engine.complete_step(task_id, label,
                                      "already done earlier in this task" if result.skipped_duplicate
                                      else f"exit 0 in {result.duration_s:.1f}s")
            continue
        may_retry = task_engine.fail_step(task_id, label, result.reason or "command failed")
        if may_retry:
            task_engine.begin_step(task_id, label)
            result = terminal.run(task_id, command, project_dir, allow_duplicate=True)
            if result.ok:
                task_engine.complete_step(task_id, label, f"succeeded on retry (exit 0)")
                continue
            task_engine.fail_step(task_id, label, result.reason or "command failed on retry")
        problems.append(f"`{command}` failed (exit {result.exit_code}): "
                        f"{(result.output or result.reason)[-300:]}")
    return problems


def _start_preview(task_id: str, project_dir: Path) -> tuple[preview.Preview | None, list[str]]:
    problems: list[str] = []
    task_engine.check_cancelled(task_id)
    task_engine.begin_step(task_id, STEP_SERVER)
    running, error = preview.start(task_id, project_dir)
    if running is None:
        task_engine.fail_step(task_id, STEP_SERVER, error)
        problems.append(f"Could not start a local server: {error}")
        return None, problems
    ok, detail = preview.probe(running.url)
    if not ok:
        may_retry = task_engine.fail_step(task_id, STEP_SERVER, detail)
        if may_retry:
            time.sleep(1.0)
            task_engine.begin_step(task_id, STEP_SERVER)
            ok, detail = preview.probe(running.url)
        if not ok:
            task_engine.fail_step(task_id, STEP_SERVER, detail)
            problems.append(detail)
            return running, problems
    task_engine.complete_step(task_id, STEP_SERVER, detail)

    task_engine.begin_step(task_id, STEP_BROWSER)
    opened, message = preview.open_in_browser(task_id, running)
    if opened:
        task_engine.complete_step(task_id, STEP_BROWSER, message)
    else:
        task_engine.skip_step(task_id, STEP_BROWSER, message)
        problems.append(message)
    return running, problems


def _verify(task_id: str, project_dir: Path, running: preview.Preview | None,
            required: list[str], issues: list[coding.Issue]) -> None:
    """Record real evidence. task_engine.complete() refuses success without it."""
    task_engine.check_cancelled(task_id)
    task_engine.set_state(task_id, task_engine.VERIFYING)
    task_engine.begin_step(task_id, STEP_VERIFY)

    report = filesystem.folder_report(project_dir)
    task_engine.record_verification(task_id, "Project folder exists", bool(report["exists"]), str(report["path"]))
    task_engine.record_verification(
        task_id, "Files were written", report["file_count"] > 0,
        f"{report['file_count']} file(s), {report['total_bytes']} bytes",
    )
    if report["empty_files"]:
        task_engine.record_verification(task_id, "No empty files", False,
                                        ", ".join(report["empty_files"][:5]))
    for name in required:
        exists = (project_dir / name).is_file()
        task_engine.record_verification(task_id, f"Required file {name}", exists,
                                        "present" if exists else "missing")

    blocking = [i for i in issues if i.kind in {"syntax", "invalid_json", "unsafe_form"}]
    task_engine.record_verification(
        task_id, "Code has no blocking defects", not blocking,
        coding.summarize(blocking) if blocking else "no syntax, JSON or unsafe-form problems",
    )

    if running is not None:
        for check in preview.check_page(running.url, project_dir):
            task_engine.record_verification(task_id, check["check"], check["ok"], check["detail"])

    on_desktop, explanation = desktop.confirm_visible(project_dir)
    if str(project_dir.parent.resolve()).casefold() == str(desktop.desktop_path().resolve()).casefold():
        task_engine.record_verification(task_id, "Visible on the Desktop", on_desktop, explanation)

    built = task_engine.get(task_id)
    failed = [c for c in (built.verification if built else []) if not c["ok"]]
    if failed:
        task_engine.fail_step(task_id, STEP_VERIFY, "; ".join(c["check"] for c in failed[:4]))
    else:
        task_engine.complete_step(task_id, STEP_VERIFY, "all checks passed")


def _report(snapshot: dict[str, Any], problems: list[str],
            fixed: list[str], notes: list[coding.Issue]) -> str:
    """The string the model reads. It must never overstate the outcome."""
    lines: list[str] = []
    state = snapshot["current_status"]
    if state == task_engine.COMPLETED:
        lines.append(f"BUILD COMPLETED and verified. Saved at: {snapshot['output_path']}")
    elif state == task_engine.CANCELLED:
        lines.append(f"BUILD CANCELLED. Partial output at: {snapshot['output_path']}")
    else:
        lines.append(f"BUILD DID NOT FULLY SUCCEED ({state}). Files are at: {snapshot['output_path']}")
        if snapshot["error_details"]:
            lines.append(f"Reason: {snapshot['error_details']}")

    lines.append(f"task_id={snapshot['task_id']} plan_id={snapshot['plan_id']} "
                 f"steps={snapshot['completed_steps']}/{snapshot['planned_total']} "
                 f"({snapshot['progress_percent']}%)")
    if snapshot["files"]:
        lines.append("Files written: " + ", ".join(snapshot["files"][:25]))
    if snapshot["preview_url"]:
        lines.append(f"Preview: {snapshot['preview_url']} (running locally, open in the browser)")
    passed = [c for c in snapshot["verification"] if c["ok"]]
    failed = [c for c in snapshot["verification"] if not c["ok"]]
    lines.append(f"Verification: {len(passed)} passed, {len(failed)} failed.")
    for check in failed[:6]:
        lines.append(f"  FAILED - {check['check']}: {check['detail']}")
    if fixed:
        lines.append("Auto-corrected: " + "; ".join(fixed[:5]))
    for problem in problems[:6]:
        lines.append(f"  PROBLEM - {problem}")
    advisory = [i for i in notes if i.kind in {"undeclared_demo", "missing_reference", "structure"}]
    for issue in advisory[:4]:
        lines.append(f"  NOTE - {issue.file}: {issue.detail}")
    if snapshot["warnings"]:
        lines.append("Warnings: " + " | ".join(list(snapshot["warnings"])[:4]))
    lines.append(
        "Report this outcome to the user exactly as stated above -- including the real path "
        "and any FAILED/PROBLEM lines. Do not claim anything here that is not in this result."
    )
    return "\n".join(lines)


# --- the registered tools ------------------------------------------------

@register(
    name="build_project",
    description=(
        "ACTUALLY BUILD AND RUN A PROJECT ON THIS COMPUTER. Use this whenever the user "
        "asks you to create, build, make, save, generate or set up a website, app, script "
        "or folder of files -- especially when they name a location like 'on my Desktop'. "
        "It really creates the folder, writes and verifies every file, runs allowed project "
        "commands, starts a local server, opens the browser, checks the page responded, and "
        "shows every step live in the Activity panel. Describing the code in your reply "
        "instead of calling this creates NOTHING. Pass the COMPLETE contents of every file "
        "in `files` -- placeholders or 'rest of code here' produce a broken project. "
        "For anything finance-related, build a clearly-labelled fictional demo with sample "
        "data and no real credential collection."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What is being built, in the user's terms."},
            "folder_name": {"type": "string", "description": "Project folder name, e.g. 'NovaBank-Demo'."},
            "destination": {
                "type": "string",
                "description": ("Where the folder is created: 'Desktop', 'Documents', 'Downloads', "
                                "'ZENO Projects', or a full folder path. Use what the user said. "
                                "Defaults to Desktop."),
            },
            "files": {
                "type": "array",
                "description": "Every file to create, with its COMPLETE content.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path inside the project, e.g. 'index.html' or 'css/styles.css'."},
                        "content": {"type": "string", "description": "The full file content."},
                    },
                    "required": ["path", "content"],
                },
            },
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("Optional project commands to run in the folder, e.g. 'npm install'. "
                                "Only project tooling (npm/node/python/git) runs automatically; "
                                "anything else is reported back for the user to approve."),
            },
            "preview": {"type": "boolean", "description": "Start a local server and open the browser. Default true."},
            "open_folder": {"type": "boolean", "description": "Reveal the finished folder. Default true."},
            "finish": {"type": "boolean", "description": "Verify and close the task. Default true. Pass false only if calling build_add_files next."},
            "task_id": {"type": "string", "description": "Continue an existing build task instead of starting a new one."},
        },
        "required": ["task", "folder_name", "files"],
    },
)
def build_project(task: str, folder_name: str, files: Any, destination: str = "Desktop",
                  commands: Any = None, preview: bool = True, open_folder: bool = True,
                  finish: bool = True, task_id: str = "") -> str:
    entries = _coerce_files(files)
    command_list = [str(c) for c in (commands or []) if str(c).strip()] if isinstance(commands, list) else []
    if not entries:
        return ("Error: `files` was empty. build_project needs the complete content of every file "
                "to create. Call it again with the real file contents.")

    existing = task_engine.get(task_id) if task_id else None
    project_name = str(folder_name).strip() or _slug(task)

    if existing is None:
        plan = [STEP_LOCATE, STEP_FOLDER]
        plan += [f"Creating {name}" for name, _ in entries]
        plan.append(STEP_CHECK)
        plan += [STEP_DEPS if re.search(r"\b(install|ci)\b", c) else f"Running {c}" for c in command_list]
        if preview:
            plan += [STEP_SERVER, STEP_BROWSER]
        plan.append(STEP_VERIFY)
        if open_folder:
            plan.append(STEP_REVEAL)
        built = task_engine.create(str(task).strip()[:160] or project_name, plan=plan)
        task_id = built.id
    else:
        task_id = existing.id

    try:
        # 1. Where does this actually go?
        task_engine.begin_step(task_id, STEP_LOCATE)
        try:
            root = desktop.resolve_destination(destination or "Desktop")
        except ValueError as exc:
            task_engine.fail_step(task_id, STEP_LOCATE, str(exc))
            task_engine.fail(task_id, str(exc))
            return f"Could not resolve the save location: {exc}"
        project_dir = (root / _slug(project_name)).resolve()
        try:
            from reyes_agent import website_builder
            website_builder.safe_project_root(project_dir)
        except ValueError as exc:
            task_engine.fail_step(task_id, STEP_LOCATE, str(exc))
            task_engine.fail(task_id, str(exc))
            return f"Could not use the requested project location: {exc}"
        task_engine.set_output_path(task_id, project_dir)
        task_engine.complete_step(task_id, STEP_LOCATE, str(project_dir))

        # 2. The folder itself.
        task_engine.begin_step(task_id, STEP_FOLDER)
        folder = filesystem.ensure_folder(project_dir)
        if not folder.ok:
            task_engine.fail_step(task_id, STEP_FOLDER, folder.message)
            task_engine.fail(task_id, folder.message)
            return f"Could not create the project folder: {folder.message}"
        task_engine.complete_step(task_id, STEP_FOLDER, str(project_dir))

        # 3..n. Real files, real commands, real server.
        problems = _write_files(task_id, project_name, project_dir, entries)
        issues, fixed = _check_code(task_id, project_dir)
        for missing in coding.missing_dependencies(project_dir):
            task_engine.record_warning(task_id, f"Not installed: {missing}")
            problems.append(f"Not installed: {missing}")
        problems += _run_commands(task_id, project_dir, command_list)

        if not finish:
            snapshot = task_engine.snapshot(task_engine.get(task_id))
            return (f"Files written so far and verified on disk. task_id={task_id} "
                    f"path={project_dir}. Call build_add_files with this task_id to add the rest, "
                    f"then finish it.\nFiles: {', '.join(snapshot['files'][:25])}")

        running = None
        if preview:
            running, preview_problems = _start_preview(task_id, project_dir)
            problems += preview_problems

        required = [name for name, _ in entries]
        _verify(task_id, project_dir, running, required, issues)

        if open_folder:
            task_engine.begin_step(task_id, STEP_REVEAL)
            shown, message = application.open_folder(project_dir)
            if shown:
                task_engine.complete_step(task_id, STEP_REVEAL, message)
            else:
                task_engine.skip_step(task_id, STEP_REVEAL, message)

        snapshot = task_engine.complete(task_id)
        if not os.environ.get("ZENO_TEST"):
            try:
                from reyes_agent import website_builder
                website_builder.register_build(project_name, project_dir, status="verified" if snapshot["verified"] else "needs_attention", files=snapshot["files"])
            except Exception:  # noqa: BLE001 -- project metadata must not affect a verified build
                pass
        return _report(snapshot, problems, fixed, issues)

    except task_engine.TaskCancelled as exc:
        snapshot = task_engine.snapshot(task_engine.get(task_id))
        return (f"BUILD CANCELLED by the user. {exc}\nPartial files remain at "
                f"{snapshot['output_path']}. Tell the user it was cancelled -- do not retry it.")
    except Exception as exc:  # noqa: BLE001 -- a crash here must not look like success
        task_engine.fail(task_id, f"{type(exc).__name__}: {exc}")
        return (f"BUILD FAILED with an unexpected error: {type(exc).__name__}: {exc}. "
                f"Report this failure to the user; do not claim the project was created.")


@register(
    name="build_add_files",
    description=(
        "Add more files to a build already started by build_project (use its task_id). "
        "For projects too large for one call. Set finish=true on the last call to verify, "
        "preview and close the task."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task_id returned by build_project."},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            "preview": {"type": "boolean", "description": "On the finishing call, start the server and open the browser. Default true."},
            "finish": {"type": "boolean", "description": "Verify and close the task. Default true."},
        },
        "required": ["task_id", "files"],
    },
)
def build_add_files(task_id: str, files: Any, preview: bool = True, finish: bool = True) -> str:
    built = task_engine.get(task_id)
    if built is None:
        return (f"No build task '{task_id}' is open. Call build_project to start one "
                "(it creates the folder and returns a task_id).")
    if built.state in task_engine.TERMINAL_STATES:
        return f"Task '{task_id}' already finished as {built.state}. Start a new build_project instead."
    entries = _coerce_files(files)
    if not entries:
        return "Error: `files` was empty -- nothing to add."
    project_dir = Path(built.output_path)
    if not project_dir.is_dir():
        return f"The project folder {project_dir} no longer exists."

    try:
        problems = _write_files(task_id, built.title, project_dir, entries)
        issues, fixed = _check_code(task_id, project_dir)
        if not finish:
            snapshot = task_engine.snapshot(built)
            return (f"Added {len(entries)} file(s), verified on disk. task_id={task_id}. "
                    f"Files: {', '.join(snapshot['files'][:25])}")
        running = None
        if preview:
            running, preview_problems = _start_preview(task_id, project_dir)
            problems += preview_problems
        _verify(task_id, project_dir, running, [name for name, _ in entries], issues)
        snapshot = task_engine.complete(task_id)
        if not os.environ.get("ZENO_TEST"):
            try:
                from reyes_agent import website_builder
                website_builder.register_build(built.title, project_dir, status="verified" if snapshot["verified"] else "needs_attention", files=snapshot["files"])
            except Exception:  # noqa: BLE001
                pass
        return _report(snapshot, problems, fixed, issues)
    except task_engine.TaskCancelled as exc:
        return f"BUILD CANCELLED by the user. {exc}"


@register(
    name="build_status",
    description=(
        "Report the real state of build tasks -- steps done, files written, verification "
        "results, preview URL and output path. Use it when the user asks how a build went "
        "or where something was saved."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "A specific task, or omit for all recent builds."},
        },
    },
)
def build_status(task_id: str = "") -> str:
    tasks = ([task_engine.snapshot(task_engine.get(task_id))] if task_id and task_engine.get(task_id)
             else task_engine.active())
    if not tasks or tasks == [None]:
        return "No build tasks have run in this session."
    lines = []
    for snapshot in tasks[-5:]:
        percent = snapshot["progress_percent"]
        lines.append(
            f"[{snapshot['current_status']}] {snapshot['title']} -- {snapshot['output_path'] or 'no path yet'}\n"
            f"  steps {snapshot['completed_steps']}/{snapshot['planned_total']}"
            f"{f' ({percent}%)' if percent is not None else ''}"
            f"  files: {len(snapshot['files'])}"
            f"{'  preview: ' + snapshot['preview_url'] if snapshot['preview_url'] else ''}"
        )
        failed = [c for c in snapshot["verification"] if not c["ok"]]
        if failed:
            lines.append("  failed checks: " + "; ".join(c["check"] for c in failed[:4]))
        if snapshot["error_details"]:
            lines.append(f"  error: {snapshot['error_details']}")
    return "\n".join(lines)


@register(
    name="cancel_build",
    description="Stop a running build task and any server or process it started.",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task to cancel. Omit to cancel the running one."},
        },
    },
)
def cancel_build(task_id: str = "") -> str:
    built = task_engine.get(task_id) if task_id else task_engine.latest_open()
    if built is None:
        return "No build task is currently running."
    snapshot = task_engine.cancel(built.id, "Cancelled on request.")
    return (f"Cancelled '{built.title}'. Any server it started has been stopped. "
            f"Files already written remain at {snapshot['output_path']}.")


@register(
    name="build_environment",
    description=(
        "Report which development tools are actually installed (Node.js, npm, Python, git) "
        "and where the real Desktop folder is. Use this before promising a build that needs "
        "a tool, and to answer 'do I have Node installed'."
    ),
    input_schema={"type": "object", "properties": {}},
)
def build_environment() -> str:
    env = terminal.environment_report()
    paths = desktop.describe()
    lines = ["Installed development tools:"]
    for name, version in env.items():
        lines.append(f"  {name}: {version or 'NOT INSTALLED'}")
    lines.append(f"Real Desktop folder: {paths['desktop']}"
                 + (" (redirected, e.g. OneDrive)" if paths["redirected"] == "true" else ""))
    lines.append(f"Documents folder: {paths['documents']}")
    servers = preview.running()
    if servers:
        lines.append("Local preview servers running: " + ", ".join(s["url"] for s in servers))
    return "\n".join(lines)
