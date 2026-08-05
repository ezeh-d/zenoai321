"""The face: a local web control panel over the same agent core.

Same `agent.run_agent` the text and voice CLIs use -- this is a third
front door, not a separate brain. Adds two things the CLIs don't have:
- A visible queue for anything gated by the Tier 6 confirmation gate
  (reyes_agent/confirmation.py), so consequential actions can be approved
  or denied from the browser instead of hanging the conversation.
- Streamed replies over SSE, so the orb UI (static/) can react the instant
  tokens start arriving instead of freezing until the whole turn is done --
  the perceived-lag fix; the model itself is only as fast as its provider.

Run: python -m reyes_agent.web
Binds 0.0.0.0:8765 -- reachable from your phone on the same Wi-Fi at
http://<this-machine's-LAN-IP>:8765 (see the console output on startup).
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from reyes_agent import config

app = FastAPI(title=config.ASSISTANT_NAME)


@app.middleware("http")
async def _no_cache(request, call_next):
    # This is a local single-user app -- caching only causes stale-file
    # bugs (WebView2 kept serving an OLD orb.js across restarts, so UI
    # fixes never reached the window). Force every response fresh.
    started = time.perf_counter()
    response = await call_next(request)
    try:
        from reyes_agent.performance_monitor import record_latency

        record_latency("http", time.perf_counter() - started)
    except Exception:  # noqa: BLE001 -- monitoring must never affect a response
        pass
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


_boot_state: dict[str, Any] = {"phase": "starting", "started_at": 0.0, "errors": []}
_boot_lock = threading.Lock()
_event_loop_probe_stop: Any = None
_event_loop_probe_task: Any = None


def _set_boot_phase(phase: str, error: Exception | None = None) -> None:
    with _boot_lock:
        _boot_state["phase"] = phase
        _boot_state["updated_at"] = time.time()
        if error is not None:
            _boot_state["errors"].append(f"{type(error).__name__}: {error}")


def _boot_core() -> None:
    """Post-readiness essentials: durable events, memory restore and agents."""
    global _restore_report
    try:
        from reyes_agent import agent_runtime, event_bus, session_recovery

        # Importing the bus establishes the lightweight core dependency. Its
        # database stays lazy until the first real event, avoiding startup I/O.
        del event_bus
        _restore_report = session_recovery.restore()
        session_recovery.start_background()
        agent_runtime.boot()
        from reyes_agent.kernel import get_kernel

        get_kernel().register_agents(list(agent_runtime.AGENT_ROLES))
        _set_boot_phase("core_ready")
    except Exception as exc:  # noqa: BLE001 -- window/status remain usable
        _set_boot_phase("core_degraded", exc)


def _boot_background_services() -> None:
    """Stage nonessential polling/maintenance only after the panel is live."""
    try:
        from reyes_agent import (
            activity_monitor, email_watcher, heartbeat, notification_listener,
            proactive, resource_manager, warmup,
        )

        warmup.start_background_keepalive()
        heartbeat.start_background()
        notification_listener.start_background()
        activity_monitor.start_background()
        email_watcher.start_background()
        proactive.start_background()
        resource_manager.start_background()
        _set_boot_phase("ready")
    except Exception as exc:  # noqa: BLE001
        _set_boot_phase("services_degraded", exc)


def _boot_executive_runtime() -> None:
    """Stage 2 imports: core capabilities after the interface is responsive.

    Importing ``agent`` registers the existing tool/mission engine; none of
    these imports creates a provider request, Playwright context, camera,
    embedding job or plugin execution.
    """
    try:
        from reyes_agent import agent, model_router, permissions, voice_manager

        # Touch stable local metadata so configuration mistakes surface in the
        # boot status, without contacting a provider or generating audio.
        del agent, model_router, permissions
        voice_manager.registry()
        _set_boot_phase("executive_ready")
    except Exception as exc:  # noqa: BLE001
        _set_boot_phase("executive_degraded", exc)


@app.on_event("startup")
async def _on_startup() -> None:
    """Make the HTTP shell responsive first; stage all substantial work."""
    global _event_loop_probe_stop, _event_loop_probe_task
    from reyes_agent.kernel import STAGE_CORE, STAGE_LAZY, get_kernel
    from reyes_agent.performance_monitor import event_loop_probe

    with _boot_lock:
        _boot_state.update({"phase": "http_ready", "started_at": time.time(), "errors": []})
    kernel = get_kernel()
    # Stage 1 owns only the cheap local runtime primitives.  The desktop
    # shell can render before this server is even reachable; this handler
    # then makes the HTTP shell ready without importing providers, voices,
    # browsers, embeddings or specialist agents.
    kernel.start_interface()
    kernel.register_service("core-runtime", stage=STAGE_CORE, start=_boot_core)
    kernel.register_service("executive-runtime", stage=STAGE_CORE, start=_boot_executive_runtime)
    kernel.register_service("core-services", stage=STAGE_CORE, start=_boot_background_services)
    kernel.register_service(
        "browser-runtime", stage=STAGE_LAZY,
        start=lambda: __import__("reyes_agent.browser_runtime", fromlist=["get_browser_runtime"]).get_browser_runtime(),
    )
    # Give the HTTP shell one clean scheduling window before creating the
    # specialist threads/restoring session state. The desktop splash hands the
    # user to this shell immediately; core work then starts in the background.
    kernel.start_service("core-runtime", delay=1.5)
    kernel.start_service("executive-runtime", delay=1.8)
    kernel.start_service("core-services", delay=2.5)
    import asyncio

    _event_loop_probe_stop = asyncio.Event()
    _event_loop_probe_task = asyncio.create_task(event_loop_probe(_event_loop_probe_stop))


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    if _event_loop_probe_stop is not None:
        _event_loop_probe_stop.set()
    if _event_loop_probe_task is not None:
        try:
            await _event_loop_probe_task
        except Exception:  # noqa: BLE001
            pass
    from reyes_agent.kernel import get_kernel

    get_kernel().shutdown()


@app.post("/api/internal/prepare-shutdown")
def prepare_shutdown(request: Request) -> dict[str, bool]:
    """Loopback-only durability handshake for the owned desktop child.

    On Windows, ``Popen.terminate`` is a hard process termination and does
    not reliably run uvicorn's shutdown hooks. The desktop parent calls this
    endpoint before stopping its own child so session state is atomically
    persisted even when a voice/model task is still in flight.
    """
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Loopback only.")
    from reyes_agent.kernel import get_kernel

    result = get_kernel().shutdown(event_flush_timeout=2.0)
    return {"snapshot_saved": bool(result.get("stopped") or result.get("already_stopping")),
            "events_flushed": bool(result.get("stopped") or result.get("already_stopping"))}


_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Serve captured/generated images so the activity feed can show them
# inline (a generated image, a screenshot) instead of only a vault path.
_CAPTURES_DIR = config.VAULT_PATH / "07-System" / "captures"
_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/captures", StaticFiles(directory=_CAPTURES_DIR), name="captures")

_lock = threading.Lock()
_history: list[dict] = []
_restore_report: dict = {}

_DONE = object()


class TTSRequest(BaseModel):
    text: str
    agent: str = "zeno"   # which specialist's voice to speak in


@app.get("/api/voices")
def voices() -> dict[str, Any]:
    """Voice registry -- which agent uses which voice, which are falling
    back to the main voice, and cache stats."""
    from reyes_agent import voice_manager

    return {"registry": voice_manager.registry(), "cache": voice_manager.cache_stats()}


class VoiceIdRequest(BaseModel):
    agent: str
    voice_id: str


@app.post("/api/voices/set")
def voices_set(req: VoiceIdRequest) -> dict[str, Any]:
    """Change an agent's voice id and persist it to .env.

    Rewrites the agent's own ELEVENLABS_VOICE_<AGENT> line in place (or
    appends it), leaving every other line untouched -- this file holds API
    keys, so it is edited surgically rather than regenerated.
    """
    from reyes_agent import voice_manager

    agent = req.agent.strip().lower()
    if agent not in voice_manager.INTRODUCTIONS and agent != "zeno":
        raise HTTPException(400, f"Unknown agent '{req.agent}'.")
    vid = req.voice_id.strip()
    if not vid or len(vid) > 64 or any(c in vid for c in "\n\r="):
        raise HTTPException(400, "Invalid voice id.")

    key = "ELEVENLABS_VOICE_ID" if agent == "zeno" else f"ELEVENLABS_VOICE_{agent.upper().replace('_COMM', '')}"
    env_path = config.PROJECT_ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HTTPException(500, f"Could not read .env: {exc}") from exc

    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={vid}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={vid}")
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, f"Could not write .env: {exc}") from exc

    # Live for this process too, so preview works immediately without a
    # restart (config module-level constants are read at import).
    os.environ[key] = vid
    if agent == "zeno":
        config.ELEVENLABS_VOICE_ID = vid
    return {"ok": True, "agent": agent, "key": key, "voice_id": vid,
            "note": "Saved to .env and applied now."}


@app.get("/api/rollcall")
def rollcall(full: bool = False) -> list[dict[str, Any]]:
    """Ordered speech sequence for the agent roll call. The browser plays
    each line through /api/tts with its agent, so every specialist speaks
    in its own voice on whichever device the panel is open."""
    from reyes_agent import voice_manager

    return voice_manager.roll_call_sequence(full=full)


@app.get("/api/voices/diagnose")
def voices_diagnose() -> dict[str, Any]:
    """Voice diagnostics, including a real check that each configured id
    exists on the ElevenLabs account."""
    return _voice_background("voice-diagnose", lambda: __import__(
        "reyes_agent.voice_manager", fromlist=["diagnose"]
    ).diagnose())


@app.get("/api/voices/preview")
def voices_preview(agent: str = "zeno") -> Response:
    """Audition one agent's voice."""
    audio = _voice_background("voice-preview", lambda: __import__(
        "reyes_agent.voice_manager", fromlist=["preview"]
    ).preview(agent))
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/tts")
def tts(req: TTSRequest) -> Response:
    """Returns real ElevenLabs audio (MP3 bytes) for the panel to play,
    rather than the browser's own built-in voice. Delivered over HTTP
    specifically so it plays correctly on whichever device has the panel
    open -- this PC, or a phone on the same LAN -- not on the server's own
    speakers, which would be wrong for the phone case."""
    from reyes_agent import config as _config
    if not _config.ELEVENLABS_API_KEY:
        raise HTTPException(503, "ElevenLabs not configured.")
    # Per-agent voice + on-disk cache. Repeated lines like "I'm listening."
    # stay fast, but cache misses and ElevenLabs requests never occupy an HTTP
    # handler (or, in desktop mode, the GUI-facing server event loop).
    audio = _voice_background("voice-tts", lambda: __import__(
        "reyes_agent.voice_manager", fromlist=["synthesize"]
    ).synthesize(req.text, req.agent))
    return Response(content=audio, media_type="audio/mpeg")


