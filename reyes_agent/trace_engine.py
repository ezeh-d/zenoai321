"""One trace architecture for everything ZENO touches (Universal Trace brief).

Every authorized adapter -- device, Gmail, browser, tool, agent, command --
emits ONE canonical TraceEvent onto this bus, instead of each integration
inventing its own log. From here ZENO builds a unified timeline, searches, and
attaches evidence. Two hard rules are enforced here, not left to callers:

* SECRETS ARE REDACTED. Passwords, API keys, OAuth tokens, cookies and private
  keys never enter a trace, even if an adapter puts them in metadata.
* EVENTS ARE DE-DUPLICATED. One Gmail event is one record, not one-per-device.

Deterministic (timestamps are supplied, never wall-clock-guessed), thread-safe,
bounded (retention), and never raises into a caller.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

# Trace categories (brief's list). One event carries exactly one category.
DEVICE = "DEVICE_TRACE"
LOCATION = "LOCATION_TRACE"
ACCOUNT = "ACCOUNT_TRACE"
EMAIL = "EMAIL_TRACE"
MESSAGE = "MESSAGE_TRACE"
CALL = "CALL_TRACE"
VOICE = "VOICE_TRACE"
BROWSER = "BROWSER_TRACE"
FILE = "FILE_TRACE"
TOOL = "TOOL_TRACE"
AGENT = "AGENT_TRACE"
COMMAND = "COMMAND_TRACE"
REMOTE_SESSION = "REMOTE_SESSION_TRACE"
SECURITY = "SECURITY_TRACE"
SPORTS = "SPORTS_TRACE"
NEWS = "NEWS_TRACE"
SYSTEM = "SYSTEM_TRACE"

CATEGORIES = {DEVICE, LOCATION, ACCOUNT, EMAIL, MESSAGE, CALL, VOICE, BROWSER,
              FILE, TOOL, AGENT, COMMAND, REMOTE_SESSION, SECURITY, SPORTS,
              NEWS, SYSTEM}

# Keys whose VALUES must never be stored, however an adapter spells them.
_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|api[_-]?key|token|bearer|cookie|authorization|"
    r"private[_-]?key|refresh[_-]?token|session[_-]?id|otp|cvv|pin)", re.I)
_REDACTED = "[REDACTED]"

MAX_EVENTS = 5000            # ring buffer bound


def _redact(value: Any) -> Any:
    """Recursively drop secret-looking values from metadata."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = _REDACTED if _SECRET_KEY.search(str(k)) else _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


@dataclass
class TraceEvent:
    event_id: str
    category: str
    event_type: str
    timestamp: float
    trace_id: str = ""
    parent_trace_id: str = ""
    asset_id: str = ""
    account_id: str = ""
    device_id: str = ""
    source: str = ""
    target: str = ""
    status: str = ""
    verification: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "category": self.category,
            "event_type": self.event_type, "timestamp": self.timestamp,
            "trace_id": self.trace_id, "parent_trace_id": self.parent_trace_id,
            "asset_id": self.asset_id, "account_id": self.account_id,
            "device_id": self.device_id, "source": self.source,
            "target": self.target, "status": self.status,
            "verification": self.verification, "metadata": self.metadata,
        }


