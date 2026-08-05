"""REYES as an actual desktop app: a native window around the same web
panel (reyes_agent/web.py), via pywebview + the system's WebView2/Edge
Chromium runtime. Same FastAPI backend, same agent core -- this is a
fourth front door (text/voice/web/desktop), not a new brain.

Doesn't fix model latency (that's the provider, see AGENT.md's lag
section) -- what it fixes is everything *around* the model call: no
browser chrome, no tab, no dev-tools-pane compositing overhead, a real
app window and taskbar icon, matching what "turn REYES into an app" means.

Run: python -m reyes_agent.desktop_app
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path

import webview

from reyes_agent import config

_PORT = 8765
_URL = f"http://127.0.0.1:{_PORT}"
_DASHBOARD_URL = _URL + ("?audit=1" if os.environ.get("ZENO_PERFORMANCE_AUDIT") == "1" else "")
# A machine-local, stable profile: WebView2 stores origin permissions here.
# Never clean, rotate or place this below a temporary workspace directory.
_WEBVIEW_STORAGE = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "WebView2" / "UserData"
_server_proc: subprocess.Popen | None = None
_owns_server = False
_MAX_LOG_BYTES = 2 * 1024 * 1024
_BOOT_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>ZENO</title>
<style>html,body{height:100%;margin:0;background:#050b1e;color:#b9d7ff;font:15px Segoe UI,sans-serif}
main{height:100%;display:grid;place-items:center}.orb{width:88px;height:88px;border-radius:50%;
background:radial-gradient(circle at 35% 30%,#d9f6ff,#177bd1 42%,#07163e 72%);box-shadow:0 0 55px #1787e880;
animation:pulse 2.8s ease-in-out infinite}
@keyframes pulse{50%{transform:scale(1.08);box-shadow:0 0 78px #36a7ffb0}}</style></head>
<body><main><div class='orb'></div></main></body></html>"""


def _rotate_log_if_needed(path: Path) -> None:
    """Keep desktop diagnostic logs useful without allowing endless growth."""
    try:
        if path.exists() and path.stat().st_size >= _MAX_LOG_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        # Logging must never delay the shell or prevent a server start.
        pass