class ChatRequest(BaseModel):
    message: str


class HeartbeatRequest(BaseModel):
    check: str


class GestureRequest(BaseModel):
    gesture: str


class MouseRequest(BaseModel):
    x: float           # 0..1 normalized across screen width
    y: float           # 0..1 normalized across screen height
    click: bool = False


@app.post("/api/mouse")
def mouse_move(req: MouseRequest) -> dict[str, Any]:
    """Move the system cursor to a normalized (x,y) and optionally click --
    driven by hand tracking in the browser. FAILSAFE off so a hand near a
    screen edge can't raise; the gesture toggle is the real off-switch."""
    import pyautogui

    pyautogui.FAILSAFE = False
    sw, sh = pyautogui.size()
    x = max(0, min(sw - 1, int(req.x * sw)))
    y = max(0, min(sh - 1, int(req.y * sh)))
    pyautogui.moveTo(x, y)
    if req.click:
        pyautogui.click()
    return {"ok": True, "x": x, "y": y}


# Webcam hand gestures -> instant local actions (no LLM call, so it's
# snappy). Only these are mapped; anything else is ignored.
_GESTURE_ACTIONS = {
    "Open_Palm":   ("media_control", {"action": "play_pause"}),
    "Closed_Fist": ("media_control", {"action": "mute"}),
    "Thumb_Up":    ("media_control", {"action": "volume_up"}),
    "Thumb_Down":  ("media_control", {"action": "volume_down"}),
    "Victory":     ("media_control", {"action": "next"}),
}


