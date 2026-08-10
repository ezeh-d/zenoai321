"""Agent-facing local device manager tools."""

from __future__ import annotations

import json

from reyes_agent.devices import get_device_manager
from reyes_agent.devices.protocol import DeviceRequest
from reyes_agent.tools import register


@register(name="device_status", description="Show real health and capabilities for registered devices.",
          input_schema={"type": "object", "properties": {}})
def device_status() -> str:
    return json.dumps(get_device_manager().health(), default=str)


@register(name="device_observe", description="Observe the current local Windows screen through accessibility/vision without acting.",
          input_schema={"type": "object", "properties": {"device_id": {"type": "string"}}})
def device_observe(device_id: str = "local-windows") -> str:
    return json.dumps(get_device_manager().observe(device_id), default=str)


@register(name="device_execute", description="Execute and verify a bounded plan on the local Windows device.",
          input_schema={"type": "object", "properties": {
              "goal": {"type": "string"}, "plan": {"type": "array", "items": {"type": "object"}},
              "device_id": {"type": "string"}}, "required": ["goal"]},
          requires_confirmation=True)
def device_execute(goal: str, plan: list[dict] | None = None,
                   device_id: str = "local-windows") -> str:
    response = get_device_manager().execute(DeviceRequest(goal=goal, plan=plan or [], approved=True),
                                            device_id=device_id)
    return json.dumps(response.as_dict(), default=str)
