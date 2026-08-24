"""Stable boundary between ZENO and a reviewed external capability.

Adapter generation deliberately produces a declarative contract, not Python
that imports or executes a repository.  A reviewed implementation can later
fulfil this protocol inside an extension-specific worker/environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from reyes_agent.extensions.models import IntegrationPlan, RepositorySnapshot


@dataclass(frozen=True)
class AdapterResult:
    state: str
    value: Any = None
    error: str = ""
    evidence: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class ZenoCapabilityAdapter(Protocol):
    def metadata(self) -> dict[str, Any]: ...
    def health(self) -> dict[str, Any]: ...
    async def execute(self, action: str, args: dict[str, Any]) -> AdapterResult: ...
    def verify(self, result: AdapterResult) -> dict[str, Any]: ...
    async def shutdown(self) -> None: ...


class AdapterGenerator:
    """Generate the reviewable adapter manifest without executing source."""

    RESULT_STATES = (
        "SUCCESS", "PARTIAL", "FAILED", "AUTH_REQUIRED", "RATE_LIMITED",
        "UNAVAILABLE", "VERIFICATION_FAILED",
    )

    def generate(self, extension_id: str, snapshot: RepositorySnapshot,
                 plan: IntegrationPlan) -> dict[str, Any]:
        return {
            "schema": 1,
            "extension_id": extension_id,
            "adapter_kind": plan.adapter_kind,
            "source": snapshot.source.as_dict(),
            "commit": snapshot.commit,
            "components": [item.as_dict() for item in plan.components],
            "permissions": plan.permissions.as_dict(),
            "feature_flag": plan.feature_flag,
            "result_states": list(self.RESULT_STATES),
            "methods": ["metadata", "health", "execute", "verify", "shutdown"],
            "execution": "isolated_worker_required",
            "environment_inheritance": "deny_by_default",
            "network": "deny_except_approved_hosts",
            "generated_code": False,
            "implementation_state": "PLANNED_NOT_EXECUTABLE",
        }


def adapter_is_healthy(adapter: ZenoCapabilityAdapter) -> tuple[bool, dict[str, Any]]:
    if not isinstance(adapter, ZenoCapabilityAdapter):
        return False, {"state": "INVALID", "reason": "Adapter contract is incomplete."}
    try:
        value = adapter.health()
        health = value.as_dict() if hasattr(value, "as_dict") else dict(value)
    except Exception as exc:  # noqa: BLE001 - extension boundary
        return False, {"state": "FAILED", "reason": f"health raised {type(exc).__name__}"}
    state = str(health.get("state") or "UNKNOWN").upper()
    return state in {"HEALTHY", "READY", "ONLINE"}, health
