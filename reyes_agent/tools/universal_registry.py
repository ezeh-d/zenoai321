"""One normalized, lazy view over every executable ZENO tool.

This module does **not** create a second executor.  ``reyes_agent.tools.TOOLS``
and :func:`reyes_agent.tools.run_tool` remain authoritative; the global
registry wraps them with the metadata, health, device, validation,
cancellation and selection contract required by the Universal Tool Catalog.

The wrapper is intentionally lazy.  Merely asking for inventory performs no
network request, starts no browser, opens no device and imports no optional
provider SDK.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

READY = "READY"
DEGRADED = "DEGRADED"
DISABLED = "DISABLED"
AUTH_REQUIRED = "AUTH_REQUIRED"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
DEVICE_OFFLINE = "DEVICE_OFFLINE"


@dataclass(frozen=True)
class ToolMetadata:
    tool_id: str
    name: str
    description: str
    category: str
    provider: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: tuple[str, ...]
    supported_devices: tuple[str, ...]
    requires_network: bool
    requires_confirmation: bool
    startup_cost: str = "lazy"
    memory_cost: str = "on-demand"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["permissions"] = list(self.permissions)
        value["supported_devices"] = list(self.supported_devices)
        return value


@dataclass(frozen=True)
class ToolHealth:
    state: str
    reason: str
    permission_state: str
    device_states: dict[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.state in {READY, DEGRADED} and self.permission_state != "blocked"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "usable": self.usable}


@dataclass
class ToolExecution:
    execution_id: str
    tool_id: str
    ok: bool
    state: str
    result: Any = None
    error: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    duration_ms: float = 0.0
    cancellation_requested: bool = False
    may_continue: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class ToolAdapter(Protocol):
    def metadata(self) -> ToolMetadata: ...
    def health(self) -> ToolHealth: ...
    def validate(self, args: dict[str, Any]) -> tuple[bool, str]: ...
    async def execute(self, args: dict[str, Any], context: dict[str, Any] | None = None
                      ) -> ToolExecution: ...
    async def cancel(self, execution_id: str) -> dict[str, Any]: ...
    def required_permissions(self) -> tuple[str, ...]: ...
    def supported_devices(self) -> tuple[str, ...]: ...


_PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float),
    "boolean": (bool,), "object": (dict,), "array": (list, tuple),
}


def _validate_schema(schema: dict[str, Any], args: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(args, dict):
        return False, "arguments must be an object"
    required = schema.get("required") or []
    missing = [str(key) for key in required if key not in args]
    if missing:
        return False, f"missing required argument(s): {', '.join(missing)}"
    properties = schema.get("properties") or {}
    for key, value in args.items():
        definition = properties.get(key)
        if not isinstance(definition, dict):
            continue
        expected = definition.get("type")
        accepted = _PYTHON_TYPES.get(str(expected))
        # bool is an int subclass; JSON Schema intentionally treats it as a
        # distinct type, so do the same here.
        if expected in {"integer", "number"} and isinstance(value, bool):
            return False, f"argument '{key}' must be {expected}"
        if accepted and not isinstance(value, accepted):
            return False, f"argument '{key}' must be {expected}"
        if isinstance(value, str):
            maximum = int(definition.get("maxLength") or 1_000_000)
            if len(value) > maximum:
                return False, f"argument '{key}' exceeds {maximum} characters"
    return True, "valid"


@lru_cache(maxsize=64)
def _package_version(module_name: str) -> str:
    root = str(module_name or "").split(".", 1)[0]
    try:
        return importlib.metadata.version(root)
    except importlib.metadata.PackageNotFoundError:
        return "1"


def _devices_for(name: str, category: str, permission: str) -> tuple[str, ...]:
    value = f"{name} {category} {permission}".casefold()
    if "android" in value or "phone" in value:
        return ("android", "web-companion")
    if any(marker in value for marker in (
            "desktop", "browser", "vision", "app_control", "clipboard",
            "audio_capture", "system_commands")):
        return ("local-windows",)
    return ("zeno-core",)


def _network_for(name: str, category: str) -> bool:
    value = f"{name} {category}".casefold()
    return any(marker in value for marker in (
        "web", "browser", "email", "message", "social", "research", "mcp",
        "github", "cloud", "remote", "calendar", "notification",
    ))


class BuiltinToolAdapter:
    """Catalog contract over one existing registered function."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self._handles: dict[str, Any] = {}
        self._lock = threading.Lock()
        from reyes_agent import permissions
        from reyes_agent.tools import group_of

        category = group_of(tool.name)
        capability = permissions.capability_for_tool(tool.name) or category
        module = getattr(tool.func, "__module__", "reyes_agent.tools")
        self._metadata = ToolMetadata(
            tool_id=f"zeno.native.{tool.name}.v1",
            name=tool.name,
            description=tool.description,
            category=category,
            provider="zeno-native",
            version=_package_version(module),
            input_schema=dict(tool.input_schema),
            output_schema={"type": ["string", "object", "array"]},
            permissions=(capability,),
            supported_devices=_devices_for(tool.name, category, capability),
            requires_network=_network_for(tool.name, category),
            requires_confirmation=bool(tool.requires_confirmation),
        )

    def metadata(self) -> ToolMetadata:
        return self._metadata

    def required_permissions(self) -> tuple[str, ...]:
        return self._metadata.permissions

    def supported_devices(self) -> tuple[str, ...]:
        return self._metadata.supported_devices

    def validate(self, args: dict[str, Any]) -> tuple[bool, str]:
        return _validate_schema(self._metadata.input_schema, args)

    def health(self) -> ToolHealth:
        from reyes_agent import permissions

        permission = permissions.check(self._tool.name)
        state = DISABLED if permission == permissions.BLOCKED else READY
        reason = ("disabled by the permission engine" if state == DISABLED
                  else "registered, lazy, and admitted through the authoritative tool runtime")
        device_states: dict[str, str] = {}
        for device in self.supported_devices():
            if device in {"zeno-core", "web-companion", "local-windows"}:
                device_states[device] = "ONLINE"
                continue
            try:
                from reyes_agent.devices import get_device_manager
                known = get_device_manager().devices()
                device_states[device] = "ONLINE" if (
                    device == "local-windows" or device in known) else "OFFLINE"
            except Exception:
                device_states[device] = "UNKNOWN"
        if device_states and all(value == "OFFLINE" for value in device_states.values()):
            state, reason = DEVICE_OFFLINE, "no supported execution device is online"
        return ToolHealth(state, reason, permission, device_states)

    async def execute(self, args: dict[str, Any], context: dict[str, Any] | None = None
                      ) -> ToolExecution:
        valid, reason = self.validate(args)
        execution_id = uuid.uuid4().hex[:16]
        if not valid:
            return ToolExecution(
                execution_id, self._metadata.tool_id, False, "INVALID_ARGUMENT",
                error={"category": "INVALID_ARGUMENT", "recovery": reason},
            )
        health = self.health()
        if not health.usable:
            category = "PERMISSION_DENIED" if health.state == DISABLED else "TOOL_UNAVAILABLE"
            return ToolExecution(
                execution_id, self._metadata.tool_id, False, category,
                error={"category": category, "recovery": health.reason},
            )

        from reyes_agent.kernel import get_kernel
        from reyes_agent.tools import classify_tool_result, run_tool
        from reyes_agent.worker_pool import PRIORITY_MISSION

        timeout_s = max(1.0, min(900.0, float((context or {}).get("timeout_s", 120))))

        def invoke(task_context):
            task_context.progress("executing", tool=self._tool.name)
            value = run_tool(self._tool.name, args)
            task_context.progress("classifying", tool=self._tool.name)
            return value

        started = time.perf_counter()
        handle = get_kernel().submit(
            invoke, name=f"universal:{self._tool.name}", priority=PRIORITY_MISSION,
            timeout=timeout_s, with_context=True,
        )
        with self._lock:
            self._handles[execution_id] = handle
        try:
            result = await asyncio.to_thread(handle.result, timeout_s + 1.0)
            outcome = classify_tool_result(result)
            # ``returned`` is the deliberate result class for a successful
            # read-only tool with no postcondition to prove.  It is usable
            # output, not an execution failure.  Effectful tools still need
            # the verifier below before this adapter reports success.
            ok = outcome.get("outcome") in {"returned", "completed", "succeeded"}
            verification: dict[str, Any] | None = None
            try:
                from reyes_agent import action_verifier
                verdict = action_verifier.verify(self._tool.name, args, result)
                verification = verdict.as_dict()
                if verdict.verifiable and not verdict.verified:
                    ok = False
            except Exception:
                verification = None
            try:
                from reyes_agent import tool_reputation
                tool_reputation.record(
                    self._tool.name, ok,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception:
                pass
            if not ok:
                result_state = str(
                    outcome.get("verification_state") or outcome.get("outcome") or "FAILED"
                ).upper()
            elif outcome.get("verification_state") == "verified":
                result_state = "VERIFIED"
            else:
                # A useful read/result is not automatically evidence that an
                # external side effect happened.
                result_state = "RETURNED_UNVERIFIED"
            return ToolExecution(
                execution_id, self._metadata.tool_id, ok,
                result_state,
                result=result, verification=verification,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except TimeoutError as exc:
            handle.cancel()
            return ToolExecution(
                execution_id, self._metadata.tool_id, False, "TOOL_TIMEOUT",
                error={"category": "TOOL_TIMEOUT", "recovery": str(exc)},
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                cancellation_requested=True,
                # Synchronous legacy functions must own their I/O timeout; a
                # cooperative token cannot interrupt native code already in a
                # syscall. Never pretend otherwise.
                may_continue=bool(handle.started_at and not handle.done),
            )
        except Exception as exc:  # noqa: BLE001 -- normalized at this boundary
            from reyes_agent import failures
            return ToolExecution(
                execution_id, self._metadata.tool_id, False, "FAILED",
                error=failures.explain(exc=exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        finally:
            with self._lock:
                # The returned execution already carries the honest
                # ``may_continue`` flag. Retaining a timed-out legacy handle
                # until process exit would turn repeated timeouts into a leak.
                self._handles.pop(execution_id, None)

    async def cancel(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            handle = self._handles.get(str(execution_id))
        if handle is None:
            return {"ok": False, "state": "NOT_FOUND", "execution_id": execution_id}
        requested = handle.cancel()
        return {
            "ok": requested,
            "state": "CANCELLATION_REQUESTED" if requested else "ALREADY_FINISHED",
            "execution_id": execution_id,
            "cooperative": True,
            "may_continue": bool(handle.started_at and not handle.done),
        }


class GlobalToolRegistry:
    """Authoritative catalog view; execution delegates to existing tools."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, ToolAdapter] = {}
        self._names: dict[str, str] = {}
        self._native_names: set[str] = set()

    def _seed(self) -> None:
        with self._lock:
            from reyes_agent.tools import TOOLS
            for tool in TOOLS.values():
                if tool.name not in self._native_names:
                    self.register(BuiltinToolAdapter(tool))
                    self._native_names.add(tool.name)

    def register(self, adapter: ToolAdapter) -> ToolMetadata:
        if not isinstance(adapter, ToolAdapter):
            raise TypeError("adapter does not implement the ToolAdapter contract")
        metadata = adapter.metadata()
        with self._lock:
            existing = self._adapters.get(metadata.tool_id)
            if existing is not None and existing is not adapter:
                raise ValueError(f"duplicate universal tool id '{metadata.tool_id}'")
            other_id = self._names.get(metadata.name)
            if other_id and other_id != metadata.tool_id:
                raise ValueError(f"duplicate universal tool name '{metadata.name}'")
            self._adapters[metadata.tool_id] = adapter
            self._names[metadata.name] = metadata.tool_id
        return metadata

    def get(self, tool_id_or_name: str) -> ToolAdapter | None:
        self._seed()
        key = str(tool_id_or_name or "").strip()
        with self._lock:
            return self._adapters.get(key) or self._adapters.get(self._names.get(key, ""))

    def all(self) -> list[ToolAdapter]:
        self._seed()
        with self._lock:
            return sorted(self._adapters.values(), key=lambda item: item.metadata().name)

    def find_by_capability(self, capability: str) -> list[ToolAdapter]:
        wanted = str(capability or "").strip().casefold()
        if not wanted:
            return []
        tokens = {token for token in re.findall(r"[a-z0-9]+", wanted) if len(token) > 1}
        matches: list[ToolAdapter] = []
        for adapter in self.all():
            haystack = " ".join((
                adapter.metadata().name, adapter.metadata().category,
                adapter.metadata().description, *adapter.required_permissions(),
            )).casefold()
            haystack_tokens = set(re.findall(r"[a-z0-9]+", haystack))
            if wanted in haystack or (tokens and tokens <= haystack_tokens):
                matches.append(adapter)
        return matches

    def find_by_device(self, device: str) -> list[ToolAdapter]:
        wanted = str(device or "").strip().casefold()
        return [adapter for adapter in self.all()
                if wanted in {item.casefold() for item in adapter.supported_devices()}]

    def list_available(self) -> list[dict[str, Any]]:
        return [self._describe(adapter) for adapter in self.all() if adapter.health().usable]

    def list_degraded(self) -> list[dict[str, Any]]:
        return [self._describe(adapter) for adapter in self.all() if not adapter.health().usable]

    def health(self) -> dict[str, Any]:
        states: dict[str, int] = {}
        permission_states: dict[str, int] = {}
        adapters = self.all()
        available = 0
        for adapter in adapters:
            current = adapter.health()
            states[current.state] = states.get(current.state, 0) + 1
            permission_states[current.permission_state] = (
                permission_states.get(current.permission_state, 0) + 1)
            available += int(current.usable)
        return {
            "state": "ONLINE",
            "registered": len(adapters),
            "by_state": states,
            "by_permission": permission_states,
            "available": available,
            "execution_authority": "reyes_agent.tools.run_tool",
            "duplicate_runtime": False,
        }

    def resolve_best_tool(self, goal: str, context: dict[str, Any] | None = None
                          ) -> dict[str, Any] | None:
        context = dict(context or {})
        capability = str(context.get("capability") or goal or "")
        candidates = self.find_by_capability(capability)
        device = str(context.get("device") or "")
        if device:
            candidates = [item for item in candidates
                          if device.casefold() in {d.casefold() for d in item.supported_devices()}]
        ranked: list[tuple[float, ToolAdapter, list[str]]] = []
        from reyes_agent import tool_reputation
        for adapter in candidates:
            health = adapter.health()
            if not health.usable:
                continue
            meta = adapter.metadata()
            reputation = tool_reputation.get_reputation().reputation(meta.name)
            score = 50.0
            reasons = ["healthy and permitted"]
            if health.permission_state == "enabled":
                score += 15.0
                reasons.append("permission enabled")
            if meta.requires_confirmation:
                score -= 5.0
                reasons.append("confirmation required")
            if not meta.requires_network:
                score += 8.0
                reasons.append("local/private")
            score += float(reputation.get("confidence") or 0) * 20.0
            latency = float(reputation.get("median_latency_ms") or 0)
            if latency:
                score -= min(10.0, latency / 1000.0)
                reasons.append(f"observed median {latency:.1f}ms")
            ranked.append((score, adapter, reasons))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1].metadata().name))
        score, adapter, reasons = ranked[0]
        return {
            "tool": self._describe(adapter),
            "score": round(score, 3),
            "reasons": reasons,
            "candidates_considered": len(ranked),
        }

    @staticmethod
    def _describe(adapter: ToolAdapter) -> dict[str, Any]:
        return {"metadata": adapter.metadata().as_dict(), "health": adapter.health().as_dict()}


_registry: GlobalToolRegistry | None = None
_registry_lock = threading.Lock()


def get_global_tool_registry() -> GlobalToolRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = GlobalToolRegistry()
    return _registry


def contract_status() -> dict[str, Any]:
    required = ("metadata", "health", "validate", "execute", "cancel",
                "required_permissions", "supported_devices")
    registry = get_global_tool_registry()
    failures: list[str] = []
    for adapter in registry.all():
        if not all(callable(getattr(adapter, name, None)) for name in required):
            failures.append(adapter.metadata().tool_id)
    return {
        "state": "READY" if not failures else "DEGRADED",
        "checked": len(registry.all()),
        "contract_failures": failures,
        "methods": list(required),
        "signature": str(inspect.signature(ToolAdapter.execute)),
    }
