"""Agent Runtime -- persistent supervised workers, real heartbeats, real
recovery.

AN HONEST NOTE ON "EVERY AGENT IS ALIVE"
----------------------------------------
A ZENO specialist is a system prompt plus a scoped toolset; its work is an
LLM call. Between tasks there is genuinely nothing for it to compute. So
"alive" here does NOT mean twelve threads busy-waiting to look impressive
-- that would burn CPU on a 4-thread machine to produce a convincing lie,
which is exactly what the spec says not to do.

What IS real, and is what this module implements:

  * Each agent owns a LIVE worker thread that exists from boot to
    shutdown, blocking on its own queue. The thread is real, its liveness
    is real, and `threading.Thread.is_alive()` is the source of truth.
  * Each agent has a REAL task queue. Work is submitted to it and
    processed in order; several agents therefore work genuinely
    concurrently rather than being spawned ad hoc per call.
  * The heartbeat is emitted BY the worker loop itself. If the thread
    dies, the heartbeat genuinely stops -- it is not a timer lying on the
    thread's behalf. That distinction is the whole point.
  * The supervisor detects a stale heartbeat and restarts that ONE worker,
    preserving its queue. This is tested by actually killing a worker.
  * Metrics (tasks done, failures, average duration, last activity) are
    counted from real executions, never estimated.

So: idle agents sit blocked on a queue consuming no CPU, and report IDLE
-- which is the truth. `health()` reports what is actually observable and
nothing more.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# Lifecycle states (spec's list, minus ones we cannot truthfully observe).
OFFLINE = "offline"
STARTING = "starting"
IDLE = "idle"
WORKING = "working"
ERROR = "error"
RESTARTING = "restarting"
STANDBY = "standby"
SLEEPING = "sleeping"

# A worker ticks its heartbeat every loop and at least this often while
# blocked on the queue (the queue.get timeout). Stale => unhealthy.
_HEARTBEAT_INTERVAL = 2.0
_STALE_AFTER = 10.0
_SUPERVISOR_INTERVAL = 4.0


@dataclass
class AgentTask:
    id: str
    agent: str
    description: str
    fn: Callable[[], str]
    submitted_at: float = field(default_factory=time.time)
    result: str | None = None
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)

    def wait(self, timeout: float | None = None) -> str:
        """Block until this task finishes. Returns its result text."""
        if not self.done.wait(timeout):
            return f"Task for {self.agent} timed out after {timeout}s."
        return self.result if self.error is None else f"Error: {self.error}"


@dataclass
class AgentMetrics:
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_duration: float = 0.0
    restarts: int = 0
    last_activity: float = 0.0
    last_task: str = ""

    @property
    def avg_duration(self) -> float:
        n = self.tasks_completed + self.tasks_failed
        return (self.total_duration / n) if n else 0.0

    @property
    def success_rate(self) -> float:
        n = self.tasks_completed + self.tasks_failed
        return (self.tasks_completed / n * 100) if n else 100.0


class AgentWorker:
    """One specialist's persistent runtime."""

    def __init__(self, agent_id: str, role: str = "") -> None:
        self.agent_id = agent_id
        self.role = role
        self.queue: queue.Queue[AgentTask | None] = queue.Queue()
        self.state = OFFLINE
        self.heartbeat = 0.0
        self.started_at = 0.0
        self.metrics = AgentMetrics()
        self.current_task: str = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._restart_lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.set()
        self.state = STARTING
        self.started_at = time.time()
        self.heartbeat = time.time()
        self._thread = threading.Thread(target=self._run, name=f"agent-{self.agent_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.queue.put(None)  # unblock the get()
        self.state = OFFLINE

    def is_alive(self) -> bool:
        """Ground truth -- the actual OS thread, not a flag we set."""
        return self._thread is not None and self._thread.is_alive()

    def is_healthy(self) -> bool:
        if self.state in (OFFLINE, STANDBY, SLEEPING):
            return True  # deliberately not running is not "unhealthy"
        return self.is_alive() and (time.time() - self.heartbeat) < _STALE_AFTER

    # -- the loop -------------------------------------------------------
    def _run(self) -> None:
        self.state = IDLE
        while not self._stop.is_set():
            if self.state == SLEEPING:
                # A sleeping specialist keeps its real thread identity but
                # blocks without a periodic wakeup until work arrives.
                self._wake.wait()
                self._wake.clear()
                if self._stop.is_set():
                    break
                self.state = IDLE
                self.heartbeat = time.time()
                continue
            self.heartbeat = time.time()  # emitted BY the worker, always
            try:
                task = self.queue.get(timeout=_HEARTBEAT_INTERVAL)
            except queue.Empty:
                continue  # idle tick; costs nothing, proves liveness
            if task is None:
                break
            self._execute(task)
            self.queue.task_done()
        self.state = OFFLINE

    def _execute(self, task: AgentTask) -> None:
        self.state = WORKING
        self.current_task = task.description[:120]
        started = time.time()
        _publish("agent.task_started", {"agent": self.agent_id, "task": task.description[:200]})
        try:
            task.result = task.fn()
            self.metrics.tasks_completed += 1
        except Exception as exc:  # noqa: BLE001 -- a failed task must not kill the worker
            task.error = f"{type(exc).__name__}: {exc}"
            task.result = f"Error: {task.error}"
            self.metrics.tasks_failed += 1
        finally:
            dur = time.time() - started
            self.metrics.total_duration += dur
            self.metrics.last_activity = time.time()
            self.metrics.last_task = task.description[:120]
            self.current_task = ""
            self.heartbeat = time.time()
            self.state = IDLE
            task.done.set()
            _publish("agent.task_finished", {
                "agent": self.agent_id, "ok": task.error is None,
                "duration_ms": int(dur * 1000),
            })

    def sleep(self) -> bool:
        if self.state != IDLE or not self.is_alive():
            return False
        self.state = SLEEPING
        self._wake.clear()
        return True

    def wake(self) -> bool:
        if self.state != SLEEPING:
            return False
        self._wake.set()
        return True

    def snapshot(self) -> dict[str, Any]:
        """Observable truth only."""
        return {
            "agent": self.agent_id,
            "role": self.role,
            "state": self.state,
            "alive": self.is_alive(),
            "healthy": self.is_healthy(),
            "heartbeat_age_s": round(time.time() - self.heartbeat, 1) if self.heartbeat else None,
            "uptime_s": round(time.time() - self.started_at) if self.started_at else 0,
            "queue_depth": self.queue.qsize(),
            "current_task": self.current_task,
            "tasks_completed": self.metrics.tasks_completed,
            "tasks_failed": self.metrics.tasks_failed,
            "success_rate": round(self.metrics.success_rate, 1),
            "avg_duration_s": round(self.metrics.avg_duration, 2),
            "restarts": self.metrics.restarts,
            "last_task": self.metrics.last_task,
            "last_activity_s_ago": (round(time.time() - self.metrics.last_activity)
                                     if self.metrics.last_activity else None),
        }


def _publish(event_type: str, payload: dict) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="agent_runtime")
    except Exception:  # noqa: BLE001 -- telemetry must never break the runtime
        pass


