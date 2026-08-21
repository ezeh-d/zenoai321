"""Lazy Windows WebRTC peer for ZENO Anywhere live desktop sessions.

Nothing is captured at import or startup.  One lightweight outbound claim
loop waits for an authenticated owner request; only then is a bounded peer
thread, screen track and (when locally enabled) input worker created.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from fractions import Fraction
from typing import Any


log = logging.getLogger(__name__)
CLAIM_PATH = "/api/owner/device/live-desktop/claim"
REGISTER_PATH = "/api/owner/device/live-desktop/register"
SIGNAL_PATH = "/api/owner/device/live-desktop/signal"
STATUS_PATH = "/api/owner/device/live-desktop/status"
END_PATH = "/api/owner/device/live-desktop/end"
PRESENCE_PATH = "/api/owner/device/agent-presence"

QUALITY_TIERS = {
    "LOW": (960, 540, 12),
    "BALANCED": (1280, 720, 20),
    "HIGH": (1920, 1080, 24),
}
_CONTROL_QUEUE = 128
_ALLOWED_KEYS = {
    "enter", "backspace", "esc", "escape", "tab", "up", "down", "left", "right",
    "ctrl", "alt", "shift", "home", "end", "pageup", "pagedown", "delete", "space",
}


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass
class NodeConfig:
    gateway: str
    device_id: str
    token: str
    streaming_enabled: bool = True
    control_enabled: bool = False


class GatewayClient:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config

    def _url(self, path: str) -> str:
        url = self.config.gateway.rstrip("/") + path
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("gateway must be HTTP(S)")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("a non-local live desktop gateway must use HTTPS")
        return url

    def post(self, path: str, body: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self._url(path), data=data, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("gateway returned an oversized live desktop response")
        return json.loads(raw or b"{}")

    def auth(self) -> dict[str, str]:
        return {"device_id": self.config.device_id, "token": self.config.token}


def _monitor_rows() -> tuple[list[dict[str, Any]], str]:
    try:
        import mss

        with mss.MSS() as capture:
            raw = list(capture.monitors)
        rows: list[dict[str, Any]] = []
        if len(raw) > 2:
            all_display = raw[0]
            rows.append({"id": "all", "label": "All Displays",
                         "width": int(all_display["width"]), "height": int(all_display["height"]),
                         "primary": False})
        for index, monitor in enumerate(raw[1:], 1):
            rows.append({"id": f"display-{index}", "label": f"Display {index}",
                         "width": int(monitor["width"]), "height": int(monitor["height"]),
                         "primary": index == 1})
        return rows, "display-1" if len(raw) > 1 else ""
    except Exception:
        return [], ""


def capabilities(config: NodeConfig) -> dict[str, Any]:
    monitors, active = _monitor_rows()
    detail = "ready" if monitors else "mss screen capture is unavailable"
    try:
        import aiortc  # noqa: F401
        import av  # noqa: F401
        media_ready = bool(monitors)
    except Exception as exc:
        media_ready = False
        detail = f"{type(exc).__name__}: install aiortc and av"
    return {
        "available": media_ready and config.streaming_enabled,
        "detail": detail,
        "monitors": monitors,
        "active_display": active,
        "streaming_enabled": config.streaming_enabled,
        "control_enabled": config.control_enabled,
        # WASAPI loopback is deliberately not faked. It can be added as a
        # separate MediaStreamTrack after a measured implementation exists.
        "audio_available": False,
    }


def _capture_monitor(identifier: str) -> dict[str, int]:
    import mss

    with mss.MSS() as capture:
        monitors = list(capture.monitors)
    if identifier == "all" and len(monitors) > 2:
        return dict(monitors[0])
    match = re.fullmatch(r"display-(\d+)", str(identifier or ""))
    index = int(match.group(1)) if match else 1
    if index < 1 or index >= len(monitors):
        raise ValueError("selected display is no longer available")
    return dict(monitors[index])


class ScreenTrack:
    """aiortc-compatible screen track with bounded adaptive quality."""

    kind = "video"

    def __init__(self, monitor: str, quality: str, *, show_cursor: bool) -> None:
        from aiortc import VideoStreamTrack

        # Composition is used instead of subclass syntax at module import so
        # ZENO starts normally when the optional media package is absent.
        class _Track(VideoStreamTrack):
            async def recv(inner_self):
                return await self.recv()

            def stop(inner_self):
                self.stop()
                return super().stop()

        self.track = _Track()
        self._monitor = _capture_monitor(monitor)
        self._quality = quality if quality in QUALITY_TIERS else "BALANCED"
        self._show_cursor = bool(show_cursor)
        self._stopped = threading.Event()
        self._capture = None
        self._started = time.monotonic()
        self._frames = 0
        self._last_frame_at = 0.0
        self._pts = 0
        self._time_base = Fraction(1, 90_000)

    @property
    def quality(self) -> str:
        return self._quality

    @property
    def fps(self) -> float:
        duration = max(0.001, time.monotonic() - self._started)
        return self._frames / duration

    def adapt(self, *, packet_loss: float = 0.0, rtt_ms: float = 0.0) -> None:
        order = ["LOW", "BALANCED", "HIGH"]
        index = order.index(self._quality)
        if (packet_loss > 0.08 or rtt_ms > 450) and index > 0:
            self._quality = order[index - 1]
        elif packet_loss < 0.01 and 0 < rtt_ms < 180 and index < 2:
            self._quality = order[index + 1]

    async def recv(self):
        if self._stopped.is_set():
            raise asyncio.CancelledError
        import av
        import mss
        import numpy as np

        width, height, target_fps = QUALITY_TIERS[self._quality]
        due = self._last_frame_at + (1.0 / target_fps)
        delay = due - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_frame_at = time.monotonic()
        if self._capture is None:
            self._capture = mss.MSS()
            try:
                self._capture.with_cursor = self._show_cursor
            except Exception:
                pass
        raw = self._capture.grab(self._monitor)
        # MSS already exposes contiguous BGRA. Scaling inside PyAV's generic
        # reformatter measured at ~5 FPS on this Windows host, so use the
        # installed OpenCV fast path when present and a bounded NumPy nearest
        # neighbour fallback otherwise. PyAV then performs colour conversion
        # only, keeping LOW close to its 12 FPS budget.
        pixels = np.asarray(raw)
        scale = min(width / pixels.shape[1], height / pixels.shape[0], 1.0)
        out_w = max(2, int(pixels.shape[1] * scale) // 2 * 2)
        out_h = max(2, int(pixels.shape[0] * scale) // 2 * 2)
        if (out_w, out_h) != (pixels.shape[1], pixels.shape[0]):
            try:
                import cv2

                pixels = cv2.resize(pixels, (out_w, out_h), interpolation=cv2.INTER_AREA)
            except ImportError:
                y_rows = np.linspace(0, pixels.shape[0] - 1, out_h, dtype=np.intp)
                x_rows = np.linspace(0, pixels.shape[1] - 1, out_w, dtype=np.intp)
                pixels = np.ascontiguousarray(pixels[y_rows[:, None], x_rows])
        frame = av.VideoFrame.from_ndarray(pixels, format="bgra").reformat(format="yuv420p")
        self._pts += max(1, round(90_000 / target_fps))
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._frames += 1
        return frame

    def stop(self) -> None:
        self._stopped.set()
        if self._capture is not None:
            try:
                self._capture.close()
            except Exception:
                pass
            self._capture = None


class RemoteInputWorker:
    """One bounded serialized input queue for a single approved session."""

    def __init__(self, monitor: dict[str, int]) -> None:
        self._monitor = monitor
        self._pressed_keys: set[str] = set()
        self._pressed_buttons: set[str] = set()
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_CONTROL_QUEUE)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="zeno-live-input", daemon=True)
        self._thread.start()

    def submit(self, raw: Any) -> bool:
        if not isinstance(raw, str) or len(raw) > 2048:
            return False
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return False
        if not isinstance(event, dict):
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            # Mouse moves are disposable; never let an overloaded phone grow
            # memory or block the WebRTC event loop.
            return False

    def _point(self, event: dict[str, Any]) -> tuple[int, int]:
        x = max(0.0, min(float(event.get("x", 0.0)), 1.0))
        y = max(0.0, min(float(event.get("y", 0.0)), 1.0))
        return (int(self._monitor["left"] + x * max(1, self._monitor["width"] - 1)),
                int(self._monitor["top"] + y * max(1, self._monitor["height"] - 1)))

    @staticmethod
    def _key(value: Any) -> str:
        key = str(value or "").casefold()
        if len(key) == 1 and key.isprintable():
            return key
        aliases = {"escape": "esc", "control": "ctrl", "arrowup": "up",
                   "arrowdown": "down", "arrowleft": "left", "arrowright": "right"}
        key = aliases.get(key, key)
        return key if key in _ALLOWED_KEYS else ""

    def _apply(self, event: dict[str, Any]) -> None:
        import pyautogui

        kind = str(event.get("type", "")).casefold()
        if kind == "pointer":
            action = str(event.get("action", "")).casefold()
            x, y = self._point(event)
            button = str(event.get("button", "left")).casefold()
            if button not in {"left", "right", "middle"}:
                button = "left"
            if action == "move":
                pyautogui.moveTo(x, y, duration=0)
            elif action == "down":
                pyautogui.moveTo(x, y, duration=0); pyautogui.mouseDown(button=button)
                self._pressed_buttons.add(button)
            elif action == "up":
                pyautogui.moveTo(x, y, duration=0); pyautogui.mouseUp(button=button)
                self._pressed_buttons.discard(button)
            elif action == "click":
                pyautogui.click(x, y, button=button)
            elif action == "double":
                pyautogui.doubleClick(x, y, button=button, interval=0.12)
            elif action == "right":
                pyautogui.click(x, y, button="right")
        elif kind == "scroll":
            amount = max(-20, min(int(event.get("dy", 0) or 0), 20))
            if amount:
                pyautogui.scroll(amount)
        elif kind == "key":
            key = self._key(event.get("key"))
            action = str(event.get("action", "press")).casefold()
            if key and action in {"press", "down", "up"}:
                {"press": pyautogui.press, "down": pyautogui.keyDown,
                 "up": pyautogui.keyUp}[action](key)
                if action == "down":
                    self._pressed_keys.add(key)
                elif action == "up":
                    self._pressed_keys.discard(key)
        elif kind == "text":
            text = str(event.get("text", ""))[:128]
            if text and all(char.isprintable() or char in "\n\t" for char in text):
                pyautogui.write(text.replace("\n", ""), interval=0)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    if item is None:
                        return
                    self._apply(item)
                except Exception as exc:
                    log.debug("live desktop input rejected: %s", type(exc).__name__)
                finally:
                    self._queue.task_done()
        finally:
            try:
                import pyautogui

                for key in tuple(self._pressed_keys):
                    pyautogui.keyUp(key)
                for button in tuple(self._pressed_buttons):
                    pyautogui.mouseUp(button=button)
            except Exception:
                pass
            self._pressed_keys.clear()
            self._pressed_buttons.clear()

    def close(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)


def _rtc_configuration(raw: list[dict[str, Any]]):
    from aiortc import RTCConfiguration, RTCIceServer

    servers = []
    for item in raw if isinstance(raw, list) else []:
        servers.append(RTCIceServer(
            urls=item.get("urls") or [], username=item.get("username"),
            credential=item.get("credential")))
    return RTCConfiguration(iceServers=servers)


async def _ice_complete(pc, timeout: float = 8.0) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def changed():
        if pc.iceGatheringState == "complete":
            done.set()

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


class LiveDesktopNode:
    """Kernel-managed outbound rendezvous plus event-driven presence bridge."""

    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.client = GatewayClient(config)
        self._stop = threading.Event()
        self._claim_thread: threading.Thread | None = None
        self._presence_thread: threading.Thread | None = None
        self._peer_lock = threading.Lock()
        self._peer_thread: threading.Thread | None = None
        self._peer_stop: threading.Event | None = None
        self._active_session_id = ""
        self._active_mode = ""

    def start(self) -> "LiveDesktopNode":
        if self._claim_thread is not None and self._claim_thread.is_alive():
            return self
        self._stop.clear()
        self._register()
        self._claim_thread = threading.Thread(target=self._claim_loop,
                                              name="zeno-live-desktop", daemon=True)
        self._presence_thread = threading.Thread(target=self._presence_loop,
                                                 name="zeno-agent-presence-bridge", daemon=True)
        self._claim_thread.start()
        self._presence_thread.start()
        return self

    def _register(self) -> None:
        self.client.post(REGISTER_PATH, {**self.client.auth(), **capabilities(self.config)}, timeout=15)

    def _claim_loop(self) -> None:
        last_register = time.monotonic()
        delay = 2.0
        while not self._stop.is_set():
            try:
                if time.monotonic() - last_register > 45:
                    self._register(); last_register = time.monotonic()
                response = self.client.post(
                    CLAIM_PATH, {**self.client.auth(), "wait_s": 20}, timeout=27)
                session = response.get("session")
                if isinstance(session, dict):
                    self._start_peer(session, response.get("ice_servers") or [])
                delay = 2.0
            except Exception as exc:
                log.warning("live desktop rendezvous unavailable: %s", type(exc).__name__)
                self._stop.wait(delay)
                delay = min(30.0, delay * 1.8)

    def _start_peer(self, session: dict[str, Any], ice_servers: list[dict[str, Any]]) -> None:
        with self._peer_lock:
            old_stop = self._peer_stop
            old = self._peer_thread
        if old_stop is not None:
            old_stop.set()
        if old is not None and old.is_alive() and old is not threading.current_thread():
            old.join(timeout=4.0)
        stop = threading.Event()
        thread = threading.Thread(
            target=self._peer_entry, args=(dict(session), list(ice_servers), stop),
            name="zeno-live-desktop-peer", daemon=True)
        with self._peer_lock:
            self._peer_stop, self._peer_thread = stop, thread
        thread.start()

    def _peer_entry(self, session: dict[str, Any], ice_servers: list[dict[str, Any]],
                    stop: threading.Event) -> None:
        with self._peer_lock:
            self._active_session_id = str(session.get("id", ""))
            self._active_mode = str(session.get("mode", "VIEW_ONLY"))
        try:
            asyncio.run(self._peer(session, ice_servers, stop))
        except Exception as exc:
            log.exception("live desktop peer failed")
            try:
                self.client.post(STATUS_PATH, {**self.client.auth(),
                    "session_id": session.get("id"), "state": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}"[:180]}, timeout=10)
            except Exception:
                pass
        finally:
            with self._peer_lock:
                if self._active_session_id == str(session.get("id", "")):
                    self._active_session_id = ""
                    self._active_mode = ""

    async def _peer(self, session: dict[str, Any], ice_servers: list[dict[str, Any]],
                    stop: threading.Event) -> None:
        from aiortc import RTCPeerConnection, RTCSessionDescription

        session_id = str(session.get("id", ""))
        track = ScreenTrack(str(session.get("monitor", "display-1")),
                            str(session.get("quality", "BALANCED")),
                            show_cursor=bool(session.get("show_cursor", True)))
        pc = RTCPeerConnection(configuration=_rtc_configuration(ice_servers))
        pc.addTrack(track.track)
        input_worker = (RemoteInputWorker(_capture_monitor(str(session.get("monitor", "display-1"))))
                        if bool(session.get("control_allowed")) and self.config.control_enabled else None)
        connection_state = "CONNECTING"

        def publish(kind: str, **payload: Any) -> None:
            try:
                from reyes_agent import event_bus

                body = {"session_id": session_id, "mode": session.get("mode"), **payload}
                event_bus.publish(kind, body, source="live_desktop_node")
            except Exception:
                pass

        @pc.on("connectionstatechange")
        async def connection_changed():
            nonlocal connection_state
            state = str(pc.connectionState or "").upper()
            connection_state = ({"NEW": "CONNECTING", "CONNECTING": "CONNECTING",
                                 "CONNECTED": "CONNECTED", "FAILED": "FAILED",
                                 "DISCONNECTED": "DEGRADED", "CLOSED": "ENDED"}.get(state, "DEGRADED"))
            if connection_state == "CONNECTED":
                publish("live_desktop.started", state=connection_state)
            if connection_state in {"FAILED", "ENDED"}:
                stop.set()

        @pc.on("datachannel")
        def channel_opened(channel):
            @channel.on("message")
            def message(raw):
                if not isinstance(raw, str):
                    return
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    return
                if isinstance(decoded, dict) and decoded.get("type") == "quality":
                    track.adapt(packet_loss=max(0.0, min(float(decoded.get("loss", 0) or 0), 1.0)),
                                rtt_ms=max(0.0, min(float(decoded.get("rtt_ms", 0) or 0), 10_000.0)))
                    return
                if channel.label == "zeno-control" and input_worker is not None:
                    input_worker.submit(raw)

        try:
            offer = session.get("offer") if isinstance(session.get("offer"), dict) else {}
            await pc.setRemoteDescription(RTCSessionDescription(
                sdp=str(offer.get("sdp", "")), type="offer"))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await _ice_complete(pc)
            local = pc.localDescription
            await asyncio.to_thread(
                self.client.post, SIGNAL_PATH,
                {**self.client.auth(), "session_id": session_id,
                 "signal": {"type": local.type, "sdp": local.sdp}}, timeout=20)
            publish("live_desktop.connecting", state="CONNECTING")
            while not stop.is_set() and not self._stop.is_set():
                await asyncio.sleep(2.0)
                if stop.is_set() or self._stop.is_set():
                    break
                response = await asyncio.to_thread(
                    self.client.post, STATUS_PATH,
                    {**self.client.auth(), "session_id": session_id,
                     "state": connection_state, "fps": track.fps,
                     "quality": track.quality}, timeout=12)
                if response.get("terminate"):
                    break
        finally:
            stop.set()
            track.stop()
            if input_worker is not None:
                input_worker.close()
            try:
                # aioice can wait indefinitely for a Windows UDP transport's
                # close callback under heavy process pressure. A live viewer
                # must never make Kernel shutdown unbounded.
                await asyncio.wait_for(pc.close(), timeout=3.0)
            except asyncio.TimeoutError:
                log.warning("live desktop WebRTC close exceeded its shutdown budget")
            publish("live_desktop.ended", state="ENDED")
            try:
                await asyncio.to_thread(
                    self.client.post, END_PATH,
                    {**self.client.auth(), "session_id": session_id,
                     "reason": "Windows peer closed"}, timeout=10)
            except Exception:
                pass

    @staticmethod
    def _presence_projection() -> dict[str, Any]:
        from reyes_agent import agent_presence, agent_space

        view = agent_space.snapshot(event_limit=30, phone=True)
        explicit = agent_presence.get_agent_presence().snapshot()
        rows_by_id = {row["id"]: dict(row) for row in view.get("agents", [])}
        active: dict[str, dict[str, Any]] = {}
        explicit_by_id = {row["agent"]: row for row in explicit.get("active_agents", [])}
        candidates = set(view.get("active_agents", [])) | set(explicit_by_id)
        speaker = str(view.get("council", {}).get("current_speaker") or "")
        for agent_id in candidates:
            base = rows_by_id.get(agent_id, {"id": agent_id, "name": agent_id.upper(),
                                             "role": "Registered specialist", "color": "#719bff"})
            extra = explicit_by_id.get(agent_id, {})
            active[agent_id] = {
                "id": agent_id, "name": base.get("name", agent_id.upper()),
                "role": base.get("role", ""), "color": base.get("color", "#719bff"),
                "state": ("SPEAKING" if agent_id == speaker else
                          str(extra.get("state") or base.get("state") or "LISTENING").upper()),
                "expression": extra.get("expression") or ("neutral" if agent_id == speaker else "curious"),
                "speaking": agent_id == speaker or bool(base.get("speaking")),
                "current_task": extra.get("current_task") or base.get("current_task", ""),
            }
        return {"active_agents": list(active.values()), "current_speaker": speaker}

    def _push_presence(self) -> None:
        self.client.post(PRESENCE_PATH, {**self.client.auth(), **self._presence_projection()}, timeout=15)

    def _presence_loop(self) -> None:
        from reyes_agent import agent_presence, event_bus

        feed = event_bus.subscribe()
        last_push = 0.0
        try:
            try:
                self._push_presence()
                last_push = time.monotonic()
            except Exception as exc:
                log.debug("initial agent presence bridge unavailable: %s", type(exc).__name__)
            while not self._stop.is_set():
                try:
                    event = feed.get(timeout=5.0)
                except queue.Empty:
                    if time.monotonic() - last_push >= 45.0:
                        try:
                            self._push_presence()
                            last_push = time.monotonic()
                        except Exception as exc:
                            log.debug("agent presence keepalive unavailable: %s", type(exc).__name__)
                    continue
                if not str(getattr(event, "type", "")).startswith("agent."):
                    continue
                agent_presence.get_agent_presence().observe_event(event)
                # Collapse bursts from queue/start/working into one current
                # projection, keeping the phone update rate bounded.
                deadline = time.monotonic() + 0.12
                while time.monotonic() < deadline:
                    try:
                        follow = feed.get_nowait()
                    except queue.Empty:
                        break
                    if str(getattr(follow, "type", "")).startswith("agent."):
                        agent_presence.get_agent_presence().observe_event(follow)
                try:
                    self._push_presence()
                    last_push = time.monotonic()
                except Exception as exc:
                    log.debug("agent presence bridge unavailable: %s", type(exc).__name__)
        finally:
            event_bus.unsubscribe(feed)

    def stop(self, timeout: float = 6.0) -> None:
        self._stop.set()
        if self._peer_stop is not None:
            self._peer_stop.set()
        deadline = time.monotonic() + max(0.0, timeout)
        for thread in (self._claim_thread, self._presence_thread, self._peer_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def status(self) -> dict[str, Any]:
        with self._peer_lock:
            return {"active": bool(self._active_session_id),
                    "session_id": self._active_session_id,
                    "mode": self._active_mode}

    def terminate_current(self) -> bool:
        with self._peer_lock:
            if self._peer_stop is None or not self._active_session_id:
                return False
            self._peer_stop.set()
            return True


_node: LiveDesktopNode | None = None
_node_lock = threading.Lock()


def configured() -> bool:
    return all(os.environ.get(name, "").strip() for name in (
        "ZENO_GATEWAY_URL", "ZENO_DEVICE_ID", "ZENO_DEVICE_TOKEN"))


def from_environment() -> LiveDesktopNode | None:
    if not configured():
        return None
    return LiveDesktopNode(NodeConfig(
        gateway=os.environ["ZENO_GATEWAY_URL"].strip(),
        device_id=os.environ["ZENO_DEVICE_ID"].strip(),
        token=os.environ["ZENO_DEVICE_TOKEN"].strip(),
        streaming_enabled=_env_true("ZENO_LIVE_DESKTOP_ENABLED", True),
        control_enabled=_env_true("ZENO_LIVE_DESKTOP_CONTROL_ENABLED", False),
    ))


def start_from_environment() -> LiveDesktopNode | None:
    global _node
    with _node_lock:
        if _node is not None:
            return _node
        node = from_environment()
        if node is None:
            return None
        _node = node.start()
        return _node


def stop_current(timeout: float = 6.0) -> None:
    global _node
    with _node_lock:
        node, _node = _node, None
    if node is not None:
        node.stop(timeout=timeout)


def current() -> LiveDesktopNode | None:
    return _node


def status() -> dict[str, Any]:
    node = current()
    return node.status() if node is not None else {"active": False, "session_id": "", "mode": ""}


def terminate_current() -> bool:
    node = current()
    return node.terminate_current() if node is not None else False