@app.post("/api/gesture")
def gesture_action(req: GestureRequest) -> dict[str, Any]:
    from reyes_agent.tools import run_tool

    mapping = _GESTURE_ACTIONS.get(req.gesture)
    if not mapping:
        return {"ok": False, "reason": "unmapped gesture"}
    name, args = mapping
    result = run_tool(name, args)
    return {"ok": True, "action": f"{name}:{args.get('action', '')}", "result": result}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/mini")
def mini_orb() -> FileResponse:
    """The desktop companion page: intentionally no dashboard DOM or panels."""
    return FileResponse(_STATIC_DIR / "mini.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(_STATIC_DIR / "favicon.ico")


@app.get("/api/status")
def status() -> dict[str, Any]:
    from reyes_agent import confirmation
    from reyes_agent.kernel import get_kernel

    with _boot_lock:
        boot = dict(_boot_state)
    return {
        "name": config.ASSISTANT_NAME,
        "provider": config.MODEL_PROVIDER,
        "tts_provider": config.TTS_PROVIDER,
        "pending_count": len(confirmation.list_pending()),
        "boot": boot,
        "kernel": get_kernel().diagnostics(),
    }


def _conversation_turn(context, message: str, callbacks: dict[str, Any] | None = None) -> dict[str, Any]:
    """One serialized mutable-history turn, always executed by the worker pool."""
    from reyes_agent.agent import run_agent
    from reyes_agent.memory_manager import trim_history
    from reyes_agent.performance_monitor import measure

    callbacks = callbacks or {}
    while not _lock.acquire(timeout=0.1):
        context.check_cancelled()
    try:
        context.progress("planning")
        turn_start = len(_history)
        _history.append({"role": "user", "content": message})
        tool_calls: list[dict[str, Any]] = []

        def on_tool_call(name: str, tool_input: dict, tool_id: str) -> None:
            context.check_cancelled()
            tool_calls.append({"name": name, "input": tool_input})
            callback = callbacks.get("tool")
            if callback:
                callback({"type": "tool", "name": name, "input": tool_input, "id": tool_id})

        def on_tool_result(name: str, result: str, tool_id: str) -> None:
            context.check_cancelled()
            callback = callbacks.get("tool_result")
            if callback:
                callback({"type": "tool_result", "name": name, "result": result[:1200], "id": tool_id})

        def on_text(chunk: str) -> None:
            context.check_cancelled()
            callback = callbacks.get("text")
            if callback:
                callback({"type": "text", "text": chunk})

        def on_stage(stage: str) -> None:
            context.progress(stage)
            callback = callbacks.get("stage")
            if callback:
                callback({"type": "stage", "stage": stage})

        try:
            with measure("ai_turn"):
                run_agent(
                    _history,
                    on_text=on_text if callbacks.get("text") else None,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    on_stage=on_stage,
                    cancel_check=context.check_cancelled,
                )
            reply = _history[-1]["content"]
        except BaseException:
            del _history[turn_start:]
            raise
        finally:
            trim_history(_history)
        return {"reply": reply, "tool_calls": tool_calls}
    finally:
        _lock.release()


def _background_result(handle, timeout: float) -> Any:
    try:
        return handle.result(timeout)
    except Exception as exc:  # noqa: BLE001 -- convert runtime/provider failures to HTTP responses
        from reyes_agent.provider import ProviderError
        from reyes_agent.worker_pool import TaskCancelled, TaskDeadlineExceeded
        from reyes_agent.voice.tts import TTSError

        if isinstance(exc, ProviderError):
            raise HTTPException(502, str(exc)) from exc
        if isinstance(exc, TTSError):
            raise HTTPException(502, str(exc)) from exc
        if isinstance(exc, (TaskCancelled, TaskDeadlineExceeded, TimeoutError)):
            raise HTTPException(504, str(exc)) from exc
        raise HTTPException(500, f"Background task failed: {type(exc).__name__}: {exc}") from exc


def _voice_background(name: str, operation):
    """Run potentially networked voice work in the bounded priority runtime."""
    from reyes_agent.performance_monitor import measure
    from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

    def job(context):
        context.progress("voice_request", operation=name)
        with measure("voice_tts" if name != "voice-diagnose" else "voice_diagnose"):
            return operation()

    handle = get_worker_pool().submit(
        job, name=name, priority=PRIORITY_VOICE, timeout=60, with_context=True,
    )
    return _background_result(handle, 65)


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    """Non-streaming chat -- kept as a simple fallback/for scripts. The
    web UI itself uses /api/chat/stream for responsiveness."""
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message.")

    from reyes_agent.worker_pool import PRIORITY_BRAIN, get_worker_pool

    handle = get_worker_pool().submit(
        _conversation_turn, message, name="chat", priority=PRIORITY_BRAIN,
        timeout=config.AI_REQUEST_TIMEOUT_S + 60, with_context=True,
    )
    return _background_result(handle, config.AI_REQUEST_TIMEOUT_S + 65)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE stream of the same turn: 'tool' events as calls happen, 'text'
    deltas as they're generated, then 'done'. Runs the actual turn on a
    background thread so tokens can be forwarded to the browser as they
    arrive instead of buffering the whole reply first.
    """
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message.")

    def generate():
        from reyes_agent.worker_pool import PRIORITY_BRAIN, get_worker_pool

        q: queue.Queue = queue.Queue(maxsize=256)

        def emit(context, event: dict[str, Any]) -> None:
            context.check_cancelled()
            try:
                q.put(event, timeout=0.25)
            except queue.Full:
                # Backpressure propagates to the model pipeline instead of
                # retaining an unbounded response for a disconnected tab.
                context.handle.cancel()
                context.check_cancelled()

        def worker(context) -> None:
            try:
                _conversation_turn(
                    context, message,
                    {kind: (lambda event, kind=kind: emit(context, event))
                     for kind in ("text", "tool", "tool_result", "stage")},
                )
            except Exception as exc:  # noqa: BLE001 -- errors are streamed, not hidden
                try:
                    emit(context, {"type": "error", "message": str(exc)})
                except Exception:  # noqa: BLE001
                    pass
            finally:
                while True:
                    try:
                        q.put_nowait(_DONE)
                        break
                    except queue.Full:
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break

        handle = get_worker_pool().submit(
            worker, name="chat-stream", priority=PRIORITY_BRAIN,
            timeout=config.AI_REQUEST_TIMEOUT_S + 60, with_context=True,
        )
        try:
            while True:
                try:
                    item = q.get(timeout=0.25)
                except queue.Empty:
                    if handle.done:
                        break
                    continue
                if item is _DONE:
                    break
                yield f"data: {json.dumps(item)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        finally:
            if not handle.done:
                handle.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/notification-events")
def notification_events() -> StreamingResponse:
    """SSE stream a connected browser tab listens on so it can react the
    instant a new desktop notification is announced -- specifically, arm
    itself to treat the user's very next utterance as a direct reply
    (no wake word needed), matching what the user actually asked for:
    REYES asks what to reply with, then just listens for the answer.
    """

    def generate():
        from reyes_agent import notification_bus

        q = notification_bus.subscribe()
        # Send bytes immediately so the browser's EventSource fires 'open'
        # (and any proxy/uvicorn buffer flushes) the moment it connects,
        # rather than staying silent until the first real notification.
        yield ": connected\n\n"
        try:
            while True:
                try:
                    event = q.get(timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    # Keepalive comment -- proves the connection is alive
                    # through idle stretches and lets a dropped client be
                    # noticed instead of pinning a thread on a dead socket.
                    yield ": keepalive\n\n"
        finally:
            notification_bus.unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/voice-turn")
def voice_turn(audio: UploadFile = File(...)) -> dict[str, Any]:
    """The browser's voice front door -- record in the page (mic button or
    wake word), post the clip here, get back what REYES heard and said.

    TTS is deliberately NOT done server-side for this endpoint: the web
    panel might be open from a phone on the LAN, and server-side SAPI/
    ElevenLabs audio plays on *this* machine's speakers, not the remote
    browser's. The browser speaks the reply itself (Web Speech API).
    """
    max_bytes = 25 * 1024 * 1024
    audio_bytes = audio.file.read(max_bytes + 1)
    if len(audio_bytes) > max_bytes:
        raise HTTPException(413, "Voice clip is larger than 25 MiB.")

    def voice_job(context) -> dict[str, Any]:
        from reyes_agent.voice.stt import STTError, transcribe
        from reyes_agent.performance_monitor import measure

        context.progress("transcribing")
        try:
            with measure("voice_stt"):
                transcript = transcribe(audio_bytes).strip()
        except STTError as exc:
            raise RuntimeError(f"Couldn't hear that: {exc}") from exc
        if not transcript:
            return {"transcript": "", "reply": "", "tool_calls": []}
        result = _conversation_turn(context, transcript)
        return {"transcript": transcript, **result}

    from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

    handle = get_worker_pool().submit(
        voice_job, name="voice-turn", priority=PRIORITY_VOICE,
        timeout=config.AI_REQUEST_TIMEOUT_S + 90, with_context=True,
    )
    return _background_result(handle, config.AI_REQUEST_TIMEOUT_S + 95)


@app.post("/api/heartbeat")
def heartbeat_check(req: HeartbeatRequest) -> dict[str, Any]:
    """Tier 5 entry point for an external scheduler (Hermes Agent's cron)
    to run a periodic check through the exact same agent core -- same
    tools, same memory, same personality. REYES decides whether it's
    worth surfacing; the caller (Hermes) just delivers `message` if
    `noteworthy` is true and stays silent otherwise. Quiet by default is
    enforced here, not trusted to the caller.

    Runs on its own throwaway history, never touching `_history` -- a
    background check shouldn't appear in, or be confused by, the live
    chat transcript.
    """
    check = req.check.strip()
    if not check:
        raise HTTPException(400, "Empty check.")

    def heartbeat_job(context) -> str:
        from reyes_agent.agent import run_agent

        history = [{
            "role": "user",
            "content": (
                "[Automated background check -- not a live message from the "
                f"user, who is not watching right now. Check: {check}\n"
                "If there's nothing worth telling the user, reply with "
                "exactly NOTHING and nothing else. Only write a real message "
                "if it's genuinely worth interrupting them for -- quiet by "
                "default is the rule, not the exception.]"
            ),
        }]
        context.progress("planning")
        run_agent(history, cancel_check=context.check_cancelled)
        return history[-1]["content"].strip()

    from reyes_agent.worker_pool import PRIORITY_BACKGROUND, get_worker_pool

    handle = get_worker_pool().submit(
        heartbeat_job, name="api-heartbeat", priority=PRIORITY_BACKGROUND,
        timeout=config.AI_REQUEST_TIMEOUT_S + 30, with_context=True,
    )
    reply = _background_result(handle, config.AI_REQUEST_TIMEOUT_S + 35)
    noteworthy = reply.upper() != "NOTHING"
    return {"noteworthy": noteworthy, "message": reply if noteworthy else ""}


@app.get("/api/speech/capabilities")
def speech_capabilities() -> dict[str, Any]:
    """Which parts of the listening stack are genuinely implemented --
    reported honestly, including what is not."""
    from reyes_agent import speech

    return speech.capabilities()


@app.get("/api/sysstats")
def sysstats() -> dict[str, Any]:
    """Tiny, cheap readings for the companion orb's hover card.

    Deliberately NOT the full system_health tool: this is polled by the UI
    while hovering, so it uses a non-blocking cpu_percent (no interval)
    and skips process enumeration entirely.
    """
    import psutil
    from reyes_agent import confirmation

    vm = psutil.virtual_memory()
    return {
        "cpu": round(psutil.cpu_percent(interval=None)),
        "ram": round(vm.percent),
        "pending": len(confirmation.list_pending()),
    }


class FreezeReport(BaseModel):
    duration_ms: float
    fps: float | None = None
    details: dict[str, Any] = {}


@app.get("/api/performance")
def performance_snapshot() -> dict[str, Any]:
    """Measured process/runtime metrics for the developer performance panel."""
    from reyes_agent.performance_monitor import snapshot

    return snapshot()


@app.post("/api/performance/freeze")
def performance_freeze(report: FreezeReport) -> dict[str, Any]:
    from reyes_agent.performance_monitor import record_freeze

    record = record_freeze(
        max(0.0, report.duration_ms / 1000), subsystem="webview_renderer",
        source="renderer", details={"fps": report.fps, **report.details},
    )
    return {"recorded": record is not None}


@app.get("/api/session")
def session_state() -> dict[str, Any]:
    """What was restored from the previous run, reported factually."""
    from reyes_agent import session_recovery

    return {"report": _restore_report,
            "summary": session_recovery.summary_line(_restore_report or {})}


@app.get("/api/galaxy")
def knowledge_galaxy() -> dict[str, Any]:
    """Knowledge Galaxy data: the REAL vault graph, laid out for drawing.

    Positions are computed here deterministically (kind-based rings +
    hashed angle) rather than by a physics simulation in the browser --
    a force layout on a weak GPU is exactly the kind of thing that made
    this app lag before. Same graph, no per-frame cost.
    """
    import hashlib
    import math

    from reyes_agent import knowledge_graph as kg

    g = kg.build()
    ring = {"folder": 0.30, "note": 0.62, "memory": 0.78, "tag": 0.92}
    nodes = []
    for nid, n in g.nodes.items():
        h = int(hashlib.md5(nid.encode()).hexdigest()[:8], 16)
        angle = (h % 3600) / 3600 * 2 * math.pi
        r = ring.get(n.kind, 0.7) + ((h >> 12) % 100) / 100 * 0.06
        nodes.append({
            "id": nid, "kind": n.kind, "label": n.label, "path": n.path,
            "degree": n.degree,
            "x": round(0.5 + r * math.cos(angle) * 0.46, 4),
            "y": round(0.5 + r * math.sin(angle) * 0.46, 4),
        })
    return {
        "nodes": nodes,
        "edges": [{"src": e.src, "dst": e.dst, "kind": e.kind} for e in g.edges],
        "counts": {"nodes": len(nodes), "edges": len(g.edges)},
    }


@app.get("/api/situation")
def situation_room() -> dict[str, Any]:
    """Situation Room: one composed view of everything that is genuinely
    observable right now. Each block comes from a subsystem that already
    reports real state -- nothing is synthesised for the dashboard."""
    import psutil

    from reyes_agent import agent_runtime, confirmation, event_bus, heartbeat, model_router, permissions, session_recovery
    from reyes_agent.tools.missions import list_missions_dicts

    vm = psutil.virtual_memory()
    agents = agent_runtime.health()
    try:
        missions = list_missions_dicts()
    except Exception:  # noqa: BLE001
        missions = []
    try:
        from reyes_agent import campaigns as _c

        camps = _c.list_campaigns(10)
    except Exception:  # noqa: BLE001
        camps = []

    return {
        "system": {
            "cpu": round(psutil.cpu_percent(interval=None)),
            "ram": round(vm.percent),
            "ram_used_gb": round(vm.used / 1e9, 1),
            "ram_total_gb": round(vm.total / 1e9, 1),
        },
        "agents": {
            "alive": agents["agents_alive"], "total": agents["agents_total"],
            "healthy": agents["agents_healthy"], "all_online": agents["all_online"],
            "working": agents["working_now"], "queued": agents["queued_tasks"],
            "uptime_s": agents["uptime_s"], "supervisor": agents["supervisor_alive"],
        },
        "missions": {"open": len(missions),
                     "top": [{"name": m["name"], "progress": m["progress"], "status": m["status"]}
                             for m in missions[:5]]},
        "campaigns": {"active": len([c for c in camps if c["status"] in ("running", "paused")]),
                      "total": len(camps)},
        "model": {"provider": model_router.explain()["active_provider"],
                  "measured": model_router.explain()["measured"]},
        "permissions": {"profile": permissions.ACTIVE_PROFILE},
        "events": event_bus.stats(),
        "pending_approvals": len(confirmation.list_pending()),
        "notices": len(heartbeat.list_notices()),
        "session": session_recovery.summary_line(_restore_report or {}),
    }


@app.get("/api/router")
def model_router_state() -> dict[str, Any]:
    """Model Router: which providers are genuinely available, how each
    route resolves, and MEASURED latency/health per provider."""
    from reyes_agent import model_router

    return model_router.explain()


@app.get("/api/agents")
def agents_health() -> dict[str, Any]:
    """Real Agent Runtime state -- live threads, heartbeat ages, queue
    depths, metrics. Nothing here is estimated."""
    from reyes_agent import agent_runtime

    return agent_runtime.health()


@app.post("/api/agents/{agent_id}/restart")
def agent_restart(agent_id: str) -> dict[str, Any]:
    from reyes_agent import agent_runtime

    return {"message": agent_runtime.restart(agent_id, reason="requested from panel")}


@app.get("/api/permissions")
def permissions_policy() -> dict[str, Any]:
    """Permission Centre data -- the active installation profile and every
    capability's current state."""
    from reyes_agent import permissions

    return permissions.describe()


@app.get("/api/events")
def events_history(limit: int = 100, event_type: str = "", correlation_id: str = "") -> list[dict[str, Any]]:
    """Durable event record -- the read side of the Event Bus, and the
    foundation the Timeline / Activity Stream will read from."""
    from reyes_agent import event_bus

    return event_bus.history(limit=limit, event_type=event_type, correlation_id=correlation_id)


@app.get("/api/events/stream")
def events_stream() -> StreamingResponse:
    """One bounded Event Bus subscription for event-driven dashboard updates."""
    def generate():
        from reyes_agent import event_bus

        subscriber = event_bus.subscribe()
        yield ": connected\n\n"
        try:
            while True:
                try:
                    event = subscriber.get(timeout=20.0)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event.as_dict())}\n\n"
        finally:
            event_bus.unsubscribe(subscriber)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/events/stats")
