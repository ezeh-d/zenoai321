"""The non-blocking queue for Council and genuinely high-impact actions.

``reyes_agent.action_policy`` decides whether one current request executes,
needs clarification, queues here, or is denied. Historical per-tool flags are
risk hints rather than unconditional prompts. A queued action never blocks the
agent thread and expires into a safe default after ``PENDING_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import contextvars
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["pending", "approved", "denied", "expired"]

PENDING_TIMEOUT_SECONDS = 15 * 60


# --- trusted-owner auto-approve -------------------------------------------
# A consequential tool normally queues here for someone with eyes on the web
# panel. But when an AUTHENTICATED owner on a TRUSTED device issues a remote
# command, that owner IS the someone -- routing it back to the PC to click
# "approve" is the exact friction that made the phone feel broken. Inside this
# context a would-be-queued action runs immediately instead.
#
# It is a ContextVar, so it is scoped to the single turn that set it and never
# leaks to a background turn running on another thread. It is enabled ONLY by
# the remote owner-command executor (every command there already passed the
# trusted-owner gate), and the high-risk floor in tools.run_tool still holds --
# a tool whose confidence is unknown is never auto-run this way, so this is not
# an arbitrary-shell backdoor. Every auto-run is audited.
_owner_auto_approve: contextvars.ContextVar[str] = contextvars.ContextVar(
    "zeno_owner_auto_approve", default="")


class owner_auto_approve:
    """Context manager enabling trusted-owner auto-approve for its duration."""

    def __init__(self, reason: str = "trusted-owner") -> None:
        self._reason = reason or "trusted-owner"
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "owner_auto_approve":
        self._token = _owner_auto_approve.set(self._reason)
        return self

    def __exit__(self, *_exc: object) -> bool:
        if self._token is not None:
            _owner_auto_approve.reset(self._token)
        return False


def auto_approve_active() -> str:
    """The reason string if trusted-owner auto-approve is in effect, else ''."""
    return _owner_auto_approve.get()


# Even WITH a fingerprint step-up, these never auto-run from a remote device --
# a phone unlock must not be able to fire a catastrophic, irreversible, public
# or code-execution action on its own. They still run, but only after an
# explicit desktop confirmation. Everything else consequential (open/close app,
# browser control, send a message, create a file) runs once the owner scanned.
_REMOTE_NEVER_AUTORUN: frozenset[str] = frozenset({
    # arbitrary code / shell / device execution -- section 18 forbids exposing
    # this from the phone
    "run_command", "coding_execute", "device_execute", "phone_action",
    "mcp_action", "skill_run",
    # irreversible / destructive
    "delete_file", "move_file", "forget_fact", "forget_relationship",
    "restore_memory_version", "memory_migrate_to_mem0", "undo_last_actions",
    "opportunity_delete", "skill_delete", "website_restore_checkpoint",
    # meta-approval that could rubber-stamp other actions
    "skill_approve", "skill_disable", "workflow_confirm", "career_profile_update",
})
# Whole families that post publicly, move money, or drive security tooling.
_REMOTE_NEVER_AUTORUN_PREFIXES: tuple[str, ...] = ("security_", "social_", "paid_work_")


def remote_auto_run_allowed(tool_name: str) -> bool:
    """Whether a fingerprint-elevated remote turn may auto-run this tool.

    True for ordinary control/communication tools; False for arbitrary
    execution, irreversible destruction, public posting, money and security
    tooling -- those always take an explicit desktop confirmation even after a
    step-up."""
    name = str(tool_name or "")
    if name in _REMOTE_NEVER_AUTORUN:
        return False
    return not name.startswith(_REMOTE_NEVER_AUTORUN_PREFIXES)


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
