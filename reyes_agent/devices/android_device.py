"""Remote Android adapter over the existing durable DeviceLink queue."""

from __future__ import annotations

import time
from typing import Any

from reyes_agent.devices.base_device import BaseDevice
from reyes_agent.devices.capabilities import Capability, DeviceType
from reyes_agent.devices.protocol import DeviceRequest, DeviceResponse
from reyes_agent.remote_access import device_link


TERMINAL = frozenset({
    device_link.DONE, device_link.FAILED, device_link.CANCELLED,
    device_link.EXPIRED, device_link.TIMEOUT, device_link.REJECTED,
})


class AndroidDevice(BaseDevice):
    type = DeviceType.ANDROID
    capabilities = frozenset({
        Capability.ACCESSIBILITY, Capability.GUI_INPUT,
        Capability.NATIVE_APP_CONTROL,
    })

    def __init__(self, device_id: str) -> None:
        self.id = str(device_id)

    def execute(self, request: DeviceRequest) -> DeviceResponse:
        started = time.perf_counter()
        if not request.approved:
            return DeviceResponse(
                False, self.id, request.request_id, "Phone action needs owner confirmation",
                error="The ZENO permission gate did not supply approval evidence.")
        if len(request.plan) != 1 or not isinstance(request.plan[0], dict):
            return DeviceResponse(
                False, self.id, request.request_id, "Phone action was not queued",
                error="Exactly one bounded Android action is required.")
        try:
            canonical = device_link.validate_android_action(request.plan[0])
            link = device_link.get_link()
            state = link.device_state(self.id)
            if state.get("platform") != "android":
                raise ValueError("Target is not a registered Android companion.")
            if state.get("state") != device_link.ONLINE:
                return DeviceResponse(
                    False, self.id, request.request_id, "Android phone is offline",
                    evidence={"state": state.get("state", device_link.OFFLINE)},
                    error="Start the ZENO orb foreground service on the phone.")
            command = link.enqueue(
                self.id, "android_action",
                {**canonical, "summary": request.goal[:120]},
                category="STANDARD_DEVICE", requesting_device="zeno-core",
                requires_approval=False,
                idempotency_key=f"android:{request.request_id}", expires_in_s=60)
            deadline = time.monotonic() + 25.0
            while time.monotonic() < deadline:
                current = link.command(command.id)
                if current is None:
                    break
                if current.status in TERMINAL:
                    ok = current.status == device_link.DONE
                    return DeviceResponse(
                        ok, self.id, request.request_id,
                        str((current.result or {}).get("summary") or
                            ("Android confirmed the action." if ok else
                             "Android rejected or failed the action."))[:300],
                        evidence={"command_id": current.id, "state": current.status,
                                  "device_result": current.result or {}},
                        error="" if ok else str((current.result or {}).get(
                            "error", current.status))[:300],
                        duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    )
                time.sleep(0.25)
            waiting = link.command(command.id) or command
            return DeviceResponse(
                False, self.id, request.request_id,
                "Phone action is still waiting for verified completion",
                evidence={"command_id": command.id, "state": waiting.status},
                error="ZENO did not receive Android completion evidence within 25 seconds.",
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except Exception as exc:  # noqa: BLE001 - stable tool boundary
            return DeviceResponse(
                False, self.id, request.request_id, "Phone action was not queued",
                error=f"{type(exc).__name__}: {str(exc)[:260]}",
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )

    def observe(self) -> dict[str, Any]:
        state = device_link.get_link().device_state(self.id)
        return {
            "ok": bool(state.get("known")),
            "summary": "Android screen contents are not streamed.",
            "device": state,
        }

    def health(self) -> dict[str, Any]:
        state = device_link.get_link().device_state(self.id)
        return {
            "device_id": self.id,
            "type": self.type.value,
            "state": state.get("state", device_link.OFFLINE),
            "capabilities": sorted(item.value for item in self.capabilities),
            "detail": {
                "label": state.get("label", "Android"),
                "approval_state": state.get("approval_state", "UNKNOWN"),
                "last_heartbeat": state.get("last_heartbeat", 0),
                "screen_streaming": False,
            },
        }
