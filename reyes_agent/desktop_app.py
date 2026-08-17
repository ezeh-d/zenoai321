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
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import webview

from reyes_agent import config

_PORT = 8765
_URL = f"http://127.0.0.1:{_PORT}"
_DESKTOP_MIC_TOKEN = secrets.token_urlsafe(32)
# Inherited only by the managed backend child. Plain Chrome tabs can still
# use typed local UI, but cannot become a second always-on microphone owner.
os.environ["ZENO_DESKTOP_MIC_TOKEN"] = _DESKTOP_MIC_TOKEN
_DASHBOARD_URL = _URL + ("?audit=1" if os.environ.get("ZENO_PERFORMANCE_AUDIT") == "1" else "")
# A machine-local, stable profile: WebView2 stores origin permissions here.
# Never clean, rotate or place this below a temporary workspace directory.
_WEBVIEW_STORAGE = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "WebView2" / "UserData"
_server_proc: subprocess.Popen | None = None
_owns_server = False
_MAX_LOG_BYTES = 2 * 1024 * 1024
_MINI_SIZE = 210
_ORB_MARGIN = 24
_OVERLAY_HEALTH_INTERVAL_S = 5.0
_TOPMOST_REASSERT_INTERVAL_S = 30.0
_ORB_POSITION_FILE = (
    Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT)))
    / "ZENO" / "mini-orb-position.json"
)
_BOOT_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>ZENO</title>
<style>html,body{height:100%;margin:0;background:#050b1e;color:#b9d7ff;font:15px Segoe UI,sans-serif}
main{height:100%;display:grid;place-items:center}.orb{width:88px;height:88px;border-radius:50%;
background:radial-gradient(circle at 35% 30%,#d9f6ff,#177bd1 42%,#07163e 72%);box-shadow:0 0 55px #1787e880;
animation:pulse 2.8s ease-in-out infinite}
@keyframes pulse{50%{transform:scale(1.08);box-shadow:0 0 78px #36a7ffb0}}</style></head>
<body><main><div class='orb'></div></main></body></html>"""


def _read_orb_position() -> tuple[int, int] | None:
    """Read the one native overlay position; malformed local state is ignored."""
    try:
        payload = json.loads(_ORB_POSITION_FILE.read_text(encoding="utf-8"))
        return int(payload["x"]), int(payload["y"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _write_orb_position(position: tuple[int, int]) -> None:
    """Persist an owner move atomically without putting runtime state in Git."""
    try:
        _ORB_POSITION_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = _ORB_POSITION_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps({"x": int(position[0]), "y": int(position[1])}), encoding="utf-8")
        temporary.replace(_ORB_POSITION_FILE)
    except OSError:
        # The orb remains usable even if a user profile is temporarily read-only.
        pass


def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    return max(0, right - left) * max(0, bottom - top)


def _position_is_visible(
    x: int, y: int, width: int, height: int, work_areas: list[tuple[int, int, int, int]],
) -> bool:
    """A saved location is valid only if a useful part of the orb is visible."""
    rect = (int(x), int(y), int(width), int(height))
    return any(_intersection_area(rect, area) >= 48 * 48 for area in work_areas)


def _visible_or_default_position(
    x: int, y: int, width: int, height: int, work_areas: list[tuple[int, int, int, int]],
) -> tuple[int, int]:
    """Preserve valid negative/multi-monitor coordinates; repair stale ones."""
    if work_areas and _position_is_visible(x, y, width, height, work_areas):
        return int(x), int(y)
    # Prefer the primary working area (the one containing 0,0), then the
    # first available monitor.  Use work area rather than screen bounds so
    # the Windows taskbar does not cover the recovered orb.
    target = next((area for area in work_areas if area[0] <= 0 < area[0] + area[2]
                   and area[1] <= 0 < area[1] + area[3]), None)
    target = target or (work_areas[0] if work_areas else (0, 0, 1920, 1080))
    left, top, work_width, work_height = target
    return (
        max(left + _ORB_MARGIN, left + work_width - width - _ORB_MARGIN),
        max(top + _ORB_MARGIN, top + work_height - height - _ORB_MARGIN),
    )


def _window_handle(window: Any) -> int | None:
    """Return the WinForms HWND without exposing a native object to JS."""
    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    try:
        return int(handle.ToInt64())
    except AttributeError:
        try:
            return int(handle)
        except (TypeError, ValueError):
            return None


def _windows_work_areas() -> list[tuple[int, int, int, int]]:
    """Physical monitor working areas, including negative secondary screens."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                       ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                       ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        areas: list[tuple[int, int, int, int]] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p,
        )

        @callback_type
        def visit(monitor, _hdc, _rect, _lparam):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                areas.append((int(work.left), int(work.top),
                              int(work.right - work.left), int(work.bottom - work.top)))
            return True

        user32.EnumDisplayMonitors(None, None, visit, None)
        return areas
    except Exception:  # noqa: BLE001 -- native overlay recovery is best effort
        return []


def _native_window_rect(window: Any) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    hwnd = _window_handle(window)
    if not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                       ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        rect = RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)
    except Exception:  # noqa: BLE001
        return None


def _native_window_is_active(window: Any) -> bool | None:
    """Return whether a created native window is visible and not minimized.

    pywebview's WinForms ``minimized`` event has proved unreliable on this
    host.  This cheap native check is therefore the source of truth used by
    the existing five-second overlay watchdog.  ``None`` means that the HWND
    has not been created yet; it must not be treated as a hidden transition.
    """
    if sys.platform != "win32":
        return None
    hwnd = _window_handle(window)
    if not hwnd:
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return bool(user32.IsWindowVisible(hwnd)) and not bool(user32.IsIconic(hwnd))
    except Exception:  # noqa: BLE001 -- lifecycle recovery is best effort
        return None


def _restore_native_overlay(
    window: Any, position: tuple[int, int], *, force_topmost: bool = False,
) -> tuple[bool, bool, tuple[int, int] | None]:
    """Repair a hidden, minimized or off-screen overlay without activation.

    pywebview's ``Window.show`` activates WinForms windows.  The overlay must
    stay visible but never steal typing focus, so Windows receives
    ``SW_SHOWNOACTIVATE`` and ``SetWindowPos(..., HWND_TOPMOST, NOACTIVATE)``
    directly.  This is the actual native topmost operation; assigning
    ``window.on_top`` after creation only changes a Python attribute.
    """
    if sys.platform != "win32":
        return False, False, None
    hwnd = _window_handle(window)
    if not hwnd:
        return False, False, None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        rect = _native_window_rect(window) or (position[0], position[1], _MINI_SIZE, _MINI_SIZE)
        width = max(_MINI_SIZE, rect[2])
        height = max(_MINI_SIZE, rect[3])
        areas = _windows_work_areas()
        x, y = _visible_or_default_position(position[0], position[1], width, height, areas)
        hidden = not bool(user32.IsWindowVisible(hwnd))
        minimized = bool(user32.IsIconic(hwnd))
        off_screen = not _position_is_visible(rect[0], rect[1], width, height, areas) if areas else False
        repaired = hidden or minimized or off_screen or (x, y) != (rect[0], rect[1])
        if hidden or minimized:
            user32.ShowWindowAsync(hwnd, 4)  # SW_SHOWNOACTIVATE
        # HWND_TOPMOST + SWP_NOACTIVATE keeps ZENO above normal windows while
        # preserving the foreground app and its keyboard focus.
        if repaired or force_topmost:
            flags = 0x0001 | 0x0010 | 0x0040 | 0x0200  # NOSIZE|NOACTIVATE|SHOWWINDOW|NOOWNERZORDER
            user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), x, y, 0, 0, flags)
        return True, repaired, (x, y)
    except Exception:  # noqa: BLE001 -- a monitor transition must not crash ZENO
        return False, False, None


