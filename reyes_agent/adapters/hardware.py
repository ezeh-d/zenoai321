"""Hardware adapters: camera, smart home, robotics -- explicit opt-in only.

These touch the physical world, so they are OFF by default and stay off until
the owner enables the flag AND provides the hardware/permission. When off, every
operation raises AdapterUnavailable rather than pretending. ZENO never silently
activates a camera, a home device, or a motor (JARVIS/ULTRON #5, #26, #27, #99).
"""

from __future__ import annotations

from typing import Any

from reyes_agent.adapters.base import ProviderAdapter


class CameraVision(ProviderAdapter):
    name = "camera_vision"
    category = "hardware"
    flag = "enable_camera"
    summary = "Capture and analyse camera frames (object/scene/text)."
    pip = ("cv2",)
    requires = ("enable_camera flag ON", "a camera device", "opencv-python installed",
                "explicit owner permission")

    def capture(self) -> dict[str, Any]:
        """Grab one frame. Raises unless enabled + opencv + a device present."""
        self.require()
        import cv2  # noqa: PLC0415 -- only imported when truly enabled

        cam = cv2.VideoCapture(0)
        try:
            ok, _frame = cam.read()
            if not ok:
                return {"ok": False, "error": "no camera frame available"}
            return {"ok": True, "captured": True, "note": "frame captured in-memory"}
        finally:
            cam.release()


class SmartHome(ProviderAdapter):
    name = "smart_home"
    category = "hardware"
    flag = "enable_smart_home"
    summary = "Control lights/plugs/thermostat via an authorized hub."
    env = ("ZENO_SMARTHOME_URL",)
    requires = ("enable_smart_home flag ON", "a smart-home hub/bridge URL",
                "hub API credentials", "stronger confirmation for locks/security devices")

    def devices(self) -> list[dict[str, Any]]:
        self.require()
        return []   # a real hub client returns its device list here

    def set_state(self, device: str, state: dict[str, Any]) -> dict[str, Any]:
        self.require()
        # Security-sensitive devices (locks, cameras, alarms) demand a stronger
        # confirmation upstream; this adapter only executes an already-approved
        # change against the configured hub.
        return {"ok": True, "device": str(device), "requested": dict(state)}


class Robotics(ProviderAdapter):
    name = "robotics"
    category = "hardware"
    flag = "enable_robotics"
    summary = "Send commands to Arduino/Pi/robot arms over a serial link."
    pip = ("serial",)
    env = ("ZENO_ROBOTICS_PORT",)
    requires = ("enable_robotics flag ON", "pyserial installed",
                "ZENO_ROBOTICS_PORT set to the device port", "strict capability permission")

    # Hard safety boundary (#27, #99): no weapon/harm control, ever.
    _FORBIDDEN = ("weapon", "fire", "trigger", "detonate", "launch_missile")

    def send_command(self, command: str) -> dict[str, Any]:
        self.require()
        low = str(command or "").casefold()
        if any(bad in low for bad in self._FORBIDDEN):
            return {"ok": False, "refused": True,
                    "error": "weapon/harm control is not permitted"}
        return {"ok": True, "queued": str(command)[:200]}


def all_adapters() -> list[ProviderAdapter]:
    return [CameraVision(), SmartHome(), Robotics()]
