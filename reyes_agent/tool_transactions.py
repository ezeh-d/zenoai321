"""Bounded, redacted lifecycle records for provider-requested tool calls.

The ledger observes the canonical ``run_tool`` path.  It never invokes a tool
and therefore cannot become a second executor or permission boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
from typing import Any


_STATUS = {
    "completed": "VERIFIED",
    "returned": "RETURNED_UNVERIFIED",
    "waiting": "WAITING",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
    "timed_out": "TIMED_OUT",
}
_TERMINAL = frozenset(_STATUS.values())
_NO_AUTO_RETRY = frozenset(
    {
        "click_element",
        "type_text",
        "press_keys",
        "send_to_chat",
        "browser_fill",
        "browser_click",
        "send_message",
        "delete_file",
        "delete_folder",
        "paper_trade",
        "record_trade",
    }
)
_NO_AUTO_RETRY_MARKERS = (
    "send_",
    "publish",
    "post_",
    "submit",
    "delete",
    "payment",
    "purchase",
    "credential",
    "security",
)
_SUCCESS_CLAIM = re.compile(
    r"^\s*(?:done|completed|finished|it(?:'s| is) (?:open|saved|sent)|"
    r"i (?:opened|saved|sent|deleted|posted|submitted)\b)[\s,.:;-]*",
    re.I,
)


def _fingerprint(tool: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        arguments,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=True,
    )
    return hashlib.sha256(f"{tool}\0{canonical}".encode("utf-8")).hexdigest()


def _bounded_text(value: object, limit: int = 240) -> str:
    text = str(value or "")
    try:
        from reyes_agent.memory.privacy import redact

        return redact(text, limit=limit)
    except Exception:
        return text[:limit]


def _result_preview(tool: str, result: object) -> str:
    try:
        from reyes_agent.tools import TOOLS

        registered = TOOLS.get(tool)
        if registered is not None and registered.audit_private:
            return f"[PRIVATE_TOOL_RESULT {len(str(result or ''))} chars]"
    except Exception:
        pass
    return _bounded_text(result, 320)


@dataclass
class ToolTransaction:
    turn_id: str
    call_id: str
    tool: str
    safe_input: Any
    status: str = "PLANNED"
    verification_state: str = "pending"
    error_category: str = ""
    retryable: bool = False
    evidence: str = ""
    result_preview: str = ""
    fingerprint: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


class ToolTransactionLedger:
    """Thread-safe finite record of observable tool-call states."""

    def __init__(self, *, max_records: int = 256, max_retries: int = 1) -> None:
        self.max_records = max(1, min(int(max_records), 2048))
        self.max_retries = max(0, min(int(max_retries), 3))
        self._lock = threading.RLock()
        self._records: OrderedDict[tuple[str, str], ToolTransaction] = OrderedDict()

    @staticmethod
    def _key(turn_id: str, call_id: str) -> tuple[str, str]:
        return str(turn_id or "")[:160], str(call_id or "")[:160]

    def _trim(self) -> None:
        while len(self._records) > self.max_records:
            self._records.popitem(last=False)

    def _publish(self, item: ToolTransaction) -> None:
        try:
            from reyes_agent import event_bus

            payload = asdict(item)
            payload["safe_input"] = item.safe_input
            event_bus.publish(
                "tool.transaction.changed",
                payload,
                source="tool_transactions",
                correlation_id=item.turn_id,
            )
        except Exception:  # noqa: BLE001 -- diagnostics cannot block a tool
            pass

    def planned(
        self,
        turn_id: str,
        call_id: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> ToolTransaction:
        key = self._key(turn_id, call_id)
        name = str(tool or "")[:160]
        raw_arguments = arguments if isinstance(arguments, dict) else {}
        try:
            from reyes_agent.tools import diagnostic_tool_input
            safe_input = diagnostic_tool_input(name, raw_arguments)
        except Exception:
            # The registry's audit projection isn't available in this tree; fall
            # back to a bounded, privacy-redacted repr so the ledger still
            # records safely (same defensive posture as the other lazy imports).
            safe_input = _bounded_text(raw_arguments, 240)
        item = ToolTransaction(
            turn_id=key[0],
            call_id=key[1],
            tool=name,
            safe_input=safe_input,
            fingerprint=_fingerprint(name, raw_arguments),
        )
        with self._lock:
            self._records[key] = item
            self._records.move_to_end(key)
            self._trim()
        self._publish(item)
        return replace(item)

    def started(self, turn_id: str, call_id: str) -> ToolTransaction:
        key = self._key(turn_id, call_id)
        with self._lock:
            item = self._records.get(key)
            if item is None:
                raise KeyError(f"unknown tool transaction {key!r}")
            item.status = "RUNNING"
            item.started_at = time.time()
            copied = replace(item)
        self._publish(copied)
        return copied

    def finished(self, turn_id: str, call_id: str, result: Any) -> ToolTransaction:
        from reyes_agent.tools import classify_tool_result

        key = self._key(turn_id, call_id)
        classification = classify_tool_result(result)
        status = _STATUS.get(str(classification.get("outcome") or ""), "RETURNED_UNVERIFIED")
        evidence = ""
        if isinstance(result, str) and result.strip()[:1] == "{":
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    evidence = _bounded_text(
                        parsed.get("evidence") or parsed.get("verification_evidence"),
                        240,
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        with self._lock:
            item = self._records.get(key)
            if item is None:
                raise KeyError(f"unknown tool transaction {key!r}")
            item.status = status
            item.verification_state = str(
                classification.get("verification_state") or "unverified"
            )[:40]
            item.error_category = str(classification.get("error_category") or "")[:80]
            item.retryable = bool(classification.get("retryable", False))
            item.evidence = evidence
            item.result_preview = _result_preview(item.tool, result)
            item.finished_at = time.time()
            copied = replace(item)
        self._publish(copied)
        return copied

    def get(self, turn_id: str, call_id: str) -> ToolTransaction | None:
        with self._lock:
            item = self._records.get(self._key(turn_id, call_id))
            return replace(item) if item is not None else None

    def cancel_turn(self, turn_id: str, *, reason: str = "") -> None:
        changed: list[ToolTransaction] = []
        now = time.time()
        with self._lock:
            for item in self._records.values():
                if item.turn_id != str(turn_id or "") or item.status in _TERMINAL:
                    continue
                item.status = "CANCELLED"
                item.verification_state = "cancelled"
                item.result_preview = _bounded_text(reason or "cancelled", 160)
                item.finished_at = now
                changed.append(replace(item))
        for item in changed:
            self._publish(item)

    def snapshot(self, *, turn_id: str = "") -> list[dict[str, Any]]:
        wanted = str(turn_id or "")
        with self._lock:
            records = [
                asdict(item)
                for item in self._records.values()
                if not wanted or item.turn_id == wanted
            ]
        return records

    def guard_reply(self, turn_id: str, text: str) -> str:
        records = self.snapshot(turn_id=turn_id)
        if not records or all(item["status"] == "VERIFIED" for item in records):
            return str(text)
        match = _SUCCESS_CLAIM.match(str(text))
        if not match:
            return str(text)
        remainder = str(text)[match.end():].strip()
        if any(item["status"] == "FAILED" for item in records):
            note = "The action failed; I did not verify completion."
        elif any(item["status"] == "WAITING" for item in records):
            note = "The action is still waiting and has not completed."
        elif any(item["status"] == "TIMED_OUT" for item in records):
            note = "The action timed out; I could not verify completion."
        elif any(item["status"] == "CANCELLED" for item in records):
            note = "The action was cancelled and did not complete."
        else:
            note = "I could not verify that action completed."
        return f"{note} {remainder}".strip()

    @staticmethod
    def _never_repeat(tool: str) -> bool:
        lowered = str(tool or "").casefold()
        return lowered in _NO_AUTO_RETRY or any(
            marker in lowered for marker in _NO_AUTO_RETRY_MARKERS
        )

    def allow_attempt(
        self, turn_id: str, tool: str, arguments: dict[str, Any]
    ) -> tuple[bool, str]:
        name = str(tool or "")
        fingerprint = _fingerprint(name, arguments if isinstance(arguments, dict) else {})
        with self._lock:
            previous = [
                item
                for item in self._records.values()
                if item.turn_id == str(turn_id or "")
                and item.tool == name
                and item.fingerprint == fingerprint
            ]
        if not previous:
            return True, "first attempt"
        if self._never_repeat(name):
            return False, "uncertain effectful action cannot repeat automatically"
        if any(item.status in {"PLANNED", "RUNNING"} for item in previous):
            return False, "the same operation is already in progress"
        if any(
            item.status
            in {"VERIFIED", "RETURNED_UNVERIFIED", "WAITING", "CANCELLED", "TIMED_OUT"}
            for item in previous
        ):
            return False, "the previous result is not safe to repeat automatically"
        failures = [item for item in previous if item.status == "FAILED"]
        if failures and all(item.retryable for item in failures):
            if len(failures) <= self.max_retries:
                return True, "bounded retry of an explicitly retryable failure"
            return False, "retry budget exhausted"
        return False, "the previous failure was not retryable"

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


_ledger: ToolTransactionLedger | None = None
_ledger_lock = threading.Lock()


def get_ledger() -> ToolTransactionLedger:
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            _ledger = ToolTransactionLedger()
        return _ledger
