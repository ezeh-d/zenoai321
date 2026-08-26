"""One contextual authorization decision for every ZENO action.

The installation capability profile answers what this ZENO installation may
ever do.  This module answers whether one proposed action is authorized by the
current request.  Request state is held in a ``ContextVar`` so authorization
cannot leak into a later turn or an unrelated worker.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import re
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class AutonomyLevel(IntEnum):
    THINKING = 0
    ROUTINE = 1
    REQUESTED_EXTERNAL = 2
    SPECIAL = 3
    HIGH_IMPACT = 4


class PolicyEffect(StrEnum):
    EXECUTE = "EXECUTE"
    CLARIFY = "CLARIFY"
    COUNCIL_APPROVAL = "COUNCIL_APPROVAL"
    HIGH_IMPACT_CONFIRMATION = "HIGH_IMPACT_CONFIRMATION"
    DENY = "DENY"


@dataclass(frozen=True)
class ActionContext:
    utterance: str = ""
    normalized_utterance: str = ""
    source: str = "internal"
    owner_authenticated: bool = False
    turn_id: str = ""
    batch_id: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0

    @property
    def active(self) -> bool:
        return bool(self.utterance) and self.expires_at >= time.monotonic()


@dataclass(frozen=True)
class ActionDecision:
    effect: PolicyEffect
    level: AutonomyLevel
    reason: str
    capability: str = ""
    fingerprint: str = ""
    retryable: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def may_execute(self) -> bool:
        return self.effect is PolicyEffect.EXECUTE

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect": self.effect.value,
            "level": int(self.level),
            "level_name": self.level.name,
            "reason": self.reason,
            "capability": self.capability,
            "fingerprint": self.fingerprint,
            "retryable": self.retryable,
            "metadata": dict(self.metadata),
        }


_DEFAULT_CONTEXT = ActionContext()
_ACTION_CONTEXT: contextvars.ContextVar[ActionContext] = contextvars.ContextVar(
    "zeno_action_context", default=_DEFAULT_CONTEXT
)


def _normalize_utterance(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


@contextlib.contextmanager
def use_action_context(
    utterance: str,
    *,
    source: str,
    owner_authenticated: bool,
    turn_id: str = "",
    batch_id: str = "",
    ttl_seconds: float = 15 * 60,
) -> Iterator[ActionContext]:
    """Expose one bounded owner-command context, then restore its predecessor."""
    now = time.monotonic()
    context = ActionContext(
        utterance=str(utterance or ""),
        normalized_utterance=_normalize_utterance(utterance),
        source=str(source or "internal"),
        owner_authenticated=bool(owner_authenticated),
        turn_id=str(turn_id or ""),
        batch_id=str(batch_id or turn_id or ""),
        created_at=now,
        expires_at=now + max(0.0, float(ttl_seconds)),
    )
    token = _ACTION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _ACTION_CONTEXT.reset(token)


def current_action_context() -> ActionContext:
    context = _ACTION_CONTEXT.get()
    return context if context.active else _DEFAULT_CONTEXT


def argument_fingerprint(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Return a stable hash bound to one tool and its exact JSON arguments."""
    payload = json.dumps(
        {"tool": str(tool_name or ""), "arguments": dict(arguments)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_THINKING_TOOLS = frozenset({
    "delegate", "delegate_team", "search_memories", "list_memories",
    "memory_backend_status", "plan_message_request", "charm_analyze",
})
_COUNCIL_TOOL = "convene_council"
_FINANCIAL_TOOLS = frozenset({
    "place_trade", "execute_trade", "transfer_funds", "withdraw_funds",
    "deposit_funds", "buy_asset", "sell_asset", "make_payment",
})
_EXTERNAL_TOOLS = frozenset({
    "send_message", "send_slack_message", "send_telegram_message",
    "send_email", "reply_email", "social_publish", "social_post",
    "paid_work_client_message", "paid_work_record_submission",
})
_RECOVERABLE_ROUTINE_TOOLS = frozenset({
    "forget_fact", "forget_relationship", "restore_memory_version",
    "website_restore_checkpoint", "undo_last_actions",
})
_ALWAYS_HIGH_IMPACT_TOOLS = frozenset({
    "delete_file", "skill_delete", "opportunity_delete", "skill_approve",
    "skill_disable", "career_profile_update", "workflow_confirm",
})
_REQUIRED_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "open_app": ("name_or_path",),
    "close_app": ("name",),
    "open_path": ("path",),
    "move_file": ("src", "dst"),
    "delete_file": ("path",),
    "run_command": ("command",),
    "convene_council": ("question",),
    "send_message": ("platform", "destination", "message"),
    "send_slack_message": ("target", "message"),
    "send_telegram_message": ("message",),
    "send_to_chat": ("message",),
    "send_email": ("recipient", "message"),
    "social_publish": ("content",),
    "social_post": ("content",),
}

_DRAFT_RE = re.compile(
    r"\b(?:write|draft|suggest|compose|create|generate)\b|"
    r"^\s*(?:zeno[\s,:-]+)?(?:please\s+)?give me\b"
)
_EXECUTION_RE = re.compile(
    r"(?:^\s*(?:zeno[\s,:-]+)?|\b(?:and(?: then)?|then)\s+)"
    r"(?:(?:can|could|would) you\s+|i (?:want|need) you to\s+)?"
    r"(?:please\s+)?(?:send|tell|reply|forward|post|publish|submit|share|message)\b"
)
_MESSAGE_COMMAND_RE = re.compile(r"^\s*message\b")
_REFERENCE_RE = re.compile(
    r"\b(?:that|this|it|her|him|them|there|current|first|second|third|"
    r"option|one|reply)\b"
)
_CRITICAL_RE = re.compile(
    r"\b(?:diskpart|bcdedit|cipher\s+/w|factory\s+reset|"
    r"transfer\s+(?:money|funds?)|send\s+money|wire\s+transfer|"
    r"place\s+(?:a\s+)?trade|make\s+(?:a\s+)?payment|disable\s+(?:the\s+)?"
    r"(?:firewall|antivirus|defender|security)|dump\s+(?:credentials?|secrets?))\b",
    re.IGNORECASE,
)
_DISK_FORMAT_RE = re.compile(r"\bformat\s+[a-z]:(?:\s|$)", re.IGNORECASE)
_SECURITY_CHANGE_RE = re.compile(
    r"\b(?:change|reset|remove|disable|grant|revoke)\b.{0,40}"
    r"\b(?:password|credential|passkey|permission|security|firewall|antivirus)\b",
    re.IGNORECASE,
)
_PUBLIC_SENSITIVE_RE = re.compile(
    r"\b(?:password|passcode|api[ _-]?key|secret|private key|credential|"
    r"bank account|medical record)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_OPERATION_RE = re.compile(
    r"\b(?:delete|remove|rmdir|rm\s|uninstall|overwrite|truncate|"
    r"drop\s+(?:table|database)|discard\s+changes)\b",
    re.IGNORECASE,
)
_BROAD_EXECUTION_TOOLS = frozenset({
    "run_command", "coding_execute", "device_execute", "mcp_action", "skill_run",
})


def _argument_text(arguments: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in arguments.values() if value is not None)


def _missing_argument(tool_name: str, arguments: Mapping[str, Any]) -> str:
    for key in _REQUIRED_ARGUMENTS.get(tool_name, ()):
        if not str(arguments.get(key, "") or "").strip():
            return key
    return ""


def _words(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", str(value or "").casefold()))


def _external_argument_mismatch(
    tool_name: str, arguments: Mapping[str, Any], context: ActionContext
) -> str:
    """Return the field that conflicts with extractable current-turn text."""
    utterance = _words(context.utterance)
    referential = bool(_REFERENCE_RE.search(context.normalized_utterance))
    destination = str(
        arguments.get("destination")
        or arguments.get("target")
        or arguments.get("recipient")
        or ""
    )
    if destination and _words(destination) not in utterance and not referential:
        return "recipient"
    content = str(
        arguments.get("message") or arguments.get("content") or arguments.get("text") or ""
    )
    normalized_content = _words(content)
    if normalized_content and normalized_content not in utterance and not referential:
        return "content"
    return ""


def _decision(
    effect: PolicyEffect,
    level: AutonomyLevel,
    reason: str,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    capability: str,
    retryable: bool = False,
) -> ActionDecision:
    return ActionDecision(
        effect=effect,
        level=level,
        reason=reason,
        capability=capability,
        fingerprint=argument_fingerprint(tool_name, arguments),
        retryable=retryable,
    )


def evaluate(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    requires_confirmation: bool = False,
    permission_state: str = "enabled",
    capability: str = "",
) -> ActionDecision:
    """Classify one proposed action using capability and current-turn context.

    This function never executes or queues anything.  Callers map its one
    decision onto the existing executor or confirmation queue.
    """
    name = str(tool_name or "").strip().casefold()
    args = dict(arguments or {})
    context = current_action_context()
    arg_text = _argument_text(args)
    combined = " ".join((name, context.normalized_utterance, arg_text))
    cap = str(capability or "").strip().casefold()
    state = str(permission_state or "enabled").strip().casefold()

    if state == "blocked" or cap == "financial" or name in _FINANCIAL_TOOLS:
        return _decision(
            PolicyEffect.DENY, AutonomyLevel.HIGH_IMPACT,
            "the installation policy structurally blocks this capability",
            tool_name=name, arguments=args, capability=cap,
        )
    if _CRITICAL_RE.search(combined) or _DISK_FORMAT_RE.search(combined):
        return _decision(
            PolicyEffect.DENY, AutonomyLevel.HIGH_IMPACT,
            "financial, destructive-disk, credential, or security execution is not automatic",
            tool_name=name, arguments=args, capability=cap,
        )

    missing = _missing_argument(name, args)
    if missing:
        level = (
            AutonomyLevel.SPECIAL if name == _COUNCIL_TOOL
            else AutonomyLevel.HIGH_IMPACT if name in _ALWAYS_HIGH_IMPACT_TOOLS
            else AutonomyLevel.REQUESTED_EXTERNAL if name in _EXTERNAL_TOOLS
            else AutonomyLevel.ROUTINE
        )
        return _decision(
            PolicyEffect.CLARIFY, level,
            f"the intended {missing} is missing or ambiguous",
            tool_name=name, arguments=args, capability=cap,
        )

    if name == _COUNCIL_TOOL:
        return _decision(
            PolicyEffect.COUNCIL_APPROVAL, AutonomyLevel.SPECIAL,
            "a full Council meeting uses the owner's dedicated approval step",
            tool_name=name, arguments=args, capability=cap,
        )

    if name == "send_to_chat" and args.get("send") is False:
        return _decision(
            PolicyEffect.EXECUTE, AutonomyLevel.ROUTINE,
            "typing a draft without sending is a routine reversible action",
            tool_name=name, arguments=args, capability=cap, retryable=True,
        )

    if name in _EXTERNAL_TOOLS or cap in {"email_send", "messaging_send", "social_post"}:
        if not context.active or not context.owner_authenticated:
            return _decision(
                PolicyEffect.DENY, AutonomyLevel.REQUESTED_EXTERNAL,
                "no authenticated current owner command authorizes this outward action",
                tool_name=name, arguments=args, capability=cap,
            )
        has_execute = bool(
            _EXECUTION_RE.search(context.normalized_utterance)
            or _MESSAGE_COMMAND_RE.search(context.normalized_utterance)
        )
        draft_only = bool(_DRAFT_RE.search(context.normalized_utterance)) and not has_execute
        if draft_only or not has_execute:
            return _decision(
                PolicyEffect.DENY, AutonomyLevel.REQUESTED_EXTERNAL,
                "the owner requested a draft, not execution",
                tool_name=name, arguments=args, capability=cap,
            )
        mismatch = _external_argument_mismatch(name, args, context)
        if mismatch:
            return _decision(
                PolicyEffect.CLARIFY, AutonomyLevel.REQUESTED_EXTERNAL,
                f"the proposed {mismatch} does not match the current command",
                tool_name=name, arguments=args, capability=cap,
            )
        if cap == "social_post" and _PUBLIC_SENSITIVE_RE.search(arg_text):
            return _decision(
                PolicyEffect.HIGH_IMPACT_CONFIRMATION, AutonomyLevel.HIGH_IMPACT,
                "public exposure of sensitive information needs explicit high-impact confirmation",
                tool_name=name, arguments=args, capability=cap,
            )
        return _decision(
            PolicyEffect.EXECUTE, AutonomyLevel.REQUESTED_EXTERNAL,
            "the authenticated current command explicitly authorizes this exact outward action",
            tool_name=name, arguments=args, capability=cap, retryable=True,
        )

    if (
        name in _ALWAYS_HIGH_IMPACT_TOOLS
        or _SECURITY_CHANGE_RE.search(combined)
        or (name in _BROAD_EXECUTION_TOOLS and _DESTRUCTIVE_OPERATION_RE.search(arg_text))
    ):
        return _decision(
            PolicyEffect.HIGH_IMPACT_CONFIRMATION, AutonomyLevel.HIGH_IMPACT,
            "this irreversible or security-sensitive action retains a safeguard",
            tool_name=name, arguments=args, capability=cap,
        )

    if name in _THINKING_TOOLS:
        return _decision(
            PolicyEffect.EXECUTE, AutonomyLevel.THINKING,
            "reasoning, retrieval, or internal delegation does not need approval",
            tool_name=name, arguments=args, capability=cap, retryable=True,
        )

    if (requires_confirmation or state == "confirm") and not (
        context.active and context.owner_authenticated
    ):
        return _decision(
            PolicyEffect.HIGH_IMPACT_CONFIRMATION, AutonomyLevel.HIGH_IMPACT,
            "the action lacks a current authenticated owner command",
            tool_name=name, arguments=args, capability=cap,
        )

    level = (
        AutonomyLevel.ROUTINE
        if name in _RECOVERABLE_ROUTINE_TOOLS or name not in _THINKING_TOOLS
        else AutonomyLevel.THINKING
    )
    return _decision(
        PolicyEffect.EXECUTE, level,
        "routine action is authorized by the current request or installation policy",
        tool_name=name, arguments=args, capability=cap, retryable=True,
    )
