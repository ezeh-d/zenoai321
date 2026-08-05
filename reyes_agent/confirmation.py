"""Tier 6 (minimal): the hard confirmation gate for consequential tools.

Any tool registered with `requires_confirmation=True` never runs
immediately -- the request lands here instead, and something with eyes on
it (the web panel) approves or denies. The agent loop never blocks waiting
on a human: a queued action just sits until someone acts on it, or expires
after PENDING_TIMEOUT_SECONDS -- "never block forever waiting on a human;
time out into a safe default" from AGENT.md's Tier 6 section, applied.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["pending", "approved", "denied", "expired"]

PENDING_TIMEOUT_SECONDS = 15 * 60


@dataclass
class PendingAction:
    id: int
    tool_name: str
    tool_input: dict[str, Any]
    description: str
    status: Status = "pending"
    created_at: float = field(default_factory=time.time)
    result: str | None = None


_lock = threading.Lock()
_counter = itertools.count(1)
_queue: dict[int, PendingAction] = {}


def request(tool_name: str, tool_input: dict[str, Any], description: str) -> PendingAction:
    from reyes_agent import audit

    with _lock:
        action = PendingAction(
            id=next(_counter),
            tool_name=tool_name,
            tool_input=tool_input,
            description=description,
        )
        _queue[action.id] = action
    audit.log("confirmation_requested", id=action.id, tool=tool_name, input=tool_input)
    return action


def _expire_stale_locked() -> None:
    now = time.time()
    for action in _queue.values():
        if action.status == "pending" and now - action.created_at > PENDING_TIMEOUT_SECONDS:
            action.status = "expired"
            action.result = "Expired -- nobody confirmed it in time. Nothing ran."


def list_pending() -> list[PendingAction]:
    with _lock:
        _expire_stale_locked()
        return sorted((a for a in _queue.values() if a.status == "pending"), key=lambda a: a.id)


def list_all(limit: int = 50) -> list[PendingAction]:
    with _lock:
        _expire_stale_locked()
        return sorted(_queue.values(), key=lambda a: a.id, reverse=True)[:limit]


def get(action_id: int) -> PendingAction | None:
    with _lock:
        _expire_stale_locked()
        return _queue.get(action_id)


def deny(action_id: int) -> PendingAction | None:
    from reyes_agent import audit

    with _lock:
        action = _queue.get(action_id)
        if action is None or action.status != "pending":
            return action
        action.status = "denied"
        action.result = "Denied by user. Nothing ran."
    audit.log("confirmation_denied", id=action_id, tool=action.tool_name)
    return action


def approve_and_run(action_id: int) -> PendingAction | None:
    """Approve a queued action and actually run the underlying tool now.

    Deferred import to dodge a circular import (tools -> confirmation ->
    tools) -- both modules are fully loaded by the time this is called.
    """
    from reyes_agent import audit

    with _lock:
        action = _queue.get(action_id)
        if action is None or action.status != "pending":
            return action
        action.status = "approved"
    audit.log("confirmation_approved", id=action_id, tool=action.tool_name)

    from reyes_agent.tools import TOOLS, execute_tool

    tool = TOOLS.get(action.tool_name)
    if tool is None:
        action.result = f"Error: tool '{action.tool_name}' is no longer registered."
    else:
        action.result = execute_tool(tool, action.tool_input)
    return action
