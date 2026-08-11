"""Private-network peer allowlist. Connectivity is not authorization."""
from __future__ import annotations

import os


def configured_peer_ids() -> frozenset[str]:
    return frozenset(
        item.strip().casefold()
        for item in os.environ.get("ZENO_PRIVATE_PEER_ALLOWLIST", "").split(",")
        if item.strip()
    )


def authorize(peer: dict) -> tuple[bool, str]:
    allowed = configured_peer_ids()
    candidates = {
        str(peer.get("id", "")).casefold(),
        str(peer.get("dns_name", "")).rstrip(".").casefold(),
        str(peer.get("host_name", "")).casefold(),
    } - {""}
    if not allowed:
        return False, "no private peer allowlist is configured"
    if candidates & allowed:
        return True, "peer appears in the explicit owner allowlist"
    return False, "connected peer is not authorized for ZENO services"