# --- the runtime -------------------------------------------------------
# Titles come from the user's AI Company spec. They are labels for the
# dashboard, not behaviour -- each agent's actual behaviour is its prompt
# and toolset in tools/subagents.py.
AGENT_ROLES: dict[str, str] = {
    "aris": "Chief Research Officer",
    "tosin": "Chief Technology Officer",
    "stark": "Chief Security Officer",
    "titan": "Chief Financial Officer",
    "kate": "Chief Education Officer",
    "ultron": "Chief Strategy Officer",
    "zeal": "Creative Director",
    "hermes_comm": "Chief Communications Officer",
    "nova": "Chief Vision Officer",
    "helios": "Chief Wellness Officer",
    "oracle": "Chief Analytics Officer",
    "apex": "Gaming Director",
    "atlas": "Mission Control",
}

_workers: dict[str, AgentWorker] = {}
_supervisor: threading.Thread | None = None
_supervisor_stop = threading.Event()
_lock = threading.Lock()
_boot_log: list[str] = []
_booted_at: float = 0.0


def boot(on_line: Callable[[str], None] | None = None) -> list[str]:
    """Start every agent worker. Returns the real boot log."""
    global _supervisor, _booted_at
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        if on_line:
            on_line(msg)

    with _lock:
        for agent_id, role in AGENT_ROLES.items():
            w = _workers.get(agent_id)
            if w is None:
                w = AgentWorker(agent_id, role)
                _workers[agent_id] = w
            w.start()

    # Confirm each thread actually reached its loop before claiming online.
    deadline = time.time() + 5
    for agent_id in AGENT_ROLES:
        w = _workers[agent_id]
        while time.time() < deadline and w.state == STARTING:
            time.sleep(0.01)
        log(f"{agent_id.upper().replace('_COMM', '')} {'online' if w.is_alive() else 'FAILED TO START'}")

    if _supervisor is None or not _supervisor.is_alive():
        _supervisor_stop.clear()
        _supervisor = threading.Thread(target=_supervise, name="agent-supervisor", daemon=True)
        _supervisor.start()
        log("Supervisor online")

    _booted_at = time.time()
    _boot_log[:] = lines
    alive = sum(1 for w in _workers.values() if w.is_alive())
    log(f"{alive} of {len(AGENT_ROLES)} specialist agents online.")
    _publish("runtime.booted", {"agents": alive, "total": len(AGENT_ROLES)})
    return lines


def shutdown() -> None:
    _supervisor_stop.set()
    with _lock:
        workers = list(_workers.values())
    for w in workers:
        w.stop()
    # The process may use daemon threads as a final safety net, but orderly
    # shutdown must first give every owned worker a chance to leave its queue.
    for w in workers:
        if w._thread is not None and w._thread is not threading.current_thread():
            w._thread.join(timeout=2.0)
    if _supervisor is not None and _supervisor is not threading.current_thread():
        _supervisor.join(timeout=2.0)


