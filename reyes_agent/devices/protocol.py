"""Local protocol objects which can later cross a device transport."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeviceRequest:
    goal: str
    plan: list[dict[str, Any]] = field(default_factory=list)
    approved: bool = False
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)


@dataclass
class DeviceResponse:
    ok: bool
    device_id: str
    request_id: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "device_id": self.device_id, "request_id": self.request_id,
                "summary": self.summary, "evidence": self.evidence,
                "error": self.error, "duration_ms": self.duration_ms}
