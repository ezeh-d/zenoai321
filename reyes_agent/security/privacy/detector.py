"""Find secrets and personal data before they leave the machine.

WHERE THIS RUNS
---------------
On the way OUT: cloud model prompts, trace exporters, external APIs, remote
sandboxes, crash reports, logs. ZENO reads the owner's files and screen, so
"send this context to a model" routinely means "send whatever happened to be
in it".

THE PART PEOPLE GET WRONG
-------------------------
Blanket redaction breaks the assistant. If the owner says "email Sarah at
sarah@work.com", redacting the address makes the task impossible -- ZENO
would be protecting the owner from their own request. So detection and
redaction are separate: this module finds things, and `policies.py` decides
what to do about each one given what the task actually needs.

Credentials are the exception. An API key or password has no legitimate
reason to appear in a prompt, a log or a trace, ever -- so those are always
redacted regardless of context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# --- categories ----------------------------------------------------------
CREDENTIAL = "CREDENTIAL"        # never leaves, no exceptions
FINANCIAL = "FINANCIAL"          # card / bank
IDENTITY = "IDENTITY"            # government identifiers
CONTACT = "CONTACT"              # email, phone, address -- often task-relevant

CATEGORIES = (CREDENTIAL, FINANCIAL, IDENTITY, CONTACT)

_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (category, label, regex)
    (CREDENTIAL, "openai key", r"\bsk-[A-Za-z0-9_-]{16,}"),
    (CREDENTIAL, "anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{16,}"),
    (CREDENTIAL, "google key", r"\bAIza[0-9A-Za-z_-]{30,}"),
    (CREDENTIAL, "aws key id", r"\b(AKIA|ASIA)[0-9A-Z]{14,}"),
    (CREDENTIAL, "github token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    (CREDENTIAL, "slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    (CREDENTIAL, "bearer token", r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"),
    (CREDENTIAL, "jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    (CREDENTIAL, "private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    (CREDENTIAL, "assigned secret",
     r"(?i)\b(api[_-]?key|secret|password|passwd|token|client[_-]?secret)\b\s*[=:]\s*[\"']?([^\s\"',;]{8,})"),
    (FINANCIAL, "card number", r"\b(?:\d[ -]?){13,19}\b"),
    (FINANCIAL, "iban", r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    (IDENTITY, "us ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    (IDENTITY, "uk ni number", r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"),
    (CONTACT, "email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    (CONTACT, "phone", r"(?<!\d)(?:\+\d{1,3}[ -]?)?(?:\(?\d{3,5}\)?[ -]?){2,3}\d{3,4}(?!\d)"),
)

_COMPILED = tuple((category, label, re.compile(pattern))
                  for category, label, pattern in _PATTERNS)

# Category that must never be sent anywhere, whatever the task.
ALWAYS_REDACT = frozenset({CREDENTIAL})


@dataclass(frozen=True)
class Hit:
    category: str
    label: str
    value: str
    start: int
    end: int

    @property
    def always_redact(self) -> bool:
        return self.category in ALWAYS_REDACT

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "label": self.label,
                "always_redact": self.always_redact,
                # The finding is reported; the value never is.
                "preview": (self.value[:2] + "..." + self.value[-2:]
                            if len(self.value) > 8 else "..."),
                "start": self.start, "end": self.end}


def _luhn(digits: str) -> bool:
    """Card numbers pass Luhn; order numbers and timestamps mostly do not."""
    numbers = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(numbers) <= 19:
        return False
    total, parity = 0, len(numbers) % 2
    for index, digit in enumerate(numbers):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def detect(text: str) -> list[Hit]:
    """Everything sensitive in `text`, most severe first."""
    body = str(text or "")
    hits: list[Hit] = []
    for category, label, pattern in _COMPILED:
        for match in pattern.finditer(body):
            value = match.group(0)
            # Without the Luhn check, every long number -- a timestamp, an
            # order id, a build hash -- is reported as a bank card, and a
            # detector that cries wolf gets turned off.
            if label == "card number" and not _luhn(value):
                continue
            hits.append(Hit(category, label, value, match.start(), match.end()))

    order = {CREDENTIAL: 0, FINANCIAL: 1, IDENTITY: 2, CONTACT: 3}
    hits.sort(key=lambda h: (order.get(h.category, 9), h.start))
    return _dedupe(hits)


def _dedupe(hits: list[Hit]) -> list[Hit]:
    """Overlapping matches keep the more severe one."""
    kept: list[Hit] = []
    for hit in hits:
        if any(hit.start < k.end and k.start < hit.end for k in kept):
            continue
        kept.append(hit)
    return sorted(kept, key=lambda h: h.start)


def summary(text: str) -> dict[str, Any]:
    hits = detect(text)
    return {
        "found": len(hits),
        "by_category": {c: sum(1 for h in hits if h.category == c)
                        for c in CATEGORIES if any(h.category == c for h in hits)},
        "must_redact": sum(1 for h in hits if h.always_redact),
        "hits": [h.as_dict() for h in hits[:20]],
    }