def _supervise() -> None:
    """Detect dead or stalled workers and restart exactly those."""
    while not _supervisor_stop.wait(_SUPERVISOR_INTERVAL):
        with _lock:
            workers = list(_workers.values())
        for w in workers:
            if w.state in (OFFLINE, STANDBY):
                continue
            if w.state == RESTARTING:
                # A long-running task can delay a restart. Never create a
                # second worker while the original OS thread still exists;
                # retry only after it has actually exited.
                if not w.is_alive():
                    restart(w.agent_id, reason="previous restart completed")
                continue
            if not w.is_healthy():
                reason = "thread died" if not w.is_alive() else "heartbeat stale"
                restart(w.agent_id, reason=reason)


def restart(agent_id: str, reason: str = "manual") -> str:
    """Restart ONE worker, preserving its queued work."""
    w = _workers.get(agent_id)
    if w is None:
        return f"No agent '{agent_id}'."
    with w._restart_lock:
        old_thread = w._thread
        w.state = RESTARTING
        _publish("agent.restarting", {"agent": agent_id, "reason": reason})
        # Signal and join the *existing* thread before replacing its control
        # events. Replacing `_stop` first made the old loop observe a fresh,
        # unset event and left duplicate agent threads alive.
        if old_thread is not None and old_thread.is_alive():
            w._stop.set()
            w._wake.set()
            w.queue.put(None)
            if old_thread is not threading.current_thread():
                old_thread.join(timeout=2.0)
        if old_thread is not None and old_thread.is_alive():
            _publish("agent.restart_deferred", {"agent": agent_id, "reason": reason})
            return f"{agent_id.upper().replace('_COMM','')} restart is waiting for its active task to finish."

        # Queue contents after the stop sentinel deliberately survive for the
        # replacement worker. Remove only stale stop sentinels: a thread can
        # observe its stop event after finishing work and exit before consuming
        # the sentinel that woke it. Real queued AgentTask objects retain their
        # order and survive the restart.
        pending: list[AgentTask] = []
        while True:
            try:
                item = w.queue.get_nowait()
            except queue.Empty:
                break
            else:
                w.queue.task_done()
                if item is not None:
                    pending.append(item)
        for item in pending:
            w.queue.put(item)

        # Only now is it safe to create fresh controls.
        w._thread = None
        w._stop = threading.Event()
        w._wake = threading.Event()
        w.metrics.restarts += 1
        w.start()
        deadline = time.time() + 5
        while time.time() < deadline and not w.is_alive():
            time.sleep(0.01)
        ok = w.is_alive()
    _publish("agent.restarted", {"agent": agent_id, "ok": ok, "reason": reason})
    return (f"{agent_id.upper().replace('_COMM','')} recovered successfully ({reason})."
            if ok else f"{agent_id} FAILED to restart.")


def submit(agent_id: str, description: str, fn: Callable[[], str]) -> AgentTask | None:
    """Queue work on a live agent. Returns the task handle, or None if the
    agent doesn't exist."""
    w = _workers.get(agent_id)
    if w is None:
        return None
    if not w.is_alive():
        restart(agent_id, reason="submit to dead worker")
    w.wake()
    task = AgentTask(id=uuid.uuid4().hex[:8], agent=agent_id, description=description, fn=fn)
    w.queue.put(task)
    return task


def is_running() -> bool:
    return bool(_workers) and any(w.is_alive() for w in _workers.values())


def health() -> dict[str, Any]:
    """The real operational state. Nothing here is estimated or assumed."""
    with _lock:
        snaps = [w.snapshot() for w in _workers.values()]
    alive = sum(1 for s in snaps if s["alive"])
    healthy = sum(1 for s in snaps if s["healthy"])
    return {
        "booted": bool(_booted_at),
        "uptime_s": round(time.time() - _booted_at) if _booted_at else 0,
        "supervisor_alive": _supervisor is not None and _supervisor.is_alive(),
        "agents_total": len(snaps),
        "agents_alive": alive,
        "agents_healthy": healthy,
        "all_online": bool(snaps) and alive == len(snaps) and healthy == len(snaps),
        "queued_tasks": sum(s["queue_depth"] for s in snaps),
        "working_now": [s["agent"] for s in snaps if s["state"] == WORKING],
        "agents": snaps,
        "boot_log": list(_boot_log),
    }


def get_worker(agent_id: str) -> AgentWorker | None:
    return _workers.get(agent_id)


def sleep_idle_agents() -> int:
    """Put idle specialists into a true blocking sleep state.

    Submission wakes the required worker automatically, so this conserves
    wakeups without changing the promise that every agent remains alive.
    """
    with _lock:
        workers = list(_workers.values())
    return sum(1 for worker in workers if worker.sleep())


def wake(agent_id: str) -> bool:
    worker = _workers.get(agent_id)
    return worker.wake() if worker is not None else False
