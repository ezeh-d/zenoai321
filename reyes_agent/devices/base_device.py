"""Device interface; no transport or distributed runtime implied."""

from __future__ import annotations

from abc import ABC, abstractmethod

from reyes_agent.devices.capabilities import Capability, DeviceType
from reyes_agent.devices.protocol import DeviceRequest, DeviceResponse


class BaseDevice(ABC):
    id: str
    type: DeviceType
    capabilities: frozenset[Capability]

    @abstractmethod
    def execute(self, request: DeviceRequest) -> DeviceResponse: ...

    @abstractmethod
    def observe(self) -> dict: ...

    @abstractmethod
    def health(self) -> dict: ...

    def shutdown(self) -> None:
        return None
