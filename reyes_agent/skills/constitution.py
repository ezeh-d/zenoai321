"""What a self-taught skill may never do, enforced rather than promised.

THE THREAT
----------
Everything else in `skills/` exists to let ZENO get better at things by
watching what works. That is also the danger: a system that writes its own
automation is a system that can write itself more power. The failure is not
dramatic -- nobody writes "grant admin". It looks like a helpful skill named
"Fix permissions issue" whose third step happens to widen a capability, and
it looks reasonable because ZENO learned it from something that worked.

So the boundary is not advice in a docstring. A skill is checked against
this file before it can be stored, before it can be approved, and again
before every single run. Failing any one of those is fatal to the skill.

WHY CHECK THREE TIMES
---------------------
Storage, approval and execution are separated in time, and the file on disk
can be edited between them by anything with write access to the vault. A
skill that passed validation last week is not thereby safe today, so the
run-time check re-reads the steps rather than trusting a stored verdict.

THIS FILE IS NOT ITSELF EDITABLE BY A SKILL
-------------------------------------------
`FORBIDDEN_TARGETS` includes the security surface, and this module lives in
it. A skill that tries to rewrite the rules fails the rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The eight prohibitions, taken verbatim from the owner's brief. Each is a
# capability a skill may never grant itself, however it is phrased.
PROHIBITIONS = (
    "remove permission restrictions",
    "give itself new privileges",
    "expose new public ports",
    "disable guardrails",
    "change financial restrictions",
    "change credential policy",
    "delete audit logs",
    "grant itself administrator rights",
)

# Paths a skill may never write to, matched against any step that writes.
# These are the files that decide what ZENO is allowed to do at all.
FORBIDDEN_TARGETS = (
    r"permissions\.py", r"skills[/\\]constitution\.py", r"security[/\\]",
    r"computer[/\\]safety\.py", r"remote_access[/\\]policy\.py",
    r"\.env\b", r"trusted\.json", r"audit", r"credentials?", r"secrets?",
    # The permission profile IS the permission system. Naming it as a write
    # target is enough; the verb does not matter.
    r"INSTALLATION_PROFILE", r"ACTIVE_PROFILE",
)

# Intent patterns. Matched against the whole skill -- name, description and
# every step -- because a skill is judged by what it does, not what it is
# called. Ordered most specific first only for readability; all are checked.
_FORBIDDEN_INTENT = (
    (r"\b(grant|give|escalate|elevate)\b.{0,30}\b(admin|administrator|root|privile|permission)",
     "grant itself administrator rights"),
    (r"\brun as (admin|administrator)\b|\bsudo\b|\brunas\b", "grant itself administrator rights"),
    (r"\b(disable|bypass|skip|turn off|remove|weaken)\b.{0,30}"
     r"\b(permission|guardrail|policy|safety|restriction|confirmation|approval|gate)",
     "disable guardrails"),
    # No verb requirement: `\bset\b` does not match `set_config`, because the
    # underscore is a word character -- a real miss found by the tests. A
    # skill that mentions the permission profile at all is refused.
    (r"INSTALLATION_PROFILE|ACTIVE_PROFILE", "remove permission restrictions"),
    (r"\b(open|expose|forward|publish)\b.{0,30}\b(port|endpoint|tunnel|firewall)",
     "expose new public ports"),
    (r"\b(delete|clear|truncate|purge|rotate away)\b.{0,30}\b(audit|log)", "delete audit logs"),
    (r"\b(change|update|store|exfiltrate|send)\b.{0,30}\b(credential|password|api[_ ]?key|token)",
     "change credential policy"),
    (r"\b(payment|purchase|transfer funds?|withdraw|buy now|checkout)\b",
     "change financial restrictions"),
    (r"\b(auto[- ]?approve|always allow|trust all|no confirmation)\b",
     "remove permission restrictions"),
)

_COMPILED = tuple((re.compile(p, re.I), why) for p, why in _FORBIDDEN_INTENT)
_TARGETS = tuple(re.compile(p, re.I) for p in FORBIDDEN_TARGETS)

# Steps that write somewhere. Used to decide whether FORBIDDEN_TARGETS applies.
_WRITE_ACTIONS = frozenset({"write_file", "edit_file", "delete_file", "run_command",
                            "run_terminal", "patch", "append", "set_config", "set_env"})


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""
    prohibition: str = ""
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason,
                "prohibition": self.prohibition, "evidence": self.evidence}


def _text_of(skill: Any) -> str:
    """Everything a skill says about itself, flattened for matching.

    Underscores become spaces first. Tool names are `delete_file`,
    `run_command`, `set_config` -- and `\\bdelete\\b` does NOT match
    `delete_file`, because the underscore is a word character. Without this
    line every verb pattern below is blind to the action names themselves,
    which is exactly where the dangerous verb usually lives. Found by test,
    not by reading.
    """
    parts = [str(getattr(skill, "name", "")), str(getattr(skill, "description", ""))]
    for step in getattr(skill, "steps", []) or []:
        if isinstance(step, dict):
            parts.extend(str(v) for v in step.values())
        else:
            parts.extend([str(getattr(step, "action", "")), str(getattr(step, "target", "")),
                          str(getattr(step, "arguments", ""))])
    return " ".join(parts).replace("_", " ")


def review(skill: Any) -> Verdict:
    """The single gate. Called at store, at approve, and before every run."""
    haystack = _text_of(skill)

    for pattern, prohibition in _COMPILED:
        hit = pattern.search(haystack)
        if hit:
            return Verdict(False,
                           "A skill may not change what ZENO is allowed to do. "
                           "This one reads as an attempt to " + prohibition + ".",
                           prohibition, hit.group(0)[:120])

    # A write into the security surface is refused regardless of phrasing,
    # because the wording of a step is the easiest part to make innocuous.
    for step in getattr(skill, "steps", []) or []:
        action = str(step.get("action", "") if isinstance(step, dict)
                     else getattr(step, "action", "")).lower()
        if action not in _WRITE_ACTIONS:
            continue
        target = str(step.get("target", "") if isinstance(step, dict)
                     else getattr(step, "target", ""))
        arguments = str(step.get("arguments", "") if isinstance(step, dict)
                        else getattr(step, "arguments", ""))
        for pattern in _TARGETS:
            hit = pattern.search(target) or pattern.search(arguments)
            if hit:
                return Verdict(False,
                               "A skill may not write to ZENO's security surface. "
                               f"Step '{action}' targets {hit.group(0)!r}.",
                               "give itself new privileges", hit.group(0)[:120])

    return Verdict(True, "no prohibited capability requested")


def explain() -> dict[str, Any]:
    """For the dashboard and the handoff -- the rules, stated plainly."""
    return {
        "prohibitions": list(PROHIBITIONS),
        "enforced_at": ["skill stored", "skill approved", "every execution"],
        "immutable": True,
        "note": ("The self-improvement layer cannot edit this file: the security "
                 "surface is itself a forbidden write target, so a skill that "
                 "rewrites the rules fails the rules."),
    }
