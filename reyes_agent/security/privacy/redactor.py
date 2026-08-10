"""Decide what to remove, given where the text is going and what the task needs.

The brief is explicit: do NOT blindly redact information when the actual
task requires it. So this takes a DESTINATION and a PURPOSE, not just text.

    LOG / TRACE / CRASH   nothing sensitive, ever. Nobody reads a log to
                          find a phone number, and logs outlive their
                          context.
    CLOUD_MODEL           credentials always go; contact details stay when
                          the task is about contacting someone, because
                          removing them makes the task impossible.
    EXTERNAL_API          credentials and identity go; the caller opted in
                          to sending the rest.
    LOCAL                 credentials only -- the data never leaves.

Redaction is reversible within a single call via `restore()`, so ZENO can
send a redacted prompt and put real values back into the resulting command
without the model ever seeing them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.security.privacy.detector import (ALWAYS_REDACT, CONTACT, CREDENTIAL,
                                                   FINANCIAL, IDENTITY, Hit, detect)

LOG = "LOG"
TRACE = "TRACE"
CRASH = "CRASH"
CLOUD_MODEL = "CLOUD_MODEL"
EXTERNAL_API = "EXTERNAL_API"
LOCAL = "LOCAL"

DESTINATIONS = (LOG, TRACE, CRASH, CLOUD_MODEL, EXTERNAL_API, LOCAL)

# What each destination strips. Credentials are in every one of them.
_POLICY: dict[str, frozenset[str]] = {
    LOG:          frozenset({CREDENTIAL, FINANCIAL, IDENTITY, CONTACT}),
    TRACE:        frozenset({CREDENTIAL, FINANCIAL, IDENTITY, CONTACT}),
    CRASH:        frozenset({CREDENTIAL, FINANCIAL, IDENTITY, CONTACT}),
    CLOUD_MODEL:  frozenset({CREDENTIAL, FINANCIAL, IDENTITY}),
    EXTERNAL_API: frozenset({CREDENTIAL, FINANCIAL, IDENTITY}),
    LOCAL:        frozenset({CREDENTIAL}),
}

# Purposes that legitimately need contact details in the text.
_CONTACT_PURPOSES = re.compile(
    r"\b(email|e-mail|contact|call|phone|message|invite|send to|write to|reply)\b", re.I)


@dataclass
class Redaction:
    text: str = ""
    removed: int = 0
    categories: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)   # placeholder -> original

    def restore(self, text: str) -> str:
        """Put the real values back. Used for the command, never the prompt."""
        result = str(text or "")
        for placeholder, original in self.mapping.items():
            result = result.replace(placeholder, original)
        return result

    def as_dict(self) -> dict[str, Any]:
        return {"removed": self.removed, "categories": sorted(set(self.categories)),
                "reversible": bool(self.mapping)}


def _should_remove(hit: Hit, destination: str, purpose: str) -> bool:
    if hit.always_redact:
        return True            # credentials, unconditionally
    removes = _POLICY.get(destination, _POLICY[LOG])
    if hit.category not in removes:
        return False
    # The context-aware exception: a task about emailing someone needs the
    # address. Only applies where the data is not inherently secret.
    if (hit.category == CONTACT and destination in (CLOUD_MODEL, EXTERNAL_API)
            and _CONTACT_PURPOSES.search(purpose or "")):
        return False
    return True


def redact(text: str, *, destination: str = LOG, purpose: str = "",
           reversible: bool = False) -> Redaction:
    """Strip what this destination must not receive, keep what the task needs."""
    body = str(text or "")
    result = Redaction(text=body)
    hits = [h for h in detect(body) if _should_remove(h, destination, purpose)]
    if not hits:
        return result

    # Replace back-to-front so earlier offsets stay valid.
    for hit in sorted(hits, key=lambda h: h.start, reverse=True):
        if reversible:
            token = f"[[{hit.category}_{uuid.uuid4().hex[:8]}]]"
            result.mapping[token] = hit.value
        else:
            token = f"[{hit.category} REDACTED]"
        body = body[:hit.start] + token + body[hit.end:]
        result.categories.append(hit.category)
        result.removed += 1

    result.text = body
    return result


def safe_for_log(text: str) -> str:
    """The one-liner for logging. Nothing sensitive survives it."""
    return redact(text, destination=LOG).text


def safe_for_model(text: str, purpose: str = "") -> str:
    return redact(text, destination=CLOUD_MODEL, purpose=purpose).text


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "destinations": list(DESTINATIONS),
        "always_redacted": sorted(ALWAYS_REDACT),
        "context_aware": ("contact details are kept for cloud prompts when the task "
                          "is about contacting someone -- redacting them would make "
                          "the task impossible"),
        "never_context_aware": "credentials, in every destination, always",
        "policy": {destination: sorted(categories) for destination, categories in _POLICY.items()},
    }
