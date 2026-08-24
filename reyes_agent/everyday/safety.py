"""Everyday safety: how risky is an action, and does it hold a secret?

Two guards Pack 10 leans on repeatedly (#17, #82, #128, #170-172, #233):

* classify_action() rates a requested action LOW / MODERATE / HIGH / SENSITIVE,
  and confirmation policy lets only LOW reversible actions run automatically --
  destructive or sensitive ones must be confirmed.
* detect_sensitive() spots likely passwords / OTPs / API keys / tokens / private
  keys / card numbers, so clipboard history, memory and traces can REFUSE to
  persist them (never store secrets).

Pure logic, deterministic, never raises.
"""

from __future__ import annotations

import re

LOW = "LOW"
MODERATE = "MODERATE"
HIGH = "HIGH"
SENSITIVE = "SENSITIVE"

_SENSITIVE_ACTION = re.compile(
    r"\b(password|passcode|credential|bank|card number|debit|credit card|"
    r"transfer (?:money|funds)|wire|send money|pay(?:ment)?|purchase|buy|"
    r"ssn|social security|private key|seed phrase|2fa|otp)\b", re.I)
_HIGH_ACTION = re.compile(
    r"\b(delete|remove|erase|wipe|format|uninstall|drop table|rm\s+-rf|"
    r"factory reset|revoke|shut ?down|power off|kill|destroy|overwrite|"
    r"disable security|clear all)\b", re.I)
_MODERATE_ACTION = re.compile(
    r"\b(send|email|message|post|publish|tweet|share|upload|forward|reply|"
    r"submit|comment|dm)\b", re.I)


def classify_action(text: str) -> str:
    t = str(text or "")
    if _SENSITIVE_ACTION.search(t):
        return SENSITIVE
    if _HIGH_ACTION.search(t):
        return HIGH
    if _MODERATE_ACTION.search(t):
        return MODERATE
    return LOW


def requires_confirmation(risk: str) -> bool:
    """Only LOW (reversible, local) may run automatically."""
    return str(risk).upper() != LOW


# --- secret detection -------------------------------------------------------
_SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "api_key": re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9]{16,}\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
    "bearer_token": re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{16,}\b"),
    "card_number": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "otp": re.compile(r"\b(?:otp|code|verification code)\b[^0-9]{0,12}\d{4,8}\b", re.I),
    "password_label": re.compile(r"\b(pass(?:word|code)|pwd)\b\s*[:=]\s*\S+", re.I),
}


def detect_sensitive(text: str) -> dict[str, object]:
    """Return {found, kinds} for likely secrets. Used to REFUSE persistence."""
    t = str(text or "")
    kinds = []
    for kind, pat in _SECRET_PATTERNS.items():
        if pat.search(t):
            # A bare 13-16 digit run is only "card" if it isn't obviously an id;
            # keep it simple and conservative -- err toward protecting.
            kinds.append(kind)
    return {"found": bool(kinds), "kinds": kinds}


def safe_to_persist(text: str) -> bool:
    """False if the text likely contains a secret that must not be stored."""
    return not detect_sensitive(text)["found"]
