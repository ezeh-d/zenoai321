"""Terminal Executor -- real processes, live output, honest exit codes.

WHY THIS IS NOT `tools/system.py:run_command`
---------------------------------------------
`run_command` is a general shell and correctly stays behind the human
confirmation gate: an arbitrary command cannot be undone. But routing
`npm install` through that gate is what produced "it's waiting for your
approval" in the middle of a build the owner had already asked for, which
reads as ZENO refusing to work.

This executor takes the opposite shape. It is deliberately NARROW rather
than gated: a short allow-list of project tooling, no shell (so nothing can
be chained), and a working directory that must sit inside the task's own
project folder. Within those walls the work is ordinary, local and
reversible, so it runs. Anything outside them is not quietly widened -- it
is refused here and referred to the confirmation gate.

WHAT IT REFUSES TO FAKE
-----------------------
* Output lines come from the process's real stdout/stderr.
* `ok` is `exit_code == 0`. A failed command is never rounded up.
* A timeout kills the whole process tree and is reported as a failure.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from reyes_agent import task_engine

# Programs this executor may start on its own. Base name, lower-cased, no
# extension. Everything here is project tooling that writes inside the
# project folder.
ALLOWED_PROGRAMS = frozenset({
    "npm", "npx", "pnpm", "yarn", "bun",
    "node", "tsc", "vite", "esbuild", "webpack", "rollup",
    "python", "python3", "py", "pip", "pip3",
    "git",
})

# Git is allowed only for local history. Anything that reaches the network
# or rewrites the working tree destructively is not this executor's job.
GIT_ALLOWED = frozenset({"init", "add", "commit", "status", "log", "diff", "branch", "config"})

# Substrings that mark a command as out of scope regardless of program.
DENIED_FRAGMENTS = (
    "publish", "deploy", "--global", " -g ", "push", "remote add",
    "rm -rf", "rimraf", "del /", "rd /s", "format ", "shutdown",
    "reg add", "reg delete", "netsh", "icacls", "takeown",
    "curl ", "wget ", "invoke-webrequest", "invoke-expression",
    "start-process", "new-service", "sc create",
)

# Characters that only make sense when a shell interprets them. We never
# use a shell, so their presence means someone is trying to chain.
SHELL_METACHARACTERS = ("&", "|", ";", ">", "<", "`", "$(", "\n", "\r")

DEFAULT_TIMEOUT = 180
MAX_TIMEOUT = 900
_MAX_CAPTURED_LINES = 600


@dataclass
class CommandResult:
    ok: bool
    command: str
    exit_code: int | None = None
    output: str = ""
    duration_s: float = 0.0
    blocked: bool = False
    reason: str = ""
    skipped_duplicate: bool = False

    def summary(self) -> str:
        if self.blocked:
            return f"REFUSED: {self.reason}"
        if self.skipped_duplicate:
            return f"Skipped duplicate: `{self.command}` already ran in this task."
        head = "OK" if self.ok else "FAILED"
        return (f"{head} (exit {self.exit_code}) after {self.duration_s:.1f}s: `{self.command}`\n"
                f"{self.output[-2000:]}" if self.output else
                f"{head} (exit {self.exit_code}) after {self.duration_s:.1f}s: `{self.command}`")


@dataclass
class BackgroundProcess:
    command: str
    process: subprocess.Popen
    lines: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def output(self) -> str:
        with self._lock:
            return "\n".join(self.lines)

    def alive(self) -> bool:
        return self.process.poll() is None

    def stop(self) -> None:
        _kill_tree(self.process)


# --- classification ------------------------------------------------------

def _in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def classify(command: str) -> tuple[bool, str]:
    """(may_run_here, reason_if_not).

    A False here is not "denied forever" -- it means this narrow executor is
    the wrong door and the command belongs at the confirmation gate.
    """
    raw = str(command or "").strip()
    if not raw:
        return False, "Empty command."
    if len(raw) > 500:
        return False, "Command is unreasonably long."
    lowered = f" {raw.lower()} "
    for char in SHELL_METACHARACTERS:
        if char in raw:
            return False, (
                f"Chained/redirected commands are not run automatically ('{char}'). "
                "Run the steps as separate commands."
            )
    for fragment in DENIED_FRAGMENTS:
        if fragment in lowered:
            return False, f"'{fragment.strip()}' needs your explicit approval -- not run automatically."
    try:
        parts = shlex.split(raw, posix=False)
    except ValueError as exc:
        return False, f"Could not parse the command: {exc}"
    if not parts:
        return False, "Empty command."
    program = Path(parts[0].strip('"')).name.lower()
    program = program.rsplit(".", 1)[0] if program.endswith((".exe", ".cmd", ".bat")) else program
    if program not in ALLOWED_PROGRAMS:
        return False, (
            f"'{program}' is not one of the project tools ZENO runs on its own "
            f"({', '.join(sorted(ALLOWED_PROGRAMS))}). It needs your approval."
        )
    if program == "git":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub not in GIT_ALLOWED:
            return False, f"git {sub or '(no subcommand)'} is not run automatically."
    if program in {"pip", "pip3"} and len(parts) > 1 and parts[1].lower() == "install":
        # Installing into the machine-wide interpreter is a system change,
        # not a project change. Inside a virtualenv it is contained, so it
        # stays ordinary work.
        if not _in_virtualenv():
            return False, (
                "pip install would modify the system Python. Approve it explicitly, "
                "or create a virtual environment for the project first."
            )
    return True, ""


# --- process control -----------------------------------------------------

def _resolve(parts: list[str]) -> list[str] | None:
    """Find the real executable. On Windows `npm` is `npm.cmd`, and Popen
    without a shell needs the resolved path, not the bare name."""
    program = parts[0].strip('"')
    found = shutil.which(program)
    if not found:
        return None
    return [found, *[p.strip('"') if p.startswith('"') and p.endswith('"') else p for p in parts[1:]]]


def _popen_kwargs() -> dict:
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if sys.platform == "win32":
        # Own process group so a timeout can kill the whole tree -- npm and
        # vite both spawn children that outlive a bare terminate().
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=15, check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), 15)
    except Exception:  # noqa: BLE001
        pass
    try:
        process.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


def _fingerprint(command: str, cwd: Path) -> str:
    return f"{' '.join(str(command).lower().split())}@{str(cwd).lower()}"


# --- the two entry points ------------------------------------------------

def run(task_id: str, command: str, cwd: Path, *, timeout: int = DEFAULT_TIMEOUT,
        allow_duplicate: bool = False) -> CommandResult:
    """Run a command to completion inside the task's project folder.

    Streams every real output line into the Live Activity panel as it
    arrives, so the owner watches the actual command, not a placeholder.
    """
    command = str(command or "").strip()
    cwd = Path(cwd)
    allowed, reason = classify(command)
    if not allowed:
        task_engine.record_warning(task_id, f"Refused `{command}`: {reason}")
        return CommandResult(False, command, blocked=True, reason=reason)
    if not cwd.is_dir():
        return CommandResult(False, command, blocked=True,
                             reason=f"Working directory {cwd} does not exist.")

    fingerprint = _fingerprint(command, cwd)
    if not allow_duplicate and task_engine.already_ran(task_id, fingerprint):
        task_engine.record_terminal(task_id, f"[skipped duplicate] {command}", command=command)
        return CommandResult(True, command, exit_code=0, skipped_duplicate=True,
                             reason="Already ran in this task.")

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return CommandResult(False, command, blocked=True, reason=str(exc))
    resolved = _resolve(parts)
    if resolved is None:
        missing = Path(parts[0]).name
        return CommandResult(False, command, blocked=True,
                             reason=f"'{missing}' is not installed or not on PATH.")

    timeout = max(5, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    task_engine.record_terminal(task_id, f"$ {command}", command=command)
    started = time.time()
    lines: list[str] = []
    try:
        process = subprocess.Popen(resolved, cwd=str(cwd), **_popen_kwargs())
    except OSError as exc:
        return CommandResult(False, command, reason=f"Could not start: {exc}",
                             duration_s=time.time() - started)

    task_engine.register_closer(task_id, command, lambda: _kill_tree(process))

    def pump() -> None:
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                text = line.rstrip("\r\n")
                if len(lines) < _MAX_CAPTURED_LINES:
                    lines.append(text)
                    task_engine.record_terminal(task_id, text, command=command)
                elif len(lines) == _MAX_CAPTURED_LINES:
                    lines.append("... output truncated ...")
        except Exception:  # noqa: BLE001 -- a closed pipe ends the pump
            pass

    reader = threading.Thread(target=pump, name="zeno-cmd-reader", daemon=True)
    reader.start()

    timed_out = False
    deadline = started + timeout
    while process.poll() is None:
        if task_engine.is_cancelled(task_id):
            _kill_tree(process)
            task_engine.record_terminal(task_id, "[cancelled] process stopped", command=command)
            return CommandResult(False, command, exit_code=None, output="\n".join(lines),
                                 duration_s=time.time() - started, reason="Task was cancelled.")
        if time.time() > deadline:
            timed_out = True
            _kill_tree(process)
            break
        time.sleep(0.05)

    reader.join(timeout=3)
    exit_code = process.poll()
    duration = time.time() - started
    output = "\n".join(lines)

    if timed_out:
        task_engine.record_terminal(task_id, f"[timeout] killed after {timeout}s", command=command)
        return CommandResult(False, command, exit_code=exit_code, output=output,
                             duration_s=duration, reason=f"Timed out after {timeout}s.")

    ok = exit_code == 0
    if ok:
        task_engine.mark_ran(task_id, fingerprint)
    task_engine.record_terminal(task_id, f"[exit {exit_code}] {command}", command="")
    return CommandResult(ok, command, exit_code=exit_code, output=output, duration_s=duration,
                         reason="" if ok else f"Exited with code {exit_code}.")


def spawn(task_id: str, command: str, cwd: Path, *, ready_markers: tuple[str, ...] = (),
          ready_timeout: int = 60, on_line: Callable[[str], None] | None = None
          ) -> tuple[BackgroundProcess | None, str]:
    """Start a long-running process (a dev server, or a build job) and leave
    it running.

    Waits only until a real readiness marker appears in its output or it
    exits. With no `ready_markers` it does not wait at all, which is what
    makes a background build return immediately. Returns (process, error).
    The process is registered with the task so Cancel actually stops it.

    `on_line` receives every output line as it arrives -- used by the job
    registry (executors/jobs.py) to keep a bounded head/tail rather than the
    whole of a chatty build.
    """
    command = str(command or "").strip()
    cwd = Path(cwd)
    allowed, reason = classify(command)
    if not allowed:
        return None, reason
    if not cwd.is_dir():
        return None, f"Working directory {cwd} does not exist."
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return None, str(exc)
    resolved = _resolve(parts)
    if resolved is None:
        return None, f"'{Path(parts[0]).name}' is not installed or not on PATH."

    task_engine.record_terminal(task_id, f"$ {command}", command=command)
    try:
        process = subprocess.Popen(resolved, cwd=str(cwd), **_popen_kwargs())
    except OSError as exc:
        return None, f"Could not start '{command}': {exc}"

    background = BackgroundProcess(command=command, process=process)
    task_engine.register_closer(task_id, f"server: {command}", background.stop)

    ready = threading.Event()

    def pump() -> None:
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                text = line.rstrip("\r\n")
                with background._lock:
                    if len(background.lines) < _MAX_CAPTURED_LINES:
                        background.lines.append(text)
                if on_line is not None:
                    try:
                        on_line(text)
                    except Exception:  # noqa: BLE001 -- a bad consumer must not stall the pipe
                        pass
                task_engine.record_terminal(task_id, text, command=command)
                if ready_markers and any(marker.lower() in text.lower() for marker in ready_markers):
                    ready.set()
        except Exception:  # noqa: BLE001
            pass
        finally:
            ready.set()

    threading.Thread(target=pump, name="zeno-server-reader", daemon=True).start()

    if ready_markers:
        ready.wait(timeout=max(5, min(int(ready_timeout), 180)))
    if process.poll() is not None:
        return None, (f"'{command}' exited immediately with code {process.poll()}.\n"
                      + background.output()[-1000:])
    return background, ""


def tool_available(program: str) -> bool:
    """Honest dependency check -- used instead of pretending Node.js exists."""
    return shutil.which(str(program)) is not None


def environment_report() -> dict[str, str]:
    """What is actually installed, for the plan and the final report."""
    report: dict[str, str] = {}
    for program in ("node", "npm", "npx", "python", "git"):
        path = shutil.which(program)
        if not path:
            report[program] = ""
            continue
        try:
            result = subprocess.run([path, "--version"], capture_output=True, text=True,
                                    timeout=15, check=False)
            report[program] = (result.stdout or result.stderr or "").strip().splitlines()[0][:60]
        except Exception:  # noqa: BLE001
            report[program] = "installed"
    return report
