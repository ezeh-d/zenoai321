"""Bounded, serialisable records for ZENO's proactive heartbeat."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Importance(str, Enum):
    IGNORE = "IGNORE"
    LOG = "LOG"
    INBOX = "INBOX"
    NOTIFY = "NOTIFY"
    URGENT = "URGENT"


class DeliveryState(str, Enum):
    NEW = "NEW"
    HELD = "HELD"
    SURFACED = "SURFACED"
    SEEN = "SEEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class VoicePolicy(str, Enum):
    SILENT = "SILENT"
    VISUAL_ONLY = "VISUAL_ONLY"
    VOICE_WHEN_IDLE = "VOICE_WHEN_IDLE"
    VOICE_NOW = "VOICE_NOW"


class PresenceState(str, Enum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    AWAY = "AWAY"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class OverlapPolicy(str, Enum):
    SKIP = "SKIP"
    COALESCE = "COALESCE"
    QUEUE_ONE = "QUEUE_ONE"


def bounded_text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def safe_facts(value: Mapping[str, Any] | None, limit: int = 20) -> dict[str, Any]:
    """Keep small operational facts and discard secret-like keys recursively."""
    sensitive = {"token", "secret", "password", "credential", "authorization", "api_key", "apikey"}
    result: dict[str, Any] = {}
    for key, item in list((value or {}).items())[:limit]:
        normalized = str(key).strip().casefold().replace("-", "_")
        if normalized in sensitive or any(word in normalized for word in sensitive):
            continue
        if isinstance(item, bool | int | float):
            result[bounded_text(key, 80)] = item
        elif isinstance(item, str):
            result[bounded_text(key, 80)] = bounded_text(item, 200)
    return result


@dataclass(frozen=True)
class ScheduledCheck:
    id: str
    description: str
    enabled: bool
    interval_s: int
    priority: int
    timeout_s: int
    overlap_policy: OverlapPolicy
    quiet_hours_policy: str
    handler_id: str
    event_types: tuple[str, ...] = ()
    next_due_at: float = 0.0
    last_run_at: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    consecutive_failures: int = 0
    last_result_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not bounded_text(self.id, 80):
            raise ValueError("scheduled check id is required")
        if not bounded_text(self.handler_id, 80):
            raise ValueError("scheduled check handler_id is required")
        if not 10 <= int(self.interval_s) <= 86_400:
            raise ValueError("scheduled check interval must be between 10 seconds and one day")
        if not 1 <= int(self.timeout_s) <= 600:
            raise ValueError("scheduled check timeout must be between 1 and 600 seconds")


@dataclass(frozen=True)
class CheckResult:
    source: str
    subject: str
    condition: str
    summary: str
    changed: bool
    facts: dict[str, Any] = field(default_factory=dict)
    importance_hint: Importance | None = None
    panel_target: str = ""
    state: str = "CHANGED"

    @classmethod
    def changed(cls, source: str, subject: str, condition: str, summary: str,
                *, facts: Mapping[str, Any] | None = None,
                importance_hint: Importance | None = None,
                panel_target: str = "") -> "CheckResult":
        return cls(bounded_text(source, 80), bounded_text(subject, 160),
                   bounded_text(condition, 120), bounded_text(summary), True,
                   safe_facts(facts), importance_hint, bounded_text(panel_target, 80), "CHANGED")

    @classmethod
    def no_change(cls, source: str, summary: str = "") -> "CheckResult":
        return cls(bounded_text(source, 80), "", "", bounded_text(summary), False, state="NO_CHANGE")

    @property
    def dedupe_key(self) -> str:
        return ":".join(part.casefold() for part in (self.source, self.subject, self.condition))


@dataclass(frozen=True)
class ProactiveNotice:
    id: str
    created_at: float
    updated_at: float
    source: str
    subject: str
    condition: str
    dedupe_key: str
    importance: Importance
    title: str
    summary: str
    facts: dict[str, Any]
    delivery_state: DeliveryState
    voice_policy: VoicePolicy = VoicePolicy.VISUAL_ONLY
    panel_target: str = ""
    explanation: str = ""
    count: int = 1
    surfaced_at: float = 0.0
    seen_at: float = 0.0
    acknowledged_at: float = 0.0
    expires_at: float = 0.0


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool = True
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    focus_until: float = 0.0
    urgent_voice: bool = False
    max_model_calls_per_hour: int = 0
    max_model_calls_per_day: int = 0
    max_concurrent_model_calls: int = 0