def _move_native_overlay(window: Any, x: int, y: int) -> bool:
    """Move the native overlay during an owner drag without activating it."""
    if sys.platform != "win32":
        return False
    hwnd = _window_handle(window)
    if not hwnd:
        return False
    try:
        import ctypes

        flags = 0x0001 | 0x0010 | 0x0040 | 0x0200  # NOSIZE|NOACTIVATE|SHOWWINDOW|NOOWNERZORDER
        return bool(ctypes.windll.user32.SetWindowPos(
            hwnd, ctypes.c_void_p(-1), int(x), int(y), 0, 0, flags,
        ))
    except Exception:  # noqa: BLE001
        return False


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


def _load_when_ready(api) -> None:
    """Load the light companion after the loopback server is ready.

    The native mini window already exists as the immediate startup shell.  A
    dashboard WebView is deliberately *not* created here: it is a lazy child
    window opened only by an explicit user action from the orb.
    """
    api.start_overlay_watchdog()
    _start_server()
    if _wait_for_server():
        api.load_mini_document()
        return
    while _server_proc is None or _server_proc.poll() is None:
        if _wait_for_server(timeout=5.0):
            api.load_mini_document()
            return
        if _server_proc is not None and _server_proc.poll() is not None:
            return


class _DesktopApi:
    """Native bridge for one persistent Mini Orb and one lazy dashboard.

    The overlay and dashboard are separate top-level windows with the same
    local backend and WebView2 profile.  They are never parent/child windows,
    and opening, hiding, or minimizing the dashboard can therefore not
    navigate, minimize, or destroy the Mini Orb.
    """

    def __init__(self) -> None:
        # All native objects stay private. pywebview reflects public fields to
        # JavaScript and walking WinForms/WebView2 COM graphs can freeze hosts.
        self._window = None  # compatibility alias for the one Mini Orb only
        self._mini_window = None
        self._dashboard_window = None
        self._dashboard_active: bool | None = None
        self._mini_loaded = False
        self._orb_pos = _read_orb_position()
        self._drag: dict[str, float] | None = None
        self._window_lock = threading.RLock()
        self._bridge_lock = threading.Lock()
        self._active_bridge_callback = ""
        self._bridge_calls = 0
        self._overlay_stop = threading.Event()
        self._overlay_repair = threading.Event()
        self._overlay_watchdog: threading.Thread | None = None
        self._last_topmost_at = 0.0
        self._shutting_down = False

    def attach_mini_window(self, window) -> None:
        with self._window_lock:
            self._mini_window = window
            self._window = window

    def microphone_token(self) -> str:
        """Capability token for the two native WebView microphone surfaces."""
        return _DESKTOP_MIC_TOKEN

    def _bridge_start(self, name: str) -> None:
        with self._bridge_lock:
            self._active_bridge_callback = name
            self._bridge_calls += 1

    def _bridge_end(self, name: str) -> None:
        with self._bridge_lock:
            if self._active_bridge_callback == name:
                self._active_bridge_callback = ""

    @staticmethod
    def _publish_desktop_state(event_type: str) -> None:
        """Announce a tiny lifecycle handoff without synchronously calling
        either WebView window.  The Event Bus fan-out is bounded and lets the
        Mini Orb and dashboard coordinate their single microphone owner."""
        try:
            from reyes_agent import event_bus

            event_bus.publish(event_type, source="desktop_app")
        except Exception:  # noqa: BLE001 -- UI state must not block a host callback
            pass

    def host_heartbeat(self, sent_at_s: float) -> dict:
        """Tiny renderer-to-host heartbeat; it never performs GUI work."""
        with self._bridge_lock:
            active = self._active_bridge_callback
            calls = self._bridge_calls
        with self._window_lock:
            dashboard_active = self._dashboard_active is True
        from reyes_agent.performance_monitor import record_host_heartbeat

        delay = record_host_heartbeat(sent_at_s, active_callback=active,
                                      bridge_activity={"calls": calls})
        # The Mini Orb already sends this heartbeat. Returning native state
        # repairs a dropped Event Bus handoff without adding another timer.
        return {"delay_ms": round(delay * 1000, 1),
                "dashboard_active": dashboard_active}

    def toggle_fullscreen(self) -> bool:
        with self._window_lock:
            dashboard = self._dashboard_window
        if dashboard is None:
            return False
        try:
            dashboard.toggle_fullscreen()
            return True
        except Exception:  # noqa: BLE001
            return False

    # --- One native, self-healing Mini Orb ---------------------------
    def _recover_mini(self, *, force_topmost: bool = False) -> bool:
        with self._window_lock:
            mini = self._mini_window
            saved = self._orb_pos or _read_orb_position()
        if mini is None:
            return False
        rect = _native_window_rect(mini)
        requested = saved or ((rect[0], rect[1]) if rect else (0, 0))
        ok, repaired, actual = _restore_native_overlay(mini, requested, force_topmost=force_topmost)
        if actual is not None:
            with self._window_lock:
                self._orb_pos = actual
            if repaired or saved != actual:
                _write_orb_position(actual)
        if repaired:
            try:
                from reyes_agent import event_bus

                event_bus.publish("desktop.mini_orb_recovered", {"x": actual[0], "y": actual[1]},
                                  source="desktop_overlay")
            except Exception:  # noqa: BLE001 -- recovery cannot depend on the server
                pass
        return ok

    def start_overlay_watchdog(self) -> None:
        """One low-frequency native health check, not a UI polling loop."""
        with self._window_lock:
            if self._overlay_watchdog is not None and self._overlay_watchdog.is_alive():
                self._overlay_repair.set()
                return
            self._overlay_stop.clear()
            self._overlay_repair.set()
            self._overlay_watchdog = threading.Thread(
                target=self._overlay_watchdog_loop, name="zeno-mini-orb-health", daemon=True,
            )
            self._overlay_watchdog.start()

    def _overlay_watchdog_loop(self) -> None:
        while not self._overlay_stop.is_set():
            requested = self._overlay_repair.wait(_OVERLAY_HEALTH_INTERVAL_S)
            self._overlay_repair.clear()
            if self._overlay_stop.is_set():
                return
            now = time.monotonic()
            force_topmost = requested or now - self._last_topmost_at >= _TOPMOST_REASSERT_INTERVAL_S
            if self._recover_mini(force_topmost=force_topmost) and force_topmost:
                self._last_topmost_at = now
            self._sync_dashboard_presence()

    def _set_dashboard_presence(self, active: bool) -> None:
        """Publish a microphone handoff only when native state really changes."""
        with self._window_lock:
            if self._dashboard_active is active:
                return
            self._dashboard_active = active
        self._publish_desktop_state(
            "desktop.dashboard_opened" if active else "desktop.dashboard_hidden"
        )

    def _sync_dashboard_presence(self) -> None:
        """Repair missed WinForms minimize/hide events without GUI calls."""
        with self._window_lock:
            dashboard = self._dashboard_window
        if dashboard is None:
            return
        active = _native_window_is_active(dashboard)
        if active is not None:
            self._set_dashboard_presence(active)

    def request_overlay_repair(self) -> None:
        """Wake the bounded watchdog after a native minimize/hide signal."""
        self._overlay_repair.set()

    def load_mini_document(self) -> bool:
        self._bridge_start("load_mini_document")
        try:
            self._recover_mini(force_topmost=True)
            with self._window_lock:
                mini = self._mini_window
                loaded = self._mini_loaded
            if mini is None:
                return False
            if not loaded:
                mini.load_url(f"{_URL}/mini")
                with self._window_lock:
                    self._mini_loaded = True
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self._bridge_end("load_mini_document")

    def _move_orb_to(self, x: int, y: int, *, persist: bool) -> bool:
        with self._window_lock:
            mini = self._mini_window
        if mini is None:
            return False
        areas = _windows_work_areas()
        x, y = _visible_or_default_position(int(x), int(y), _MINI_SIZE, _MINI_SIZE, areas)
        ok, _repaired, actual = _restore_native_overlay(mini, (x, y), force_topmost=True)
        if actual is None:
            actual = (x, y)
        with self._window_lock:
            self._orb_pos = actual
        if persist:
            _write_orb_position(actual)
        return ok or _window_handle(mini) is None  # initial boot completes before an HWND exists

    def move_window(self, x: int, y: int) -> bool:
        """Compatibility bridge for an explicit owner move, never screen-zero clamped."""
        self._bridge_start("move_window")
        try:
            return self._move_orb_to(int(x), int(y), persist=True)
        finally:
            self._bridge_end("move_window")

    def begin_orb_drag(self, screen_x: float, screen_y: float, css_width: float = _MINI_SIZE) -> bool:
        """Capture a native starting rect so dragging survives DPI scaling."""
        with self._window_lock:
            mini = self._mini_window
        rect = _native_window_rect(mini) if mini is not None else None
        if rect is None:
            return False
        physical_per_css = max(0.5, min(3.0, rect[2] / max(1.0, float(css_width or _MINI_SIZE))))
        with self._window_lock:
            self._drag = {"screen_x": float(screen_x), "screen_y": float(screen_y),
                          "native_x": float(rect[0]), "native_y": float(rect[1]),
                          "scale": physical_per_css}
        return True

    def move_orb_drag(self, screen_x: float, screen_y: float) -> bool:
        """Coalesced browser calls land as native no-activate moves."""
        with self._window_lock:
            mini = self._mini_window
            drag = dict(self._drag) if self._drag else None
        if mini is None or drag is None:
            return False
        x = round(drag["native_x"] + (float(screen_x) - drag["screen_x"]) * drag["scale"])
        y = round(drag["native_y"] + (float(screen_y) - drag["screen_y"]) * drag["scale"])
        return _move_native_overlay(mini, x, y)

    def end_orb_drag(self) -> dict:
        """Persist a drag and repair only truly unreachable coordinates.

        The orb may be placed anywhere.  It gently docks only when the owner
        releases it within 16 physical pixels of a monitor edge.
        """
        with self._window_lock:
            mini = self._mini_window
            self._drag = None
        rect = _native_window_rect(mini) if mini is not None else None
        if rect is None:
            return {"ok": False}
        x, y, width, height = rect
        areas = _windows_work_areas()
        x, y = _visible_or_default_position(x, y, width, height, areas)
        for left, top, work_width, work_height in areas:
            if _intersection_area((x, y, width, height), (left, top, work_width, work_height)) < 48 * 48:
                continue
            right, bottom = left + work_width - width, top + work_height - height
            if abs(x - left) <= 16:
                x = left
            elif abs(x - right) <= 16:
                x = right
            if abs(y - top) <= 16:
                y = top
            elif abs(y - bottom) <= 16:
                y = bottom
            break
        ok = self._move_orb_to(x, y, persist=True)
        return {"ok": bool(ok), "x": x, "y": y}

    def snap_orb(self, size: int = _MINI_SIZE, margin: int = _ORB_MARGIN) -> dict:
        """Legacy bridge name; preserves a free placement rather than forcing a corner."""
        del size, margin
        return self.end_orb_drag()

    def restore_orb_position(self, x: int | None = None, y: int | None = None) -> bool:
        # A native saved position wins. Optional JS coordinates migrate old
        # localStorage positions only when no native position has been saved.
        with self._window_lock:
            saved = self._orb_pos or _read_orb_position()
        if saved is None and x is not None and y is not None:
            saved = (int(x), int(y))
        if saved is None:
            self.request_overlay_repair()
            return True
        return self._move_orb_to(saved[0], saved[1], persist=True)

    def set_mini(self, on: bool) -> bool:
        """Compatibility API: the orb is always independent and available."""
        if on:
            self.request_overlay_repair()
            return self.load_mini_document()
        return True

    def show_mini(self) -> bool:
        return self.load_mini_document()

    # --- Lazy dashboard ------------------------------------------------
    def _ensure_dashboard(self):
        with self._window_lock:
            existing = self._dashboard_window
            if existing is not None:
                return existing
            dashboard = webview.create_window(
                title=config.ASSISTANT_NAME,
                url=_DASHBOARD_URL,
                width=1600,
                height=1000,
                min_size=(900, 600),
                background_color="#050b1e",
                js_api=self,
                on_top=False,
            )
            if dashboard is not None:
                dashboard.events.closing += self._hide_dashboard_on_close
                try:
                    dashboard.events.minimized += self._dashboard_hidden
                    dashboard.events.restored += self._dashboard_opened
                except Exception:  # noqa: BLE001 -- older pywebview builds lack these events
                    pass
                self._dashboard_window = dashboard
            return dashboard

    def _dashboard_hidden(self, *_args) -> None:
        self._set_dashboard_presence(False)

    def _dashboard_opened(self, *_args) -> None:
        self._set_dashboard_presence(True)

    def _hide_dashboard_on_close(self) -> bool:
        """Close means hide dashboard; only an explicit Mini Orb close exits ZENO."""
        if self._shutting_down:
            return True
        with self._window_lock:
            dashboard = self._dashboard_window
        hwnd = _window_handle(dashboard)
        if hwnd and sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.user32.ShowWindowAsync(hwnd, 0)  # SW_HIDE, no focus changes
            except Exception:  # noqa: BLE001
                pass
        self._dashboard_hidden()
        return False

    def show_dashboard(self) -> bool:
        """Open the lazy dashboard without navigating, hiding, or resizing the orb."""
        self._bridge_start("show_dashboard")
        try:
            dashboard = self._ensure_dashboard()
            if dashboard is None:
                return False
            try:
                dashboard.restore()
            except Exception:  # noqa: BLE001
                pass
            # This is an explicit click/wake request, so activating the
            # dashboard is appropriate. The watchdog never calls show().
            dashboard.show()
            self._dashboard_opened()
            self.request_overlay_repair()
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self._bridge_end("show_dashboard")

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._overlay_stop.set()
        self._overlay_repair.set()
        # The dashboard is a lazy child WebView.  Once it has been created it
        # keeps pywebview's native loop alive even after the Mini Orb closes.
        # Closing the orb is ZENO's explicit exit gesture, so release that
        # child as part of the same lifecycle instead of leaving a headless
        # desktop/backend process behind.
        with self._window_lock:
            dashboard = self._dashboard_window
            self._dashboard_window = None
        if dashboard is not None:
            try:
                dashboard.destroy()
            except Exception:  # noqa: BLE001 -- it may already be closing
                pass
        thread = self._overlay_watchdog
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)


