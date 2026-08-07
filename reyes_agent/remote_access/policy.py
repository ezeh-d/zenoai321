"""What a phone is allowed to ask for, and how often.

TWO SEPARATE QUESTIONS
----------------------
1. CATEGORY -- is this request safe to run from a pocket at all?
2. RATE     -- is this device asking too fast?

They are different failures with different answers, so they are decided
separately and reported separately.

THE THREAT THIS EXISTS FOR
--------------------------
A stolen, unlocked phone with a live session. That device already passed
WebAuthn at some point, so authentication alone does not protect the
desktop. Categories are the second wall: a phone can ask questions and read
status freely, can be allowed to open an app, and can NEVER change security
settings or move money regardless of what its session says.

This layer does not replace `reyes_agent/permissions.py` or the confirmation
gate -- it sits in front of them. A CONTROL command that passes here still
meets every local check it would have met if typed on the desktop.
"""

from __future__ import annotations

import threading
import time
from collections import deque
import re
from dataclasses import dataclass
from typing import Any

from reyes_agent import cognition

# --- categories ----------------------------------------------------------
SAFE = "SAFE"              # questions, status, reading, notes
CONTROL = "CONTROL"        # opening apps, desktop actions, building
SENSITIVE = "SENSITIVE"    # security settings, credentials, system-level
FINANCIAL = "FINANCIAL"    # money movement -- never remote
CATEGORIES = (SAFE, CONTROL, SENSITIVE, FINANCIAL)

# Device scopes (see phone_security.DEFAULT_SCOPES) required per category.
_SCOPE_FOR = {SAFE: "status", CONTROL: "talk", SENSITIVE: "talk", FINANCIAL: "talk"}

# Unambiguous money language -- these alone are enough.
_FINANCIAL_MARKERS = (
    "transfer money", "send money", "wire money", "payment", "purchase",
    "invest", "trade", "withdraw", "deposit", "bank transfer", "crypto",
    "card number", "my card", "paypal", "stripe", "bank account", "sort code",
    "iban", "routing number", "refund", "subscription", "top up", "topup",
)
# Verbs that become financial once an AMOUNT or CURRENCY is present.
# "transfer the file" is not money; "transfer 500 to my brother" is, and the
# fixed-phrase list missed it entirely (measured 2026-08-07).
_MONEY_VERBS = ("transfer", "send", "pay", "buy", "sell", "wire", "spend", "charge")
# Things one pays FOR or trades IN. A money verb plus one of these is money
# regardless of whether an amount was stated -- "pay the electricity bill"
# names no figure and is obviously financial.
_MONEY_NOUNS = (
    "bill", "bills", "invoice", "rent", "salary", "wages", "fee", "fees", "tax",
    "taxes", "loan", "debt", "mortgage", "tuition", "fare", "ticket", "tickets",
    "bitcoin", "btc", "ethereum", "eth", "shares", "stock", "stocks", "coin",
    "airtime", "data bundle", "recharge",
)
_CURRENCY = re.compile(r"[$£€₦]|\b(?:usd|gbp|eur|ngn|naira|dollars?|pounds?|euros?|cash|money|funds)\b", re.I)
_AMOUNT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:k|m|thousand|million)?\b", re.I)
_RECIPIENT = re.compile(r"\bto\s+(?:my\s+)?(?:\w+)", re.I)


def _looks_financial(text: str) -> bool:
    """Money language, or a money verb with money context.

    Deliberately biased toward refusing. A false positive costs the owner
    one trip to the desktop; a false negative lets a stolen phone move
    money. "transfer the file" stays non-financial because `file` is not
    money context -- it falls through to CONTROL, where it belongs.
    """
    if cognition._has(text, _FINANCIAL_MARKERS):
        return True
    if not any(cognition._has(text, (verb,)) for verb in _MONEY_VERBS):
        return False
    if _CURRENCY.search(text) or cognition._has(text, _MONEY_NOUNS):
        return True
    # An amount plus a recipient is a payment even with no currency named:
    # "send 500 to my brother".
    return bool(_AMOUNT.search(text) and _RECIPIENT.search(text))
_SENSITIVE_MARKERS = (
    "password", "passphrase", "credential", "api key", "secret key", "token",
    "firewall", "antivirus", "defender", "registry", "regedit", "administrator",
    "sudo", "elevate", "disable security", "turn off security", "uac",
    "format drive", "wipe", "bitlocker", "ssh key", "private key",
    "delete all", "factory reset", "shut down the computer", "restart the computer",
)
_CONTROL_MARKERS = (
    "open ", "launch ", "start ", "close ", "run ", "install", "build", "deploy",
    "create ", "make ", "write ", "edit ", "delete ", "move ", "rename",
    "screenshot", "volume", "lock screen", "type ", "click ", "preview", "restart the build",
    # File operations. These share verbs with money ("transfer", "send"),
    # which is why the financial check runs first and needs money context.
    "transfer ", "copy ", "download", "upload", "save ", "checkpoint", "undo",
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    category: str
    reason: str
    needs_local_approval: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "category": self.category, "reason": self.reason,
                "needs_local_approval": self.needs_local_approval}


