"""Read-only peer projection used by diagnostics."""
from .manager import get_manager


def list_peers() -> list[dict]:
    return list(get_manager().status().get("peers", []))
