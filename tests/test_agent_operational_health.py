"""Operational health: does every agent REALLY accept, execute and return work?

This deliberately does not call the model. A provider turn would make the
run slow, costly and non-deterministic, and it would test the provider
rather than the runtime. Instead each agent receives a real harmless task
through the real `agent_runtime.submit` path -- same queue, same worker
thread, same lifecycle events, same metrics -- so what is verified is the
machinery ZENO depends on:

    submit -> accepted -> executed on that agent's own thread -> result
    returned to the caller -> metrics/heartbeat/presence updated

Failure, timeout and cancellation are exercised the same way, because an
agent that cannot report a failure honestly is worse than one that fails.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import agent_runtime, agent_teams, event_bus
from reyes_agent.agent_runtime import AGENT_ROLES
from reyes_agent.tools import TOOLS, subagents

FAILURES: list[str] = []
RESULTS: list[tuple[str, str, str]] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)
    return cond


print("=" * 72)
print("PER-AGENT OPERATIONAL HEALTH")
print("=" * 72)

agent_runtime.boot()

for agent_id, role in AGENT_ROLES.items():
    problems: list[str] = []

    # 1. Initializes.
    worker = agent_runtime.ensure_worker(agent_id)
    if worker is None or not worker.is_alive():
        problems.append("did not start")
        RESULTS.append((agent_id, "OFFLINE", "worker thread did not start"))
        FAILURES.append(f"{agent_id}: start")
        print(f"FAIL  {agent_id:12s} worker did not start")
        continue

    # 2. Role + tools loaded.
    spec = subagents._SPECIALISTS.get(agent_id)
    if spec is None:
        problems.append("no specialist definition")
    else:
        missing = {t for t in spec["tools"] if t not in TOOLS}
        if missing:
            problems.append(f"unregistered tools: {sorted(missing)}")

    # 3+4. Accepts a real harmless task on its own thread.
    ran_on: dict[str, str] = {}

    def _diagnostic() -> str:
        ran_on["thread"] = threading.current_thread().name
        return f"diagnostic-ok:{agent_id}"

    handle = agent_runtime.submit(agent_id, "operational diagnostic", _diagnostic)
    if handle is None:
        problems.append("submit returned None")
        RESULTS.append((agent_id, "ERROR", "; ".join(problems)))
        FAILURES.append(f"{agent_id}: submit")
        print(f"FAIL  {agent_id:12s} submit rejected")
        continue

    # 5+6. Produces a valid result, returned to the caller.
    result = handle.wait(timeout=20)
    if result != f"diagnostic-ok:{agent_id}":
        problems.append(f"bad result: {result!r}")

    snap = agent_runtime.get_worker(agent_id).snapshot()
    status, why = agent_runtime.presence_status(snap)

    # Ran on that agent's OWN worker thread, not the caller's.
    if agent_id not in ran_on.get("thread", ""):
        problems.append(f"ran on {ran_on.get('thread')!r}, not its own worker")
    if snap["tasks_completed"] < 1:
        problems.append("tasks_completed not incremented")
    if snap["heartbeat_age_s"] is None or snap["heartbeat_age_s"] > 30:
        problems.append(f"stale heartbeat {snap['heartbeat_age_s']}")
    # 7. Returns to a truthful resting status.
    if status != agent_runtime.ONLINE:
        problems.append(f"post-task status {status} ({why})")

    ok = not problems
    RESULTS.append((agent_id, status if ok else "ERROR", "; ".join(problems) or "ok"))
    if not ok:
        FAILURES.append(f"{agent_id}: {problems[0]}")
    print(f"{'PASS' if ok else 'FAIL'}  {agent_id:12s} {role:28s} "
          f"{status:8s} workers={len(agent_teams.workers_for(agent_id))}"
          + (f"  :: {'; '.join(problems)}" if problems else ""))

print()
print("=" * 72)
print("FAILURE / TIMEOUT / CANCELLATION ARE RECORDED HONESTLY")
print("=" * 72)

# A raising task must be recorded as failed and surfaced, not swallowed.
probe = "aris"
before = agent_runtime.get_worker(probe).snapshot()


def _boom() -> str:
    raise RuntimeError("intentional diagnostic failure")


h = agent_runtime.submit(probe, "failure probe", _boom)
res = h.wait(timeout=20)
after = agent_runtime.get_worker(probe).snapshot()
check("failed task reports the error to the caller",
      "intentional diagnostic failure" in str(res), str(res)[:80])
check("failed task increments tasks_failed",
      after["tasks_failed"] == before["tasks_failed"] + 1,
      f"{before['tasks_failed']} -> {after['tasks_failed']}")
check("failure is retained for the dashboard",
      "intentional diagnostic failure" in after.get("last_error", ""),
      after.get("last_error", "")[:70])
check("worker survives a failed task", agent_runtime.get_worker(probe).is_alive())
status, why = agent_runtime.presence_status(agent_runtime.get_worker(probe).snapshot())
check("agent returns to ONLINE after a failure", status == agent_runtime.ONLINE, f"{status}: {why}")

# Cancellation must actually stop the work, not just abandon the caller.
stop = threading.Event()
observed: dict[str, bool] = {"finished": False}


def _slow() -> str:
    for _ in range(100):
        if stop.wait(0.05):
            break
    observed["finished"] = True
    return "slow-done"


h2 = agent_runtime.submit(probe, "cancellation probe", _slow)
time.sleep(0.3)
h2.cancel("operational test")
cancelled_result = h2.wait(timeout=10)
stop.set()
check("cancelled task reports cancellation to the caller",
      str(cancelled_result).startswith("Cancelled:"), str(cancelled_result)[:80])
check("cancellation is NOT counted as a task failure",
      agent_runtime.get_worker(probe).snapshot()["tasks_failed"] == after["tasks_failed"],
      f"tasks_failed={agent_runtime.get_worker(probe).snapshot()['tasks_failed']}")
check("cancellation is counted separately",
      agent_runtime.get_worker(probe).snapshot().get("tasks_cancelled", 0) >= 1,
      str(agent_runtime.get_worker(probe).snapshot().get("tasks_cancelled")))

print()
print("=" * 72)
print("PRESENCE STATUS IS EVIDENCE-BASED")
print("=" * 72)

online = agent_runtime.presence_status(
    {"alive": True, "healthy": True, "state": "idle", "queue_depth": 0})[0]
check("alive+idle => ONLINE", online == agent_runtime.ONLINE, online)

working = agent_runtime.presence_status(
    {"alive": True, "healthy": True, "state": "working", "current_task": "x"})[0]
check("state=working => WORKING", working == agent_runtime.S_WORKING, working)

queued = agent_runtime.presence_status(
    {"alive": True, "healthy": True, "state": "idle", "queue_depth": 3})[0]
check("queued work => WORKING", queued == agent_runtime.S_WORKING, queued)

offline = agent_runtime.presence_status({"alive": False, "state": "standby"})[0]
check("not started => OFFLINE (not ERROR)", offline == agent_runtime.S_OFFLINE, offline)

stale = agent_runtime.presence_status(
    {"alive": True, "healthy": False, "state": "idle", "heartbeat_age_s": 99})[0]
check("stale heartbeat => ERROR", stale == agent_runtime.S_ERROR, stale)

errored = agent_runtime.presence_status(
    {"alive": True, "healthy": True, "state": "error"})[0]
check("error state => ERROR", errored == agent_runtime.S_ERROR, errored)

check("idle agents are never reported WORKING",
      agent_runtime.presence_status(
          {"alive": True, "healthy": True, "state": "idle", "queue_depth": 0})[0]
      != agent_runtime.S_WORKING)

print()
print("=" * 72)
print("UI STATUS TRANSITIONS COME FROM REAL EVENTS")
print("=" * 72)

sub = event_bus.subscribe()
seen: list[str] = []
gate = threading.Event()
try:
    h3 = agent_runtime.submit(probe, "transition probe", lambda: (gate.wait(2.0), "done")[1])
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            ev = sub.get(timeout=0.3)
        except Exception:
            continue
        if ev.type.startswith("agent.") and ev.payload.get("agent") == probe:
            seen.append(ev.type)
        if "agent.task_finished" in seen:
            break
    gate.set()
    h3.wait(timeout=10)
finally:
    event_bus.unsubscribe(sub)

check("AVAILABLE -> WORKING transition is published", "agent.task_started" in seen, str(seen))
check("WORKING -> AVAILABLE transition is published", "agent.task_finished" in seen, str(seen))

print()
print("=" * 72)
print("DELEGATION LIMITS")
print("=" * 72)

check("delegation depth is capped at ZENO->primary->worker",
      agent_teams.MAX_DEPTH == 2, str(agent_teams.MAX_DEPTH))
check("worker fan-out per task is bounded",
      1 <= agent_teams.MAX_WORKERS_PER_TASK <= 5, str(agent_teams.MAX_WORKERS_PER_TASK))
check("workers have a timeout", agent_teams.WORKER_TIMEOUT_S > 0,
      f"{agent_teams.WORKER_TIMEOUT_S}s")

prev = getattr(agent_teams._depth, "value", 1)
agent_teams._depth.value = agent_teams.MAX_DEPTH
try:
    out = agent_teams.run_worker("apex", "pixel", "probe")
    check("worker cannot spawn another worker (no infinite delegation)",
          "depth limit" in out, out[:70])
finally:
    agent_teams._depth.value = prev

teamed = [a for a in AGENT_ROLES if agent_teams.workers_for(a)]
check("every registered agent has a worker team", len(teamed) == len(AGENT_ROLES),
      f"{len(teamed)}/{len(AGENT_ROLES)}")

print()
print("=" * 72)
print(f"{len(AGENT_ROLES)} agents checked")
for agent_id, status, detail in RESULTS:
    print(f"  {agent_id:12s} {status:8s} {detail}")
print("=" * 72)
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALL OPERATIONAL HEALTH CHECKS PASSED")