def main() -> None:
    _redirect_stdio_if_console_free()
    from reyes_agent.runtime_environment import require_safe_startup
    require_safe_startup()
    from reyes_agent.single_instance import SingleInstanceGuard

    instance = SingleInstanceGuard(config.ASSISTANT_NAME, config.PROJECT_ROOT)
    if not instance.acquire():
        # The existing desktop window was asked to foreground itself.  Do not
        # start a second server, microphone/speech queue, mini-orb or browser.
        return

    try:
        api = _DesktopApi()
        # ZENO starts as one compact, frameless native overlay. The dashboard
        # is a separate *lazy* child window created only when the owner opens
        # it, so it cannot replace or hide the Mini Orb.
        window = webview.create_window(
            title=f"{config.ASSISTANT_NAME} Mini Orb",
            html=_BOOT_HTML,
            width=_MINI_SIZE,
            height=_MINI_SIZE,
            min_size=(_MINI_SIZE, _MINI_SIZE),
            background_color="#000000",
            frameless=True,
            on_top=True,
            focus=False,
            easy_drag=False,
            js_api=api,
        )
        api.attach_mini_window(window)
        # Keep the historical private alias until the next test-contract
        # cleanup. It is not reflected to JavaScript (leading underscore) and
        # points at the same Mini Orb already set by attach_mini_window().
        api._window = window
        try:
            window.events.minimized += api.request_overlay_repair
            window.events.restored += api.request_overlay_repair
            window.events.closed += api.shutdown
        except Exception:  # noqa: BLE001 -- older pywebview builds lack this event
            pass
        # debug=False -- user does not want the right-click "Inspect"
        # dev-tools option available at all when using the app normally.
        # pywebview defaults to a private, temporary WebView2 profile. That
        # made Windows ask for microphone permission after every restart.
        # This app-local profile preserves the user's one-time grants.
        webview.start(
            _load_when_ready, args=(api,), debug=False,
            private_mode=False, storage_path=str(_WEBVIEW_STORAGE),
        )
        # Window closed -> shut the server process down so it doesn't linger.
        api.shutdown()
        _stop_server()
    finally:
        instance.release()


if __name__ == "__main__":
    main()
