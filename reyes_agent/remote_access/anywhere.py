"""ZENO Anywhere -- the supervisor that keeps ZENO reachable, on its own.

THE PROBLEM THIS SOLVES
-----------------------
A tunnel and a server started from a terminal die when the terminal closes.
ZENO Anywhere must outlive every terminal, IDE and dev session: as long as the
PC is on, online, and the feature is enabled, ZENO should be reachable.

WHAT IT DOES
------------
One long-lived supervisor, started by Windows at logon (Task Scheduler), owns
two child processes and nothing else:

  * the ZENO remote SERVER  -- uvicorn serving reyes_agent.web:app on 8768
  * the TUNNEL              -- cloudflared, dialing out to a public URL

It watches both, restarts either on crash with backoff, waits out internet
outages, publishes the current tunnel URL so the Netlify launcher can find it,
and writes a status file the CLI reads. It refuses to run twice (one lock),
and it never opens a port on the machine -- cloudflared dials out.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not weaken authentication, it does not expose new routes (the
fail-closed boundary still decides what a tunnelled request may reach), and it
does not touch ZENO's core AI. It is plumbing for reachability, nothing more.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

# Everything ZENO Anywhere writes lives here, away from the repo.
_HOME = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "anywhere"
STATUS_FILE = _HOME / "status.json"
LOG_FILE = _HOME / "anywhere.log"
PID_FILE = _HOME / "supervisor.pid"
STOP_FLAG = _HOME / "stop.flag"
URL_FILE = _HOME / "current_url.txt"
LOCK_FILE = _HOME / "supervisor.lock"

PORT = int(config.PHONE_COMPANION_PORT)

# Monitor cadence and recovery bounds. A restart STORM helps nobody, so a
# child that keeps dying backs off, and a child that has died too many times
# in a short window trips a breaker and waits a long cooldown before trying
# again rather than hammering forever.
CHECK_EVERY_S = 10.0
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
BREAKER_FAILURES = 6          # failures within the window...
BREAKER_WINDOW_S = 180.0      # ...that trips the breaker
BREAKER_COOLDOWN_S = 300.0    # ...for this long
URL_TIMEOUT_S = 90.0
PUBLISH_EVERY_S = 30.0
TUNNEL_READY_GRACE_S = 60.0
TUNNEL_FAILED_PROBES = 3


class _SingleInstance:
    """Process-wide supervisor lock, independent of a racy PID-file check."""

    def __init__(self, name: str = "Local\\ZENOAnywhereSupervisor",
                 lock_file: Path = LOCK_FILE) -> None:
        self._name = name
        self._lock_file = lock_file
        self._handle: int | None = None
        self._fd: int | None = None

    def acquire(self) -> bool:
        _HOME.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetLastError(0)
            handle = kernel32.CreateMutexW(None, False, self._name)
            if not handle:
                return False
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            self._handle = int(handle)
            return True
        try:
            self._fd = os.open(str(self._lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode("ascii"))
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            try:
                self._lock_file.unlink(missing_ok=True)
            except OSError:
                pass


def _now() -> float:
    return time.time()


def _log(event: str, **detail: Any) -> None:
    """Append one status line. NEVER called with a password, token or URL
    secret -- the tunnel URL is not a secret (the login behind it is the
    gate), but auth material must never reach this file."""
    _HOME.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": round(_now(), 1), "event": event, **detail})
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


# --- child processes -----------------------------------------------------
@dataclass
class Child:
    """One supervised subprocess, with its own restart bookkeeping."""

    name: str
    argv: list[str]
    proc: subprocess.Popen | None = None
    owned: bool = False               # did WE spawn it (vs adopt an existing)?
    restarts: int = 0
    backoff_s: float = 0.0
    next_try: float = 0.0
    recent_failures: list[float] = field(default_factory=list)
    breaker_until: float = 0.0
    last_error: str = ""

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self) -> bool:
        try:
            self.proc = subprocess.Popen(
                self.argv, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               | getattr(subprocess, "DETACHED_PROCESS", 0)))
            self.owned = True
            _log(f"{self.name}_started", pid=self.proc.pid, restart=self.restarts)
            return True
        except OSError as exc:
            self.last_error = str(exc)
            _log(f"{self.name}_spawn_failed", error=str(exc)[:200])
            return False

    def note_failure(self) -> None:
        """Record a death and decide the next-try time (backoff or breaker)."""
        now = _now()
        self.recent_failures = [t for t in self.recent_failures if now - t < BREAKER_WINDOW_S]
        self.recent_failures.append(now)
        if len(self.recent_failures) >= BREAKER_FAILURES:
            self.breaker_until = now + BREAKER_COOLDOWN_S
            self.recent_failures.clear()
            _log(f"{self.name}_breaker_open", cooldown_s=BREAKER_COOLDOWN_S)
            self.next_try = self.breaker_until
            return
        self.restarts += 1
        self.backoff_s = min(BACKOFF_MAX_S, BACKOFF_START_S * (2 ** min(self.restarts, 6)))
        self.next_try = now + self.backoff_s

    def may_try(self) -> bool:
        return _now() >= self.next_try

    def reap_failure(self) -> bool:
        """Notice one owned child exit exactly once and apply recovery policy."""
        if self.proc is None or not self.owned or self.proc.poll() is None:
            return False
        code = self.proc.returncode
        self.proc = None
        self.last_error = f"exited with code {code}"
        self.note_failure()
        _log(f"{self.name}_exited", code=code, next_try=self.next_try)
        return True

    def stop(self) -> None:
        if self.owned and self.alive():
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.proc = None


# --- health probes -------------------------------------------------------
def server_healthy(timeout: float = 4.0) -> bool:
    """Is the ZENO server actually answering on 8768 (not just a live port)?"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/app", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def port_listening(timeout: float = 2.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def tunnel_reachable(url: str, timeout: float = 8.0) -> bool:
    """Does the PUBLIC url actually reach ZENO? The end-to-end truth."""
    if not url:
        return False
    try:
        req = urllib.request.Request(url.rstrip("/") + "/app", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def tunnel_connection_healthy(log_path: Path) -> bool:
    """Does cloudflared's OWN log say it currently holds edge connections?

    The public-URL probe above is the end-to-end truth for an EXTERNAL client,
    but the supervisor runs ON the same machine, and many home routers cannot
    hairpin a request back to their own public address -- so that probe times
    out even while real phones connect fine. cloudflared's log is the reliable
    local signal: it records a 'Registered tunnel connection' per edge link and
    an 'Unregistered'/'Lost connection' when one drops. This reads the tail and
    reports whether the last connection event was a registration, not a loss.
    """
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-60:]
    except OSError:
        return False
    last_up = last_down = -1
    for i, line in enumerate(lines):
        low = line.lower()
        if "registered tunnel connection" in low:
            last_up = i
        if ("unregistered tunnel connection" in low or "lost connection with the edge" in low
                or "connection terminated" in low or "i/o timeout" in low
                or "failed to serve" in low):
            last_down = i
    return last_up >= 0 and last_up >= last_down


def internet_up(timeout: float = 4.0) -> bool:
    """Reach Cloudflare's resolver. Distinguishes 'we are offline' from 'the
    tunnel broke', so an outage waits instead of restart-storming."""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


# --- the supervisor ------------------------------------------------------
class Supervisor:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.started_at = _now()
        self.url = ""
        self.last_reconnect = 0.0
        self.last_publish = 0.0
        self.tunnel_verified = False
        self.tunnel_probe_failures = 0
        self.last_error = ""
        self._tunnel_log = _HOME / "cloudflared.log"
        self.server = Child("server", self._server_argv())
        self.tunnel = Child("tunnel", self._tunnel_argv())

    def _server_argv(self) -> list[str]:
        return [sys.executable, "-m", "uvicorn", "reyes_agent.web:app",
                "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"]

    def _tunnel_argv(self) -> list[str]:
        binary = os.environ.get("ZENO_CLOUDFLARED_PATH", "cloudflared")
        return [binary, "tunnel", "--url", f"http://localhost:{PORT}",
                "--no-autoupdate", "--logfile", str(self._tunnel_log),
                # Force IPv4 to Cloudflare's edge. The observed failure was
                # "lookup region1.v2.argotunnel.com: i/o timeout" -- cloudflared
                # timing out on IPv6 DNS for the edge, made worse by the WSL/
                # Docker virtual adapters on this host. IPv4 avoids that path.
                "--edge-ip-version", "4",
                # Keep retrying the edge rather than giving up on a blip.
                "--retries", "5"]

    # ---- server ----
    def ensure_server(self) -> None:
        self.server.reap_failure()
        if server_healthy():
            if self.server.proc is None:
                # Adopted an already-running server (e.g. the desktop app).
                _log("server_adopted")
            return
        if not self.server.owned and port_listening():
            # Something else holds the port but is not answering; leave it a
            # moment rather than fighting for the port.
            return
        if self.server.alive():
            return                       # spawned, still booting
        if not self.server.may_try():
            return
        _log("server_restart", restarts=self.server.restarts)
        if not self.server.spawn():
            self.server.note_failure()

    # ---- tunnel ----
    def _read_tunnel_url(self) -> str:
        try:
            text = self._tunnel_log.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        import re

        matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        return matches[-1] if matches else ""

    def ensure_tunnel(self) -> None:
        if self.tunnel.reap_failure():
            # Never retain a verified/public address after its owning process
            # exited.  The rendezvous TTL will remove the last published value
            # while recovery backoff runs.
            self.url = ""
            self.tunnel_verified = False
            self.tunnel_probe_failures = 0
        if self.tunnel.alive():
            # Process up; make sure we have learned its URL.
            if not self.url:
                self.url = self._read_tunnel_url()
                if self.url:
                    self.last_reconnect = _now()
                    self.tunnel_verified = False
                    self.tunnel_probe_failures = 0
                    _log("tunnel_announced", url=self.url)
            elif (self.tunnel_verified and
                  _now() - self.last_publish >= PUBLISH_EVERY_S):
                # A quick-tunnel address must expire when the PC disappears.
                # Refresh the rendezvous while the complete chain is alive.
                self._publish(self.url)
            return
        if not self.tunnel.may_try():
            return
        # A fresh tunnel means a fresh URL: clear the old log so the reader
        # cannot pick up a stale address from a previous run.
        try:
            self._tunnel_log.unlink(missing_ok=True)
        except OSError:
            pass
        self.url = ""
        self.tunnel_verified = False
        self.tunnel_probe_failures = 0
        _log("tunnel_restart", restarts=self.tunnel.restarts)
        if not self.tunnel.spawn():
            self.tunnel.note_failure()
            return
        # Wait briefly for the URL to appear in the log.
        deadline = _now() + URL_TIMEOUT_S
        while _now() < deadline and self.tunnel.alive():
            url = self._read_tunnel_url()
            if url:
                self.url = url
                self.last_reconnect = _now()
                self.tunnel_verified = False
                self.tunnel_probe_failures = 0
                _log("tunnel_announced", url=url)
                return
            time.sleep(1.0)
        if not self.url:
            self.last_error = "tunnel produced no URL"
            self.tunnel.stop()
            self.tunnel.note_failure()
            _log("tunnel_no_url")

    def _publish(self, url: str) -> None:
        """Make the current URL findable: a local file always, and the
        rendezvous the Netlify launcher reads if one is configured."""
        try:
            URL_FILE.write_text(url, encoding="utf-8")
        except OSError:
            pass
        try:
            from reyes_agent.remote_access import rendezvous

            if not rendezvous.configured():
                self.last_publish = _now()
                return
            ok, detail = rendezvous.publish(url)
            if ok:
                self.last_publish = _now()
            else:
                _log("rendezvous_publish_failed", error=detail[:150])
        except Exception as exc:  # noqa: BLE001
            _log("rendezvous_publish_failed", error=str(exc)[:150])

    def verify_public_path(self, *, local_server_ok: bool) -> None:
        """Verify the whole public path without misclassifying local restarts."""
        if not local_server_ok:
            # A public probe cannot succeed while our own server is down.  Do
            # not blame/recycle a healthy tunnel for a local child restart;
            # verify it again after the server has recovered.
            self.tunnel_verified = False
            self.tunnel_probe_failures = 0
            return
        if (not self.tunnel.alive() or not self.url or
                _now() - self.last_reconnect < TUNNEL_READY_GRACE_S):
            return
        if tunnel_reachable(self.url):
            self.tunnel_probe_failures = 0
            if not self.tunnel_verified:
                self.tunnel_verified = True
                self._publish(self.url)
                _log("tunnel_online", url=self.url)
            return
        # HAIRPIN GUARD. The public probe just failed -- but on a router that
        # cannot hairpin, it fails even while real phones connect. If
        # cloudflared's own log says it still holds edge connections, believe
        # the log: keep the tunnel, keep publishing, and do NOT count this
        # toward a recycle. Otherwise a working tunnel would be torn down every
        # cycle and the owner's URL would churn endlessly.
        if tunnel_connection_healthy(self._tunnel_log):
            self.tunnel_probe_failures = 0
            if not self.tunnel_verified:
                self.tunnel_verified = True
                self._publish(self.url)
                _log("tunnel_online_via_log", url=self.url)
            return
        self.tunnel_verified = False
        self.tunnel_probe_failures += 1
        _log("tunnel_probe_failed", url=self.url,
             failures=self.tunnel_probe_failures)
        if self.tunnel_probe_failures >= TUNNEL_FAILED_PROBES:
            _log("tunnel_unreachable_recycling", url=self.url)
            self.tunnel.stop()
            self.tunnel.note_failure()
            self.url = ""
            self.tunnel_probe_failures = 0

    # ---- status ----
    def write_status(self) -> None:
        server_ok = server_healthy()
        tunnel_proc = self.tunnel.alive()
        online = server_ok and tunnel_proc and bool(self.url) and self.tunnel_verified
        status = {
            "state": "ONLINE" if online else "DEGRADED",
            "updated": round(_now(), 1),
            "server": {"ok": server_ok, "port": PORT, "owned": self.server.owned,
                       "restarts": self.server.restarts},
            "tunnel": {"ok": tunnel_proc and self.tunnel_verified, "url": self.url,
                       "process_running": tunnel_proc,
                       "verified": tunnel_proc and self.tunnel_verified,
                       "restarts": self.tunnel.restarts},
            "public_entry": _public_entry(),
            "uptime_s": round(_now() - self.started_at, 1),
            "last_reconnect": round(self.last_reconnect, 1) if self.last_reconnect else None,
            "last_error": self.last_error[:200],
            "internet": internet_up(),
            "pid": os.getpid(),
        }
        try:
            _HOME.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- main loop ----
    def run(self) -> int:
        instance = _SingleInstance()
        if not instance.acquire():
            _log("supervisor_duplicate_refused", pid=os.getpid())
            return 1
        _HOME.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        STOP_FLAG.unlink(missing_ok=True)
        _log("supervisor_started", pid=os.getpid(), port=PORT)

        try:
            while not self._stop.is_set():
                if STOP_FLAG.exists():
                    _log("stop_flag_seen")
                    break
                if not internet_up():
                    # Offline: do not thrash the tunnel. Wait it out.
                    self.last_error = "waiting for internet"
                    self.write_status()
                    self._stop.wait(CHECK_EVERY_S)
                    continue
                try:
                    self.ensure_server()
                    self.ensure_tunnel()
                    # If the tunnel process is up but the public URL stopped
                    # reaching ZENO, force a reconnect.
                    local_server_ok = server_healthy()
                    self.verify_public_path(local_server_ok=local_server_ok)
                    self.last_error = "" if (
                        local_server_ok and self.tunnel_verified) else self.last_error
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    _log("loop_error", error=str(exc)[:200])
                self.write_status()
                self._stop.wait(CHECK_EVERY_S)
        finally:
            _log("supervisor_stopping")
            try:
                from reyes_agent.remote_access import rendezvous

                if rendezvous.configured():
                    rendezvous.clear()
            except Exception as exc:  # noqa: BLE001
                _log("rendezvous_clear_failed", error=str(exc)[:150])
            self.tunnel.stop()
            self.server.stop()
            PID_FILE.unlink(missing_ok=True)
            self.write_status()
            _log("supervisor_stopped")
            instance.release()
        return 0

    def stop(self) -> None:
        self._stop.set()


def _public_entry() -> str:
    return (os.environ.get("ZENO_ANYWHERE_ENTRY", "").strip()
            or "https://zenoai321.netlify.app")


# --- control (start / stop / status), used by the CLI --------------------
def read_status() -> dict[str, Any]:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "OFFLINE", "reason": "supervisor not running (no status file)"}
    # A status file older than a few cycles means the supervisor is not
    # actually updating it -- report OFFLINE rather than a stale ONLINE.
    if _now() - data.get("updated", 0) > CHECK_EVERY_S * 4:
        data["state"] = "STALE"
        data["reason"] = "status file is not being updated; supervisor may be dead"
    return data


