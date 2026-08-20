"""Publish the current tunnel URL so the Netlify launcher finds it itself.

WHY
---
A free Cloudflare quick tunnel hands out a new address every restart. The
owner should still only ever need `https://zenoai321.netlify.app`. So the PC
PUBLISHES its current address to a rendezvous, and the launcher READS it.

WHERE
-----
A tiny Netlify Function on the SAME site (`/api/endpoint`), backed by Netlify
Blobs. Same-origin, so the launcher fetches it with no CORS and no third
party. Writes are authenticated with a shared secret only the owner's PC
holds; reads are public (the tunnel URL is not a secret -- the login behind it
is the gate).

SAFETY
------
The secret stops a stranger repointing the launcher at a phishing page. As a
second layer, the launcher only accepts a URL that matches the expected tunnel
shape, so even a compromised rendezvous cannot send the owner to an arbitrary
site. This module never logs the secret.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _entry() -> str:
    return (os.environ.get("ZENO_ANYWHERE_ENTRY", "").strip()
            or "https://zenoai321.netlify.app").rstrip("/")


def _secret() -> str:
    """The write secret. Keyring first, environment second. Never a literal."""
    try:
        from reyes_agent.security.secrets import manager

        value = manager.get("ZENO_ANYWHERE_SECRET")
        if value:
            return value
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("ZENO_ANYWHERE_SECRET", "").strip()


def configured() -> bool:
    return bool(_secret())


def publish(url: str, *, timeout: float = 12.0) -> tuple[bool, str]:
    """POST the current URL to the rendezvous. No secret -> quietly skip
    (the local file still carries the URL for manual paste)."""
    secret = _secret()
    if not secret:
        return False, "no ZENO_ANYWHERE_SECRET set; rendezvous skipped"
    body = json.dumps({"url": url}).encode()
    request = urllib.request.Request(
        _entry() + "/api/endpoint", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {secret}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:150]


def clear(*, timeout: float = 12.0) -> tuple[bool, str]:
    """Remove the published address during an orderly supervisor shutdown."""
    secret = _secret()
    if not secret:
        return False, "no ZENO_ANYWHERE_SECRET set; rendezvous skipped"
    request = urllib.request.Request(
        _entry() + "/api/endpoint", data=b"", method="DELETE",
        headers={"Authorization": f"Bearer {secret}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:150]


def current() -> str:
    """Read back what the rendezvous is serving (for diagnostics)."""
    try:
        with urllib.request.urlopen(_entry() + "/api/endpoint", timeout=10) as resp:
            data: dict[str, Any] = json.loads(resp.read() or b"{}")
            return str(data.get("url", ""))
    except Exception:  # noqa: BLE001
        return ""