def classify(message: str) -> str:
    """Category for one natural-language remote request.

    Uses the same normaliser as the local router, so Pidgin and informal
    phrasing classify the same way remotely as they do on the desktop.
    Checked most-restrictive first: a sentence mentioning both a payment and
    an app is a FINANCIAL request that also opens an app, not the reverse.
    """
    text = cognition.normalize(message)
    if _looks_financial(text):
        return FINANCIAL
    if cognition._has(text, _SENSITIVE_MARKERS):
        return SENSITIVE
    if any(marker.strip() in text for marker in _CONTROL_MARKERS):
        return CONTROL
    return SAFE


def evaluate(message: str, *, scopes: set[str] | None = None,
             allow_control: bool = True) -> Decision:
    """Decide whether a remote request may proceed at all."""
    category = classify(message)
    scopes = scopes or set()

    if category == FINANCIAL:
        # Never, from a phone, regardless of session or scope. The desktop
        # confirmation gate is not a substitute: the point is that a stolen
        # phone cannot even start this.
        return Decision(False, category,
                        "Money movement is never available from a remote device. "
                        "Do this at the desktop.")
    if category == SENSITIVE:
        return Decision(False, category,
                        "Security, credential and system-level changes are desktop-only.")

    required = _SCOPE_FOR[category]
    if scopes and required not in scopes:
        return Decision(False, category,
                        f"This device does not have the '{required}' scope.")

    if category == CONTROL:
        if not allow_control:
            return Decision(False, category, "This device is limited to read-only requests.")
        # Allowed through, but everything the desktop would ask about still
        # gets asked -- the confirmation gate is untouched by this layer.
        return Decision(True, category,
                        "Desktop action permitted; local confirmation rules still apply.",
                        needs_local_approval=True)

    return Decision(True, SAFE, "Read-only or conversational request.")


# --- rate limiting -------------------------------------------------------
# Deliberately generous for conversation and tight for the things people
# actually attack. A chat limit that makes talking to ZENO annoying would
# get switched off, which protects nothing.

LIMITS: dict[str, tuple[int, float]] = {
    # bucket        -> (max events, window seconds)
    "command":        (60, 60.0),      # ordinary conversation: ~1/second sustained
    "login":          (8, 300.0),      # WebAuthn assertions
    "pair":           (5, 900.0),      # pairing attempts -- the brute-force target
    "pair_failure":   (5, 900.0),      # wrong/expired tokens specifically
    "auth_failure":   (10, 600.0),     # any 401 from this source
    "ws_connect":     (20, 300.0),     # reconnect storms
}

_lock = threading.Lock()
_buckets: dict[tuple[str, str], deque] = {}
_MAX_TRACKED = 2000


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    bucket: str
    remaining: int
    retry_after: float

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "bucket": self.bucket,
                "remaining": self.remaining, "retry_after": round(self.retry_after, 1)}


def check_rate(bucket: str, identity: str, *, record: bool = True) -> RateResult:
    """Sliding-window limiter. `identity` is a device id or client address.

    In-memory and bounded: a limiter that grows a dict per attacker IP is
    itself a denial-of-service vector.
    """
    limit, window = LIMITS.get(bucket, (60, 60.0))
    key = (bucket, str(identity or "unknown")[:120])
    now = time.time()
    with _lock:
        if len(_buckets) > _MAX_TRACKED:
            # Drop the coldest half rather than growing without bound.
            for stale in sorted(_buckets, key=lambda k: _buckets[k][-1] if _buckets[k] else 0)[:_MAX_TRACKED // 2]:
                _buckets.pop(stale, None)
        seen = _buckets.setdefault(key, deque())
        while seen and now - seen[0] > window:
            seen.popleft()
        if len(seen) >= limit:
            retry = window - (now - seen[0])
            return RateResult(False, bucket, 0, max(0.0, retry))
        if record:
            seen.append(now)
        return RateResult(True, bucket, max(0, limit - len(seen)), 0.0)


def reset_rates() -> None:
    """Test hook."""
    with _lock:
        _buckets.clear()


def status() -> dict[str, Any]:
    with _lock:
        tracked = len(_buckets)
    return {"limits": {k: {"max": v[0], "window_s": v[1]} for k, v in LIMITS.items()},
            "tracked_identities": tracked,
            "categories": list(CATEGORIES),
            "note": ("FINANCIAL and SENSITIVE are refused for every remote device. "
                     "CONTROL still passes through the normal desktop confirmation gate.")}
