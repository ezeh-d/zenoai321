"""Regression checks for truthful worker lifecycle events.

No provider call is made.  These cases used to publish ``success`` from a
``finally`` block even when a worker had failed, timed out, or been cancelled;
the Subspace therefore showed a false result.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import agent_teams, event_bus
from reyes_agent.provider import ProviderError
from reyes_agent.worker_pool import TaskCancelled


def finished_event(invoke) -> tuple[str, dict]:
    subscription = event_bus.subscribe()
    try:
        result = invoke()
        deadline = time.time() + 2
        while time.time() < deadline:
            event = subscription.get(timeout=0.2)
            if event.type == "agent.worker_finished":
                return result, event.payload
        raise AssertionError("worker did not publish agent.worker_finished")
    finally:
        event_bus.unsubscribe(subscription)


failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


with patch("reyes_agent.provider.run_turn", side_effect=ProviderError("offline for test")):
    result, event = finished_event(lambda: agent_teams.run_worker("apex", "pixel", "diagnose"))
check("provider failure is reported as error", "failed" in result.lower() and event.get("visual_state") == "error"
      and event.get("outcome") == "failed", str(event))

old_timeout = agent_teams.WORKER_TIMEOUT_S
agent_teams.WORKER_TIMEOUT_S = -1
try:
    result, event = finished_event(lambda: agent_teams.run_worker("apex", "pixel", "diagnose"))
finally:
    agent_teams.WORKER_TIMEOUT_S = old_timeout
check("worker timeout is not reported as success", "timed out" in result.lower()
      and event.get("visual_state") == "error" and event.get("outcome") == "timed_out", str(event))

with patch("reyes_agent.agent_runtime.current_task_cancel_check", side_effect=TaskCancelled("stop")):
    result, event = finished_event(lambda: agent_teams.run_worker("apex", "pixel", "diagnose"))
check("cancellation is reported as cancelled", result.startswith("Cancelled:")
      and event.get("visual_state") == "cancelled" and event.get("outcome") == "cancelled", str(event))

if failures:
    print(f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1)
print("all worker lifecycle tests passed")
