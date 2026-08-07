"""The Build Task Engine -- lifecycle for a request that must actually happen.

WHY THIS EXISTS
---------------
ZENO could already write a file (`write_project_file`) and already had a
Live Activity projection (`project_activity`). What it did not have was a
*task*: a declared plan with a finite number of steps, a state that moves
forward on real evidence, a cancel token, a retry budget scoped to the one
step that failed, and a verified output path at the end. Without that, a
multi-step request ("build it, run it, open it, check it") had nowhere to
live, so the model did the only thing left available to it and described
the work instead.

HONESTY RULES BAKED IN
----------------------
* A step only becomes `completed` when a caller reports a real outcome.
  Nothing in this module advances state on a timer or an estimate.
* `progress_percent` is emitted ONLY when a finite plan was declared, and
  it is completed/total over that declared plan -- never a guess.
* Terminal lines are captured from actual process output. There is no
  path in this module that writes a synthetic command result.
* `COMPLETED` is refused unless the caller passes verification evidence.
  A task that ran without being verified ends `FAILED`, not `COMPLETED`.

Bounded on purpose: this is a live projection, the Event Bus is the
durable history. A long build cannot grow the process without limit.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# --- lifecycle states ---------------------------------------------------
PLANNING = "PLANNING"
WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
RETRYING = "RETRYING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TERMINAL_STATES = frozenset({COMPLETED, FAILED, CANCELLED})
ALL_STATES = frozenset({
    PLANNING, WAITING_FOR_APPROVAL, RUNNING, VERIFYING, RETRYING,
    COMPLETED, FAILED, CANCELLED,
})

# A failed step gets this many extra attempts before the task gives up.
# Deliberately small: a step that fails three times is reporting a real
# blocker, and grinding on it hides that from the owner.
MAX_STEP_ATTEMPTS = 3

_MAX_TASKS = 12
_MAX_STEPS = 200
_MAX_TERMINAL_LINES = 400
_MAX_FILES = 200
_MAX_NOTES = 40


class TaskCancelled(Exception):
    """Raised inside an executor when the owner cancelled the task."""


@dataclass
class Step:
    id: str
    label: str
    state: str = "pending"          # pending | running | completed | failed | skipped
    detail: str = ""
    attempts: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.id, "label": self.label, "state": self.state,
            "detail": self.detail, "attempts": self.attempts,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "error": self.error,
        }


@dataclass
class Task:
    id: str
    plan_id: str
    title: str
    output_path: str = ""
    state: str = PLANNING
    steps: list[Step] = field(default_factory=list)
    files: deque = field(default_factory=lambda: deque(maxlen=_MAX_FILES))
    terminal: deque = field(default_factory=lambda: deque(maxlen=_MAX_TERMINAL_LINES))
    warnings: deque = field(default_factory=lambda: deque(maxlen=_MAX_NOTES))
    errors: deque = field(default_factory=lambda: deque(maxlen=_MAX_NOTES))
    current_file: str = ""
    current_command: str = ""
    preview_url: str = ""
    verified: bool = False
    verification: list[dict[str, Any]] = field(default_factory=list)
    planned_total: int = 0
    error_details: str = ""
    start_time: float = field(default_factory=time.time)
    completion_time: float = 0.0
    # Cancellation and process ownership. `closers` are callables that stop
    # something this task started (a preview server, a subprocess); cancel
    # runs them so "Cancel Task" actually stops the work, not just the label.
    cancel_event: threading.Event = field(default_factory=threading.Event)
    closers: list[tuple[str, Callable[[], None]]] = field(default_factory=list)
    # Command fingerprints already executed, so a retried plan step or a
    # repeated model call cannot run `npm install` twice.
    ran_commands: set[str] = field(default_factory=set)
    last_tool_call_id: str = ""


_lock = threading.RLock()
_tasks: dict[str, Task] = {}


# --- event emission -----------------------------------------------------

def _emit(action: str, task: Task) -> None:
    """Publish a bounded snapshot. Observability never blocks real work."""
    try:
        from reyes_agent import event_bus

        event_bus.publish(
            "build.task",
            {"action": action, "task": snapshot(task)},
            source="task_engine",
            correlation_id=task.id,
        )
    except Exception:  # noqa: BLE001 -- a dead bus cannot fail a file write
        pass


def snapshot(task: Task) -> dict[str, Any]:
    """The shape the Live Activity panel renders.

    `progress_percent` stays None unless a finite plan was declared. The
    panel then shows a completed-step count instead of inventing a bar.
    """
    with _lock:
        total = max(task.planned_total, len(task.steps))
        done = sum(1 for step in task.steps if step.state in {"completed", "skipped"})
        percent = int(round(done * 100 / total)) if task.planned_total and total else None
        current = next((s for s in task.steps if s.state == "running"), None)
        retrying = [s.as_dict() for s in task.steps if s.state == "failed" and 0 < s.attempts < MAX_STEP_ATTEMPTS]
        return {
            "task_id": task.id,
            "plan_id": task.plan_id,
            "title": task.title,
            "output_path": task.output_path,
            "current_status": task.state,
            "state": task.state,
            "steps": [step.as_dict() for step in task.steps],
            "current_step": current.as_dict() if current else None,
            "completed_steps": done,
            "pending_steps": [s.label for s in task.steps if s.state == "pending"],
            "planned_total": task.planned_total,
            "progress_percent": percent,
            "files": list(task.files),
            "current_file": task.current_file,
            "current_command": task.current_command,
            "terminal": list(task.terminal),
            "warnings": list(task.warnings),
            "errors": list(task.errors),
            "retrying": retrying,
            "preview_url": task.preview_url,
            "verified": task.verified,
            "verification": list(task.verification),
            "error_details": task.error_details,
            "start_time": task.start_time,
            "completion_time": task.completion_time,
            "cancellable": task.state not in TERMINAL_STATES,
        }


# --- lifecycle ----------------------------------------------------------

def create(title: str, plan: list[str] | None = None, output_path: str = "") -> Task:
    """Open a task in PLANNING. `plan` is the declared, finite step list."""
    task = Task(
        id=uuid.uuid4().hex[:12],
        plan_id=uuid.uuid4().hex[:12],
        title=(title or "Untitled task").strip()[:160],
        output_path=str(output_path or ""),
    )
    with _lock:
        _tasks[task.id] = task
        # Evict the oldest FINISHED task first; a running task is never
        # dropped out from under its executor just because it is old.
        while len(_tasks) > _MAX_TASKS:
            victim = next(
                (tid for tid, t in _tasks.items() if t.state in TERMINAL_STATES),
                next(iter(_tasks)),
            )
            _tasks.pop(victim, None)
    if plan:
        set_plan(task.id, plan)
    _emit("created", task)
    return task


def set_plan(task_id: str, labels: list[str]) -> Task | None:
    """Declare the plan. This is what makes a real percentage possible."""
    task = get(task_id)
    if task is None:
        return None
    with _lock:
        task.steps = [
            Step(id=f"{task.plan_id}-{index:02d}", label=str(label).strip()[:160])
            for index, label in enumerate(labels[:_MAX_STEPS])
            if str(label).strip()
        ]
        task.planned_total = len(task.steps)
        task.state = PLANNING
    _emit("planned", task)
    return task


def get(task_id: str) -> Task | None:
    with _lock:
        return _tasks.get(str(task_id or ""))


def active() -> list[dict[str, Any]]:
    with _lock:
        return [snapshot(task) for task in _tasks.values()]


def latest_open() -> Task | None:
    """The most recent task that has not finished -- what the panel follows."""
    with _lock:
        open_tasks = [t for t in _tasks.values() if t.state not in TERMINAL_STATES]
    return open_tasks[-1] if open_tasks else None


def set_state(task_id: str, state: str, detail: str = "") -> None:
    task = get(task_id)
    if task is None or state not in ALL_STATES:
        return
    with _lock:
        task.state = state
        if detail:
            task.error_details = detail[:1000] if state == FAILED else task.error_details
    _emit("state", task)


def check_cancelled(task_id: str) -> None:
    """Executors call this between units of work. Raises to unwind cleanly."""
    task = get(task_id)
    if task is not None and task.cancel_event.is_set():
        raise TaskCancelled(f"Task '{task.title}' was cancelled.")


def is_cancelled(task_id: str) -> bool:
    task = get(task_id)
    return bool(task and task.cancel_event.is_set())


# --- steps --------------------------------------------------------------

def _find_step(task: Task, label_or_id: str) -> Step | None:
    key = str(label_or_id or "").strip()
    if not key:
        return None
    folded = key.casefold()
    for step in task.steps:
        if step.id == key:
            return step
    for step in task.steps:
        if step.label.casefold() == folded and step.state in {"pending", "running"}:
            return step
    for step in task.steps:
        if step.label.casefold() == folded:
            return step
    return None


def begin_step(task_id: str, label: str) -> str:
    """Start a step. Matches the declared plan when the label is one of its
    entries, otherwise appends -- real work that was not planned still shows
    up rather than being hidden to protect a tidy percentage."""
    task = get(task_id)
    if task is None:
        return ""
    check_cancelled(task_id)
    with _lock:
        step = _find_step(task, label)
        if step is None or step.state in {"completed", "skipped"}:
            step = Step(id=f"{task.plan_id}-x{len(task.steps):02d}", label=str(label).strip()[:160])
            if len(task.steps) < _MAX_STEPS:
                task.steps.append(step)
        if step.state == "failed":
            task.state = RETRYING
        elif task.state in {PLANNING, RETRYING}:
            task.state = RUNNING
        step.state = "running"
        step.attempts += 1
        step.started_at = time.time()
        step.error = ""
    _emit("step_started", task)
    return step.id


def complete_step(task_id: str, label_or_id: str, detail: str = "") -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        step = _find_step(task, label_or_id)
        if step is None:
            return
        step.state = "completed"
        step.finished_at = time.time()
        if detail:
            step.detail = str(detail)[:500]
        if task.state == RETRYING:
            task.state = RUNNING
    _emit("step_completed", task)


def fail_step(task_id: str, label_or_id: str, error: str) -> bool:
    """Mark a step failed. Returns True while retry budget remains.

    Only the failed step retries -- the task is not restarted, so files
    already written are not rewritten and servers already up are not
    started a second time.
    """
    task = get(task_id)
    if task is None:
        return False
    with _lock:
        step = _find_step(task, label_or_id)
        if step is None:
            return False
        step.state = "failed"
        step.finished_at = time.time()
        step.error = str(error)[:500]
        task.errors.append(f"{step.label}: {str(error)[:300]}")
        may_retry = step.attempts < MAX_STEP_ATTEMPTS
        task.state = RETRYING if may_retry else task.state
    _emit("step_failed", task)
    return may_retry


def skip_step(task_id: str, label_or_id: str, reason: str) -> None:
    """A planned step that turned out not to apply (no Node.js, no deps).

    Skipped is honest: it counts as resolved for progress but is labelled
    as skipped in the panel, so nobody reads it as work that happened.
    """
    task = get(task_id)
    if task is None:
        return
    with _lock:
        step = _find_step(task, label_or_id)
        if step is None:
            return
        step.state = "skipped"
        step.detail = str(reason)[:300]
        step.finished_at = time.time()
        task.warnings.append(f"Skipped {step.label}: {str(reason)[:200]}")
    _emit("step_skipped", task)


# --- observable detail ---------------------------------------------------

def record_file(task_id: str, relative_path: str) -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.current_file = str(relative_path)
        if relative_path not in task.files:
            task.files.append(str(relative_path))
    _emit("file", task)


def record_terminal(task_id: str, line: str, *, command: str = "") -> None:
    """One real line of process output. Called from the reader thread."""
    task = get(task_id)
    if task is None:
        return
    with _lock:
        if command:
            task.current_command = str(command)[:300]
        task.terminal.append(str(line)[:500])
    _emit("terminal", task)


def record_warning(task_id: str, message: str) -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.warnings.append(str(message)[:300])
    _emit("warning", task)


def record_verification(task_id: str, check: str, ok: bool, detail: str = "") -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.verification.append({"check": str(check)[:120], "ok": bool(ok), "detail": str(detail)[:300]})
        if not ok:
            task.warnings.append(f"Check failed: {check} -- {detail}"[:300])
    _emit("verification", task)


def set_preview_url(task_id: str, url: str) -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.preview_url = str(url)[:300]
    _emit("preview", task)


def set_output_path(task_id: str, path: str | Path) -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.output_path = str(path)
    _emit("output_path", task)


# --- process ownership ---------------------------------------------------

def register_closer(task_id: str, name: str, closer: Callable[[], None]) -> None:
    """Register something to stop when this task is cancelled or finished."""
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.closers.append((name, closer))


def _run_closers(task: Task) -> list[str]:
    with _lock:
        closers = list(task.closers)
        task.closers.clear()
    stopped = []
    for name, closer in closers:
        try:
            closer()
            stopped.append(name)
        except Exception:  # noqa: BLE001 -- best-effort teardown
            pass
    return stopped


def already_ran(task_id: str, fingerprint: str) -> bool:
    """Duplicate-command guard. See terminal executor."""
    task = get(task_id)
    if task is None:
        return False
    with _lock:
        return fingerprint in task.ran_commands


def mark_ran(task_id: str, fingerprint: str) -> None:
    task = get(task_id)
    if task is None:
        return
    with _lock:
        task.ran_commands.add(fingerprint)


# --- finish --------------------------------------------------------------

def cancel(task_id: str, reason: str = "Cancelled by the owner.") -> dict[str, Any] | None:
    """Stop the task AND everything it started."""
    task = get(task_id)
    if task is None:
        return None
    task.cancel_event.set()
    stopped = _run_closers(task)
    with _lock:
        for step in task.steps:
            if step.state in {"running", "pending"}:
                step.state = "skipped"
                step.detail = "Cancelled"
        task.state = CANCELLED
        task.error_details = str(reason)[:500]
        task.completion_time = time.time()
        task.current_command = ""
        if stopped:
            task.terminal.append(f"[cancelled] stopped: {', '.join(stopped)}")
    _emit("cancelled", task)
    return snapshot(task)


def fail(task_id: str, error: str) -> dict[str, Any] | None:
    task = get(task_id)
    if task is None:
        return None
    _run_closers(task)
    with _lock:
        task.state = FAILED
        task.error_details = str(error)[:1000]
        task.errors.append(str(error)[:300])
        task.completion_time = time.time()
    _emit("failed", task)
    return snapshot(task)


def complete(task_id: str, *, keep_running: bool = True) -> dict[str, Any] | None:
    """Finish the task -- but only if verification actually passed.

    This is the guardrail behind the whole feature request: a task that was
    never verified, or whose checks failed, cannot be reported as done. It
    ends FAILED with the reason attached, so the owner is told the truth.

    `keep_running=True` leaves a preview server up on purpose -- the point
    of the build was to look at it -- while cancellation still stops it.
    """
    task = get(task_id)
    if task is None:
        return None
    with _lock:
        failed_checks = [c for c in task.verification if not c["ok"]]
        unfinished = [s.label for s in task.steps if s.state in {"pending", "running"}]
        if not task.verification:
            task.state = FAILED
            task.error_details = (
                "Refusing to report success: no verification evidence was recorded. "
                "Run the verify step before finishing."
            )
        elif failed_checks:
            task.state = FAILED
            task.error_details = "Verification failed: " + "; ".join(
                f"{c['check']} ({c['detail']})" for c in failed_checks[:5]
            )
        elif unfinished:
            task.state = FAILED
            task.error_details = "Steps never ran: " + ", ".join(unfinished[:6])
        else:
            task.state = COMPLETED
            task.verified = True
        task.completion_time = time.time()
        task.current_command = ""
        result_state = task.state
    if result_state != COMPLETED or not keep_running:
        _run_closers(task)
    _emit("completed" if result_state == COMPLETED else "failed", task)
    return snapshot(task)


def shutdown_all() -> None:
    """Stop every process any task started -- used by orderly shutdown."""
    with _lock:
        tasks = list(_tasks.values())
    for task in tasks:
        _run_closers(task)
