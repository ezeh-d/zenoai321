"""Owner-confirmed tools for the optional native Android companion."""

from __future__ import annotations

import json

from reyes_agent.devices import get_device_manager
from reyes_agent.devices.protocol import DeviceRequest
from reyes_agent.remote_access.device_link import validate_android_action
from reyes_agent.tools import register


def _target(device_id: str) -> str:
    manager = get_device_manager()
    candidates = manager.android_devices()
    requested = str(device_id or "").strip()
    if requested:
        if not any(item.get("device_id") == requested for item in candidates):
            raise ValueError("That Android companion is not registered.")
        return requested
    online = [item for item in candidates if item.get("state") == "ONLINE"]
    if online:
        return str(online[0]["device_id"])
    if candidates:
        return str(candidates[0]["device_id"])
    raise ValueError("No Android companion is registered.")


@register(
    name="phone_device_status",
    description="Show real approval, connectivity and capability state for paired Android companions.",
    input_schema={"type": "object", "properties": {}},
)
def phone_device_status() -> str:
    return json.dumps(get_device_manager().android_devices(), default=str)


@register(
    name="phone_action",
    description=(
        "Perform one owner-confirmed basic action on a paired Android phone. "
        "Allowed operations: BACK, HOME, RECENTS, NOTIFICATIONS, QUICK_SETTINGS, "
        "SCROLL_UP, SCROLL_DOWN, OPEN_APP. OPEN_APP requires an Android package "
        "name such as com.android.chrome. Arbitrary taps, typing, messages, "
        "payments, deletion, settings and permissions are impossible."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": [
                "BACK", "HOME", "RECENTS", "NOTIFICATIONS", "QUICK_SETTINGS",
                "SCROLL_UP", "SCROLL_DOWN", "OPEN_APP"]},
            "target": {"type": "string"},
            "device_id": {"type": "string"},
        },
        "required": ["operation"],
    },
    requires_confirmation=True,
)
def phone_action(operation: str, target: str = "", device_id: str = "") -> str:
    canonical = validate_android_action({"operation": operation, "target": target})
    selected = _target(device_id)
    request = DeviceRequest(
        goal=f"Android {canonical['operation']}",
        plan=[canonical], approved=True,
    )
    response = get_device_manager().execute(request, device_id=selected)
    return json.dumps(response.as_dict(), default=str)
