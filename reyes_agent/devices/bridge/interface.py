from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeStatus:
    name: str
    state: str
    paired: bool
    capabilities: tuple[str, ...] = ()
