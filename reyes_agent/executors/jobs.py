"""Background jobs for long project commands.

THE PROBLEM
-----------
`terminal.run` blocks until the command exits. That is right for `git init`
and wrong for `npm install`, which can take ten minutes -- and because a
tool call runs on the chat worker, a synchronous install held that worker
for the whole time. ZENO stayed technically alive but could not answer.

So commands that are long BY NATURE become jobs: started, tracked, polled
and cancellable, with the caller returning immediately.

WHAT THIS DOES NOT DO
---------------------
It does not introduce a second runtime. Processes are still started by
`terminal.spawn` (allow-list, no shell, cwd confined to the project), whose
reader thread already drains the pipe -- which is what stops a chatty build
from deadlocking on a full stdout buffer. This module adds a registry, a
state machine and ONE shared watchdog thread for the whole process, not one
thread per job.

Output is bounded. A webpack build can emit tens of thousands of lines;
keeping them all would trade a blocked worker for a memory leak. The head
and tail are kept, which is where the useful information actually is.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.executors import terminal

# --- states --------------------------------------------------------------
QUEUED = "QUEUED"
STARTING = "STARTING"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
TIMED_OUT = "TIMED_OUT"
CANCELLED = "CANCELLED"

FINISHED = frozenset({SUCCESS, FAILED, TIMED_OUT, CANCELLED})
ALL_STATES = frozenset({QUEUED, STARTING, RUNNING, *FINISHED})

# Command kinds -> configured timeout. Anything unrecognised gets the build
# timeout, which is the conservative middle.
BUILD, INSTALL, TEST, DEV = "build", "install", "test", "dev"

_MAX_JOBS = 40
_HEAD_LINES, _TAIL_LINES = 80, 200
_POLL_S = 0.5

_lock = threading.RLock()
_jobs: dict[str, "Job"] = {}
_watchdog: threading.Thread | None = None
_watchdog_stop = threading.Event()


def timeout_for(kind: str) -> int:
    return {
        BUILD: config.WEB_BUILD_TIMEOUT_SECONDS,
        INSTALL: config.WEB_INSTALL_TIMEOUT_SECONDS,
        TEST: config.WEB_TEST_TIMEOUT_SECONDS,
    }.get(kind, config.WEB_BUILD_TIMEOUT_SECONDS)


def classify(command: str) -> str:
    """Which timeout budget a command belongs to, from what it actually is."""
    text = " ".join(str(command or "").lower().split())
    if "install" in text or text.endswith(" ci") or " ci " in text:
        return INSTALL
    if "test" in text or "vitest" in text or "jest" in text:
        return TEST
    if " dev" in text or text.endswith("dev") or "serve" in text:
        return DEV
    return BUILD


@dataclass
class Job:
    id: str
    project: str
    command: str
    cwd: str
    kind: str
    timeout: int
    state: str = QUEUED
    pid: int | None = None
    exit_code: int | None = None
    started_at: float = 0.0
    _started_monotonic: float = 0.0
    finished_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    error: str = ""
    _head: list[str] = field(default_factory=list)
    _tail: deque = field(default_factory=lambda: deque(maxlen=_TAIL_LINES))
    _lines_seen: int = 0
    _process: Any = None

    # --- output ---------------------------------------------------------
    def record(self, line: str) -> None:
        self._lines_seen += 1
        if len(self._head) < _HEAD_LINES:
            self._head.append(line)
        else:
            self._tail.append(line)

    def output(self) -> str:
        """Head + tail, with an honest marker for what was dropped."""
        if self._lines_seen <= _HEAD_LINES:
            return "\n".join(self._head)
        dropped = self._lines_seen - len(self._head) - len(self._tail)
        middle = [f"... {dropped} line(s) omitted ..."] if dropped > 0 else []
        return "\n".join([*self._head, *middle, *self._tail])

    @property
    def running(self) -> bool:
        return self.state in {QUEUED, STARTING, RUNNING}

    @property
    def duration(self) -> float:
        if not self.started_at:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id, "project_id": self.project, "command": self.command,
            "cwd": self.cwd, "kind": self.kind, "state": self.state, "pid": self.pid,
            "exit_code": self.exit_code, "started_at": self.started_at,
            "finished_at": self.finished_at, "duration_s": round(self.duration, 2),
            "timeout": self.timeout, "lines": self._lines_seen, "error": self.error,
        }


def _ensure_watchdog() -> None:
    """ONE thread for every job, not one per job.

    A watchdog per job would mean a thread per concurrent build on top of
    each process's reader thread; a single poller keeps thread count flat.
    """
    global _watchdog
    with _lock:
        if _watchdog is not None and _watchdog.is_alive():
            return
        _watchdog_stop.clear()
        _watchdog = threading.Thread(target=_watch, name="zeno-job-watchdog", daemon=True)
        _watchdog.start()


def _watch() -> None:
    while not _watchdog_stop.is_set():
        time.sleep(_POLL_S)
        with _lock:
            live = [job for job in _jobs.values() if job.running]
        if not live:
            with _lock:
                if not any(job.running for job in _jobs.values()):
                    return          # nothing to watch; restarted on next start()
            continue
        for job in live:
            process = job._process
            if process is None:
                continue
            code = process.process.poll()
            if code is not None:
                _finish(job, SUCCESS if code == 0 else FAILED, exit_code=code)
                continue
            if (job.timeout and job._started_monotonic
                    and (time.monotonic() - job._started_monotonic) > job.timeout):
                # Kills only THIS job's process tree -- never a sweep of node
                # processes, which would take out unrelated work.
                try:
                    process.stop()
                except Exception:  # noqa: BLE001
                    pass
                _finish(job, TIMED_OUT, error=f"exceeded {job.timeout}s")


def _finish(job: Job, state: str, *, exit_code: int | None = None, error: str = "") -> None:
    with _lock:
        if not job.running:
            return
        job.state = state
        job.exit_code = exit_code
        job.finished_at = time.time()
        if error:
            job.error = error
    _emit(job, "finished")


def _emit(job: Job, action: str) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish("website.job", {"action": action, **job.as_dict()},
                          source="jobs", correlation_id=job.id)
    except Exception:  # noqa: BLE001 -- telemetry never blocks a build
        pass


def start(command: str, cwd: Path, *, project: str = "", task_id: str = "",
          kind: str = "", timeout: int | None = None) -> tuple[Job | None, str]:
    """Start a long command and return IMMEDIATELY. (job, error)."""
    command = str(command or "").strip()
    cwd = Path(cwd)
    kind = kind or classify(command)
    job = Job(id=uuid.uuid4().hex[:12], project=str(project or cwd.name), command=command,
              cwd=str(cwd), kind=kind,
              timeout=int(timeout) if timeout else timeout_for(kind))

    with _lock:
        # Same command already running for the same folder -> reuse it rather
        # than starting a second `npm install` over the same node_modules.
        for existing in _jobs.values():
            if (existing.running and existing.command == command
                    and Path(existing.cwd).resolve() == cwd.resolve()):
                return existing, ""
        _jobs[job.id] = job
        while len(_jobs) > _MAX_JOBS:
            victim = next((jid for jid, item in _jobs.items() if not item.running), None)
            if victim is None:
                break
            _jobs.pop(victim, None)

    job.state = STARTING
    _emit(job, "starting")
    background, error = terminal.spawn(task_id or "", command, cwd,
                                       on_line=job.record)
    if background is None:
        _finish(job, FAILED, error=error)
        return None, error

    with _lock:
        job._process = background
        job.pid = getattr(background.process, "pid", None)
        job.started_at = time.time()
        job._started_monotonic = time.monotonic()
        job.state = RUNNING
    _emit(job, "running")
    _ensure_watchdog()
    return job, ""


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(str(job_id or ""))


def active() -> list[dict[str, Any]]:
    with _lock:
        return [job.as_dict() for job in _jobs.values()]


def cancel(job_id: str) -> dict[str, Any] | None:
    """Stop one job's process tree. Unrelated processes are untouched."""
    job = get(job_id)
    if job is None:
        return None
    if not job.running:
        return job.as_dict()
    process = job._process
    if process is not None:
        try:
            process.stop()
        except Exception:  # noqa: BLE001
            pass
    _finish(job, CANCELLED, error="cancelled on request")
    return job.as_dict()


def cancel_for(cwd: Path) -> list[dict[str, Any]]:
    """Cancel every running job for one project folder."""
    target = Path(cwd).resolve()
    with _lock:
        matching = [job.id for job in _jobs.values()
                    if job.running and Path(job.cwd).resolve() == target]
    return [result for result in (cancel(jid) for jid in matching) if result]


def wait(job_id: str, timeout: float = 60.0) -> Job | None:
    """Block the CALLER (a test, or a step that genuinely needs the result).

    Never used by the chat path -- that is the entire point of this module.
    """
    job = get(job_id)
    if job is None:
        return None
    deadline = time.monotonic() + max(0.0, timeout)
    while job.running and time.monotonic() < deadline:
        time.sleep(_POLL_S / 2)
    return job


def shutdown_all() -> None:
    """Stop every running job -- used by orderly shutdown."""
    _watchdog_stop.set()
    with _lock:
        running = [job.id for job in _jobs.values() if job.running]
    for job_id in running:
        cancel(job_id)
