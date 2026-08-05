"""Bounded controller for the owner-configured Cloudflare Tunnel connector."""
from __future__ import annotations
import os, subprocess, threading, time
from pathlib import Path
from typing import Any

class CloudflareTunnel:
    def __init__(self) -> None:
        self._lock = threading.RLock(); self._process: subprocess.Popen | None = None
        self._attempts = 0; self._last_error = ""; self._next_retry = 0.0
    def configured(self) -> bool:
        return bool(os.environ.get("ZENO_PHONE_PUBLIC_HOST") and os.environ.get("ZENO_CLOUDFLARE_TUNNEL_CONFIG"))
    def start(self) -> bool:
        with self._lock:
            if not self.configured(): self._last_error = "Tunnel not configured"; return False
            if self._process and self._process.poll() is None: return True
            config = Path(os.environ["ZENO_CLOUDFLARE_TUNNEL_CONFIG"])
            if not config.is_file(): self._last_error = "Tunnel configuration file not found"; return False
            if self._attempts >= 3 and time.monotonic() < self._next_retry: return False
            try:
                self._process = subprocess.Popen([os.environ.get("ZENO_CLOUDFLARED_PATH", "cloudflared"), "tunnel", "--config", str(config), "run"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._attempts += 1; self._next_retry = time.monotonic() + min(60, 2 ** self._attempts); self._last_error = ""; return True
            except OSError as exc: self._last_error = str(exc); return False
    def stop(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None: self._process.terminate()
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"configured": self.configured(), "running": bool(self._process and self._process.poll() is None), "attempts": self._attempts, "error": self._last_error}
_tunnel: CloudflareTunnel | None = None
def get_cloudflare_tunnel() -> CloudflareTunnel:
    global _tunnel
    if _tunnel is None: _tunnel = CloudflareTunnel()
    return _tunnel