def events_stats() -> dict[str, Any]:
    from reyes_agent import event_bus

    return event_bus.stats()


@app.get("/api/missions")
def missions_list() -> list[dict[str, Any]]:
    from reyes_agent.tools.missions import list_missions_dicts

    return list_missions_dicts()


@app.get("/api/notices")
def notices() -> list[dict[str, Any]]:
    """Tier 5's dismissible queue -- anything REYES's own heartbeat
    surfaced while nobody was watching, held here until acknowledged."""
    from reyes_agent import heartbeat

    return heartbeat.list_notices()


@app.post("/api/notices/{notice_id}/dismiss")
def dismiss_notice(notice_id: int) -> dict[str, Any]:
    from reyes_agent import heartbeat

    ok = heartbeat.dismiss_notice(notice_id)
    if not ok:
        raise HTTPException(404, "No such notice.")
    return {"ok": True}


@app.get("/api/kill-switch")
def kill_switch_status() -> dict[str, Any]:
    from reyes_agent import heartbeat

    return {"killed": heartbeat.is_killed()}


@app.post("/api/kill-switch")
def kill_switch_set(killed: bool) -> dict[str, Any]:
    """Tier 6's kill switch -- pauses REYES's own heartbeat checks without
    tearing anything down. Does NOT affect direct, user-initiated actions
    (chat, tools) -- only proactive/unattended runs."""
    from reyes_agent import heartbeat

    heartbeat.set_killed(killed)
    return {"killed": heartbeat.is_killed()}