class UniversalTraceEngine:
    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._lock = threading.RLock()
        self._events: Deque[TraceEvent] = deque(maxlen=max(1, int(max_events)))
        self._seen: set[str] = set()

    def record(self, category: str, event_type: str, *, timestamp: float,
               event_id: str, **fields: Any) -> TraceEvent | None:
        """Record ONE canonical event. Duplicate event_ids are ignored (the same
        Gmail event from two devices is one trace). Secrets are stripped. Never
        raises."""
        try:
            eid = str(event_id or "").strip()
            cat = category if category in CATEGORIES else SYSTEM
            if not eid:
                return None
            with self._lock:
                if eid in self._seen:
                    return None
                metadata = _redact(fields.pop("metadata", {}) or {})
                event = TraceEvent(
                    event_id=eid, category=cat, event_type=str(event_type),
                    timestamp=float(timestamp),
                    trace_id=str(fields.get("trace_id", "")),
                    parent_trace_id=str(fields.get("parent_trace_id", "")),
                    asset_id=str(fields.get("asset_id", "")),
                    account_id=str(fields.get("account_id", "")),
                    device_id=str(fields.get("device_id", "")),
                    source=str(fields.get("source", "")),
                    target=str(fields.get("target", "")),
                    status=str(fields.get("status", "")),
                    verification=str(fields.get("verification", "")),
                    metadata=metadata)
                # Evict the oldest id from the seen-set when the ring drops it.
                if len(self._events) == self._events.maxlen and self._events:
                    self._seen.discard(self._events[0].event_id)
                self._events.append(event)
                self._seen.add(eid)
                return event
        except Exception:  # noqa: BLE001 -- tracing must never break a caller
            return None

    def query(self, *, category: str = "", account_id: str = "", device_id: str = "",
              asset_id: str = "", status: str = "", since: float | None = None,
              until: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        out = []
        for e in reversed(events):          # newest first
            if category and e.category != category:
                continue
            if account_id and e.account_id != account_id:
                continue
            if device_id and e.device_id != device_id:
                continue
            if asset_id and e.asset_id != asset_id:
                continue
            if status and e.status != status:
                continue
            if since is not None and e.timestamp < since:
                continue
            if until is not None and e.timestamp > until:
                continue
            out.append(e.as_dict())
            if len(out) >= max(1, int(limit)):
                break
        return out

    def timeline(self, *, since: float | None = None, until: float | None = None,
                 limit: int = 100) -> list[dict[str, Any]]:
        events = self.query(since=since, until=until, limit=10_000)
        events.sort(key=lambda e: e["timestamp"])   # chronological
        return events[-max(1, int(limit)):]

    def search(self, text: str, limit: int = 50) -> list[dict[str, Any]]:
        needle = str(text or "").strip().casefold()
        if not needle:
            return []
        with self._lock:
            events = list(self._events)
        hits = []
        for e in reversed(events):
            hay = f"{e.category} {e.event_type} {e.source} {e.target} {e.status} {e.metadata}".casefold()
            if needle in hay:
                hits.append(e.as_dict())
                if len(hits) >= max(1, int(limit)):
                    break
        return hits

    def delete_category(self, category: str) -> int:
        with self._lock:
            keep = [e for e in self._events if e.category != category]
            removed = len(self._events) - len(keep)
            self._events.clear()
            self._events.extend(keep)
            self._seen = {e.event_id for e in self._events}
        return removed

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seen.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


# --- evidence ledger ---------------------------------------------------------
@dataclass
class Evidence:
    action: str
    account: str
    provider_result: str
    verification: str          # VERIFIED | UNVERIFIED | FAILED
    timestamp: float
    trace_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "account": self.account,
                "provider_result": self.provider_result,
                "verification": self.verification,
                "timestamp": self.timestamp, "trace_id": self.trace_id}


class EvidenceLedger:
    """Ties a consequential action to its provider result + verification, so
    'email sent' means the provider returned a message id -- not that a button
    was clicked (brief: ACTION VERIFICATION)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list[Evidence] = []

    def record(self, action: str, account: str, provider_result: str,
               verification: str, *, timestamp: float, trace_id: str = "") -> Evidence:
        ev = Evidence(str(action), str(account),
                      _REDACTED if _SECRET_KEY.search(str(provider_result)) else str(provider_result),
                      str(verification or "UNVERIFIED"), float(timestamp), str(trace_id))
        with self._lock:
            self._items.append(ev)
        return ev

    def for_account(self, account: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e.as_dict() for e in self._items if e.account == account]

    def verified_only(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.as_dict() for e in self._items if e.verification == "VERIFIED"]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


_engine: UniversalTraceEngine | None = None
_ledger: EvidenceLedger | None = None
_lock = threading.Lock()


def get_trace_engine() -> UniversalTraceEngine:
    global _engine
    with _lock:
        if _engine is None:
            _engine = UniversalTraceEngine()
        return _engine


def get_evidence_ledger() -> EvidenceLedger:
    global _ledger
    with _lock:
        if _ledger is None:
            _ledger = EvidenceLedger()
        return _ledger
