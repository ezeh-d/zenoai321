"""Evidence-based, lazy and bounded tool health checks."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from typing import Any, Callable, Iterable

from reyes_agent.workspace.manager import RevisionClock
from reyes_agent.workspace.models import HealthRecord, ToolHealthState
from reyes_agent.workspace.redaction import redact_text, safe_text
from reyes_agent.workspace.registry import HealthProbe, HealthProbeRegistry

_STATE_PRIORITY = {
    ToolHealthState.AVAILABLE: 0,
    ToolHealthState.DEGRADED: 1,
    ToolHealthState.AUTH_REQUIRED: 2,
    ToolHealthState.DEPENDENCY_MISSING: 3,
    ToolHealthState.DISCONNECTED: 4,
    ToolHealthState.UNAVAILABLE: 5,
    ToolHealthState.ERROR: 6,
}


class ToolHealthManager:
    def __init__(
        self,
        *,
        adapters: Iterable[Any] | None = None,
        probes: HealthProbeRegistry | None = None,
        breaker: Any = None,
        revisions: RevisionClock | None = None,
        ttl_s: float = 30.0,
        max_workers: int = 4,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.revisions = revisions or RevisionClock()
        self.probes = probes or HealthProbeRegistry()
        if breaker is None:
            from reyes_agent.circuit_breaker import get_breaker

            breaker = get_breaker()
        self._breaker = breaker
        self._adapter_map = None if adapters is None else {
            str(adapter.metadata().name).casefold(): adapter for adapter in adapters}
        self._ttl_s = max(1.0, min(float(ttl_s), 300.0))
        self._clock = clock
        self._lock = threading.RLock()
        self._cache: dict[str, HealthRecord] = {}
        self._inflight: dict[str, Future[HealthRecord]] = {}
        self._generation: dict[str, int] = {}
        self._timed_out: set[tuple[str, int]] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 4)),
            thread_name_prefix="zeno-tool-health",
        )

    def _adapter(self, name: str):
        key = str(name or "").strip().casefold()
        if self._adapter_map is not None:
            return self._adapter_map.get(key)
        try:
            from reyes_agent.tools.universal_registry import get_global_tool_registry

            return get_global_tool_registry().get(key)
        except Exception:
            return None

    def _known_names(self) -> set[str]:
        names = {probe.name.casefold() for probe in self.probes.all()}
        if self._adapter_map is not None:
            names.update(self._adapter_map)
        else:
            try:
                from reyes_agent.tools.universal_registry import get_global_tool_registry

                names.update(adapter.metadata().name.casefold()
                             for adapter in get_global_tool_registry().all())
            except Exception:
                pass
        return names

    @staticmethod
    def _metadata(adapter: Any, probe: HealthProbe | None, name: str) -> dict[str, Any]:
        metadata = adapter.metadata() if adapter is not None else None
        category = safe_text(
            getattr(metadata, "category", "") or (probe.category if probe else "unknown"), 80)
        permissions = tuple(probe.permissions_required if probe else
                            (getattr(metadata, "permissions", ()) or ()))
        dependencies = tuple(probe.dependencies if probe else ())
        operations = tuple(probe.supported_operations if probe else ())
        return {
            "name": safe_text(getattr(metadata, "name", "") or name, 80),
            "category": category or "unknown",
            "permissions": permissions[:50],
            "dependencies": dependencies[:50],
            "operations": operations[:50],
        }

    def _store(self, record: HealthRecord) -> HealthRecord:
        with self._lock:
            self._cache[record.name.casefold()] = record
        return record

    def _record(
        self,
        name: str,
        status: ToolHealthState,
        *,
        adapter: Any = None,
        probe: HealthProbe | None = None,
        reason: str = "",
        initialized: bool = False,
        latency_ms: float = 0.0,
        error_code: str = "",
        suggested_repair: str = "",
        evidence_source: str = "",
        last_success: float | None = None,
        last_failure: float | None = None,
    ) -> HealthRecord:
        key = str(name or "").strip().casefold()
        facts = self._metadata(adapter, probe, key)
        with self._lock:
            previous = self._cache.get(key)
        now = self._clock()
        record = HealthRecord(
            name=facts["name"],
            category=facts["category"],
            status=status,
            available=status is ToolHealthState.AVAILABLE,
            initialized=bool(initialized),
            reason=redact_text(reason, 500),
            dependencies=facts["dependencies"],
            permissions_required=facts["permissions"],
            last_checked=now,
            last_success=(last_success if last_success is not None else
                          (previous.last_success if previous else 0.0)),
            last_failure=(last_failure if last_failure is not None else
                          (previous.last_failure if previous else 0.0)),
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            last_error_code=redact_text(error_code, 100),
            suggested_repair=redact_text(suggested_repair, 300),
            supported_operations=facts["operations"],
            evidence_source=safe_text(evidence_source, 80),
            revision=self.revisions.next(),
        )
        return self._store(record)

    def _adapter_record(self, name: str) -> HealthRecord:
        adapter = self._adapter(name)
        if adapter is None:
            return self._record(
                name, ToolHealthState.UNAVAILABLE,
                reason="No registered tool or health probe by that name.",
                evidence_source="not_registered")
        try:
            health = adapter.health()
            state = safe_text(getattr(health, "state", ""), 60).upper()
            permission = safe_text(getattr(health, "permission_state", ""), 60).casefold()
            reason = safe_text(getattr(health, "reason", ""), 500)
        except Exception as exc:
            return self._record(
                name, ToolHealthState.ERROR, adapter=adapter,
                reason=f"Health metadata failed: {type(exc).__name__}",
                error_code=type(exc).__name__, evidence_source="adapter_error")
        if permission == "blocked" or state in {"DISABLED", "BLOCKED"}:
            return self._record(
                name, ToolHealthState.UNAVAILABLE, adapter=adapter, reason=reason,
                suggested_repair="Enable the required permission.",
                evidence_source="permission")
        if state == "AUTH_REQUIRED":
            return self._record(
                name, ToolHealthState.AUTH_REQUIRED, adapter=adapter, reason=reason,
                suggested_repair="Sign in to this provider.", evidence_source="configuration")
        if state == "DEPENDENCY_MISSING":
            return self._record(
                name, ToolHealthState.DEPENDENCY_MISSING, adapter=adapter, reason=reason,
                suggested_repair="Install the reported dependency.", evidence_source="configuration")
        if state in {"DEVICE_OFFLINE", "DISCONNECTED"}:
            return self._record(
                name, ToolHealthState.DISCONNECTED, adapter=adapter, reason=reason,
                suggested_repair="Reconnect the required device or service.",
                evidence_source="configuration")
        if self._breaker.is_open(name):
            return self._record(
                name, ToolHealthState.UNAVAILABLE, adapter=adapter,
                reason="Recent failures opened the circuit breaker.",
                suggested_repair="Wait for the bounded recovery probe.",
                evidence_source="circuit_breaker")
        return self._record(
            name, ToolHealthState.DEGRADED, adapter=adapter,
            reason="Registered, but not recently verified by a safe operation.",
            evidence_source="registration_only")

    def _probe_record(self, name: str, probe: HealthProbe, generation: int) -> HealthRecord:
        started = time.perf_counter()
        try:
            raw = probe.check()
            result = raw if isinstance(raw, dict) else {"ok": False, "error": "invalid probe result"}
        except Exception as exc:
            result = {"ok": False, "error": type(exc).__name__}
        if result.get("ok") is not True and probe.recover is not None:
            try:
                recovered = probe.recover()
                result = (recovered if isinstance(recovered, dict) else
                          {"ok": False, "error": "invalid recovery result"})
            except Exception as exc:
                result = {"ok": False, "error": type(exc).__name__}
        with self._lock:
            if (name, generation) in self._timed_out:
                return self._cache[name]
        latency = result.get("latency_ms")
        if not isinstance(latency, (int, float)):
            latency = (time.perf_counter() - started) * 1000.0
        if result.get("ok") is True:
            status = ToolHealthState.AVAILABLE
            reason = result.get("reason") or "Safe health operation succeeded."
            repair = ""
        elif result.get("auth_required") is True:
            status, reason, repair = ToolHealthState.AUTH_REQUIRED, "Authentication is required.", "Sign in to this provider."
        elif result.get("dependency_missing"):
            status = ToolHealthState.DEPENDENCY_MISSING
            reason = f"Missing dependency: {safe_text(result.get('dependency_missing'), 120)}"
            repair = "Install the reported dependency."
        elif result.get("disconnected") is True:
            status, reason, repair = ToolHealthState.DISCONNECTED, "The service or device is disconnected.", "Reconnect the service or device."
        elif result.get("unavailable") is True:
            status, reason, repair = ToolHealthState.UNAVAILABLE, "The capability is currently unavailable.", "Check its configuration and dependency."
        elif result.get("degraded") is True:
            status, reason, repair = ToolHealthState.DEGRADED, safe_text(result.get("reason") or "The capability is partially available.", 500), safe_text(result.get("suggested_repair"), 300)
        else:
            status, reason, repair = ToolHealthState.ERROR, safe_text(result.get("error") or "Health operation failed.", 500), safe_text(result.get("suggested_repair") or "Inspect the provider status and retry safely.", 300)
        now = self._clock()
        if status is ToolHealthState.AVAILABLE:
            self._breaker.record(name, True)
        elif status in {ToolHealthState.ERROR, ToolHealthState.UNAVAILABLE}:
            self._breaker.record(name, False)
        return self._record(
            name, status, probe=probe,
            reason=reason, initialized=bool(result.get("initialized", result.get("ok") is True)),
            latency_ms=float(latency), error_code=safe_text(result.get("error_code") or result.get("error"), 100),
            suggested_repair=repair, evidence_source="safe_probe",
            last_success=now if status is ToolHealthState.AVAILABLE else None,
            last_failure=now if status in {ToolHealthState.ERROR, ToolHealthState.UNAVAILABLE} else None,
        )

    def _drop_inflight(self, name: str, future: Future[HealthRecord]) -> None:
        with self._lock:
            if self._inflight.get(name) is future:
                self._inflight.pop(name, None)

    def check(self, name: str, force: bool = False) -> HealthRecord:
        key = str(name or "").strip().casefold()
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and not force and now - cached.last_checked < self._ttl_s:
                return cached
            probe = self.probes.get(key)
            if probe is None:
                return self._adapter_record(key)
            if not self._breaker.allow(key):
                return self._record(
                    key, ToolHealthState.UNAVAILABLE, probe=probe,
                    reason="Recent failures opened the circuit breaker.",
                    suggested_repair="Wait for the bounded recovery probe.",
                    evidence_source="circuit_breaker")
            future = self._inflight.get(key)
            if future is None:
                generation = self._generation.get(key, 0) + 1
                self._generation[key] = generation
                future = self._executor.submit(self._probe_record, key, probe, generation)
                self._inflight[key] = future
                future.add_done_callback(lambda done, n=key: self._drop_inflight(n, done))
            else:
                generation = self._generation[key]
        try:
            return future.result(timeout=max(0.01, min(float(probe.timeout_s), 30.0)))
        except TimeoutError:
            with self._lock:
                self._timed_out.add((key, generation))
            self._breaker.record(key, False)
            return self._record(
                key, ToolHealthState.ERROR, probe=probe,
                reason="The safe health operation timed out.", error_code="HEALTH_TIMEOUT",
                suggested_repair="Retry after the provider recovers.",
                evidence_source="safe_probe_timeout", last_failure=self._clock())

    def check_many(self, names: Iterable[str] | None = None, force: bool = False) -> list[HealthRecord]:
        wanted = list(names) if names is not None else sorted(self._known_names())
        return [self.check(name, force=force) for name in wanted[:500]]

    def observe_execution(self, name: str, ok: bool, latency_ms: float = 0.0,
                          error_code: str = "") -> HealthRecord:
        key = str(name or "").strip().casefold()
        self._breaker.record(key, bool(ok))
        adapter = self._adapter(key)
        now = self._clock()
        with self._lock:
            previous = self._cache.get(key)
        status = ToolHealthState.AVAILABLE if ok else (
            ToolHealthState.DEGRADED if previous and previous.last_success else ToolHealthState.ERROR)
        return self._record(
            key, status, adapter=adapter,
            reason=("A real execution succeeded." if ok else "A real execution failed."),
            initialized=bool(ok or (previous and previous.initialized)),
            latency_ms=latency_ms, error_code=error_code,
            suggested_repair="Retry only if the operation is safe." if not ok else "",
            evidence_source="verified_execution",
            last_success=now if ok else None,
            last_failure=now if not ok else None,
        )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = sorted(self._cache.values(), key=lambda item: (
                _STATE_PRIORITY[item.status], item.category, item.name))
        return [item.as_dict() for item in rows]

    def capability_summary(self, query: str) -> dict[str, Any]:
        label = safe_text(query, 120)
        tokens = {part for part in label.casefold().replace("_", " ").split() if len(part) > 1}
        names = [name for name in self._known_names()
                 if any(token in name.replace("_", " ") for token in tokens)]
        rows = [self.check(name) for name in sorted(names)[:25]]
        if not rows:
            return {"capability": label, "status": "UNAVAILABLE",
                    "detail": "No registered capability by that name.", "tools": []}
        best = min(rows, key=lambda item: _STATE_PRIORITY[item.status])
        return {
            "capability": label,
            "status": best.status.value,
            "detail": best.reason,
            "tools": [item.as_dict() for item in rows],
        }

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