@app.get("/api/pending")
def pending() -> list[dict[str, Any]]:
    from reyes_agent import confirmation

    return [_action_dict(a) for a in confirmation.list_all()]


@app.post("/api/pending/{action_id}/approve")
def approve(action_id: int) -> dict[str, Any]:
    from reyes_agent import confirmation

    action = confirmation.approve_and_run(action_id)
    if action is None:
        raise HTTPException(404, "No such request.")
    return _action_dict(action)


@app.post("/api/pending/{action_id}/deny")
def deny(action_id: int) -> dict[str, Any]:
    from reyes_agent import confirmation

    action = confirmation.deny(action_id)
    if action is None:
        raise HTTPException(404, "No such request.")
    return _action_dict(action)


def _action_dict(action: confirmation.PendingAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "tool_name": action.tool_name,
        "tool_input": action.tool_input,
        "description": action.description,
        "status": action.status,
        "result": action.result,
    }


# --- Phone Companion ---------------------------------------------------
# A mobile-shaped page on this SAME server (reusing /api/chat/stream,
# /api/tts, /api/notification-events, /api/pending as-is -- they already
# work from any device on the LAN, phone included) rather than a separate
# native app. Conversation sync is free: phone and desktop share the same
# `_history` list already. The one genuinely new surface is pairing + file
# transfer, both below. Scope note, stated plainly rather than silently
# glossed over: the pairing token gates the /phone entry point and the new
# file-transfer endpoints only -- the underlying /api/* endpoints have no
# auth today on desktop either (this app has always assumed "reachable
# only means someone on your own Wi-Fi"), so this raises the bar at the
# phone's front door without claiming a LAN-wide auth system that doesn't
# exist.
def _check_phone_token(token: str) -> None:
    import secrets

    if not token or not secrets.compare_digest(token, config.PHONE_PAIR_TOKEN):
        raise HTTPException(403, "Invalid or missing pairing token.")