def _redirect_stdio_if_console_free() -> None:
    """Launched via pythonw.exe (the silent launcher -- no console window
    at all, by request) means sys.stdout/stderr are None, not just quiet --
    ANY print() or uncaught traceback would crash the whole app with
    nothing to say why. Redirect to a log file in that case so it's still
    debuggable with zero visible window. No-op if a real console exists
    (e.g. running `python -m reyes_agent.desktop_app` directly to debug)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = config.PROJECT_ROOT / "zeno_desktop_app.log"
    _rotate_log_if_needed(log_path)
    log_file = open(log_path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 -- lives for the app's lifetime
    sys.stdout = log_file
    sys.stderr = log_file


def _start_server() -> None:
    """Run the FastAPI server as its OWN PROCESS (`python -m reyes_agent.web`),
    not a background thread. uvicorn's event loop doesn't reliably serve
    requests from a non-main thread on Windows -- it binds the port but
    hangs on actual requests -- so a thread here left the whole app dead on
    launch. A child process runs uvicorn in ITS main thread (the proven
    path) and binds loopback-only. Cloudflare Tunnel is the sole remote
    transport for the Phone Companion. Killed on exit.
    """
    global _server_proc, _owns_server
    if _server_proc is not None and _server_proc.poll() is None:
        return
    # A second desktop window must not blindly race another healthy ZENO
    # backend for port 8765. Reuse it and, importantly, never terminate it
    # when this window closes.
    if _server_available(timeout=0.25):
        _server_proc = None
        _owns_server = False
        return
    # No new console window for the child; inherit env so .env/venv resolve.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Explicit real file handles for the child's stdout/stderr -- when THIS
    # process is launched via pythonw.exe (no console at all, the whole
    # point of the silent launcher), there is nothing valid to inherit and
    # the child died on startup with no output anywhere (root-caused
    # 2026-07-31: reyes_agent.web ran fine standalone under pythonw with
    # real handles, but silently never bound the port when spawned as an
    # inherited-handle child of a console-less parent). A log file makes
    # this work AND keeps it debuggable with zero visible window.
    log_path = config.PROJECT_ROOT / "zeno_server.log"
    _rotate_log_if_needed(log_path)
    # Popen duplicates these handles for the child on Windows. Closing the
    # parent's copies immediately avoids one leaked descriptor per restart.
    with open(log_path, "a", buffering=1, encoding="utf-8") as log_file:
        _server_proc = subprocess.Popen(
            [sys.executable, "-m", "reyes_agent.web"],
            creationflags=creationflags,
            stdout=log_file,
            stderr=log_file,
        )
    _owns_server = True
    atexit.register(_stop_server)


def _stop_server() -> None:
    global _server_proc, _owns_server
    if _owns_server and _server_proc is not None and _server_proc.poll() is None:
        # Windows terminate() is not a graceful POSIX SIGTERM. Ask the owned
        # loopback child to atomically persist its session before ending it;
        # never send this lifecycle command to a backend we did not launch.
        try:
            import urllib.request

            request = urllib.request.Request(
                f"{_URL}/api/internal/prepare-shutdown", data=b"", method="POST",
            )
            urllib.request.urlopen(request, timeout=2).read()
        except OSError:
            pass
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            _server_proc.kill()
    _server_proc = None
    _owns_server = False


def _server_available(timeout: float = 1.0) -> bool:
    import urllib.request

    try:
        urllib.request.urlopen(f"{_URL}/api/status", timeout=timeout)
        return True
    except OSError:
        return False


def _wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_available(timeout=1):
            return True
        time.sleep(0.3)
    return False


def _load_when_ready(window, api) -> None:
    """Wait away from the native UI thread, then hand the same window to the
    web panel. The user sees a real ZENO window immediately even if a provider
    import, database recovery, or background service is slow."""
    _start_server()
    if _wait_for_server():
        try:
            api.show_mini()
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        window.evaluate_js(
            "document.querySelector('.label').textContent = "
            "'ZENO is still starting — retrying automatically…';"
        )
        while _server_proc is None or _server_proc.poll() is None:
            if _wait_for_server(timeout=5.0):
                api.show_mini()
                return
            if _server_proc is not None and _server_proc.poll() is not None:
                window.evaluate_js(
                    "document.querySelector('.label').textContent = "
                    "'ZENO server failed to start — see zeno_server.log';"
                )
                return
    except Exception:  # noqa: BLE001
        pass


class _DesktopApi:
    """Exposed to the page as window.pywebview.api -- lets the in-page
    fullscreen button/F11 drive the NATIVE window fullscreen, which is more
    reliable inside WebView2 than the browser Fullscreen API alone.
    """

    def __init__(self) -> None:
        self.window = None
        self._orb_pos = None  # last known companion-orb position (x, y)

    def toggle_fullscreen(self) -> bool:
        if self.window is not None:
            self.window.toggle_fullscreen()
            return True
        return False

    # --- Desktop Companion Mode ---------------------------------------
    # The mini orb is a real floating desktop companion: draggable, edge
    # snapping, and it remembers where it was left. The native window has
    # no title bar in mini mode, so dragging is done by the page reporting
    # mouse deltas here and this moving the OS window to match.
    def screen_size(self) -> dict:
        try:
            screens = webview.screens
            if screens:
                return {"w": screens[0].width, "h": screens[0].height}
        except Exception:  # noqa: BLE001
            pass
        return {"w": 1920, "h": 1080}

    def move_window(self, x: int, y: int) -> bool:
        w = self.window
        if w is None:
            return False
        try:
            scr = self.screen_size()
            # Clamp so the orb can never be dragged fully off-screen and
            # become unreachable.
            x = max(0, min(int(x), scr["w"] - 60))
            y = max(0, min(int(y), scr["h"] - 60))
            w.move(x, y)
            self._orb_pos = (x, y)
            return True
        except Exception:  # noqa: BLE001
            return False

    def snap_orb(self, size: int = 210, margin: int = 30) -> dict:
        """Snap the companion orb to the nearest edge/corner, then report
        where it landed so the page can remember it."""
        w = self.window
        if w is None:
            return {"ok": False}
        scr = self.screen_size()
        try:
            x, y = getattr(self, "_orb_pos", (scr["w"] - size - margin, scr["h"] - size - 120))
        except Exception:  # noqa: BLE001
            x, y = scr["w"] - size - margin, scr["h"] - size - 120
        # Horizontal: nearest of left / right. Vertical: nearest of top /
        # bottom. That yields the four corners plus, when one axis is near
        # centre, the edge positions in between.
        left = margin
        right = scr["w"] - size - margin
        top = margin
        bottom = scr["h"] - size - 120
        snap_x = left if x < (scr["w"] / 2 - size / 2) else right
        snap_y = top if y < (scr["h"] / 2 - size / 2) else bottom
        self.move_window(snap_x, snap_y)
        return {"ok": True, "x": snap_x, "y": snap_y}

    def restore_orb_position(self, x: int, y: int) -> bool:
        """Put the companion orb back where the user last left it."""
        return self.move_window(x, y)

    def set_mini(self, on: bool) -> bool:
        """Shrink the whole window to a small corner orb (floating over
        other apps) while REYES works, then restore. Called by the page
        auto-shrink logic. Best-effort -- silently no-ops if the pywebview
        build doesn't support a given call."""
        w = self.window
        if w is None:
            return False
        try:
            screens = webview.screens
            sw = screens[0].width if screens else 1920
            sh = screens[0].height if screens else 1080
        except Exception:  # noqa: BLE001
            sw, sh = 1920, 1080
        try:
            try:
                w.on_top = bool(on)          # float over apps in mini mode
            except Exception:  # noqa: BLE001
                pass
            if on:
                try:
                    w.restore()
                except Exception:  # noqa: BLE001
                    pass
                w.resize(210, 210)
                w.move(sw - 240, sh - 300)   # bottom-right corner
            else:
                w.resize(1600, 1000)
                w.move(max(0, (sw - 1600) // 2), max(0, (sh - 1000) // 2))
        except Exception:  # noqa: BLE001
            return False
        return True

    def show_mini(self) -> bool:
        """Switch this one WebView to the lightweight companion document."""
        if not self.set_mini(True) or self.window is None:
            return False
        try:
            self.window.load_url(f"{_URL}/mini")
            return True
        except Exception:  # noqa: BLE001
            return False

    def show_dashboard(self) -> bool:
        """Return the same WebView (not a second frontend) to the dashboard."""
        if self.window is None:
            return False
        try:
            self.set_mini(False)
            self.window.load_url(_URL)
            return True
        except Exception:  # noqa: BLE001
            return False


def main() -> None:
    _redirect_stdio_if_console_free()
    from reyes_agent.single_instance import SingleInstanceGuard

    instance = SingleInstanceGuard(config.ASSISTANT_NAME, config.PROJECT_ROOT)
    if not instance.acquire():
        # The existing desktop window was asked to foreground itself.  Do not
        # start a second server, microphone/speech queue, mini-orb or browser.
        return

    try:
        api = _DesktopApi()
        # ZENO starts as the compact, frameless companion. The full dashboard
        # is intentionally opt-in through the Mini Orb's Open button.
        window = webview.create_window(
            title=config.ASSISTANT_NAME,
            html=_BOOT_HTML,
            width=210,
            height=210,
            min_size=(210, 210),
            background_color="#000000",
            frameless=True,
            on_top=True,
            js_api=api,
        )
        api.window = window
        try:
            window.events.minimized += lambda: api.show_mini()
        except Exception:  # noqa: BLE001 -- older pywebview builds lack this event
            pass
        # debug=False -- user does not want the right-click "Inspect"
        # dev-tools option available at all when using the app normally.
        # pywebview defaults to a private, temporary WebView2 profile. That
        # made Windows ask for microphone permission after every restart.
        # This app-local profile preserves the user's one-time grants.
        webview.start(
            _load_when_ready, args=(window, api), debug=False,
            private_mode=False, storage_path=str(_WEBVIEW_STORAGE),
        )
        # Window closed -> shut the server process down so it doesn't linger.
        _stop_server()
    finally:
        instance.release()


if __name__ == "__main__":
    main()