def supervisor_running() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def start_detached() -> tuple[bool, str]:
    """Launch the supervisor as a detached background process."""
    if supervisor_running():
        return False, "ZENO Anywhere is already running."
    _HOME.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.unlink(missing_ok=True)
    pyw = Path(sys.executable).with_name("pythonw.exe")
    launcher = str(pyw) if pyw.exists() else sys.executable
    try:
        subprocess.Popen(
            [launcher, "-m", "reyes_agent.remote_access.anywhere", "run"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=str(config.PROJECT_ROOT),
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                           | getattr(subprocess, "DETACHED_PROCESS", 0)))
    except OSError as exc:
        return False, f"could not start supervisor: {exc}"
    # Give it a moment to write its PID.
    for _ in range(20):
        if supervisor_running():
            return True, "ZENO Anywhere started."
        time.sleep(0.5)
    return True, "ZENO Anywhere launching (PID not confirmed yet)."


def stop_running() -> tuple[bool, str]:
    if not supervisor_running():
        STOP_FLAG.unlink(missing_ok=True)
        return False, "ZENO Anywhere is not running."
    STOP_FLAG.write_text(str(_now()), encoding="utf-8")
    for _ in range(30):
        if not supervisor_running():
            return True, "ZENO Anywhere stopped."
        time.sleep(0.5)
    # Still alive: terminate by PID as a last resort.
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)  # TERMINATE
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
    return True, "ZENO Anywhere stop signalled."


