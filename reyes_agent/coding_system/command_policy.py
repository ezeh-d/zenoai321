"""Execution policy for the optional Open Interpreter process."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDecision:
    allowed: bool
    autonomy_level: int
    reason: str


_BLOCKED = (
    re.compile(r"(?i)\b(?:format|diskpart|bcdedit|cipher\s+/w|reg\s+delete)\b"),
    re.compile(r"(?i)\b(?:transfer|wire|purchase|checkout|place\s+order|send\s+money)\b"),
    re.compile(r"(?i)\b(?:dump|print|echo|show)\b.{0,30}\b(?:environment|env|api key|token|password|secret)\b"),
)
_MUTATING = re.compile(r"(?i)\b(?:delete|remove|rmdir|rm\s|move|rename|install|uninstall|write|edit|fix|modify|commit|push|deploy)\b")
_HIGH_IMPACT = re.compile(r"(?i)\b(?:delete|remove|rmdir|rm\s|uninstall|push|deploy)\b")


def classify(goal: str, *, read_only: bool) -> CommandDecision:
    text = " ".join(str(goal or "").split())
    if not text:
        return CommandDecision(False, 4, "empty goal")
    for pattern in _BLOCKED:
        if pattern.search(text):
            return CommandDecision(False, 4, "blocked destructive, financial, credential, or secret-exposure request")
    if read_only and not _MUTATING.search(text):
        return CommandDecision(True, 1, "read-only repository/system inspection")
    if _HIGH_IMPACT.search(text):
        return CommandDecision(True, 3, "destructive or externally consequential development action")
    return CommandDecision(True, 2, "owner-requested workspace development action")


def safe_args(executable: str, goal: str, *, read_only: bool, timeout_s: int) -> list[str]:
    """Argument vector only; never a shell command string."""
    args = [executable, "exec", "--json", "--ephemeral", "--verify",
            "--timeout", str(max(10, min(600, int(timeout_s))))]
    if read_only:
        args += ["--sandbox", "read-only", "--ask-for-approval", "untrusted"]
    else:
        args += ["--sandbox", "workspace-write", "--ask-for-approval", "never"]
    args.append(str(goal))
    return args
