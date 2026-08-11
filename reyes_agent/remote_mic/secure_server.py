"""A second, TLS listener for the phone -- so the microphone page can work.

WHY A SECOND PORT AND NOT A CHANGE TO THE MAIN SERVER
-----------------------------------------------------
ZENO's desktop server binds plain HTTP on loopback, which is right: nothing
on this machine needs TLS to talk to itself, and a certificate would only
add a moving part. The phone is the exception -- it is a different device on
a different address, and browsers will not give a web page the microphone
unless the page arrived over HTTPS.

So this runs the SAME FastAPI application on a second port with a
certificate. No proxy, no signalling to forward, no second implementation of
anything. If it fails to start, the desktop server is untouched and ZENO
carries on exactly as before.

WHAT GOES OVER IT, AND WHAT DOES NOT
------------------------------------
Only the signalling: the page itself and the WebRTC offer/answer. The AUDIO
never travels through this listener -- WebRTC negotiates a direct peer
connection between phone and PC, so the voice path is not proxied and does
not inherit this port's latency.

BINDING BEYOND LOOPBACK
-----------------------
This is the one listener that must accept a connection from another device,
so it binds the LAN address rather than 127.0.0.1. That is a deliberate
widening and it is why the page behind it is the microphone page and not the
dashboard -- and why an unpaired device still gets nothing.
"""

from __future__ import annotations

import socket as _socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.remote_mic import pairing

_lock = threading.RLock()
_server: Any = None
_thread: threading.Thread | None = None
_state: dict[str, Any] = {"running": False, "url": "", "error": "", "since": 0.0}


@dataclass
class Started:
    ok: bool = False
    url: str = ""
    transport: str = ""
    reason: str = ""
    steps: list[str] = field(default_factory=list)
    qr_png: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "url": self.url, "transport": self.transport,
                "reason": self.reason, "steps": self.steps, "qr_png": self.qr_png}


def running() -> bool:
    with _lock:
        return bool(_state["running"])


def start(*, token: str = "", prefer: str = "", port: int = 0) -> Started:
    """Bring up the TLS listener and return everything the phone needs."""
    link = pairing.build(token=token, prefer=prefer,
                         port=port or pairing.TLS_PORT)
    if not link.ok:
        return Started(reason=link.reason)
    if not (link.cert and link.key):
        return Started(reason="no certificate is available for that transport")

    with _lock:
        if _state["running"]:
            return Started(True, _state["url"], link.transport,
                           "already listening", link.steps, link.qr_png)

    # Refuse to start on a port somebody else already holds. Probing the port
    # AFTER launching cannot tell a healthy new listener from a stale one left
    # behind by an earlier run -- and a stale listener accepts the connection
    # and then closes it, which reads as a TLS failure and sends you hunting
    # for a certificate problem that does not exist. Ask first.
    probe = _socket.socket()
    probe.settimeout(0.5)
    in_use = probe.connect_ex(("127.0.0.1", link.port)) == 0
    probe.close()
    if in_use:
        return Started(reason=(
            f"port {link.port} is already in use. If an earlier phone-mic "
            "listener is still running, stop it first -- I will not assume a "
            "socket somebody else owns is mine."))

    # A CHILD PROCESS, not a thread. `desktop_app.py` already learned this the
    # hard way and says so: uvicorn in a background thread on Windows binds
    # the port and then hangs on real requests -- the socket accepts and the
    # connection closes with no response, which is exactly what happened when
    # this module first used a thread. A child process runs uvicorn in ITS
    # main thread, which is the path already proven here.
    runner = (
        "import uvicorn;"
        "from reyes_agent.web import app;"
        f"uvicorn.run(app, host='0.0.0.0', port={link.port}, log_level='warning',"
        f" access_log=False, ssl_certfile=r'{link.cert}', ssl_keyfile=r'{link.key}')"
    )
    try:
        from reyes_agent import config

        process = subprocess.Popen(
            [sys.executable, "-c", runner],
            cwd=str(config.PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        return Started(reason=f"could not start the TLS listener: "
                              f"{type(exc).__name__}: {exc}")

    # Wait for the port to actually accept. "Started" without a listening
    # socket is the same lie as a render that produced no file.
    deadline = time.time() + 25
    listening = False
    while time.time() < deadline:
        if process.poll() is not None:
            error = (process.stderr.read() or b"").decode("utf-8", "replace")[-400:]
            return Started(reason=f"the TLS listener exited: {error.strip() or 'no output'}")
        probe = _socket.socket()
        probe.settimeout(0.4)
        if probe.connect_ex(("127.0.0.1", link.port)) == 0:
            probe.close()
            listening = True
            break
        probe.close()
        time.sleep(0.3)

    if not listening:
        process.terminate()
        return Started(reason=f"the TLS listener did not bind port {link.port} in time")

    global _server, _thread
    with _lock:
        _server, _thread = process, None
        _state.update({"running": True, "url": link.url, "error": "",
                       "since": time.time()})

    return Started(True, link.url, link.transport,
                   "listening; scan the code with your phone",
                   link.steps, link.qr_png)


def stop() -> bool:
    global _server, _thread
    with _lock:
        server, thread = _server, _thread
        _server = _thread = None
        _state.update({"running": False, "url": ""})
    if server is None:
        return False
    try:
        server.terminate()
        server.wait(timeout=10)
    except Exception:  # noqa: BLE001
        try:
            server.kill()
        except Exception:  # noqa: BLE001
            pass
    return True


def status() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    link = pairing.build()
    return {
        "state": "ONLINE" if snapshot["running"] else "STANDBY",
        **snapshot,
        "transport": link.transport,
        "would_use": link.url,
        "audio_path": ("WebRTC peer-to-peer -- the voice does not travel through "
                       "this listener"),
        "scope": "serves the microphone page and its signalling only",
    }
