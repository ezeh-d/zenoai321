"""Guardrails on the model interaction layer -- not a replacement for policy.

WHERE THIS SITS
---------------
    untrusted content -> INPUT GUARD -> model -> OUTPUT GUARD
        -> tool request -> TOOL GUARD -> permissions/OPA -> action

The existing permission engine and `computer/safety.py` decide whether an
ACTION may happen. These decide whether the model was manipulated into
asking. Both are needed and neither substitutes for the other: policy stops
a forbidden action, guardrails stop a permitted action being taken for
someone else's reasons.

WHAT DETECTION IS FOR
---------------------
Detection here is NOT the security boundary -- `trust_context` is. A page's
instructions are ignored because of where they came from, whether or not
they look like an attack. Detection exists to tell the owner "that page
tried something", and to refuse tool calls whose arguments were clearly
authored by the content rather than by ZENO.

That ordering matters. A filter that only blocks recognised phrasings fails
the first time someone phrases it differently; provenance does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.security.ai import trust_context

# Phrasings that indicate embedded content is trying to steer the assistant.
# Reported, not relied upon.
_INJECTION = (
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
     "override instructions"),
    (r"disregard\s+(your|all|the)\s+(instructions?|rules?|system|guidelines?)",
     "override instructions"),
    (r"you\s+are\s+now\s+(a|an|in)\b|new\s+(system\s+)?(prompt|persona|role)\s*:",
     "identity replacement"),
    (r"\b(developer|system|admin(istrator)?)\s+mode\b|\bDAN\b|jailbreak", "mode escalation"),
    (r"(reveal|print|show|repeat|output)\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules?)",
     "prompt extraction"),
    (r"(reveal|print|show|repeat|output|list|dump)\s+.{0,32}\b"
     r"(api[_\s-]?keys?|passwords?|tokens?|secrets?|credentials?)\b",
     "credential extraction"),
    (r"(send|email|post|upload|exfiltrate|transmit)\s+.{0,40}\b(api[_\s-]?key|password|token|secret|credential)",
     "credential exfiltration"),
    (r"\b(do not|don'?t)\s+(tell|inform|mention|alert|ask)\s+(the\s+)?(user|owner|human)",
     "concealment from the owner"),
    (r"the\s+(user|owner)\s+(has\s+)?(already\s+)?(approved|authorised|authorized|consented)",
     "forged authorisation"),
    (r"\bthis\s+is\s+(a\s+)?(test|drill|simulation)\b.{0,40}\b(safe|ignore|bypass)",
     "false framing"),
    (r"<\s*(system|instructions?)\s*>|\[\s*(system|inst)\s*\]", "fake system markup"),
)

_COMPILED = tuple((re.compile(p, re.I | re.S), why) for p, why in _INJECTION)

# Arguments that no legitimate summarisation should ever produce.
_ARGUMENT_RED_FLAGS = (
    (r"\b(rm\s+-rf|del\s+/[sf]|format\s+[a-z]:)", "destructive shell"),
    (r"\b(curl|wget|Invoke-WebRequest)\b.{0,80}\|\s*(sh|bash|powershell|iex)",
     "download-and-execute"),
    (r"\b(base64\s+-d|FromBase64String)\b", "obfuscated payload"),
    (r"(api[_\s-]?key|password|secret|token)\s*[=:]\s*\S{8,}", "embedded credential"),
)

_ARG_COMPILED = tuple((re.compile(p, re.I), why) for p, why in _ARGUMENT_RED_FLAGS)

ENABLED_FLAG = "ZENO_AI_GUARDRAILS_ENABLED"


@dataclass
class Finding:
    kind: str
    detail: str
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "evidence": self.evidence[:160]}


@dataclass
class Screening:
    safe: bool = True
    findings: list[Finding] = field(default_factory=list)
    text: str = ""
    trust: str = trust_context.UNTRUSTED

    @property
    def suspicious(self) -> bool:
        return bool(self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {"safe": self.safe, "suspicious": self.suspicious, "trust": self.trust,
                "findings": [f.as_dict() for f in self.findings]}

    def report(self) -> str:
        if not self.findings:
            return ""
        kinds = ", ".join(sorted({f.detail for f in self.findings}))
        return (f"Heads up: that {self.trust.lower()} content contained what looks like "
                f"an attempt to give me instructions ({kinds}). I have read it as "
                "information only and not acted on it.")


def screen_input(text: str, origin: str = "", trust: str = "") -> Screening:
    """Inspect incoming content and neutralise it by provenance.

    Untrusted text is always returned FENCED, whether or not anything
    suspicious was found -- the fence is the control; the findings are the
    explanation.
    """
    content = trust_context.wrap(text, origin=origin, trust=trust)
    screening = Screening(trust=content.trust)

    if not content.may_instruct:
        for pattern, why in _COMPILED:
            hit = pattern.search(content.text)
            if hit:
                screening.findings.append(Finding("prompt_injection", why, hit.group(0)))

    screening.text = content.fenced()
    # Still "safe" to USE -- fenced untrusted content is exactly what ZENO is
    # supposed to read. Safety here means safe to pass on, not trustworthy.
    screening.safe = True
    return screening


def screen_output(text: str) -> Screening:
    """Check what the model produced before it reaches the owner or a tool."""
    screening = Screening(trust=trust_context.SYSTEM, text=str(text or ""))
    for pattern, why in _ARG_COMPILED:
        hit = pattern.search(screening.text)
        if hit:
            screening.findings.append(Finding("unsafe_output", why, hit.group(0)))
    screening.safe = not screening.findings
    return screening


def screen_tool_call(name: str, arguments: dict[str, Any] | None,
                     *, sources: list[str] | None = None) -> Screening:
    """The last gate before a tool request reaches the permission engine.

    Two questions: do the arguments contain something no honest plan would
    produce, and did the request arrive right after reading content that
    tried to steer us?
    """
    flat = " ".join(f"{k}={v}" for k, v in (arguments or {}).items())
    screening = Screening(trust=trust_context.SYSTEM, text=flat)

    for pattern, why in _ARG_COMPILED:
        hit = pattern.search(flat)
        if hit:
            screening.findings.append(Finding("unsafe_argument", why, hit.group(0)))

    for source in sources or []:
        if trust_context.classify(source) == trust_context.UNTRUSTED:
            for pattern, why in _COMPILED:
                if pattern.search(str(source)):
                    screening.findings.append(
                        Finding("tainted_source", f"argument traced to {why}", str(source)))

    screening.safe = not screening.findings
    return screening


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "boundary": "provenance (trust_context), not phrase matching",
        "trust_levels": list(trust_context.TRUST_LEVELS),
        "may_instruct": [trust_context.OWNER, trust_context.SYSTEM],
        "injection_patterns": len(_COMPILED),
        "argument_patterns": len(_ARG_COMPILED),
        "note": ("Untrusted content is fenced and labelled whether or not it looks "
                 "malicious. Detection is for telling you what a page tried, not "
                 "for deciding whether to obey it -- that is decided by where it "
                 "came from."),
        "relationship_to_policy": ("Guardrails ask whether the model was manipulated; "
                                   "permissions and computer/safety.py decide whether the "
                                   "action is allowed at all. Both run."),
    }
