"""One local device manager; multi-device is an interface, not a daemon."""

from __future__ import annotations

import threading

from reyes_agent.devices import health as device_health
from reyes_agent.devices.android_device import AndroidDevice
from reyes_agent.devices.base_device import BaseDevice
from reyes_agent.devices.protocol import DeviceRequest, DeviceResponse
from reyes_agent.devices.windows_device import WindowsDevice


class DeviceManager:
    def __init__(self) -> None:
        local = WindowsDevice()
        self._devices: dict[str, BaseDevice] = {local.id: local}
        self._locks: dict[str, threading.Lock] = {local.id: threading.Lock()}

    def devices(self) -> list[str]:
        return sorted({*self._devices, *(item["device_id"] for item in
                        self.android_devices())})

    @staticmethod
    def android_devices() -> list[dict]:
        try:
            from reyes_agent.remote_access.device_link import get_link

            return [item for item in get_link().devices()
                    if str(item.get("platform", "")).casefold() == "android"]
        except Exception:
            return []

    def _resolve(self, device_id: str) -> BaseDevice | None:
        existing = self._devices.get(device_id)
        if existing is not None:
            return existing
        if any(item.get("device_id") == device_id for item in self.android_devices()):
            device = AndroidDevice(device_id)
            self._devices.setdefault(device_id, device)
            self._locks.setdefault(device_id, threading.Lock())
            return self._devices[device_id]
        return None

    def execute(self, request: DeviceRequest, *, device_id: str = "local-windows") -> DeviceResponse:
        device = self._resolve(device_id)
        if device is None:
            return DeviceResponse(False, device_id, request.request_id, "Unknown device",
                                  error=f"No device '{device_id}' is registered.")
        # Two foreground plans cannot safely drive the same device at once.
        # The lock is per-device and bounded.
        lock = self._locks.setdefault(device_id, threading.Lock())
        if not lock.acquire(timeout=2.0):
            return DeviceResponse(False, device_id, request.request_id, "Device is busy",
                                  error="Another foreground task owns this device.")
        try:
            return device.execute(request)
        finally:
            lock.release()

    def observe(self, device_id: str = "local-windows") -> dict:
        device = self._resolve(device_id)
        return device.observe() if device else {"ok": False, "error": "unknown device"}

    def health(self) -> dict:
        for descriptor in self.android_devices():
            self._resolve(str(descriptor["device_id"]))
        return device_health.summarize([device.health() for device in self._devices.values()])

    def shutdown(self) -> None:
        for device in self._devices.values():
            try:
                device.shutdown()
            except Exception:
                pass


_manager: DeviceManager | None = None
_lock = threading.Lock()


def get_device_manager() -> DeviceManager:
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = DeviceManager()
    return _manager
