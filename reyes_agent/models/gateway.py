"""Capability-aware facade over ZENO's existing measured model router."""
from __future__ import annotations

import importlib.util
import threading
from dataclasses import dataclass
from typing import Any

from reyes_agent import model_router
from reyes_agent.models.capability_registry import CAPABILITIES, supports


@dataclass(frozen=True)
class Route:
    provider: str
    kind: str
    required: tuple[str, ...]
    fallback_chain: tuple[str, ...]
    reason: str


class ModelGateway:
    """Selects providers; provider.py remains the only execution seam."""

    def select(self, kind: str = "general", required: set[str] | None = None) -> Route:
        required = {item.upper() for item in (required or {"TEXT"})}
        chain = model_router.chain_for(kind)
        selected = next((name for name in chain if supports(name, required)), "")
        if not selected:
            routed = model_router.route(kind)
            selected = routed["provider"]
            reason = f"no configured provider declares {sorted(required)}; using existing fallback"
        else:
            reason = "first healthy configured provider satisfying required capabilities"
        return Route(selected, kind, tuple(sorted(required)), tuple(chain), reason)

    def status(self) -> dict[str, Any]:
        data = model_router.explain()
        data.update({
            "gateway": "existing provider.py + measured model_router",
            "litellm_installed": importlib.util.find_spec("litellm") is not None,
            "capabilities": {key: sorted(value) for key, value in CAPABILITIES.items()},
            "duplicate_clients": False,
        })
        return data


_gateway: ModelGateway | None = None
_lock = threading.Lock()


def get_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        with _lock:
            if _gateway is None:
                _gateway = ModelGateway()
    return _gateway
