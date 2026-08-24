"""Bounded failure classification and recovery planning over existing breakers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

FAILURE_CLASSES = {
    "NETWORK_ERROR", "AUTH_REQUIRED", "DEVICE_OFFLINE", "TOOL_TIMEOUT",
    "TOOL_CRASH", "UI_CHANGED", "RATE_LIMITED", "MODEL_FAILURE",
    "DEPENDENCY_MISSING", "VERIFICATION_FAILED", "PERMISSION_DENIED", "UNKNOWN",
}

SAFE_RETRY = "SAFE_RETRY"
RETRY_AFTER_BACKOFF = "RETRY_AFTER_BACKOFF"
REQUIRES_REAUTH = "REQUIRES_REAUTH"
REQUIRES_DEVICE = "REQUIRES_DEVICE"
DO_NOT_RETRY = "DO_NOT_RETRY"
REQUIRES_USER = "REQUIRES_USER"


class FailureClassifier:
    _RULES = (
        ("AUTH_REQUIRED", ("401", "unauthor", "auth required", "token expired", "invalid api key")),
        ("DEVICE_OFFLINE", ("device offline", "node offline", "not connected")),
        ("PERMISSION_DENIED", ("permission denied", "forbidden", "not allowed", "403")),
        ("RATE_LIMITED", ("rate limit", "429", "too many requests")),
        ("TOOL_TIMEOUT", ("timed out", "timeout")),
        ("NETWORK_ERROR", ("connection refused", "connection reset", "dns", "network error")),
        ("DEPENDENCY_MISSING", ("no module named", "not installed", "executable not found")),
        ("UI_CHANGED", ("selector", "element not found", "stale element")),
        ("VERIFICATION_FAILED", ("verification failed", "expected state")),
        ("MODEL_FAILURE", ("provider failed", "model unavailable", "llm")),
        ("TOOL_CRASH", ("traceback", "crashed", "process exited")),
    )

    def classify(self, error: Any, *, code: str = "") -> str:
        text = f"{code} {error}".casefold()
        for failure, needles in self._RULES:
            if any(needle in text for needle in needles):
                return failure
        return "UNKNOWN"


class RetryPolicyManager:
    _POLICY = {
        "NETWORK_ERROR": RETRY_AFTER_BACKOFF,
        "AUTH_REQUIRED": REQUIRES_REAUTH,
        "DEVICE_OFFLINE": REQUIRES_DEVICE,
        "TOOL_TIMEOUT": SAFE_RETRY,
        "TOOL_CRASH": SAFE_RETRY,
        "UI_CHANGED": REQUIRES_USER,
        "RATE_LIMITED": RETRY_AFTER_BACKOFF,
        "MODEL_FAILURE": SAFE_RETRY,
        "DEPENDENCY_MISSING": DO_NOT_RETRY,
        "VERIFICATION_FAILED": REQUIRES_USER,
        "PERMISSION_DENIED": DO_NOT_RETRY,
        "UNKNOWN": REQUIRES_USER,
    }

    def policy(self, failure_class: str) -> str:
        return self._POLICY.get(failure_class, REQUIRES_USER)


class FallbackResolver:
    def __init__(self) -> None:
        self._fallbacks: dict[str, list[str]] = {
            "browser": ["playwright", "cdp", "accessibility", "visual_grounding", "controlled_input"],
            "stt": ["primary_stt", "faster_whisper", "whisper_cpp"],
            "tts": ["elevenlabs", "kokoro", "piper", "sapi"],
        }

    def register(self, capability: str, providers: list[str]) -> None:
        self._fallbacks[str(capability)] = list(dict.fromkeys(map(str, providers)))

    def next(self, capability: str, failed_provider: str = "") -> str | None:
        providers = self._fallbacks.get(str(capability), [])
        start = providers.index(failed_provider) + 1 if failed_provider in providers else 0
        try:
            from reyes_agent import circuit_breaker
            return next((p for p in providers[start:] if circuit_breaker.allow(p)), None)
        except Exception:
            return providers[start] if start < len(providers) else None


@dataclass
class RecoveryPlan:
    failure_class: str
    retry_policy: str
    fallback: str | None
    max_attempts: int
    user_action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecoveryPlanner:
    def __init__(self) -> None:
        self.classifier = FailureClassifier()
        self.policies = RetryPolicyManager()
        self.fallbacks = FallbackResolver()

    def plan(self, error: Any, *, capability: str = "", provider: str = "",
             code: str = "") -> RecoveryPlan:
        failure = self.classifier.classify(error, code=code)
        policy = self.policies.policy(failure)
        fallback = self.fallbacks.next(capability, provider) if capability else None
        attempts = 1 if policy in {SAFE_RETRY, RETRY_AFTER_BACKOFF} else 0
        action = {
            REQUIRES_REAUTH: "Reconnect the provider account.",
            REQUIRES_DEVICE: "Reconnect or wake the required device.",
            REQUIRES_USER: "Owner review is required before another attempt.",
        }.get(policy, "")
        plan = RecoveryPlan(failure, policy, fallback, attempts, action)
        try:
            from reyes_agent import event_bus
            event_bus.publish("recovery.planned", plan.as_dict(), source="recovery_engine")
        except Exception:
            pass
        return plan


SelfHealingEngine = RecoveryPlanner

_planner = RecoveryPlanner()


def get_recovery_planner() -> RecoveryPlanner:
    return _planner