def format_status(data: dict[str, Any]) -> str:
    if data.get("state") in ("OFFLINE", "STALE"):
        return (f"ZENO Anywhere: {data.get('state')}\n"
                f"  {data.get('reason', '')}\n"
                f"  Public entry: {_public_entry()}")
    s, t = data.get("server", {}), data.get("tunnel", {})
    up = data.get("uptime_s", 0)
    hours = int(up // 3600)
    mins = int((up % 3600) // 60)
    lines = [
        f"ZENO Anywhere: {data.get('state')}",
        f"  Local server: {'ONLINE' if s.get('ok') else 'DOWN'}  (port {s.get('port')}, "
        f"{'owned' if s.get('owned') else 'adopted'}, {s.get('restarts', 0)} restarts)",
        f"  Tunnel:       {'ONLINE' if t.get('ok') else 'DOWN'}  ({t.get('restarts', 0)} restarts)",
        f"  Tunnel URL:   {t.get('url') or '(none yet)'}",
        f"  Internet:     {'UP' if data.get('internet') else 'DOWN'}",
        f"  Public entry: {data.get('public_entry')}",
        f"  Uptime:       {hours}h {mins}m",
    ]
    if data.get("last_reconnect"):
        ago = int(_now() - data["last_reconnect"])
        lines.append(f"  Last reconnect: {ago}s ago")
    if data.get("last_error"):
        lines.append(f"  Last error:   {data['last_error']}")
    return "\n".join(lines)


# --- Windows auto-start (Task Scheduler at logon) ------------------------
# There is one authoritative task definition.  Keep these compatibility
# functions because older admin scripts import them, but delegate every
# operation to the hardened XML installer instead of creating a second task.
def install_autostart() -> tuple[bool, str]:
    from tools import zeno_anywhere_startup

    return zeno_anywhere_startup.install()


def uninstall_autostart() -> tuple[bool, str]:
    from tools import zeno_anywhere_startup

    return zeno_anywhere_startup.uninstall()


def autostart_installed() -> bool:
    from tools import zeno_anywhere_startup

    return zeno_anywhere_startup.status()[0]


def _start_registered_task() -> tuple[bool, str]:
    """Start the one installed task so Task Scheduler owns recovery."""
    from tools import zeno_anywhere_startup

    if not autostart_installed():
        return start_detached()
    if supervisor_running():
        return False, "ZENO Anywhere is already running."

    # Task Scheduler can briefly keep the previous invocation in RUNNING after
    # Supervisor.run() has exited.  /Run returns success in that window but
    # IgnoreNew means it starts nothing.  Retry until a NEW supervisor PID is
    # real instead of trusting the scheduler's request receipt as completion.
    deadline = _now() + 75.0
    last_detail = "Task Scheduler did not confirm a start."
    while _now() < deadline:
        ok, detail = zeno_anywhere_startup.start()
        last_detail = detail
        if not ok:
            time.sleep(2.0)
            continue
        for _ in range(10):
            if supervisor_running():
                return True, "ZENO Anywhere started through Task Scheduler."
            time.sleep(0.5)
    return False, f"start requested but no supervisor PID appeared: {last_detail}"


def _main(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "run":                      # the supervisor itself (Task Scheduler)
        return Supervisor().run()
    if cmd == "install":
        ok, msg = install_autostart()
        print(msg)
        return 0 if ok else 1
    if cmd == "uninstall":
        ok, msg = uninstall_autostart()
        print(msg)
        return 0 if ok else 1
    if cmd == "start":
        ok, msg = _start_registered_task()
        print(msg)
        return 0 if ok else 1
    if cmd == "stop":
        ok, msg = stop_running()
        print(msg)
        return 0 if ok else 1
    if cmd == "restart":
        stop_running()
        time.sleep(2)
        ok, msg = _start_registered_task()
        print(msg)
        return 0 if ok else 1
    if cmd == "status":
        print(format_status(read_status()))
        return 0
    print("usage: python -m reyes_agent.remote_access.anywhere "
          "[run|start|stop|restart|status]")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