@app.get("/phone")
def phone_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "phone.html")


class PhoneVerifyRequest(BaseModel):
    token: str


@app.post("/api/phone/verify")
def phone_verify(req: PhoneVerifyRequest) -> dict[str, Any]:
    import secrets

    ok = bool(req.token) and secrets.compare_digest(req.token, config.PHONE_PAIR_TOKEN)
    return {"ok": ok}


@app.get("/api/phone/pair-info")
def phone_pair_info() -> dict[str, Any]:
    """For the DESKTOP settings panel to display -- the phone reads this
    from its own trusted operator, not over the network unauthenticated."""
    return {"lan_url": f"http://{_lan_ip()}:8765/phone", "token": config.PHONE_PAIR_TOKEN}


_PHONE_TRANSFER_DIR = config.VAULT_PATH / "00-Inbox"


@app.get("/api/phone/files")
def phone_list_files(token: str) -> list[dict[str, Any]]:
    _check_phone_token(token)
    _PHONE_TRANSFER_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for base in (_PHONE_TRANSFER_DIR, config.VAULT_PATH / "02-Projects"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out.append({"path": str(p.relative_to(config.VAULT_PATH)), "size": p.stat().st_size})
    return out


@app.get("/api/phone/download")
def phone_download(token: str, path: str) -> FileResponse:
    _check_phone_token(token)
    target = (config.VAULT_PATH / path).resolve()
    if config.VAULT_PATH.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "No such file.")
    return FileResponse(target, filename=target.name)


@app.post("/api/phone/upload")
def phone_upload(token: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Phone -> desktop file transfer. Lands in the vault's own Inbox --
    the same place a human dropping a file in Obsidian would put it, so it
    shows up for search_notes/list_notes/RAG like anything else, not in a
    side channel only the phone endpoint knows about."""
    _check_phone_token(token)
    _PHONE_TRANSFER_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name  # strip any path components
    target = _PHONE_TRANSFER_DIR / safe_name
    temporary = target.with_name(target.name + ".uploading")
    maximum = 100 * 1024 * 1024
    total = 0
    try:
        with temporary.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > maximum:
                    raise HTTPException(413, "Upload is larger than 100 MiB.")
                out.write(chunk)
        temporary.replace(target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {"ok": True, "saved_as": str(target.relative_to(config.VAULT_PATH)), "size": total}


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    import uvicorn

    print(f"{config.ASSISTANT_NAME} panel:")
    print(f"  this machine -> http://127.0.0.1:8765")
    print(f"  phone / LAN  -> http://{_lan_ip()}:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
