"""Local Windows adapter over Claude's Phase 1 hybrid controller."""

from __future__ import annotations

import time

from reyes_agent.devices.base_device import BaseDevice
from reyes_agent.devices.capabilities import Capability, DeviceType
from reyes_agent.devices.protocol import DeviceRequest, DeviceResponse
from reyes_agent.memory.privacy import redact


class WindowsDevice(BaseDevice):
    id = "local-windows"
    type = DeviceType.WINDOWS_PC
    capabilities = frozenset({
        Capability.OBSERVE_SCREEN, Capability.ACCESSIBILITY,
        Capability.GUI_INPUT, Capability.NATIVE_APP_CONTROL,
        Capability.FILESYSTEM, Capability.SHELL, Capability.BROWSER,
    })

    def execute(self, request: DeviceRequest) -> DeviceResponse:
        started = time.perf_counter()
        try:
            # Lazy import: UIA/vision/browser dependencies stay out of startup.
            from reyes_agent.computer import controller

            result = controller.run(request.goal, request.plan or None, approved=request.approved)
            return DeviceResponse(
                ok=bool(result.ok), device_id=self.id, request_id=request.request_id,
                summary=str(result.summary), evidence={"path": result.path, **dict(result.detail)},
                error="" if result.ok else str(result.summary),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except Exception as exc:
            return DeviceResponse(False, self.id, request.request_id, "Windows action did not run",
                                  error=f"{type(exc).__name__}: {redact(exc, limit=300)}",
                                  duration_ms=round((time.perf_counter() - started) * 1000, 1))

    def observe(self) -> dict:
        try:
            from reyes_agent.computer import controller

            return {"ok": True, "summary": controller.observe()}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {redact(exc, limit=300)}"}

    def health(self) -> dict:
        try:
            from reyes_agent.computer import controller

            state = controller.status()
            return {"device_id": self.id, "type": self.type.value, "state": "ONLINE",
                    "capabilities": sorted(item.value for item in self.capabilities), "detail": state}
        except Exception as exc:
            return {"device_id": self.id, "type": self.type.value, "state": "DEGRADED",
                    "capabilities": sorted(item.value for item in self.capabilities),
                    "error": f"{type(exc).__name__}: {redact(exc, limit=300)}"}
