"""The gateway that puts ZENO online without opening a port on the PC.

HOW IT WORKS, AND WHY IT IS SAFE
--------------------------------
cloudflared dials OUT from this machine to Cloudflare and holds the
connection. Cloudflare gives back a public HTTPS URL and forwards requests
down that outbound connection to ZENO's LOCAL server. The Windows machine
never listens on a public port; there is nothing to port-scan.

The important part is what a request coming down the tunnel can reach. Every
tunneled request carries `cf-connecting-ip`, so `remote_access.boundary`
classifies it as REMOTE and applies the fail-closed allow-list -- the phone
surface and the owner web app (which is behind OwnerAuthService), and nothing
else. The full desktop API is not reachable through the tunnel even though the
tunnel points at the same server. The boundary is the guard; the tunnel is
only the pipe.

TWO MODES
---------
* quick   -- `cloudflared tunnel --url http://localhost:PORT`. No account, a
             throwaway *.trycloudflare.com URL, up in seconds. For "let me
             reach ZENO from my phone right now".
* named   -- a persistent tunnel bound to the owner's own domain, configured
             through ZENO_CLOUDFLARE_TUNNEL_CONFIG. For a stable address.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_QUICK_TIMEOUT_S = 30.0


@dataclass
class GatewayState:
    running: bool = False
    mode: str = ""
    url: str = ""
    port: int = 0
    error: str = ""
    started_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"running": self.running, "mode": self.mode, "url": self.url,
                "port": self.port, "error": self.error,
                "uptime_s": round(time.time() - self.started_at, 1) if self.running else 0}


class Gateway:
    """Owns the cloudflared process and the public URL it produced."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._state = GatewayState()
        self._reader: threading.Thread | None = None

    # ---- lifecycle ------------------------------------------------------
    def cloudflared(self) -> str:
        return os.environ.get("ZENO_CLOUDFLARED_PATH", "cloudflared")

    def available(self) -> bool:
        try:
            subprocess.run([self.cloudflared(), "--version"],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except Exception:  # noqa: BLE001
            return False

    def start(self, *, port: int | None = None, mode: str = "quick") -> GatewayState:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return self._state          # already up
            if not self.available():
                self._state = GatewayState(
                    error="cloudflared is not installed or not on PATH. "
                          "Install it, or set ZENO_CLOUDFLARED_PATH.")
                return self._state

            port = int(port or config.PHONE_COMPANION_PORT)
            if mode == "named":
                return self._start_named(port)
            return self._start_quick(port)

    def _start_quick(self, port: int) -> GatewayState:
        try:
            proc = subprocess.Popen(
                [self.cloudflared(), "tunnel", "--url", f"http://localhost:{port}",
                 "--no-autoupdate"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self._state = GatewayState(error=str(exc))
            return self._state

        self._proc = proc
        self._state = GatewayState(running=True, mode="quick", port=port,
                                   started_at=time.time())
        # cloudflared prints the URL to stdout within a few seconds. Read in a
        # thread so start() can wait briefly for the URL without blocking on
        # the whole process lifetime.
        found = threading.Event()

        def read_output() -> None:
            # No self._lock here, deliberately. start() holds that lock across
            # found.wait() below, so taking it here would deadlock: the reader
            # would block on the lock, never set `found`, and every quick
            # tunnel would "time out" after 30s despite cloudflared printing
            # the URL immediately. The `found` Event is the synchronisation --
            # it gives the happens-before for the single url write/read.
            assert proc.stdout is not None
            for line in proc.stdout:
                match = _URL_RE.search(line)
                if match and not self._state.url:
                    self._state.url = match.group(0)
                    found.set()
                    break
                if proc.poll() is not None:
                    break

        self._reader = threading.Thread(target=read_output, daemon=True)
        self._reader.start()

        found.wait(timeout=_QUICK_TIMEOUT_S)
        if not self._state.url:
            # No URL means it never came up. Do not report a running gateway
            # with no address -- that is the "it said it worked" failure.
            self.stop()
            self._state = GatewayState(
                error=f"cloudflared did not produce a URL within {_QUICK_TIMEOUT_S:.0f}s")
        return self._state

    def _start_named(self, port: int) -> GatewayState:
        config_path = os.environ.get("ZENO_CLOUDFLARE_TUNNEL_CONFIG", "")
        if not config_path or not Path(config_path).is_file():
            self._state = GatewayState(
                error="named mode needs ZENO_CLOUDFLARE_TUNNEL_CONFIG pointing at a "
                      "cloudflared config file. Use quick mode for no-setup access.")
            return self._state
        host = os.environ.get("ZENO_PHONE_PUBLIC_HOST", "")
        try:
            self._proc = subprocess.Popen(
                [self.cloudflared(), "tunnel", "--config", config_path, "run"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self._state = GatewayState(error=str(exc))
            return self._state
        self._state = GatewayState(running=True, mode="named", port=port,
                                   url=f"https://{host}" if host else "",
                                   started_at=time.time())
        return self._state

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            self._state.running = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is not None:
                self._state.running = False
            return self._state.as_dict()


_gateway: Gateway | None = None
_gateway_lock = threading.Lock()


def get_gateway() -> Gateway:
    global _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = Gateway()
        return _gateway


def reset_for_tests() -> Gateway:
    global _gateway
    with _gateway_lock:
        if _gateway is not None:
            _gateway.stop()
        _gateway = Gateway()
        return _gateway


# --- CLI: one command to go live ----------------------------------------
def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Put ZENO online through a Cloudflare tunnel (no open ports).")
    parser.add_argument("--port", type=int, default=config.PHONE_COMPANION_PORT,
                        help="Local ZENO port to expose (default: phone companion port).")
    parser.add_argument("--named", action="store_true",
                        help="Use the configured named tunnel instead of a quick one.")
    args = parser.parse_args()

    gateway = get_gateway()
    print(f"Starting the ZENO gateway on local port {args.port} ...", flush=True)
    state = gateway.start(port=args.port, mode="named" if args.named else "quick")

    if state.error:
        print(f"\nCould not start: {state.error}")
        return 1
    print("\n" + "=" * 60)
    print("  ZENO IS ONLINE")
    print("=" * 60)
    print(f"  Open this from any device:  {state.url}/app")
    print("  Nothing on this PC is exposed except through Cloudflare, and only")
    print("  the owner web app and phone surface are reachable -- log in first.")
    print("=" * 60)
    print("\nLeave this running. Ctrl+C to take ZENO offline.\n")
    try:
        while gateway.status().get("running"):
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nTaking ZENO offline ...")
    finally:
        gateway.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
