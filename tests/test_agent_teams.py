"""Worker-team (sub-sub-agent) architecture tests.

These verify the SAFETY properties of the hierarchy -- depth cap, budget,
parent attribution, privilege containment, thread isolation and event
emission -- without spending model calls. The end-to-end model path is
exercised separately against the live server.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import agent_teams, event_bus
from reyes_agent.tools import TOOLS, subagents

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


# 1. Every worker's tools genuinely exist in the registry.
missing: list[str] = []
for parent, ws in agent_teams.teams().items():
    for w in ws:
        for t in w.tools:
            if t not in TOOLS:
                missing.append(f"{parent}/{w.name}:{t}")
check("every worker tool is registered", not missing, ", ".join(missing[:6]))

# 2. A worker can never hold a tool its parent lacks (no privilege escalation).
escalations: list[str] = []
for parent, ws in agent_teams.teams().items():
    spec = subagents._SPECIALISTS.get(parent)
    if not spec:
        escalations.append(f"{parent}: no such primary specialist")
        continue
    for w in ws:
        extra = w.tools - set(spec["tools"])
        if extra:
            escalations.append(f"{parent}/{w.name} gains {sorted(extra)}")
check("no worker exceeds its parent's tools", not escalations, "; ".join(escalations[:6]))

# 3. Every parent in the team map is a real registered agent.
from reyes_agent.agent_runtime import AGENT_ROLES

unknown = [p for p in agent_teams.teams() if p not in AGENT_ROLES]
check("every team parent is a registered agent", not unknown, str(unknown))

# 4. Worker names are globally unique (Subspace addresses them by name).
seen: dict[str, str] = {}
dupes: list[str] = []
for parent, ws in agent_teams.teams().items():
    for w in ws:
        if w.name in seen:
            dupes.append(f"{w.name} in {seen[w.name]} and {parent}")
        seen[w.name] = parent
check("worker names are unique", not dupes, "; ".join(dupes))

# 5. call_worker refuses when no specialist owns the thread.
out = subagents.call_worker("pixel", "test")
check("call_worker rejected outside a specialist", out.startswith("Error:"), out[:70])

# 6. Parent attribution comes from the stack, not the model: while APEX is
#    active, asking for another team's worker must fail.
subagents._active.specialist = "apex"
subagents._worker_budget.used = 0
try:
    out = subagents.call_worker("scholar", "test")  # scholar belongs to KATE
    check("cannot call another team's worker", out.startswith("Error:") and "no worker named" in out, out[:80])

    out = subagents.call_worker("nonexistent_xyz", "test")
    check("unknown worker names its real team", "Its team:" in out, out[:80])

    # 7. Budget is enforced.
    subagents._worker_budget.used = agent_teams.MAX_WORKERS_PER_TASK
    out = subagents.call_worker("pixel", "test")
    check("worker budget enforced", "budget exhausted" in out, out[:70])
finally:
    subagents._active.specialist = None
    subagents._worker_budget.used = 0

# 8. Depth cap: at worker depth, run_worker refuses (no worker->worker).
prev = getattr(agent_teams._depth, "value", 1)
agent_teams._depth.value = agent_teams.MAX_DEPTH
try:
    out = agent_teams.run_worker("apex", "pixel", "test")
    check("depth cap blocks worker->worker", "depth limit" in out, out[:70])
finally:
    agent_teams._depth.value = prev

# 9. UNAVAILABLE workers refuse to run rather than answering hollow.
probe = agent_teams.Worker(name="probe_unavail", parent="apex", role="probe",
                           prompt="probe", tools={"definitely_not_a_real_tool"})
status, _ = agent_teams.capability_of(probe)
check("missing tools report UNAVAILABLE", status == agent_teams.UNAVAILABLE, status)
agent_teams._TEAMS["apex"].append(probe)
try:
    out = agent_teams.run_worker("apex", "probe_unavail", "test")
    check("UNAVAILABLE worker refuses to run", "UNAVAILABLE" in out, out[:80])
finally:
    agent_teams._TEAMS["apex"].remove(probe)

# 10. Thread isolation: parallel specialists must not share parent/budget.
results: dict[str, str] = {}


def _worker_thread(name: str) -> None:
    subagents._active.specialist = name
    subagents._worker_budget.used = 0
    time.sleep(0.05)
    results[name] = subagents._active_specialist() or "?"


threads = [threading.Thread(target=_worker_thread, args=(n,)) for n in ("apex", "kate", "stark")]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("parent identity is thread-isolated",
      results == {"apex": "apex", "kate": "kate", "stark": "stark"}, str(results))

# 11. Worker lifecycle reaches the Event Bus (real subscription, real events).
sub = event_bus.subscribe()
try:
    agent_teams._publish("agent.worker_started",
                         {"agent": "pixel", "parent": "apex", "visual_state": "working"})
    got = None
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            ev = sub.get(timeout=0.3)
        except Exception:
            continue
        if ev.type == "agent.worker_started":
            got = ev
            break
    check("worker events reach the Event Bus", got is not None and got.payload.get("parent") == "apex",
          str(got.payload if got else "no event"))
finally:
    event_bus.unsubscribe(sub)

# 12. describe() is well-formed and honest.
d = agent_teams.describe()
check("describe() reports depth cap", d["max_depth"] == agent_teams.MAX_DEPTH, str(d["max_depth"]))
check("describe() covers every team", len(d["parents"]) == len(agent_teams.teams()))
check("describe() counts workers", d["total_workers"] == sum(len(v) for v in agent_teams.teams().values()),
      str(d["total_workers"]))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all agent-team tests passed")
