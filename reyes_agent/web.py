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
Binds the desktop surface to 127.0.0.1:8765. When the local Phone Companion
is enabled, the same process/event loop also listens on 0.0.0.0:8768; the
remote boundary exposes only the narrow authenticated phone routes there.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (Body, Cookie, Depends, FastAPI, File, Form, HTTPException, Request,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from reyes_agent import config


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    """Delegate FastAPI lifecycle to ZENO's existing staged handlers.

    The names resolve when the server enters the lifespan, after this module
    has finished defining them. Keeping the handlers separate preserves the
    existing diagnostics/tests while avoiding FastAPI's deprecated
    ``on_event`` registration path.
    """
    await _on_startup()
    try:
        yield
    finally:
        await _on_shutdown()


app = FastAPI(title=config.ASSISTANT_NAME, lifespan=_lifespan)

# --- remote access (optional, off unless configured) ---------------------
# CORS did not exist anywhere in this app before now, which was fine while
# the phone page was same-origin. The planned split -- app.zenoassitant.com
# calling api.zenoassitant.com -- makes it mandatory.
#
# The allow-list comes from remote_access.domains and is EMPTY until a domain
# is configured, so this adds no reachable surface by itself. It is never a
# wildcard: `allow_credentials=True` with `*` is rejected by browsers anyway,
# and reaching for `*` is how people end up turning credentials off instead.
try:
    from fastapi.middleware.cors import CORSMiddleware

    from reyes_agent.remote_access import domains as _domains

    _allowed = _domains.allowed_origins()
    if _allowed:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_allowed,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Zeno-CSRF"],
            max_age=600,
        )
    from reyes_agent.remote_access.api import router as _remote_router

    app.include_router(_remote_router)

    # The authenticated owner surface: /api/owner/*. Everything except
    # login, refresh, logout and the device-agent callbacks sits behind an
    # owner session. Registered here so a route added later without its own
    # dependency is still protected -- see cloud_api.register().
    from reyes_agent.remote_access import cloud_api as _cloud_api

    _cloud_api.register(app)
    from reyes_agent.remote_access import live_desktop_api as _live_desktop_api

    _live_desktop_api.register(app)
except Exception as _remote_exc:  # noqa: BLE001 -- must never block ZENO booting
    # Swallowing this silently means ZENO can boot with NO owner API and no
    # remote surface while looking perfectly healthy. Booting anyway is still
    # right -- the desktop must work even if remote access is broken -- but it
    # has to say so.
    import logging as _logging

    _logging.getLogger(__name__).error(
        "remote access and owner API failed to register: %s: %s",
        type(_remote_exc).__name__, _remote_exc, exc_info=True)

# Browser-provided JSON is never sufficient evidence that its speaker is the
# owner.  The /api/transcribe worker creates a short-lived, server-signed
# proof for the identity it actually measured, and /api/chat verifies it
# before applying voice-specific privacy restrictions/context.
_VOICE_IDENTITY_SIGNING_MATERIAL = os.urandom(32)
_VOICE_IDENTITY_MAX_AGE_S = 120
_DESKTOP_MIC_TOKEN = os.environ.get("ZENO_DESKTOP_MIC_TOKEN", "").strip()


def _require_desktop_mic_token(request: Request) -> None:
    """Reject stale/plain-browser listeners when desktop ownership is active.

    A standalone development server has no token and keeps the historical
    local testing behavior. The managed desktop server always has one.
    """
    if not _DESKTOP_MIC_TOKEN:
        return
    supplied = request.headers.get("X-Zeno-Mic-Token", "")
    if not supplied or not hmac.compare_digest(supplied, _DESKTOP_MIC_TOKEN):
        raise HTTPException(403, "Microphone capture belongs to the native ZENO window.")


def _issue_voice_identity(identity: dict[str, Any]) -> tuple[dict[str, Any], str]:
    public = {
        "status": str(identity.get("status") or ""),
        "confidence": identity.get("confidence"),
        "issued_at": time.time(),
    }
    raw = json.dumps(public, sort_keys=True, separators=(",", ":")).encode("utf-8")
    proof = hmac.new(_VOICE_IDENTITY_SIGNING_MATERIAL, raw, hashlib.sha256).digest()
    return public, base64.urlsafe_b64encode(proof).decode("ascii")


def _validated_voice_identity(identity: dict[str, Any] | None, proof: str) -> dict[str, Any] | None:
    if not identity or not proof:
        return None
    try:
        public = {
            "status": str(identity.get("status") or ""),
            "confidence": identity.get("confidence"),
            "issued_at": float(identity.get("issued_at")),
        }
        raw = json.dumps(public, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(_VOICE_IDENTITY_SIGNING_MATERIAL, raw, hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(proof.encode("ascii"))
    except Exception:  # noqa: BLE001 -- a malformed client proof is simply untrusted
        return None
    if time.time() - public["issued_at"] > _VOICE_IDENTITY_MAX_AGE_S:
        return None
    return public if hmac.compare_digest(expected, supplied) else None


@app.middleware("http")
async def _no_cache(request, call_next):
    # This is a local single-user app -- caching only causes stale-file
    # bugs (WebView2 kept serving an OLD orb.js across restarts, so UI
    # fixes never reached the window). Force every response fresh.
    started = time.perf_counter()
    from reyes_agent.remote_access.boundary import decision as remote_boundary
    allowed, status_code, reason = remote_boundary(
        request.url.path, request.headers,
        enabled=bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)),
        client_host=(request.client.host if request.client else ""),
        local_enabled=bool(getattr(config, "PHONE_COMPANION_LOCAL_ENABLED", False)),
    )
    if not allowed:
        try:
            from reyes_agent import audit
            audit.log("remote_boundary_denied", actor="remote_client",
                      action_type="http_request", target=request.url.path,
                      policy="remote_surface_allowlist", outcome="denied",
                      reason=reason)
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse({"detail": reason}, status_code=status_code,
                            headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    try:
        from reyes_agent.performance_monitor import record_latency

        record_latency("http", time.perf_counter() - started)
    except Exception:  # noqa: BLE001 -- monitoring must never affect a response
        pass
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    # Phone endpoints are intended to be reachable only through Cloudflare
    # Access. These headers also make the browser surface safe when it is
    # opened directly on loopback during desktop pairing.
    if request.url.path.startswith(("/phone", "/pair", "/mic", "/api/phone")):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "media-src 'self' blob:; base-uri 'none'"
        )
    return response


_boot_state: dict[str, Any] = {"phase": "starting", "started_at": 0.0, "errors": []}
_boot_lock = threading.Lock()
_boot_required = frozenset({"core", "executive", "services"})
_boot_completed: set[str] = set()
_event_loop_probe_stop: Any = None
_event_loop_probe_task: Any = None


def _set_boot_phase(phase: str, error: Exception | None = None) -> None:
    with _boot_lock:
        _boot_state["phase"] = phase
        _boot_state["updated_at"] = time.time()
        if error is not None:
            _boot_state["errors"].append(f"{type(error).__name__}: {error}")


def _complete_boot_stage(stage: str, phase: str, error: Exception | None = None) -> None:
    """Advance startup monotonically regardless of worker completion order."""
    with _boot_lock:
        _boot_completed.add(stage)
        if error is not None:
            _boot_state["errors"].append(f"{type(error).__name__}: {error}")
        if _boot_required <= _boot_completed:
            _boot_state["phase"] = "ready_degraded" if _boot_state["errors"] else "ready"
        else:
            _boot_state["phase"] = phase
        _boot_state["updated_at"] = time.time()


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
        _complete_boot_stage("core", "core_ready")
    except Exception as exc:  # noqa: BLE001 -- window/status remain usable
        _complete_boot_stage("core", "core_degraded", exc)


def _boot_background_services() -> None:
    """Start the optional pollers the user has actually asked for.

    HISTORY: this function was previously reduced to just marking the phase
    ready, as part of the WebView2 idle-cost work. That silently disabled
    ZENO's notifications -- the listener code was fine, nothing was calling
    `start_background()`. Restored here, but deliberately NOT as an
    unconditional "start everything again":

      * the notification listener starts only when notifications are
        enabled in the user's saved settings, so turning them off really
        stops the polling rather than just hiding the output;
      * activity monitoring respects the Digital DNA kill switch;
      * each service starts inside its own try block, so one failing
        cannot stop the rest or the boot phase.
    """
    from reyes_agent import notifications

    started: list[str] = []

    def _try(name: str, fn) -> None:
        try:
            fn()
            started.append(name)
        except Exception as exc:  # noqa: BLE001 -- one service must not block the others
            _set_boot_phase("services_degraded", exc)

    if notifications.load_settings().enabled:
        from reyes_agent import notification_listener

        _try("notifications", notification_listener.start_background)

    if not (config.VAULT_PATH / "07-System" / "dna_disabled.flag").exists():
        from reyes_agent import activity_monitor

        _try("activity", activity_monitor.start_background)

    from reyes_agent import heartbeat, proactive

    _try("heartbeat", heartbeat.start_background)
    _try("proactive", proactive.start_background)

    # Generate the configured ZENO-voice realtime phrases once, well after first
    # render and on the existing bounded pool.  The realtime wake route is
    # cache-only and will never wait for this provider work.
    prewarm = os.environ.get("ZENO_WAKE_ACK_PREWARM", "true").strip().casefold() not in {"0", "false", "no", "off"}
    if prewarm and config.ELEVENLABS_API_KEY and config.ELEVENLABS_VOICE_ID:
        from reyes_agent.worker_pool import PRIORITY_MAINTENANCE, get_worker_pool

        def _queue_ack_warm() -> None:
            handle = get_worker_pool().submit(
                lambda _context: __import__("reyes_agent.voice_manager", fromlist=["warm_realtime_phrases"])
                .warm_realtime_phrases(),
                name="voice-realtime-cache", priority=PRIORITY_MAINTENANCE,
                timeout=120, with_context=True,
            )
            del handle

        _try("voice-realtime-cache", _queue_ack_warm)

    # Warm the brain path once, off the interface-critical route, so the FIRST
    # phone->desktop turn after a restart is as quick as later ones. A cold
    # server pays ~15-25s to import the agent/tool stack, build the provider
    # client and finish the first model handshake; a single throwaway turn on a
    # PRIVATE history pays that cost up front and never touches the real
    # conversation. It runs on a dedicated daemon thread, never the worker pool
    # -- the same reason interactive remote commands avoid it (a boot-time pool
    # slot must stay free for real work).
    if os.environ.get("ZENO_BRAIN_PREWARM", "true").strip().casefold() not in {"0", "false", "no", "off"}:
        def _warm_brain() -> None:
            try:
                time.sleep(4.0)   # let interface-critical boot settle first
                # 1) Deterministically pre-import the provider SDK and build the
                #    configured clients (network-free). This alone removes the
                #    freeze where the first real turn stalls on a cold
                #    `import openai` WHILE holding the turn lock, queueing every
                #    other turn and request behind a one-off disk read.
                from reyes_agent import provider
                provider.warm()
                # 2) Then run one throwaway turn on a PRIVATE history to warm the
                #    network path, tool registry and capability router so the
                #    first real phone->desktop turn is as quick as later ones.
                from reyes_agent.agent import run_agent
                run_agent([{"role": "user", "content": "hi"}])
            except Exception:      # noqa: BLE001 -- best-effort; never affects boot
                pass
        _try("brain-prewarm",
             lambda: threading.Thread(target=_warm_brain,
                                      name="zeno-brain-prewarm", daemon=True).start())

    with _boot_lock:
        _boot_state["background_services"] = started
    _complete_boot_stage("services", "services_ready")


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
        _complete_boot_stage("executive", "executive_ready")
    except Exception as exc:  # noqa: BLE001
        _complete_boot_stage("executive", "executive_degraded", exc)


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
    # ZENO Anywhere is an outbound-only service and belongs to the same
    # lifecycle authority as every other long-running worker.  Registration
    # itself performs no I/O.  It is scheduled only when all credentials are
    # present and Kernel shutdown always joins it through stop_current().
    from reyes_agent.remote_access import desktop_agent as _desktop_agent
    anywhere_connector_enabled = _desktop_agent.configured()
    kernel.register_service(
        "zeno-anywhere-connector",
        stage=STAGE_CORE if anywhere_connector_enabled else STAGE_LAZY,
        start=_desktop_agent.start_from_environment,
        stop=_desktop_agent.stop_current,
    )
    # The live-desktop node shares only the connector's outbound gateway
    # credentials. It owns no command executor and captures nothing until an
    # authenticated short-lived WebRTC session is claimed. Its second idle
    # thread is the event-driven agent-presence bridge used by the phone.
    from reyes_agent.remote_access import live_desktop_node as _live_desktop_node
    live_desktop_enabled = _live_desktop_node.configured()
    kernel.register_service(
        "zeno-live-desktop-node",
        stage=STAGE_CORE if live_desktop_enabled else STAGE_LAZY,
        start=_live_desktop_node.start_from_environment,
        stop=_live_desktop_node.stop_current,
    )
    # The connector has no credentials in this process. It starts only when
    # the owner supplied a named-tunnel configuration, and remains bounded
    # under the kernel's lifecycle/shutdown authority.
    from reyes_agent.cloudflare_tunnel import get_cloudflare_tunnel
    tunnel = get_cloudflare_tunnel()
    tunnel_enabled = bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)) and tunnel.configured()

    def _start_tunnel() -> None:
        if not tunnel.start():
            status = tunnel.status()
            raise RuntimeError(status.get("error") or "Cloudflare tunnel did not start")

    # An unconfigured optional connector is lazy, not a perpetually pending
    # core service. If the owner has enabled and configured it, it becomes a
    # real Stage 2 service and a failed launch degrades health honestly.
    kernel.register_service("phone-cloudflare-tunnel",
                            stage=STAGE_CORE if tunnel_enabled else STAGE_LAZY,
                            start=_start_tunnel, stop=tunnel.stop)
    kernel.register_service(
        "browser-runtime", stage=STAGE_LAZY,
        start=lambda: __import__("reyes_agent.browser_runtime", fromlist=["get_browser_runtime"]).get_browser_runtime(),
    )
    kernel.register_service(
        "workflow-engine", stage=STAGE_LAZY,
        start=lambda: __import__("reyes_agent.workflow_engine", fromlist=["get_workflow_engine"]).get_workflow_engine(),
        stop=lambda: __import__("reyes_agent.workflow_engine", fromlist=["get_workflow_engine"]).get_workflow_engine().shutdown(),
    )
    # Metadata-only registration: optional Phase 3 adapters remain dormant
    # until their flag is enabled and a real request explicitly activates one.
    from reyes_agent.phase3 import register_with_kernel
    register_with_kernel()
    # Give the HTTP shell one clean scheduling window before creating the
    # specialist threads/restoring session state. The desktop splash hands the
    # user to this shell immediately; core work then starts in the background.
    kernel.start_service("core-runtime", delay=1.5)
    kernel.start_service("executive-runtime", delay=1.8)
    kernel.start_service("core-services", delay=2.5)
    if anywhere_connector_enabled:
        kernel.start_service("zeno-anywhere-connector", delay=3.0)
    if live_desktop_enabled:
        kernel.start_service("zeno-live-desktop-node", delay=3.1)
    if tunnel_enabled:
        kernel.start_service("phone-cloudflare-tunnel", delay=3.2)
    import asyncio

    _event_loop_probe_stop = asyncio.Event()
    _event_loop_probe_task = asyncio.create_task(event_loop_probe(_event_loop_probe_stop))


async def _on_shutdown() -> None:
    if _event_loop_probe_stop is not None:
        _event_loop_probe_stop.set()
    if _event_loop_probe_task is not None:
        try:
            await _event_loop_probe_task
        except Exception:  # noqa: BLE001
            pass
    from reyes_agent.audio.manager import get_audio_manager
    from reyes_agent.remote_mic import get_remote_mic_runtime
    from reyes_agent.kernel import get_kernel

    await get_remote_mic_runtime().shutdown()
    get_audio_manager().shutdown()
    get_kernel().shutdown()


@app.websocket("/api/audio/frames")
async def shared_audio_frames(websocket: WebSocket) -> None:
    """Receive the one WebView2 PCM stream without blocking the event loop.

    Authentication is the first websocket message rather than a query-string
    token, so the desktop capability does not leak into access logs or URLs.
    Frame consumers run on AudioManager's one bounded worker.
    """
    await websocket.accept()
    try:
        import asyncio

        hello = await asyncio.wait_for(websocket.receive_json(), timeout=3.0)
        supplied = str(hello.get("token") or "") if isinstance(hello, dict) else ""
        if _DESKTOP_MIC_TOKEN and not hmac.compare_digest(supplied, _DESKTOP_MIC_TOKEN):
            await websocket.close(code=1008, reason="native microphone capability required")
            return
        from reyes_agent.audio.manager import get_audio_manager

        manager = get_audio_manager()
        requested_source = str(hello.get("source") or "mini-orb") if isinstance(hello, dict) else "mini-orb"
        source = requested_source if requested_source in {"mini-orb", "dashboard"} else "unknown"
        await websocket.send_json({"ready": True, "format": "pcm_s16le/16000/mono"})
        while True:
            data = await websocket.receive_bytes()
            manager.publish(data, sample_rate=16_000, source=f"webview2-{source}")
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


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


@app.get("/api/internal/diagnostics/threads")
def diagnostic_thread_stacks(request: Request) -> dict[str, Any]:
    """Loopback-only, on-demand Python stack capture for freeze diagnosis."""
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Loopback only.")
    from reyes_agent.performance_monitor import thread_stack_snapshot
    return thread_stack_snapshot()


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


# --- Universal Media Intelligence: live panel + real-time stream ---------
class MediaCommandRequest(BaseModel):
    action: str
    reference: str | None = None
    level: float | None = None
    position_s: float | None = None
    query: str | None = None


@app.get("/api/media/panel")
def media_panel_state() -> dict[str, Any]:
    """The live media panel: active session (art/title/artist/progress), every
    known source, and the compact mini-card for the corner widget."""
    from reyes_agent.media import get_media_manager

    st = get_media_manager().state(with_art=True)
    return {"ok": True, **st.to_dict()}


@app.post("/api/media/command")
def media_do(req: MediaCommandRequest) -> dict[str, Any]:
    """Drive playback from the UI -- play/pause/next/previous/seek/volume/
    status. Closes the loop: UI -> OS -> state -> event -> UI."""
    from reyes_agent.media import get_media_manager

    return get_media_manager().command(
        req.action, reference=req.reference, level=req.level,
        position_s=req.position_s, query=req.query)


@app.get("/api/media/stream")
def media_stream() -> StreamingResponse:
    """Server-sent media events -- the panel updates the instant playback
    changes (including a track changed inside Spotify itself), no polling on
    the client. Emits an initial snapshot, then live events; a lightweight
    server poller runs only while at least one client is connected."""
    import queue as _queue

    from reyes_agent.media import get_media_manager
    from reyes_agent.media.events import get_event_bus

    mgr = get_media_manager()
    q: _queue.Queue = _queue.Queue(maxsize=64)

    def _sink(evt) -> None:
        try:
            q.put_nowait(evt.to_dict())
        except _queue.Full:
            pass

    off = get_event_bus().subscribe(_sink)
    mgr.add_live_watcher()

    def gen():
        try:
            yield (f"data: {json.dumps({'type': 'state', 'payload': mgr.state(with_art=True).to_dict()})}\n\n")
            while True:
                try:
                    item = q.get(timeout=15.0)
                    yield f"data: {json.dumps(item)}\n\n"
                except _queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            off()
            mgr.remove_live_watcher()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/media/art")
def media_art(app_id: str = "") -> Response:
    """Serve a session's cached album art (the panel can't load a local path).

    Defaults to the active session. 404 when there's no art (the client then
    shows a placeholder)."""
    import os as _os

    from reyes_agent.media import get_media_manager
    from reyes_agent.media import sessions as _ms

    st = get_media_manager().state()
    target = None
    for s in st.sessions:
        if (app_id and s.get("app_id") == app_id) or (not app_id and s is (st.active)):
            target = s
            break
    if target is None:
        target = st.active
    if not target:
        raise HTTPException(404, "no media session")
    path = _ms.fetch_album_art(target.get("app_id", ""), target.get("title", ""),
                               target.get("artist", ""))
    if not path or not _os.path.exists(path):
        raise HTTPException(404, "no album art")
    ext = _os.path.splitext(path)[1].lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise HTTPException(404, f"art unavailable: {exc}") from exc
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "max-age=30"})


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


@app.get("/api/voice/wake-ack")
def cached_wake_ack() -> Response:
    """Cache-only local wake acknowledgement; this route never uses network."""
    from reyes_agent.voice_manager import cached_wake_acknowledgement

    cached = cached_wake_acknowledgement()
    if cached is None:
        return Response(status_code=204, headers={"X-Zeno-Ack-State": "CACHE_EMPTY"})
    phrase, audio = cached
    return Response(content=audio, media_type="audio/mpeg", headers={
        "X-Zeno-Ack-State": "CACHED", "X-Zeno-Ack-Phrase": phrase,
        "Cache-Control": "no-store",
    })


@app.get("/api/voice/thinking-ack")
def cached_thinking_ack() -> Response:
    """Cache-only audible progress; a slow model can never delay this route."""
    from reyes_agent.voice_manager import cached_thinking_acknowledgement

    cached = cached_thinking_acknowledgement()
    if cached is None:
        return Response(status_code=204, headers={"X-Zeno-Ack-State": "CACHE_EMPTY"})
    phrase, audio = cached
    return Response(content=audio, media_type="audio/mpeg", headers={
        "X-Zeno-Ack-State": "CACHED", "X-Zeno-Ack-Phrase": phrase,
        "Cache-Control": "no-store",
    })


@app.get("/api/voice/latency-policy")
def voice_latency_policy() -> dict[str, object]:
    from reyes_agent.voice.latency_governor import diagnostics

    return diagnostics()


class ChatRequest(BaseModel):
    message: str
    voice_identity: dict[str, Any] | None = None
    voice_identity_proof: str = ""
    # Supplied by the browser for voice turns so the latency timeline can
    # start at the microphone rather than at the HTTP request -- the two are
    # seconds apart and only the first is what the owner experiences.
    turn_id: str = ""
    turn_kind: str = "typed"


class VocabularyCorrectionRequest(BaseModel):
    heard: str
    intended: str


class HeartbeatRequest(BaseModel):
    check: str


class GestureRequest(BaseModel):
    gesture: str


class MouseRequest(BaseModel):
    x: float           # 0..1 normalized across screen width
    y: float           # 0..1 normalized across screen height
    click: bool = False


class WorkflowControlRequest(BaseModel):
    action: str
    name: str = ""


class RuntimeControlRequest(BaseModel):
    action: str = "cancel"
    correction: str = ""


class SimulationRequest(BaseModel):
    goal: str
    steps: list[str]
    risk: str = "medium"
    files: list[str] = []


class PermissionStateRequest(BaseModel):
    state: str


class OwnerSetupRequest(BaseModel):
    display_name: str
    timezone: str = ""
    language_preferences: list[str] | None = None
    assistant_preferences: dict[str, Any] | None = None


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
def index(request: Request) -> FileResponse:
    from reyes_agent.remote_access.boundary import is_direct_remote

    if is_direct_remote(request.client.host if request.client else ""):
        return FileResponse(_STATIC_DIR / "phone.html")
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/mini")
def mini_orb() -> FileResponse:
    """The desktop companion page: intentionally no dashboard DOM or panels."""
    return FileResponse(_STATIC_DIR / "mini.html")


@app.get("/career")
def career_dashboard_page() -> FileResponse:
    """Lazy, data-backed paid-work view; it creates no second runtime."""
    return FileResponse(_STATIC_DIR / "career.html")


@app.get("/api/career/dashboard")
def career_dashboard() -> dict[str, Any]:
    from reyes_agent.paid_work_engine import get_career_engine

    return get_career_engine().dashboard(include_test=False)


# --- social ------------------------------------------------------------
# These are NOT in remote_access.boundary._PUBLIC_REMOTE_PREFIXES, so the
# fail-closed boundary refuses them for any non-loopback caller. That is
# deliberate: ZENO's social controls stay desktop-only until the cloud owner
# authentication in ZENO_REMOTE_ACCESS.md exists. A test asserts it.
@app.get("/api/social/dashboard")
def social_dashboard() -> dict[str, Any]:
    """The whole social overview. Safe to call when nothing is configured."""
    from reyes_agent.social import dashboard

    return dashboard.overview()


@app.get("/api/social/summary")
def social_summary() -> dict[str, str]:
    """What ZENO says out loud when asked how its socials are doing."""
    from reyes_agent.social import dashboard

    return {"summary": dashboard.spoken_summary()}


@app.get("/auth/instagram/callback")
def instagram_oauth_callback(code: str = "", error: str = "",
                             error_description: str = "",
                             state: str = "") -> Response:
    """OAuth redirect target for connecting ZENO's own Instagram account.

    This is the loopback path on the main app; the public Cloudflare tunnel
    forwards to the standalone callback service instead (see
    reyes_agent/social/instagram_callback_server.py), which is why this route
    is not on the remote allow-list. The exchange is server-side and no token
    is ever placed in the page or a log.
    """
    from reyes_agent.social import instagram_login
    from reyes_agent.social.instagram_callback_server import _render

    result = instagram_login.handle_callback(
        code=code, error=error, error_description=error_description, state=state)
    status, page = _render(result)
    return Response(content=page, media_type="text/html", status_code=status)


# --- language intelligence ---------------------------------------------
@app.get("/api/language/status")
def language_status_route() -> dict[str, Any]:
    """Detector, engines, speech models and hardware. Never claims a model
    that is not actually installed -- sizes are read off disk."""
    from reyes_agent.language import cli as language_cli

    return language_cli.status()


@app.post("/api/language/understand")
def language_understand_route(payload: dict = Body(...)) -> dict[str, Any]:
    """What ZENO understood, and how confident it is.

    This is the "show detected translation" toggle and the debug view. It
    returns processing METADATA -- language, confidence, which engine ran --
    never hidden reasoning.
    """
    from reyes_agent.language import understand_text

    text = str(payload.get("text", ""))[:8000]
    return understand_text(text).as_dict()


@app.post("/api/language/teach")
def language_teach_route(payload: dict = Body(...)) -> dict[str, Any]:
    """"When I say X, I mean Y." Owner vocabulary, individually removable."""
    from reyes_agent.language import memory as language_memory

    phrase = str(payload.get("phrase", "")).strip()
    meaning = str(payload.get("meaning", "")).strip()
    if not phrase or not meaning:
        raise HTTPException(status_code=400, detail="phrase and meaning are required")
    ok = language_memory.get_memory().teach(phrase, meaning, source="taught")
    return {"ok": ok, "phrase": phrase}


@app.get("/api/language/phrases")
def language_phrases_route() -> dict[str, Any]:
    from reyes_agent.language import memory as language_memory

    return {"phrases": language_memory.get_memory().all(limit=200)}


@app.post("/api/language/phrases/clear")
def language_clear_route() -> dict[str, Any]:
    """"ZENO, clear my learned language preferences." Only those."""
    from reyes_agent.language import memory as language_memory

    return {"ok": True, "removed": language_memory.get_memory().clear()}


@app.get("/api/social/health")
def social_health_route() -> dict[str, Any]:
    """Per-platform integration health, plus the owner control panel state."""
    from reyes_agent.social import control
    from reyes_agent.social.adapters import health

    return {"platforms": health(), "control": control.panel()}


@app.get("/api/social/content")
def social_content_route(status: str = "", platform: str = "") -> dict[str, Any]:
    from reyes_agent.social import store as social_store

    items = social_store.get_store().list_content(
        status=(status.strip().upper() or None),
        platform=(platform.strip().casefold() or None), limit=50)
    return {"items": items, "count": len(items)}


@app.get("/api/social/approval/{content_id}")
def social_approval_route(content_id: str) -> dict[str, Any]:
    """The owner approval card: preview, caption, tags, time and reasoning."""
    from reyes_agent.social.pipeline import ContentPipeline

    return ContentPipeline().approval_card(content_id)


@app.get("/api/social/leads")
def social_leads_route(status: str = "") -> dict[str, Any]:
    from reyes_agent.social import store as social_store

    rows = social_store.get_store().leads(
        status=(status.strip().upper() or None), limit=50)
    return {"leads": rows, "count": len(rows)}


@app.get("/api/social/audit")
def social_audit_route(limit: int = 50) -> dict[str, Any]:
    """Every social action taken. Never contains a token or a password."""
    from reyes_agent.social import store as social_store

    return {"entries": social_store.get_store().audit_log(
        limit=max(1, min(int(limit), 500)))}


@app.post("/api/social/kill")
def social_kill_route() -> dict[str, Any]:
    """One action stops all social automation. Published posts are untouched."""
    from reyes_agent.social import control

    return {"ok": True, "detail": control.engage_kill_switch()}


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(_STATIC_DIR / "favicon.ico")


# --- the owner web app (PWA) -------------------------------------------
# Served WITHOUT authentication on purpose: this is the login page. It holds
# no secret -- every byte of it is public once deployed, which is exactly why
# no credential or API key may ever be compiled into it. Everything it can
# actually DO requires an owner session from /api/owner/auth/login.
@app.get("/app")
@app.get("/app/")
def owner_app() -> FileResponse:
    return FileResponse(_STATIC_DIR / "app.html", headers={
        # no-store: an updated app must never be served from a stale cache,
        # and the service worker handles genuine offline use.
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    })


@app.get("/zeno-config.js")
def owner_app_config() -> Response:
    # Local FastAPI is same-origin.  Netlify replaces this public file during
    # its build with the configured HTTPS gateway URL.  No secret is ever
    # written into either variant.
    return Response('window.ZENO_CONFIG = {"apiBaseUrl":""};\n',
                    media_type="text/javascript",
                    headers={"Cache-Control": "no-store",
                             "X-Content-Type-Options": "nosniff"})


@app.get("/app/manifest.webmanifest")
def owner_app_manifest() -> FileResponse:
    return FileResponse(_STATIC_DIR / "app" / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/app/sw.js")
def owner_app_sw() -> FileResponse:
    # A service worker may only control the paths in its own scope, and the
    # browser refuses a wider scope unless the script is served from it.
    return FileResponse(_STATIC_DIR / "app" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-store",
                                 "Service-Worker-Allowed": "/app"})


@app.get("/app/icon-{size}.png")
def owner_app_icon(size: str) -> FileResponse:
    if size not in {"192", "512"}:
        raise HTTPException(status_code=404, detail="No such icon.")
    return FileResponse(_STATIC_DIR / "app" / f"icon-{size}.png", media_type="image/png")


@app.get("/api/status")
def status(request: Request) -> dict[str, Any]:
    from reyes_agent.remote_access.boundary import is_direct_remote

    if is_direct_remote(request.client.host if request.client else ""):
        # Pre-authentication liveness only. Network addresses, tasks, devices,
        # model/provider details and desktop state remain behind a session.
        return {"name": config.ASSISTANT_NAME, "pc": "ONLINE",
                "state": "PAIRING_OR_AUTHENTICATION_REQUIRED",
                "companion": bool(config.PHONE_COMPANION_LOCAL_ENABLED)}
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


@app.get("/api/health")
def central_health() -> dict[str, Any]:
    """One real, on-demand health surface. It starts no polling loop."""
    from reyes_agent import system_health

    return system_health.snapshot()


class EmergencyControlRequest(BaseModel):
    command: str


@app.get("/api/control-plane/session")
def control_plane_session(request: Request) -> dict[str, Any]:
    """Local desktop projection of the shared session authority."""
    _loopback(request)
    from reyes_agent.unified_session import get_session_state
    return get_session_state().snapshot()


@app.get("/api/control-plane/capabilities")
def control_plane_capabilities(request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.capability_truth import get_truth, seed_baseline, seed_tool_registry
    seed_baseline()
    seed_tool_registry()
    return {"capabilities": get_truth().dashboard(), "dependencies": get_truth().dependencies()}


@app.get("/api/control-plane/doctor")
def control_plane_doctor(request: Request, capability: str = "") -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.doctor import get_doctor
    return get_doctor().diagnose(capability)


@app.get("/api/control-plane/mission-control")
def control_plane_mission_control(request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.mission_control import get_mission_control
    return get_mission_control().snapshot()


@app.get("/api/control-plane/quality")
def control_plane_quality(request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.quality_score import get_quality_score
    return get_quality_score().score()


@app.post("/api/control-plane/emergency")
def control_plane_emergency(req: EmergencyControlRequest, request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.emergency_control import execute
    return execute(req.command)


@app.get("/api/phase3/status")
def phase3_status() -> dict[str, Any]:
    """Real feature/availability state; starts no optional service."""
    from reyes_agent.phase3 import status
    return status()


@app.get("/api/phase5/status")
def phase5_status() -> dict[str, Any]:
    """On-demand Phase 5 truth; starts no optional model or service."""
    from reyes_agent.phase5 import status
    return status()


@app.get("/api/human-companion/status")
def human_companion_status() -> dict[str, Any]:
    from reyes_agent.human_companion import status

    return status()


@app.post("/api/vocabulary/correction")
def vocabulary_correction(req: VocabularyCorrectionRequest, request: Request) -> dict[str, Any]:
    """Persist an explicit local owner correction; never infer one."""
    _require_desktop_mic_token(request)
    from reyes_agent.voice.vocabulary import add_correction

    try:
        return {"ok": True, **add_correction(req.heard, req.intended)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/wake/status")
def wake_status() -> dict[str, Any]:
    from reyes_agent.wake import get_wake_engine

    return get_wake_engine().status()


@app.post("/api/wake/detect")
def wake_detect(request: Request, audio: UploadFile = File(...)) -> dict[str, Any]:
    """Score one VAD-approved PCM clip locally before any cloud STT call."""
    _require_desktop_mic_token(request)
    from reyes_agent.wake import get_wake_engine

    try:
        data = _read_audio_upload(audio)
        return get_wake_engine().detect_wav(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        # Fault isolation: caller may use the conventional STT fallback.
        return {"configured": get_wake_engine().status()["backend"]["state"] == "READY",
                "detected": False, "confidence": 0.0,
                "reason": "wake_backend_failed", "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/intelligence/situation")
def intelligence_situation() -> dict[str, Any]:
    from reyes_agent import intelligence

    return intelligence.situation()


@app.post("/api/intelligence/interrupt")
def intelligence_interrupt(req: RuntimeControlRequest) -> dict[str, Any]:
    from reyes_agent import intelligence

    return intelligence.get_runtime_control().interrupt(action=req.action, correction=req.correction)


@app.get("/api/intelligence/actions")
def intelligence_actions(limit: int = 10) -> dict[str, Any]:
    from reyes_agent import intelligence

    return {"actions": intelligence.action_history(limit)}


@app.post("/api/intelligence/undo")
def intelligence_undo(count: int = 1) -> dict[str, Any]:
    # Direct HTTP must not bypass the same confirmation gate that protects
    # model-initiated undo. The Activity View can show action history and use
    # the established approval queue to invoke the registered undo tool.
    from reyes_agent import intelligence

    return {"ok": False, "count": max(1, min(10, count)),
            "message": "Undo requires an explicit approval in ZENO before any file is restored or removed.",
            "available": [item for item in intelligence.action_history(count)
                          if item.get("reversible") and not item.get("undone")]}


@app.get("/api/intelligence/capabilities")
def intelligence_capabilities() -> dict[str, Any]:
    from reyes_agent import intelligence

    return {"capabilities": intelligence.capabilities()}


@app.get("/api/intelligence/health")
def intelligence_health() -> dict[str, Any]:
    from reyes_agent import system_health

    return system_health.snapshot()


@app.post("/api/intelligence/simulate")
def intelligence_simulate(req: SimulationRequest) -> dict[str, Any]:
    from reyes_agent import intelligence

    return intelligence.simulate_plan(req.goal, req.steps, risk=req.risk, files=req.files)


def _open_turn(message: str, requested_id: str = "", *, kind: str = "typed") -> str:
    """Start a tracked turn: one id shared by the state machine and timeline.

    The browser may supply the id (it starts timing at the microphone, long
    before the server hears anything). Falls back to a server-side id for
    typed turns and scripted callers.
    """
    try:
        from reyes_agent import conversation_state, latency

        # A new message while ZENO is still talking IS a barge-in, whether it
        # was typed or spoken. Handling it here stops the previous turn's
        # audio and closes it, instead of leaving it orphaned mid-sentence
        # with its own SPEAKING events arriving against a superseded turn.
        if conversation_state.current() in {conversation_state.SPEAKING,
                                            conversation_state.ADVISORY}:
            conversation_state.barge_in(source="new-message")

        turn_id = conversation_state.begin_turn(requested_id)
        latency.begin(turn_id, kind=kind, message_preview=message)
        # A typed turn has no speech endpoint, so the clock starts here.
        if kind == "typed":
            latency.mark(turn_id, "stt_final")
        conversation_state.enter("UNDERSTANDING", source="web", turn_id=turn_id)
        return turn_id
    except Exception:  # noqa: BLE001 -- diagnostics never block a conversation
        return requested_id or ""


def _turn_state(turn_id: str, state: str, detail: str = "") -> None:
    if not turn_id:
        return
    try:
        from reyes_agent import conversation_state

        conversation_state.enter(state, source="web", turn_id=turn_id, detail=detail)
    except Exception:  # noqa: BLE001
        pass


def _finish_turn(turn_id: str) -> None:
    """The MODEL is done -- but the turn is not over until audio has played.

    Closing the state machine here was wrong and running it proved it: the
    browser starts TTS only after the reply arrives, so its SPEAKING report
    landed on an already-finished turn and was (correctly) rejected as
    stale. The machine then sat at IDLE while ZENO was audibly talking.

    So this records the timeline and leaves the turn OPEN. The browser
    closes it via /api/turn/end once audio finishes, and a turn that is
    never closed is superseded by the next `begin_turn`, so nothing leaks.
    """
    if not turn_id:
        return
    try:
        from reyes_agent import latency

        latency.finish(turn_id)
    except Exception:  # noqa: BLE001
        pass


def _end_turn(turn_id: str) -> None:
    if not turn_id:
        return
    try:
        from reyes_agent import conversation_state

        conversation_state.end_turn(turn_id)
    except Exception:  # noqa: BLE001
        pass


def _fast_local_reply(message: str):
    """Return only a policy-approved local reply, if any.

    Agent Space navigation is presentation-only: it performs no tool work
    and reads no private content, so a provider call would add only latency.
    """
    try:
        import re

        from reyes_agent import agent_presence, agent_runtime, notification_bus
        from reyes_agent.voice.latency_governor import FastReply, reply_for

        normalized = " ".join(re.sub(r"[^a-z0-9_ ]+", " ", str(message).casefold()).split())
        presence_reply = agent_presence.handle_command(message)
        if presence_reply is not None:
            return FastReply(presence_reply, "agent_presence")
        mode, focus = "", ""
        if normalized in {"show me the agent space", "show agent space", "open agent space",
                          "show all your agents", "show me all your agents"}:
            mode = "space"
        elif normalized in {"show council mode", "open council mode", "show the council"}:
            mode = "council"
        elif normalized in {"who is active right now", "who s active right now",
                            "show active agents", "show active tasks"}:
            mode = "active"
        elif normalized in {"show active handoffs", "show me all agent conversations",
                            "show agent conversations", "show conversation flow"}:
            mode = "flow"
        elif normalized in {"return to zeno", "focus on zeno", "open zeno"}:
            mode, focus = "space", "zeno"
        else:
            match = re.fullmatch(r"(?:focus on|open) ([a-z0-9_]+)", normalized)
            aliases = {"hermes": "hermes_comm"}
            candidate = aliases.get(match.group(1), match.group(1)) if match else ""
            if candidate in agent_runtime.AGENT_ROLES:
                mode, focus = "detail", candidate
        if mode:
            notification_bus.publish({"type": "agent_space", "mode": mode, "focus": focus})
            label = (focus or "agent space").replace("hermes_comm", "Hermes").replace("_", " ")
            return FastReply(f"Opening {label}.", "agent_space")

        return reply_for(message)
    except Exception:  # noqa: BLE001 -- optimisation never gates the real brain
        return None


def _mark_fast_reply(turn_id: str) -> None:
    """Record truthful local stages without pretending a model was called."""
    try:
        from reyes_agent import latency

        for mark_name in ("intent_ready", "context_ready", "first_sentence_ready"):
            latency.mark(turn_id, mark_name)
        latency.finish(turn_id)
    except Exception:  # noqa: BLE001
        pass


def _record_latency(stage: str, t0: float) -> None:
    """Feed the conversation latency recorder (p50/p95/p99). Best-effort;
    instrumentation must never affect a turn."""
    try:
        from reyes_agent.conversation.latency_metrics import get_latency_recorder
        get_latency_recorder().record(stage, (time.perf_counter() - t0) * 1000.0)
    except Exception:  # noqa: BLE001
        pass


def _conversation_turn(
    context, message: str, callbacks: dict[str, Any] | None = None,
    voice_identity: dict[str, Any] | None = None, turn_id: str = "",
) -> dict[str, Any]:
    """One serialized mutable-history turn, always executed by the worker pool."""
    _lat_t0 = time.perf_counter()
    from reyes_agent.agent import run_agent
    from reyes_agent.memory_manager import trim_history
    from reyes_agent.performance_monitor import measure

    from reyes_agent import speaker_identity

    callbacks = callbacks or {}
    realtime_session = None
    wake_engine = None
    if voice_identity is not None:
        try:
            from reyes_agent.voice import realtime_session
            from reyes_agent.wake import get_wake_engine

            wake_engine = get_wake_engine()

            if realtime_session.is_standby(message):
                realtime_session.end("owner standby phrase")
                wake_engine.standby()
                _finish_turn(turn_id)
                _end_turn(turn_id)
                return {"reply": "Standing by.", "tool_calls": []}
            realtime_session.start()
            realtime_session.touch()
            wake_engine.begin_processing()
        except Exception:  # noqa: BLE001 -- local voice fallback still works
            realtime_session = None
    try:
        from reyes_agent import intelligence

        intelligence.update_situation(recent_command=message, current_task="conversation", current_step="planning")
    except Exception:  # noqa: BLE001
        intelligence = None
    while not _lock.acquire(timeout=0.1):
        context.check_cancelled()
    try:
        context.progress("planning")
        # An unknown voice gets a clean, non-persistent conversation instead
        # of the shared history (which could contain Divine's previous private
        # turns).  This applies the identity result before a provider prompt
        # is built, not after an answer was already generated.
        source = "voice" if voice_identity else "typed"
        with speaker_identity.use_context(voice_identity, source=source):
            use_shared_history = speaker_identity.current_context().may_access_private_data
            history = _history if use_shared_history else [{"role": "user", "content": message}]
            turn_start = len(history)
            if use_shared_history:
                history.append({"role": "user", "content": message})
            tool_calls: list[dict[str, Any]] = []

            def on_tool_call(name: str, tool_input: dict, tool_id: str) -> None:
                context.check_cancelled()
                tool_calls.append({"name": name, "input": tool_input})
                # Say what is being done, while it is being done. A person
                # asked to check something says "let me look" BEFORE looking;
                # four silent seconds read as a fault even when the answer is
                # perfect. Only fires on spoken turns, once per turn, and only
                # when the work is slow enough for the silence to be felt.
                if voice_identity is not None:
                    try:
                        from reyes_agent.voice import narration

                        narration.narrate(name, spoken_turn=True)
                    except Exception:  # noqa: BLE001
                        pass
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
                if intelligence is not None:
                    intelligence.update_situation(current_task="conversation", current_step=stage)
                callback = callbacks.get("stage")
                if callback:
                    callback({"type": "stage", "stage": stage})

            try:
                with measure("ai_turn"):
                    run_agent(
                        history,
                        on_text=on_text if callbacks.get("text") else None,
                        on_tool_call=on_tool_call,
                        on_tool_result=on_tool_result,
                        on_stage=on_stage,
                        cancel_check=context.check_cancelled,
                        turn_id=turn_id,
                        # A voice turn is one ZENO will SAY, so it gets the
                        # spoken-reply style. `voice_identity` is present
                        # only on turns that arrived as speech.
                        spoken=voice_identity is not None,
                    )
                reply = history[-1]["content"]
            except BaseException:
                # An error is a real conversation state, not just an
                # exception -- the machine has to see it or the UI is left
                # showing THINKING forever.
                _turn_state(turn_id, "ERROR", "the turn failed")
                # A failed turn has no audio coming, so it ends here rather
                # than waiting for a browser callback that will never arrive.
                _end_turn(turn_id)
                if use_shared_history:
                    del history[turn_start:]
                raise
            finally:
                if use_shared_history:
                    trim_history(history)
                _finish_turn(turn_id)
            if realtime_session is not None:
                try:
                    realtime_session.touch(turn=True)
                except Exception:
                    pass
            _record_latency("full_task", _lat_t0)
            return {"reply": reply, "tool_calls": tool_calls}
    finally:
        _lock.release()
        if wake_engine is not None:
            try:
                wake_engine.finish_processing()
            except Exception:
                pass


def _background_result(handle, timeout: float) -> Any:
    try:
        return handle.result(timeout)
    except Exception as exc:  # noqa: BLE001 -- convert runtime/provider failures to HTTP responses
        from reyes_agent.provider import ProviderError
        from reyes_agent.worker_pool import TaskCancelled, TaskDeadlineExceeded
        from reyes_agent.voice.stt import STTError
        from reyes_agent.voice.tts import TTSError

        if isinstance(exc, ProviderError):
            raise HTTPException(502, str(exc)) from exc
        if isinstance(exc, TTSError):
            raise HTTPException(502, str(exc)) from exc
        if isinstance(exc, STTError):
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

    from reyes_agent.intelligence import get_runtime_control, update_situation

    control = get_runtime_control()
    control_reply, message = control.handle_user_message(message)
    if control_reply is not None:
        return {"reply": control_reply, "tool_calls": [], "interrupted": True}
    update_situation(recent_command=message, current_task="conversation", current_step="planning")

    try:
        from reyes_agent.voice import narration

        narration.begin_turn(turn_id)
    except Exception:  # noqa: BLE001
        pass
    fast_reply = _fast_local_reply(message)
    if fast_reply is not None:
        turn_id = _open_turn(message, req.turn_id, kind=req.turn_kind)
        _mark_fast_reply(turn_id)
        return {
            "reply": fast_reply.text, "tool_calls": [], "interrupted": False,
            "local_fast_path": True, "intent": fast_reply.intent,
        }

    from reyes_agent.worker_pool import PRIORITY_BRAIN, get_worker_pool

    voice_identity = _validated_voice_identity(req.voice_identity, req.voice_identity_proof)
    turn_id = _open_turn(message, req.turn_id, kind=req.turn_kind)
    handle = get_worker_pool().submit(
        _conversation_turn, message, voice_identity=voice_identity, turn_id=turn_id,
        name="chat", priority=PRIORITY_BRAIN,
        timeout=config.AI_REQUEST_TIMEOUT_S + 60, with_context=True,
    )
    control.register(handle, label="Conversation", kind="brain")
    try:
        return _background_result(handle, config.AI_REQUEST_TIMEOUT_S + 65)
    finally:
        control.release(handle)


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

    from reyes_agent.intelligence import get_runtime_control, update_situation

    control = get_runtime_control()
    control_reply, message = control.handle_user_message(message)
    if control_reply is not None:
        def interrupted():
            yield f"data: {json.dumps({'type': 'text', 'text': control_reply})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'interrupted': True})}\n\n"
        return StreamingResponse(interrupted(), media_type="text/event-stream")
    update_situation(recent_command=message, current_task="conversation", current_step="planning")

    voice_identity = _validated_voice_identity(req.voice_identity, req.voice_identity_proof)
    turn_id = _open_turn(message, req.turn_id, kind=req.turn_kind)
    fast_reply = _fast_local_reply(message)

    if fast_reply is not None:
        def immediate():
            _mark_fast_reply(turn_id)
            yield f"data: {json.dumps({'type': 'stage', 'stage': 'responding', 'local': True})}\n\n"
            yield f"data: {json.dumps({'type': 'text', 'text': fast_reply.text, 'local': True, 'intent': fast_reply.intent})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'local': True})}\n\n"

        return StreamingResponse(immediate(), media_type="text/event-stream")

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
                    voice_identity=voice_identity, turn_id=turn_id,
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
        control.register(handle, label="Conversation", kind="brain")
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
            control.release(handle)

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


def _read_audio_upload(audio: UploadFile) -> bytes:
    """Read one bounded microphone clip before it enters the worker pool."""
    max_bytes = 25 * 1024 * 1024
    audio_bytes = audio.file.read(max_bytes + 1)
    if len(audio_bytes) > max_bytes:
        raise HTTPException(413, "Voice clip is larger than 25 MiB.")
    return audio_bytes


@app.post("/api/transcribe")
def transcribe_audio(request: Request, audio: UploadFile = File(...),
                     speaker_audio: UploadFile | None = File(None),
                     pending_text: str = Form("")) -> dict[str, Any]:
    """Transcribe one VAD-bounded browser clip without starting an agent turn.

    The desktop UI calls this from its single processed microphone stream.
    Keeping transcription separate from ``/api/voice-turn`` is important:
    normal room noise and wake-word listening must never execute an agent
    request merely because a clip was captured.
    """
    _require_desktop_mic_token(request)
    audio_bytes = _read_audio_upload(audio)
    # The WebM clip goes to STT; the small browser-generated PCM WAV copy is
    # used only locally for speaker comparison, then discarded in the worker.
    speaker_bytes = _read_audio_upload(speaker_audio) if speaker_audio is not None else b""
    if len(speaker_bytes) > 5 * 1024 * 1024:
        raise HTTPException(413, "Speaker PCM sample is larger than 5 MiB.")

    def transcribe_job(context) -> dict[str, Any]:
        from reyes_agent.voice.stt import transcribe_result
        from reyes_agent.performance_monitor import measure
        from reyes_agent.confidence import record
        from reyes_agent import speaker_identity
        from reyes_agent.voice.turn import detect as detect_turn
        from reyes_agent.voice.language_context import observe as observe_language

        context.progress("transcribing")
        identity = (speaker_identity.identify(speaker_bytes) if speaker_bytes else {
            "status": speaker_identity.INSUFFICIENT_AUDIO,
            "confidence": None,
            "reason": "No local PCM speaker sample was supplied.",
            "stored_audio": False,
        })
        with measure("voice_stt"):
            result = transcribe_result(audio_bytes)
        transcript = " ".join(part for part in (str(pending_text).strip(), str(result["transcript"]).strip()) if part)
        confidence = result.get("confidence")
        record("speech", confidence, "Deepgram final alternative" if confidence is not None else
               "Deepgram response did not provide a confidence value")
        signed_identity, proof = _issue_voice_identity(identity)
        turn = detect_turn(transcript)
        language = observe_language(transcript)
        return {"transcript": transcript, "confidence": confidence, "turn": turn,
                "language": language, "speaker": {**identity, **signed_identity}, "speaker_proof": proof}

    from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

    handle = get_worker_pool().submit(
        transcribe_job, name="voice-transcribe", priority=PRIORITY_VOICE,
        timeout=config.TRANSCRIBE_TIMEOUT_SECONDS + 2, with_context=True,
    )
    return _background_result(handle, config.TRANSCRIBE_TIMEOUT_SECONDS + 4)


@app.post("/api/voice-turn")
def voice_turn(audio: UploadFile = File(...), speaker_audio: UploadFile | None = File(None)) -> dict[str, Any]:
    """The browser's voice front door -- record in the page (mic button or
    wake word), post the clip here, get back what REYES heard and said.

    TTS is deliberately NOT done server-side for this endpoint: the web
    panel might be open from a phone on the LAN, and server-side SAPI/
    ElevenLabs audio plays on *this* machine's speakers, not the remote
    browser's. The browser speaks the reply itself (Web Speech API).
    """
    audio_bytes = _read_audio_upload(audio)
    speaker_bytes = _read_audio_upload(speaker_audio) if speaker_audio is not None else b""
    if len(speaker_bytes) > 5 * 1024 * 1024:
        raise HTTPException(413, "Speaker PCM sample is larger than 5 MiB.")

    def voice_job(context) -> dict[str, Any]:
        from reyes_agent.voice.stt import STTError, transcribe_result
        from reyes_agent.performance_monitor import measure
        from reyes_agent.confidence import record
        from reyes_agent import speaker_identity
        from reyes_agent.intelligence import get_runtime_control, update_situation

        control = get_runtime_control()
        control.register(context.handle, label="Voice command", kind="voice")
        try:
            context.progress("transcribing")
            try:
                with measure("voice_stt"):
                    stt_result = transcribe_result(audio_bytes)
                    transcript = str(stt_result["transcript"]).strip()
                    record("speech", stt_result.get("confidence"),
                           "Deepgram final alternative" if stt_result.get("confidence") is not None else
                           "Deepgram response did not provide a confidence value")
            except STTError as exc:
                raise RuntimeError(f"Couldn't hear that: {exc}") from exc
            if not transcript:
                return {"transcript": "", "reply": "", "tool_calls": []}
            # A completed voice utterance can interrupt a preceding turn. Do
            # not cancel this transcription task itself while returning its
            # truthful stop/pause acknowledgement.
            control_reply, transcript = control.handle_user_message(transcript, exclude_id=context.handle.id)
            if control_reply is not None:
                return {"transcript": transcript or "", "reply": control_reply, "tool_calls": [], "interrupted": True}
            update_situation(recent_command=transcript, current_task="voice conversation", current_step="planning")
            identity = (speaker_identity.identify(speaker_bytes) if speaker_bytes else {
                "status": speaker_identity.INSUFFICIENT_AUDIO, "confidence": None,
                "reason": "No local PCM speaker sample was supplied.", "stored_audio": False,
            })
            result = _conversation_turn(context, transcript, voice_identity=identity)
            signed_identity, proof = _issue_voice_identity(identity)
            return {"transcript": transcript, "speech_confidence": stt_result.get("confidence"),
                    "speaker": {**identity, **signed_identity}, "speaker_proof": proof, **result}
        finally:
            control.release(context.handle)

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


class FrontendAuditReport(BaseModel):
    avg_frame_ms: float = 0.0
    worst_frame_ms: float = 0.0
    heartbeat_delay_ms: float = 0.0
    messages_per_second: float = 0.0
    active_animation_loops: int = 0
    active_timers: int = 0


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


@app.post("/api/performance/frontend")
def performance_frontend(report: FrontendAuditReport) -> dict[str, bool]:
    """Receive opt-in WebView audit telemetry; never enables a render loop."""
    from reyes_agent.performance_monitor import record_frontend_audit

    record_frontend_audit(report.model_dump())
    return {"recorded": True}


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

    from reyes_agent import agent_runtime, confirmation, event_bus, heartbeat, intelligence, model_router, permissions, session_recovery
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

    try:
        from reyes_agent import anticipation, awareness

        observed = awareness.observe().as_dict()
        predicted = anticipation.predict_app()
        anticipated = {
            "readiness": anticipation.readiness(),
            "current_prediction": predicted.as_dict() if predicted else None,
        }
    except Exception as exc:  # noqa: BLE001 -- the dashboard names unavailable evidence
        observed = None
        anticipated = {"readiness": None, "current_prediction": None,
                       "error": type(exc).__name__}

    router_state = model_router.explain()
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
        "model": {"provider": router_state["active_provider"],
                  "measured": router_state["measured"],
                  "validation": router_state.get("validation", {})},
        "permissions": {"profile": permissions.ACTIVE_PROFILE},
        "events": event_bus.stats(),
        "pending_approvals": len(confirmation.list_pending()),
        "notices": len(heartbeat.list_notices()),
        "session": session_recovery.summary_line(_restore_report or {}),
        "intelligence": {
            "situation": intelligence.situation(),
            "capabilities": intelligence.capabilities(),
            "observed": observed,
            "anticipation": anticipated,
        },
    }


@app.get("/api/router")
def model_router_state() -> dict[str, Any]:
    """Model Router: which providers are genuinely available, how each
    route resolves, and MEASURED latency/health per provider."""
    from reyes_agent import model_router

    return model_router.explain()


@app.get("/api/providers")
def provider_states() -> dict[str, Any]:
    """Credential presence and real validation state, with no secret values."""
    from reyes_agent import provider_manager

    return provider_manager.status()


@app.post("/api/providers/{provider}/validate")
def validate_provider(provider: str) -> dict[str, Any]:
    """Run one bounded real provider probe in FastAPI's sync worker pool."""
    from reyes_agent import provider_manager

    try:
        result = provider_manager.validate(provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"provider": result, "registry": provider_manager.status()}


@app.get("/api/agents")
def agents_health() -> dict[str, Any]:
    """Real Agent Runtime state -- live threads, heartbeat ages, queue
    depths, metrics. Nothing here is estimated."""
    from reyes_agent import agent_runtime

    return agent_runtime.health()


@app.get("/api/hierarchy")
def agent_hierarchy() -> dict[str, Any]:
    """ZENO -> primary specialists -> their workers, with REAL capability
    status per worker. Backs the Subspace hierarchy view.

    Capability status is computed from the live tool registry on every
    call, so a worker drawn in Subspace can still report UNAVAILABLE --
    being visible is explicitly not a claim that it works.
    """
    from reyes_agent import agent_runtime, agent_teams
    from reyes_agent.tools.subagents import _SPECIALISTS

    teams = agent_teams.describe()
    health = agent_runtime.health()
    runtime_by_id = {a["agent"]: a for a in health["agents"]}

    primaries = []
    for agent_id, role in agent_runtime.AGENT_ROLES.items():
        rt = runtime_by_id.get(agent_id, {})
        team = teams["parents"].get(agent_id, {"workers": [], "count": 0})
        status, why = agent_runtime.presence_status(rt) if rt else (
            agent_runtime.S_OFFLINE, "no runtime snapshot")
        primaries.append({
            "agent": agent_id,
            "role": role,
            "description": (_SPECIALISTS.get(agent_id) or {}).get("description", ""),
            "state": rt.get("state", "standby"),
            # `status` is the single display truth -- see presence_status().
            "status": status,
            "status_reason": why,
            "alive": rt.get("alive", False),
            "healthy": rt.get("healthy", True),
            "queue_depth": rt.get("queue_depth", 0),
            "current_task": rt.get("current_task", ""),
            "last_task": rt.get("last_task", ""),
            "last_result": rt.get("last_result", ""),
            "last_error": rt.get("last_error", ""),
            "last_error_s_ago": rt.get("last_error_s_ago"),
            "heartbeat_age_s": rt.get("heartbeat_age_s"),
            "last_activity_s_ago": rt.get("last_activity_s_ago"),
            "uptime_s": rt.get("uptime_s", 0),
            "tasks_completed": rt.get("tasks_completed", 0),
            "tasks_failed": rt.get("tasks_failed", 0),
            "restarts": rt.get("restarts", 0),
            "workers": team["workers"],
            "worker_count": team["count"],
        })

    return {
        "root": "zeno",
        "owner": "divine",
        "max_depth": teams["max_depth"],
        "max_workers_per_task": teams["max_workers_per_task"],
        "worker_timeout_s": teams["worker_timeout_s"],
        "primaries": primaries,
        "total_workers": teams["total_workers"],
        "status_counts": teams["status_counts"],
        "agents_alive": health["agents_alive"],
        "agents_total": health["agents_total"],
    }


@app.get("/api/agent-space")
def agent_space_snapshot(limit: int = 60) -> dict[str, Any]:
    """Canonical, privacy-safe Agent Space projection.

    This composes the existing runtime/teams/Event Bus. It never starts an
    agent and it is not a second registry or scheduler.
    """
    from reyes_agent import agent_space

    return agent_space.snapshot(event_limit=max(10, min(100, limit)))


@app.get("/api/agent-space/{agent_id}")
def agent_space_detail(agent_id: str) -> dict[str, Any]:
    from reyes_agent import agent_space

    detail = agent_space.agent_detail(agent_id)
    if detail is None:
        raise HTTPException(404, "That agent is not registered.")
    return detail


@app.post("/api/agents/summon-all")
def summon_all_agents() -> dict[str, Any]:
    """Actually spawn every registered specialist's worker thread.

    This makes them genuinely alive -- real threads on their real queues,
    emitting real heartbeats -- rather than reporting 'standby' until first
    delegated to. It does NOT mark anyone as working: an agent that is alive
    with an empty queue is IDLE, and Subspace shows it that way. Making idle
    agents render as busy would destroy the one thing the view is for.

    Cost is real but small: each worker blocks on its queue when idle. The
    response reports the measured thread/RAM delta so the trade-off is
    visible rather than assumed.
    """
    import threading as _t

    from reyes_agent import agent_runtime

    def _rss_mb() -> float:
        try:
            import psutil

            return psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:  # noqa: BLE001
            return 0.0

    before_threads, before_rss = _t.active_count(), _rss_mb()
    started, already = [], []
    for agent_id in agent_runtime.AGENT_ROLES:
        w = agent_runtime.get_worker(agent_id)
        if w is not None and w.is_alive():
            already.append(agent_id)
            continue
        if agent_runtime.ensure_worker(agent_id) is not None:
            started.append(agent_id)

    health = agent_runtime.health()
    return {
        "started": started,
        "already_alive": already,
        "agents_alive": health["agents_alive"],
        "agents_total": health["agents_total"],
        "threads_before": before_threads,
        "threads_after": _t.active_count(),
        "rss_mb_before": round(before_rss, 1),
        "rss_mb_after": round(_rss_mb(), 1),
        "note": ("Alive and idle. None are marked working -- that only happens "
                 "when a real task is queued to them."),
    }


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


@app.get("/api/onboarding/status")
def onboarding_status() -> dict[str, Any]:
    from reyes_agent import microphone, provider_manager, user_profiles

    identity = user_profiles.status()
    return {
        **identity,
        "steps": {
            "owner": "READY" if identity.get("owner") else "REQUIRED",
            "local_permissions": "READY",
            "microphone": microphone.runtime_status().get("status", "NOT_CONFIGURED"),
            "voice": "CONFIGURED" if (config.ELEVENLABS_API_KEY or config.TTS_PROVIDER == "sapi") else "NOT_CONFIGURED",
            "ai_provider": provider_manager.status()["state"],
            "optional_integrations": "OPTIONAL",
            "security": "READY",
        },
    }


@app.post("/api/onboarding/owner")
def onboarding_owner(req: OwnerSetupRequest) -> dict[str, Any]:
    from reyes_agent import user_profiles

    try:
        profile = user_profiles.create_owner(
            req.display_name, timezone=req.timezone,
            language_preferences=req.language_preferences,
            assistant_preferences=req.assistant_preferences,
        )
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"state": "READY", "owner": profile}


@app.post("/api/permissions/{capability}")
def update_permission(capability: str, req: PermissionStateRequest) -> dict[str, Any]:
    """Persist a desktop-only owner choice used by the real execution gate."""
    from reyes_agent import permissions

    try:
        effective = permissions.set_state(capability, req.state)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"capability": capability, "state": effective,
            "policy": permissions.describe()}


@app.get("/api/confidence")
def confidence_status() -> dict[str, Any]:
    """Bounded, evidence-backed confidence diagnostics for the owner."""
    from reyes_agent import confidence

    return confidence.snapshot()


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


@app.get("/api/mini-status")
def mini_status() -> dict[str, Any]:
    """Small companion payload; it deliberately avoids dashboard snapshots."""
    from reyes_agent.kernel import get_kernel

    workers = get_kernel().diagnostics().get("workers", {})
    active = workers.get("active_tasks", [])
    task = active[0] if active else None
    agents: list[str] = []
    runtime = sys.modules.get("reyes_agent.agent_runtime")
    if runtime is not None:
        try:
            agents = list(runtime.health().get("working_now", []))
        except Exception:  # noqa: BLE001 -- companion status is best effort
            pass
    try:
        from reyes_agent.agent_presence import get_agent_presence

        summoned_agents = get_agent_presence().active_ids()
        agents = list(dict.fromkeys(agents + summoned_agents))
    except Exception:  # noqa: BLE001 -- presence must not break Mini status
        summoned_agents = []
    try:
        from reyes_agent.workflow_engine import get_workflow_engine

        workflow = get_workflow_engine().status()
    except Exception:  # noqa: BLE001 -- Mini Orb status remains best effort
        workflow = {"mode": "NORMAL"}
    try:
        from reyes_agent.remote_access import live_desktop_node
        live_desktop = live_desktop_node.status()
    except Exception:
        live_desktop = {"active": False, "session_id": "", "mode": ""}
    return {
        "task": task,
        "queue_depth": workers.get("queue_depth", 0),
        "active_count": len(active),
        "agents": agents,
        "summoned_agents": summoned_agents,
        "workflow": workflow,
        "live_desktop": live_desktop,
    }


@app.get("/api/live-desktop/status")
def local_live_desktop_status() -> dict[str, Any]:
    """Loopback-only status for the visible laptop privacy indicator."""
    from reyes_agent.remote_access import live_desktop_node

    return live_desktop_node.status()


@app.post("/api/live-desktop/end")
def local_live_desktop_end() -> dict[str, bool]:
    """Laptop-side emergency stop; the remote boundary never exposes it."""
    from reyes_agent.remote_access import live_desktop_node

    return {"ok": live_desktop_node.terminate_current()}


@app.get("/api/workflows")
def workflows_list() -> dict[str, Any]:
    """Saved owner-approved workflows and the one live workflow state."""
    from reyes_agent.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    return {"workflows": engine.list_workflows(), "runtime": engine.status()}


@app.post("/api/workflows/teach")
def workflows_teach(req: WorkflowControlRequest) -> dict[str, Any]:
    from reyes_agent.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    action = req.action.strip().lower()
    handlers = {
        "start": engine.start_teaching, "pause": engine.pause_teaching,
        "resume": engine.resume_teaching, "stop": engine.stop_teaching,
        "review": engine.review, "discard": engine.discard_teaching,
    }
    if action == "save":
        message = engine.save(req.name)
    elif action in handlers:
        message = handlers[action]()
    else:
        raise HTTPException(400, "Unknown workflow teaching action.")
    return {"message": message, "runtime": engine.status()}


@app.post("/api/workflows/run")
def workflows_run(req: WorkflowControlRequest) -> dict[str, Any]:
    from reyes_agent.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    action = req.action.strip().lower()
    if action == "start":
        message = engine.start_run(req.name)
    elif action == "confirm":
        # Keep local UI confirmations on the same Permission Engine path as
        # voice/agent calls; this endpoint must not become a bypass for a
        # cautious profile.
        from reyes_agent.tools import run_tool

        message = run_tool("workflow_confirm", {"name": req.name})
    elif action == "resume":
        message = engine.resume_run(req.name)
    elif action == "pause":
        message = engine.pause_run()
    elif action == "cancel":
        message = engine.cancel_run()
    else:
        raise HTTPException(400, "Unknown workflow run action.")
    return {"message": message, "runtime": engine.status()}


@app.get("/api/events/stats")
def events_stats() -> dict[str, Any]:
    from reyes_agent import event_bus

    return event_bus.stats()


@app.get("/api/missions")
def missions_list() -> list[dict[str, Any]]:
    from reyes_agent.tools.missions import list_missions_dicts

    return list_missions_dicts()


class ProjectDestinationRequest(BaseModel):
    project_name: str
    destination: str


@app.get("/api/projects/activity")
def projects_activity() -> dict[str, Any]:
    """A bounded live projection of observable project work.

    This is intentionally not a chain-of-thought endpoint. It exposes only
    destination, steps, files, tools, agent and reported outcomes.
    """
    from reyes_agent import project_activity

    return {"projects": project_activity.status()}


@app.post("/api/projects/destination")
def projects_destination(req: ProjectDestinationRequest) -> dict[str, Any]:
    name = req.project_name.strip()
    destination = req.destination.strip()
    if not name or len(name) > 160:
        raise HTTPException(400, "A valid project name is required.")
    if not destination or len(destination) > 500:
        raise HTTPException(400, "Choose Desktop, Documents, ZENO Projects, or a full folder path.")
    from reyes_agent import project_activity

    try:
        return {"project": project_activity.select_destination(name, destination)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TurnMarkRequest(BaseModel):
    """Browser-observed latency marks and conversation states.

    The browser owns the marks nothing else can see -- when the microphone
    heard speech start, when endpointing fired, when audio actually reached
    the speaker. Those are the endpoints of the numbers the owner feels, so
    they cannot be inferred server-side.
    """
    turn_id: str
    mark: str = ""
    state: str = ""
    at: float | None = None
    detail: str = ""
    source: str = "browser"


class WakeAckMarkRequest(BaseModel):
    detected_at: float
    audio_started_at: float
    phrase: str = ""
    source: str = "mini-orb"


class BargeInMarkRequest(BaseModel):
    detected_at: float
    audio_stopped_at: float
    source: str = "browser"


@app.post("/api/turn/mark")
def turn_mark(req: TurnMarkRequest) -> dict[str, Any]:
    from reyes_agent import conversation_state, latency

    if not req.turn_id or len(req.turn_id) > 64:
        raise HTTPException(400, "A valid turn_id is required.")
    stored = latency.mark(req.turn_id, req.mark, req.at) if req.mark else False
    transition = None
    if req.state:
        result = conversation_state.enter(
            req.state.upper(), source=str(req.source or "browser")[:64],
            turn_id=req.turn_id, detail=req.detail)
        transition = result.as_dict()
    return {"marked": stored, "transition": transition}


@app.post("/api/diagnostics/wake-ack")
def wake_ack_mark(req: WakeAckMarkRequest) -> dict[str, Any]:
    from reyes_agent import latency

    try:
        return latency.record_wake_ack(
            detected_at=req.detected_at, audio_started_at=req.audio_started_at,
            phrase=req.phrase, source=req.source,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/diagnostics/barge-in")
def barge_in_mark(req: BargeInMarkRequest) -> dict[str, Any]:
    from reyes_agent import latency

    try:
        return latency.record_barge_in(
            detected_at=req.detected_at, audio_stopped_at=req.audio_stopped_at, source=req.source,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/turn/end")
def turn_end(req: TurnMarkRequest) -> dict[str, Any]:
    """The browser finished playing (or skipped) the reply audio.

    This is what actually closes a turn, because only the browser knows
    when the owner stopped hearing ZENO.
    """
    _end_turn(req.turn_id)
    from reyes_agent import conversation_state

    return {"state": conversation_state.current()}


@app.post("/api/turn/barge-in")
def turn_barge_in() -> dict[str, Any]:
    """The user cut in while ZENO was speaking.

    Routed through the state machine so the interrupted turn is closed and
    its late events cannot re-assert SPEAKING afterwards.
    """
    from reyes_agent import conversation_state

    return {"transition": conversation_state.barge_in(source="browser").as_dict()}


@app.get("/api/diagnostics/conversation")
def diagnostics_conversation() -> dict[str, Any]:
    """Developer diagnostics: current state plus duplicate-listener evidence."""
    from reyes_agent import conversation_state

    return {"state": conversation_state.snapshot(),
            "duplicates": conversation_state.duplicate_report()}


@app.get("/api/diagnostics/latency")
def diagnostics_latency(limit: int = 50) -> dict[str, Any]:
    """Developer diagnostics: the turn timeline and its percentiles."""
    from reyes_agent import latency

    return {"summary": latency.summary(limit=limit),
            "recent": latency.recent(limit=10),
            "marks": list(latency.MARKS)}


class BuildTaskRequest(BaseModel):
    task_id: str = ""


@app.get("/api/build/tasks")
def build_tasks() -> dict[str, Any]:
    """Live state of real build tasks -- what the Activity panel renders.

    Every field here originates in an executor that observed something:
    a verified file write, a captured process line, an HTTP response. There
    is no estimated or simulated progress in this payload.
    """
    from reyes_agent import task_engine

    return {"tasks": task_engine.active()}


@app.post("/api/build/cancel")
def build_cancel(req: BuildTaskRequest) -> dict[str, Any]:
    """Cancel Task button. Stops the work AND the processes it started."""
    from reyes_agent import task_engine

    task = task_engine.get(req.task_id) if req.task_id else task_engine.latest_open()
    if task is None:
        raise HTTPException(404, "No build task is running.")
    return {"task": task_engine.cancel(task.id, "Cancelled from the Activity panel.")}


@app.post("/api/build/open-folder")
def build_open_folder(req: BuildTaskRequest) -> dict[str, Any]:
    """Open Folder button -- only ever the task's own output folder."""
    from reyes_agent import task_engine
    from reyes_agent.executors import application

    task = task_engine.get(req.task_id) if req.task_id else task_engine.latest_open()
    if task is None or not task.output_path:
        raise HTTPException(404, "That build has no output folder yet.")
    ok, message = application.open_folder(Path(task.output_path))
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message, "path": task.output_path}


@app.post("/api/build/open-preview")
def build_open_preview(req: BuildTaskRequest) -> dict[str, Any]:
    """Open Website button. Refuses if the server is not actually responding."""
    from reyes_agent import task_engine
    from reyes_agent.executors import application, preview

    task = task_engine.get(req.task_id) if req.task_id else task_engine.latest_open()
    if task is None or not task.preview_url:
        raise HTTPException(404, "That build has no preview server.")
    responding, detail = preview.probe(task.preview_url)
    if not responding:
        raise HTTPException(409, detail)
    ok, message = application.open_url(task.preview_url)
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message, "url": task.preview_url}


class WebsiteProjectRequest(BaseModel):
    location: str


@app.get("/api/website/projects")
def website_projects() -> dict[str, Any]:
    """Website Studio inventory plus the actual managed preview record."""
    from reyes_agent import website_builder
    from reyes_agent.executors import preview

    projects = []
    for item in website_builder.projects():
        copy = dict(item)
        copy["preview"] = preview.for_project(Path(item["location"]))
        projects.append(copy)
    return {"projects": projects}


@app.post("/api/website/open-folder")
def website_open_folder(req: WebsiteProjectRequest) -> dict[str, Any]:
    from reyes_agent import website_builder
    from reyes_agent.executors import application

    root = website_builder.safe_project_root(Path(req.location).expanduser())
    ok, message = application.open_folder(root)
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message, "path": str(root)}


@app.post("/api/website/inspect")
def website_inspect(req: WebsiteProjectRequest) -> dict[str, Any]:
    from reyes_agent import website_builder

    root = website_builder.safe_project_root(Path(req.location).expanduser())
    return {"findings": website_builder.inspect(root)}


@app.post("/api/website/visual-inspect")
def website_visual_inspect(req: WebsiteProjectRequest) -> dict[str, Any]:
    from reyes_agent import website_builder

    try:
        return website_builder.visual_inspect(Path(req.location).expanduser())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc


class NotificationSettingsRequest(BaseModel):
    enabled: bool | None = None
    read_aloud: bool | None = None
    desktop_toast: bool | None = None
    priority_only: bool | None = None
    do_not_disturb: bool | None = None
    volume: float | None = None
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


class NotificationStateRequest(BaseModel):
    state: str
    reply: str = ""


@app.get("/api/notifications")
def notifications_status() -> dict[str, Any]:
    """Settings, listener state, unread count and recent history."""
    from reyes_agent import notifications

    return notifications.status()


@app.get("/api/notifications/history")
def notifications_history(limit: int = 50, state: str = "",
                          include_dismissed: bool = False) -> list[dict[str, Any]]:
    from reyes_agent import notifications

    return notifications.history(limit=limit, state=state,
                                 include_dismissed=include_dismissed)


@app.post("/api/notifications/settings")
def notifications_set_settings(req: NotificationSettingsRequest) -> dict[str, Any]:
    """Persist settings, and start/stop the listener to match immediately --
    turning notifications off must actually stop polling, not just hide it."""
    from reyes_agent import notifications

    was_enabled = notifications.load_settings().enabled
    saved = notifications.save_settings(**req.model_dump(exclude_none=True))
    if saved.enabled and not was_enabled:
        try:
            from reyes_agent import notification_listener

            notification_listener.start_background()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "settings": saved.as_dict(),
            "note": ("Listener starts on the next boot if it is not already running."
                     if saved.enabled else
                     "Notifications are off; the system listener stops at the next restart.")}


@app.post("/api/notifications/{notification_id}/state")
def notifications_set_state(notification_id: int, req: NotificationStateRequest) -> dict[str, Any]:
    from reyes_agent import notifications

    ok = notifications.set_state(notification_id, req.state.strip().upper(), req.reply)
    if not ok:
        raise HTTPException(400, "unknown notification or invalid state")
    return {"ok": True, "id": notification_id, "state": req.state.strip().upper()}


class MicrophoneRuntimeRequest(BaseModel):
    status: str
    detail: str = ""
    source: str = "dashboard"
    audio_received: bool = False
    device_id: str = ""


class PerformanceFeatureSettingsRequest(BaseModel):
    dream_mode: bool | None = None
    dashboard_updates: bool | None = None
    cursor_eye_tracking: bool | None = None
    eye_tracking_fps: str | None = None
    performance_mode: str | None = None


@app.get("/api/microphone/diagnose")
def microphone_diagnose(browser_error: str = "", permission_state: str = "",
                        selected_device: str = "") -> dict[str, Any]:
    """Distinguish actual Windows, WebView2, device and capture faults.

    Reads Windows privacy policy READ-ONLY and never changes a system
    setting -- if Windows is the blocker, the user is told exactly which
    toggle to flip.
    """
    from reyes_agent import microphone

    return microphone.diagnose(browser_error, permission_state, selected_device).as_dict()


@app.get("/api/microphone/status")
def microphone_status() -> dict[str, Any]:
    """The latest browser-observed capture evidence; no audio is retained."""
    from reyes_agent import microphone

    return microphone.runtime_status()


@app.post("/api/microphone/runtime")
def microphone_runtime(payload: MicrophoneRuntimeRequest, request: Request) -> dict[str, Any]:
    """Accept compact browser capture lifecycle evidence from the current owner."""
    from reyes_agent import microphone

    _require_desktop_mic_token(request)
    try:
        return microphone.report_runtime(
            payload.status, detail=payload.detail, source=payload.source,
            audio_received=payload.audio_received, device_id=payload.device_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/performance-features/settings")
def performance_feature_settings() -> dict[str, Any]:
    from reyes_agent import performance_features

    return {"settings": performance_features.load_settings().as_dict(),
            "dream": performance_features.dream_status()}


@app.post("/api/performance-features/settings")
def update_performance_feature_settings(request: PerformanceFeatureSettingsRequest) -> dict[str, Any]:
    from reyes_agent import event_bus, performance_features

    changes = request.model_dump(exclude_none=True)
    settings = performance_features.save_settings(**changes)
    event_bus.publish("performance.features_changed", settings.as_dict(), source="settings")
    return {"settings": settings.as_dict(), "dream": performance_features.dream_status()}


class AwarenessSettingsRequest(BaseModel):
    visual_awareness: bool | None = None
    microphone_recognition: bool | None = None
    system_audio_recognition: bool | None = None
    rolling_buffer: bool | None = None
    screen_interval_s: int | None = None
    rolling_seconds: int | None = None


class VisualAnalysisRequest(BaseModel):
    question: str = "Describe what is visible."
    lookback_seconds: int = 0


@app.get("/api/speaker/profile")
def speaker_profile() -> dict[str, Any]:
    """Profile status only; no vector, recording or secret ever leaves ZENO."""
    from reyes_agent import speaker_identity

    return speaker_identity.enrollment_status()


@app.post("/api/speaker/enroll")
def speaker_enroll(clips: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Store a fresh Divine profile from multiple browser-captured WAV clips."""
    from reyes_agent import speaker_identity
    from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

    if not 5 <= len(clips) <= 8:
        raise HTTPException(400, "Provide 5 to 8 varied Divine voice recordings.")
    audio_clips = [_read_audio_upload(clip) for clip in clips]
    if sum(len(clip) for clip in audio_clips) > 20 * 1024 * 1024:
        raise HTTPException(413, "Voice-profile recordings exceed the 20 MiB combined limit.")
    handle = get_worker_pool().submit(
        lambda _context: speaker_identity.enroll(audio_clips), name="speaker-enroll",
        priority=PRIORITY_VOICE, timeout=45, with_context=True,
    )
    try:
        return _background_result(handle, 50)
    except HTTPException as exc:
        raise HTTPException(exc.status_code, str(exc.detail)) from exc


@app.delete("/api/speaker/profile")
def speaker_delete_profile() -> dict[str, Any]:
    from reyes_agent import speaker_identity

    return speaker_identity.delete_profile()


@app.get("/api/awareness/settings")
def awareness_settings() -> dict[str, Any]:
    from reyes_agent import visual_awareness

    return visual_awareness.settings()


@app.post("/api/awareness/settings")
def awareness_set_settings(req: AwarenessSettingsRequest) -> dict[str, Any]:
    from reyes_agent import visual_awareness

    return visual_awareness.update_settings(**req.model_dump(exclude_none=True))


@app.post("/api/awareness/clear-visual-history")
def awareness_clear_visual_history() -> dict[str, Any]:
    from reyes_agent import visual_awareness

    return visual_awareness.clear_visual_history()


@app.post("/api/awareness/clear-audio-history")
def awareness_clear_audio_history() -> dict[str, Any]:
    from reyes_agent import visual_awareness

    return visual_awareness.clear_audio_history()


@app.post("/api/audio/recognize")
def recognize_uploaded_audio(audio: UploadFile = File(...)) -> dict[str, Any]:
    """Recognize a user-provided short clip; the request worker owns I/O."""
    from reyes_agent import audio_recognition
    from reyes_agent.worker_pool import PRIORITY_VOICE, get_worker_pool

    audio_bytes = _read_audio_upload(audio)
    handle = get_worker_pool().submit(
        lambda _context: audio_recognition.recognize(audio_bytes, source="uploaded"),
        name="audio-recognize-upload", priority=PRIORITY_VOICE, timeout=30, with_context=True,
    )
    return _background_result(handle, 35)


@app.post("/api/visual/analyze")
def analyze_visual(req: VisualAnalysisRequest) -> dict[str, Any]:
    """One explicit, bounded screen/video analysis outside the HTTP/UI thread."""
    from reyes_agent import video_recognition
    from reyes_agent.worker_pool import PRIORITY_BACKGROUND, get_worker_pool

    handle = get_worker_pool().submit(
        lambda _context: video_recognition.analyze(req.question, lookback_seconds=req.lookback_seconds),
        name="visual-analyze", priority=PRIORITY_BACKGROUND, timeout=60, with_context=True,
    )
    return _background_result(handle, 65)


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


# --- Phone Companion: dedicated authenticated remote surface ------------
# The former LAN pairing token and file APIs intentionally do not survive
# this replacement: a phone must never be able to call desktop /api routes.
_PHONE_SCOPES = {"status", "talk", "missions", "agents", "saved_routines"}

class PhonePairRequest(BaseModel):
    token: str
    name: str

class PhoneCredentialRequest(BaseModel):
    credential: dict[str, Any]
    challenge: str

class PhoneLoginRequest(BaseModel):
    device_id: str

class PhoneCommandRequest(BaseModel):
    command_id: str
    nonce: str
    timestamp: float
    message: str

class PhoneMicOfferRequest(BaseModel):
    sdp: str
    type: str = "offer"

class PhoneMicMetricsRequest(BaseModel):
    rtt_ms: float | None = None
    jitter_ms: float | None = None
    packets_lost: int | None = None
    packets_sent: int | None = None
    battery: float | None = None
    network: str = ""

class PhoneScopesRequest(BaseModel):
    scopes: list[str]

def _phone_origin(request: Request) -> tuple[str, str]:
    """Return the externally-visible HTTPS origin/RP ID.

    Cloudflare Access terminates TLS, so it supplies X-Forwarded-Host and
    X-Forwarded-Proto. Direct loopback is useful only for the desktop admin
    panel and cannot perform WebAuthn registration.
    """
    visible_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    host = (request.url.hostname or visible_host.split(":", 1)[0]).lower()
    tailscale_identity = bool(request.headers.get("tailscale-user-login"))
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).lower()
    # Tailscale Serve terminates a valid tailnet HTTPS certificate and then
    # uses loopback HTTP for the private backend hop. It supplies a verified
    # identity header and retains the public .ts.net Host.
    if tailscale_identity and host.endswith(".ts.net"):
        proto = "https"
    if proto == "http" and bool(getattr(config, "PHONE_COMPANION_LOCAL_ENABLED", False)):
        peer = request.client.host if request.client else ""
        try:
            peer_private = ipaddress.ip_address(peer).is_private
            host_private = ipaddress.ip_address(host).is_private
        except ValueError:
            peer_private = host_private = False
        port = request.url.port or 80
        if peer_private and host_private and port == int(config.PHONE_COMPANION_PORT):
            # Chrome must independently report this exact origin as a secure
            # context before the frontend attempts WebAuthn. Accepting the
            # origin here does not bypass that browser requirement.
            return f"http://{visible_host.lower()}", host
    if proto != "https" or not host or host in {"127.0.0.1", "localhost"}:
        raise HTTPException(503, "BIOMETRIC_UNAVAILABLE_IN_CURRENT_ORIGIN")
    configured = os.environ.get("ZENO_PHONE_PUBLIC_HOST", "").strip().lower()
    if configured and host != configured:
        raise HTTPException(403, "Unexpected Phone Companion host.")
    return f"https://{host}", host

def _loopback(request: Request) -> None:
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Desktop-only endpoint.")


@app.get("/api/tool-library")
def universal_tool_library(request: Request, state: str = "", q: str = "",
                           limit: int = 100) -> dict[str, Any]:
    """Read-only desktop inventory; never returns secret values or runs tools."""
    _loopback(request)
    from reyes_agent.tools import universal_catalog

    return universal_catalog.query(state=state, text=q, limit=limit)


@app.get("/api/tool-library/health")
def universal_tool_library_health(request: Request) -> dict[str, Any]:
    """One local health view over the real tool runtime and catalog."""
    _loopback(request)
    from reyes_agent.tools import universal_catalog
    from reyes_agent.tools.universal_registry import (
        contract_status,
        get_global_tool_registry,
    )

    return {
        "catalog": universal_catalog.status(),
        "registry": get_global_tool_registry().health(),
        "contract": contract_status(),
    }

def _phone_session(request: Request, zeno_phone_session: str | None = Cookie(default=None)):
    from reyes_agent.phone_security import get_phone_security
    bearer = request.headers.get("authorization", "")
    token = zeno_phone_session or (bearer[7:].strip() if bearer.lower().startswith("bearer ") else "")
    try:
        return get_phone_security().session(token, request.headers.get("x-zeno-csrf", ""),
                                            request.method not in {"GET", "HEAD"})
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc


def _phone_session_response(payload: dict[str, Any], login: dict[str, Any],
                            request: Request) -> Response:
    """Return JSON and persist one scheme-correct HttpOnly phone session."""
    response = Response(json.dumps(payload), media_type="application/json")
    visible_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip().lower()
    response.set_cookie(
        "zeno_phone_session", login["session"], httponly=True,
        secure=visible_scheme == "https", samesite="strict",
        max_age=1800, path="/",
    )
    return response

@app.get("/phone")
@app.get("/pair")
@app.get("/chat")
@app.get("/companion")
def phone_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "phone.html")


@app.get("/phone-manifest.json")
def phone_manifest() -> FileResponse:
    return FileResponse(_STATIC_DIR / "phone-manifest.json",
                        media_type="application/manifest+json")


@app.get("/phone-sw.js")
def phone_service_worker() -> FileResponse:
    return FileResponse(_STATIC_DIR / "phone-sw.js",
                        media_type="application/javascript")

@app.get("/mic")
def phone_mic_page() -> FileResponse:
    # NEVER cached. The page carries its own inline script, so a cached copy
    # means the phone keeps running an OLD version -- which is exactly how a
    # fix that was verified on the server never reached the device, and an
    # error message that had already been corrected kept appearing. A few
    # kilobytes on each load is a trivial price for the phone always running
    # the code that is actually on disk.
    return FileResponse(_STATIC_DIR / "mic.html", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache", "Expires": "0"})

@app.post("/api/phone/admin/pairing")
def phone_create_pairing(request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent import phone_companion

    offer = phone_companion.pairing_offer(all_routes=True)
    if not offer.get("ok"):
        raise HTTPException(503, offer.get("reason", "No local companion route is ready."))
    offer["manual_url"] = offer["origin"] + "/companion?code=" + offer["manual_code"]
    return offer

@app.get("/api/phone/admin/devices")
def phone_devices(request: Request) -> list[dict[str, Any]]:
    _loopback(request)
    from reyes_agent.phone_security import get_phone_security
    return get_phone_security().devices()

@app.post("/api/phone/admin/devices/{device_id}/{state}")
async def phone_set_device(device_id: str, state: str, request: Request) -> dict[str, bool]:
    _loopback(request)
    from reyes_agent.phone_security import get_phone_security
    try:
        get_phone_security().set_device(device_id, state=state.upper())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if state.upper() in {"LOCKED", "REVOKED", "EXPIRED"}:
        from reyes_agent.remote_mic import get_remote_mic_runtime
        await get_remote_mic_runtime().close(device_id)
    return {"ok": True}

@app.post("/api/phone/admin/devices/{device_id}/scopes")
def phone_set_device_scopes(device_id: str, req: PhoneScopesRequest,
                            request: Request) -> dict[str, Any]:
    """Desktop-only capability editor; remote audio is never ambient authority."""
    _loopback(request)
    allowed = _PHONE_SCOPES | {"remote_audio_send"}
    scopes = {str(item).strip().lower() for item in req.scopes}
    if not scopes <= allowed:
        raise HTTPException(400, "Unknown phone capability.")
    from reyes_agent.phone_security import get_phone_security
    get_phone_security().set_device(device_id, scopes=scopes)
    return {"ok": True, "scopes": sorted(scopes)}

@app.get("/api/phone/admin/mic/status")
def phone_admin_mic_status(request: Request) -> dict[str, Any]:
    _loopback(request)
    from reyes_agent.remote_mic import get_remote_mic_runtime
    return get_remote_mic_runtime().status()

@app.post("/api/phone/admin/mic/stop/{device_id}")
async def phone_admin_mic_stop(device_id: str, request: Request) -> dict[str, bool]:
    _loopback(request)
    from reyes_agent.remote_mic import get_remote_mic_runtime
    await get_remote_mic_runtime().close(device_id)
    return {"ok": True}


@app.post("/api/phone/admin/devices/{device_id}/role/{role}")
def phone_set_device_role(device_id: str, role: str, request: Request) -> dict[str, bool]:
    """Desktop-only explicit owner/trusted/guest/service role assignment."""
    _loopback(request)
    from reyes_agent.phone_security import get_phone_security
    try:
        get_phone_security().set_role(device_id, role)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}

@app.post("/api/phone/pair/options")
def phone_pair_options(req: PhonePairRequest, request: Request) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security
    origin, rp_id = _phone_origin(request)
    try:
        return get_phone_security().registration_options(req.token, req.name, rp_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc

@app.post("/api/phone/pair/complete")
def phone_pair_complete(req: PhoneCredentialRequest, request: Request) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security
    origin, rp_id = _phone_origin(request)
    try:
        device_id = get_phone_security().finish_registration(req.credential, req.challenge, origin, rp_id)
    except Exception as exc:
        raise HTTPException(403, f"Secure device verification failed: {exc}") from exc
    return {"state": "PENDING_APPROVAL", "device_id": device_id}

class PhoneLocalPairRequest(BaseModel):
    token: str = ""
    key: str = ""           # standing microphone key: does not expire
    device_name: str = ""


class PhoneStandingMicPairRequest(BaseModel):
    key: str = ""
    device_name: str = ""


class PhoneCompanionPairRequest(BaseModel):
    token: str = ""
    device_name: str = "Divine's Redmi 14C"
    browser: str = "Chrome"
    device_public_key: dict[str, Any]


class PhoneDeviceAuthRequest(BaseModel):
    device_id: str
    challenge: str = ""
    signature: str = ""


class PhoneOutputRequest(BaseModel):
    output: str = "AUTO"


class PhoneRoutePreferenceRequest(BaseModel):
    route: str = "AUTO"


class PhoneTaskRequest(BaseModel):
    task_id: str


class PhoneWebAuthnEnrollmentRequest(BaseModel):
    credential: dict[str, Any]
    challenge: str


@app.post("/api/phone/pair/local")
def phone_pair_local(req: PhoneLocalPairRequest, request: Request) -> Response:
    """LAN pairing with a one-time token. No WebAuthn, no biometrics.

    WebAuthn is unavailable on an http:// origin, so on the local network it
    leaves the phone stuck on "Verify this device". This path proves
    possession of the QR code instead, and grants ONLY remote_audio_send --
    the phone becomes a microphone and nothing more.

    The WebAuthn endpoints above are untouched and become the right path
    again the moment ZENO is served over real HTTPS.
    """
    from reyes_agent.phone_security import get_phone_security

    token, key = (req.token or "").strip(), (req.key or "").strip()
    if not token and not key:
        raise HTTPException(400, "No pairing code was supplied. Scan the QR code "
                                 "again, or open the link it contains.")
    peer = request.client.host if request.client else ""
    try:
        # The standing key wins when both are present: it is what a phone
        # re-presents on every reconnect, and it is the one that survives.
        paired = (get_phone_security().pair_with_mic_key(key, req.device_name, peer)
                  if key else
                  get_phone_security().pair_local(token, req.device_name))
    except PermissionError as exc:
        # A plain string, never a structure -- the phone renders `detail`
        # directly, and an object here is what produced "[object Object]".
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Pairing failed: {type(exc).__name__}") from exc

    session = paired.pop("session")
    response = Response(json.dumps({"state": "PAIRED", **paired}),
                        media_type="application/json")
    # `secure` MUST follow the real scheme. A Secure cookie is silently
    # DROPPED by the browser on an http:// origin -- the phone would pair,
    # look successful, then fail every later call with 401 because it never
    # stored the session. That is exactly the "connected but nothing happens"
    # symptom. Over LAN HTTP the session's protection is that it is
    # unguessable, expires in 30 minutes, and carries one scope.
    response.set_cookie("zeno_phone_session", session, httponly=True,
                        secure=request.url.scheme == "https",
                        samesite="strict", max_age=1800, path="/")
    return response


@app.post("/api/phone/pair/key")
def phone_pair_standing_mic(req: PhoneStandingMicPairRequest,
                            request: Request) -> Response:
    """Re-pair an audio-only phone using the owner's standing local QR.

    The key is accepted only from a socket peer on one of this laptop's live
    local networks.  It grants the same single ``remote_audio_send`` scope as
    the short-lived QR; it is not a companion-control credential.
    """
    from reyes_agent.phone_security import get_phone_security

    key = (req.key or "").strip()
    if not key:
        raise HTTPException(400, "No standing microphone key was supplied.")
    try:
        paired = get_phone_security().pair_with_mic_key(
            key, req.device_name,
            peer_ip=(request.client.host if request.client else ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Pairing failed: {type(exc).__name__}") from exc

    session = paired.pop("session")
    response = Response(json.dumps({"state": "PAIRED", **paired}),
                        media_type="application/json")
    response.set_cookie("zeno_phone_session", session, httponly=True,
                        secure=request.url.scheme == "https",
                        samesite="strict", max_age=1800, path="/")
    return response


@app.post("/api/phone/companion/pair/local")
def phone_companion_pair_local(req: PhoneCompanionPairRequest,
                               request: Request) -> dict[str, Any]:
    """Pin a browser-generated device key, pending explicit PC approval."""
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_access import policy

    peer = request.client.host if request.client else "unknown"
    rate = policy.check_rate("pair", peer)
    if not rate.allowed:
        raise HTTPException(429, f"Too many pairing attempts; retry in {rate.retry_after:.0f}s.")
    try:
        return get_phone_security().pair_companion_local(
            req.token, req.device_name, req.device_public_key, req.browser)
    except (PermissionError, ValueError) as exc:
        policy.check_rate("pair_failure", peer)
        raise HTTPException(403, str(exc)) from exc


@app.get("/api/phone/companion/pair/status")
def phone_companion_pair_status(device_id: str) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security

    try:
        return get_phone_security().pairing_status(device_id)
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/phone/companion/auth/options")
def phone_companion_auth_options(req: PhoneDeviceAuthRequest,
                                 request: Request) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_access import policy

    peer = request.client.host if request.client else "unknown"
    if not policy.check_rate("login", peer).allowed:
        raise HTTPException(429, "Too many authentication attempts.")
    try:
        return get_phone_security().device_authentication_options(req.device_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.post("/api/phone/companion/auth/complete")
def phone_companion_auth_complete(req: PhoneDeviceAuthRequest,
                                  request: Request) -> Response:
    from reyes_agent.phone_security import get_phone_security

    try:
        login = get_phone_security().finish_device_authentication(
            req.device_id, req.challenge, req.signature)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    if login.get("biometric_required"):
        return Response(json.dumps(login), media_type="application/json")
    return _phone_session_response(
        {key: value for key, value in login.items() if key != "session"},
        login, request)


@app.post("/api/phone/webauthn/enroll/options")
def phone_webauthn_enroll_options(request: Request,
                                  session=Depends(_phone_session)) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security

    _, rp_id = _phone_origin(request)
    try:
        return get_phone_security().webauthn_enrollment_options(
            session["device_id"], rp_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.post("/api/phone/webauthn/enroll/complete")
def phone_webauthn_enroll_complete(req: PhoneWebAuthnEnrollmentRequest,
                                   request: Request,
                                   session=Depends(_phone_session)) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security

    origin, rp_id = _phone_origin(request)
    try:
        return get_phone_security().finish_webauthn_enrollment(
            session["device_id"], req.credential, req.challenge, origin, rp_id)
    except Exception as exc:
        raise HTTPException(403, f"Platform verification enrollment failed: {exc}") from exc


@app.post("/api/voice/enrol")
def enrol_owner_voice(request: Request) -> dict[str, Any]:
    """Learn the owner's voice from the LIVE microphone.

    This must run in the server process. Audio arrives here, and the
    AudioManager is a per-process singleton -- a capture started anywhere
    else subscribes to an empty stream and reports hearing nothing, which is
    exactly what happened on the first attempt.
    """
    _loopback(request)
    from reyes_agent.identity.speaker.capture import enrol_from_live_microphone

    return enrol_from_live_microphone(timeout_s=90)


@app.get("/api/mode")
def assistant_mode(request: Request) -> dict[str, Any]:
    """The live runtime state the Ultron HUD renders.

    Read-only and loopback-free on purpose: the dashboard is already served
    on loopback, and a page that cannot ask what mode it is in would have to
    guess -- which is the failure this endpoint exists to prevent.
    """
    from reyes_agent import modes

    return {**modes.status(), "runtime": modes.runtime_state().as_dict()}


class ModeRequest(BaseModel):
    mode: str = ""


@app.post("/api/mode")
def set_assistant_mode(req: ModeRequest, request: Request) -> dict[str, Any]:
    """Change mode. The BACKEND decides; the page reflects."""
    _loopback(request)
    from reyes_agent import modes

    result = modes.set_mode(req.mode, source="dashboard")
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "Unknown mode."))
    return result


@app.get("/api/phone/networks")
def phone_networks(request: Request) -> dict[str, Any]:
    """Every local route the phone could use -- Wi-Fi and hotspot together.

    Loopback only. This lists the laptop's own addresses, which is exactly
    the map an attacker would want and the owner already has.
    """
    _loopback(request)
    from reyes_agent.remote_mic import routes

    return routes.status()


class PhoneQrRequest(BaseModel):
    mode: str = ""          # AUTO | LAN_WIFI | LAPTOP_HOTSPOT
    save_to: str = ""


@app.post("/api/phone/networks/qr")
def phone_network_qr(req: PhoneQrRequest, request: Request) -> dict[str, Any]:
    """A fresh pairing QR for a chosen network. Either route, any time."""
    _loopback(request)
    from reyes_agent.remote_mic import connect

    result = (connect.save_qr(req.mode, req.save_to) if req.save_to
              else connect.offer(req.mode))
    if not result.get("ok"):
        raise HTTPException(409, result.get("reason", "No usable network."))
    return result


@app.get("/api/phone/mic/levels")
def phone_mic_levels(request: Request) -> dict[str, Any]:
    """How LOUD the incoming audio actually is, per source.

    The quality score measures jitter and clipping, so a silent stream can
    score 86 and look healthy -- which is exactly what happened: frames
    arriving at 52/s, VAD firing, and every transcript coming back with zero
    characters. None of the existing status endpoints reported signal LEVEL,
    so there was no way to tell "the phone is sending speech" from "the phone
    is sending a stable stream of almost nothing".

    RMS is that missing number. Rough guide for 16-bit audio: under ~150 is
    effectively silence, 300-800 is faint or distant, 1500+ is someone
    speaking normally into the phone.
    """
    _loopback(request)
    from reyes_agent.audio.manager import get_audio_manager

    state = get_audio_manager().status()
    sources = state.get("sources") or {}
    readable = {}
    for name, metrics in sources.items():
        rms = float((metrics or {}).get("rms", 0) or 0)
        readable[name] = {
            "rms": round(rms, 1),
            "noise_floor": round(float((metrics or {}).get("noise_floor", 0) or 0), 1),
            "score": (metrics or {}).get("score"),
            "reads_as": ("silence" if rms < 150 else
                         "faint" if rms < 400 else
                         "quiet speech" if rms < 1200 else "normal speech"),
        }
    return {"active_source": state.get("active_source") or state.get("physical_owner"),
            "published": state.get("published"), "sources": readable,
            "guide": "under 150 = silence, 400-1200 = quiet, 1200+ = normal speech"}


@app.get("/api/phone/mic/network")
def phone_mic_network(request: Request) -> dict[str, Any]:
    """Which network the phone is ACTUALLY on, not which one was offered.

    The answer is derived from the peer address of the live session, so
    "I'm receiving your microphone through my laptop hotspot" is a fact
    read off the socket rather than a guess from whichever QR was scanned.
    """
    _loopback(request)
    from reyes_agent.remote_mic import get_remote_mic_runtime, routes

    runtime = get_remote_mic_runtime()
    live = runtime.status()
    peer = str(live.get("peer_ip") or "")
    route = routes.selector().route_for_peer(peer) if peer else None
    return {
        "connected": bool(peer),
        "peer_ip": peer,
        "mode": route.mode if route else "",
        "label": route.label if route else "",
        "via": route.as_dict() if route else None,
        "spoken": (
            f"I'm receiving your phone microphone through "
            f"{'my laptop hotspot' if route and route.mode == routes.HOTSPOT else 'the normal Wi-Fi network'}."
            if route else
            "No phone microphone is connected right now."),
        "audio": live.get("state", ""),
    }


@app.post("/api/phone/login/options")
def phone_login_options(req: PhoneLoginRequest, request: Request) -> dict[str, Any]:
    from reyes_agent.phone_security import get_phone_security
    _, rp_id = _phone_origin(request)
    try:
        return get_phone_security().authentication_options(req.device_id, rp_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc

@app.post("/api/phone/login/complete")
def phone_login_complete(req: PhoneCredentialRequest, request: Request) -> Response:
    from reyes_agent.phone_security import get_phone_security
    origin, rp_id = _phone_origin(request)
    try:
        login = get_phone_security().finish_authentication(req.credential, req.challenge, origin, rp_id)
    except Exception as exc:
        raise HTTPException(403, f"Secure device verification failed: {exc}") from exc
    return _phone_session_response(
        {"device_id": login["device_id"], "csrf": login["csrf"],
         "auth_level": login.get("auth_level", "OWNER_VERIFIED")},
        login, request)

@app.get("/api/phone/status")
def phone_status(request: Request, session=Depends(_phone_session)) -> dict[str, Any]:
    from reyes_agent import phone_companion

    return {"desktop": "ready", "device_id": session["device_id"], "device": session["name"],
            "role": session["role"], "auth_level": session["auth_level"],
            "scopes": json.loads(session["scopes"]), "runtime": _boot_state["phase"],
            "audio_output": phone_companion.audio_output(session["device_id"]),
            "route": phone_companion.route_for_peer(request.client.host if request.client else "")}


@app.get("/api/phone/tasks")
def phone_tasks(request: Request, session=Depends(_phone_session)) -> list[dict[str, Any]]:
    if "missions" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot read missions or tasks.")
    from reyes_agent import phone_companion

    return phone_companion.tasks()


@app.post("/api/phone/tasks/cancel")
def phone_cancel_task(req: PhoneTaskRequest, request: Request,
                      session=Depends(_phone_session)) -> dict[str, Any]:
    if "talk" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot cancel tasks.")
    from reyes_agent import phone_companion

    if not phone_companion.cancel(req.task_id):
        raise HTTPException(404, "That task is not active or cannot be cancelled.")
    return {"ok": True, "task_id": req.task_id, "state": "CANCEL_REQUESTED"}


@app.get("/api/phone/devices")
def phone_companion_devices(request: Request,
                            session=Depends(_phone_session)) -> list[dict[str, Any]]:
    from reyes_agent.phone_security import OWNER_AUTH, get_phone_security

    devices = get_phone_security().devices()
    if session["auth_level"] != OWNER_AUTH:
        devices = [item for item in devices if item["device_id"] == session["device_id"]]
    safe_keys = {"device_id", "name", "state", "role", "device_type", "browser", "pinned",
                 "owner_device", "preferred_route", "last_network", "biometric_enabled",
                 "authentication", "last_activity"}
    return [{key: item.get(key) for key in safe_keys} for item in devices]


@app.get("/api/phone/audio/output")
def phone_audio_output(request: Request, session=Depends(_phone_session)) -> dict[str, str]:
    from reyes_agent import phone_companion

    return {"output": phone_companion.audio_output(session["device_id"])}


@app.post("/api/phone/audio/output")
def phone_set_audio_output(req: PhoneOutputRequest, request: Request,
                           session=Depends(_phone_session)) -> dict[str, str]:
    from reyes_agent import phone_companion

    try:
        output = phone_companion.set_audio_output(session["device_id"], req.output)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"output": output}


@app.post("/api/phone/route")
def phone_set_route(req: PhoneRoutePreferenceRequest, request: Request,
                    session=Depends(_phone_session)) -> dict[str, str]:
    from reyes_agent.phone_security import get_phone_security

    try:
        get_phone_security().set_preferred_route(session["device_id"], req.route)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"route": req.route.strip().upper()}


@app.post("/api/phone/session/lock")
def phone_lock_session(request: Request, session=Depends(_phone_session)) -> dict[str, bool]:
    from reyes_agent.phone_security import get_phone_security

    get_phone_security().end_sessions(session["device_id"])
    return {"ok": True}


@app.get("/api/phone/health")
def phone_health(request: Request, session=Depends(_phone_session)) -> dict[str, Any]:
    if "status" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot read ZENO health.")
    from reyes_agent import phone_companion

    return phone_companion.health()


@app.get("/api/phone/agents")
def phone_agents(request: Request, session=Depends(_phone_session)) -> dict[str, Any]:
    if "agents" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot read agent state.")
    from reyes_agent import agent_space

    return agent_space.snapshot(event_limit=30, phone=True)


@app.get("/api/phone/approvals")
def phone_approvals(request: Request, session=Depends(_phone_session)) -> list[dict[str, Any]]:
    if "status" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot read pending approvals.")
    from reyes_agent import agent_space

    return agent_space.snapshot(event_limit=10, phone=True)["approvals"]


@app.post("/api/phone/tts")
def phone_tts(req: TTSRequest, request: Request,
              session=Depends(_phone_session)) -> Response:
    if "talk" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "This phone cannot request speech.")
    if not req.text.strip() or len(req.text) > 1200:
        raise HTTPException(400, "Speech text must be between 1 and 1200 characters.")
    from reyes_agent import phone_companion, voice_manager

    output = phone_companion.audio_output(session["device_id"])
    if output in {phone_companion.OUTPUT_PC, phone_companion.OUTPUT_HEADSET}:
        voice_manager.speak_queued(req.text, req.agent)
        return Response(status_code=204, headers={"X-Zeno-Audio-Output": output})
    try:
        audio = voice_manager.synthesize(req.text, req.agent)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Voice generation unavailable: {type(exc).__name__}") from exc
    if output == phone_companion.OUTPUT_BOTH:
        voice_manager.speak_cached_queued(audio, req.agent)
    return Response(audio, media_type="audio/mpeg", headers={"X-Zeno-Audio-Output": output})


def _remote_mic_command(context, message: str, identity: dict[str, Any],
                        requested_turn_id: str, device_id: str) -> dict[str, Any]:
    """Route remote audio through the established brain and desktop voice."""
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_access import policy
    from reyes_agent.voice_manager import cached_audio, speak_cached_queued, speak_queued

    device = next((item for item in get_phone_security().devices()
                   if item["device_id"] == device_id), None)
    if not device or device["state"] != "TRUSTED":
        raise PermissionError("Remote microphone device is no longer trusted.")
    decision = policy.evaluate(message, scopes=set(device["scopes"]))
    if not decision.allowed:
        reply = decision.reason
        hit = cached_audio(reply)
        speak_cached_queued(hit) if hit else speak_queued(reply)
        return {"reply": reply, "tool_calls": [], "blocked": True}

    turn_id = _open_turn(message, requested_turn_id, kind="voice")
    try:
        from reyes_agent import latency
        latency.mark(turn_id, "stt_final")
    except Exception:
        pass
    fast_reply = _fast_local_reply(message)
    if fast_reply is not None:
        _mark_fast_reply(turn_id)
        result = {"reply": fast_reply.text, "tool_calls": [], "local_fast_path": True}
    else:
        result = _conversation_turn(context, message, voice_identity=identity, turn_id=turn_id)
    reply = str(result.get("reply") or "")
    hit = cached_audio(reply)
    speak_cached_queued(hit) if hit else speak_queued(reply)
    # ZENO has answered, so a follow-up is now plausible without the name.
    # Opened HERE, on a real reply, rather than on hearing speech -- the
    # window has to be evidence that a conversation exists, not a hope.
    try:
        from reyes_agent.presentation import visit as _visit
        from reyes_agent.voice import continuity

        continuity.open_window(source="reply", visit=_visit.session().active)
    except Exception:  # noqa: BLE001
        pass
    _end_turn(turn_id)
    return result


@app.post("/api/phone/mic/offer")
async def phone_mic_offer(req: PhoneMicOfferRequest, request: Request,
                          session=Depends(_phone_session)) -> dict[str, str]:
    if not config.REMOTE_MIC_ENABLED:
        raise HTTPException(503, "Remote microphone is disabled on this ZENO.")
    scopes = set(json.loads(session["scopes"]))
    if "remote_audio_send" not in scopes:
        raise HTTPException(403, "This phone does not have REMOTE_AUDIO_SEND capability.")
    from reyes_agent.remote_access import policy
    if not policy.check_rate("remote_mic_offer", session["device_id"]).allowed:
        raise HTTPException(429, "Too many microphone connection attempts.")
    if len(req.sdp) > 128_000 or req.type != "offer":
        raise HTTPException(400, "Invalid WebRTC offer.")
    from reyes_agent.remote_mic import get_remote_mic_runtime
    runtime = get_remote_mic_runtime()
    runtime.set_command_handler(_remote_mic_command)
    try:
        return await runtime.offer(session["device_id"], req.sdp, req.type,
                                   session_expires=float(session["expires"]),
                                   peer_ip=(request.client.host if request.client else ""))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/phone/mic/metrics")
def phone_mic_metrics(req: PhoneMicMetricsRequest, request: Request,
                      session=Depends(_phone_session)) -> dict[str, bool]:
    if "remote_audio_send" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "REMOTE_AUDIO_SEND capability required.")
    from reyes_agent.remote_mic import get_remote_mic_runtime
    get_remote_mic_runtime().client_metrics(session["device_id"], req.model_dump())
    return {"ok": True}


@app.post("/api/phone/mic/close")
async def phone_mic_close(request: Request, session=Depends(_phone_session)) -> dict[str, bool]:
    from reyes_agent.remote_mic import get_remote_mic_runtime
    await get_remote_mic_runtime().close(session["device_id"])
    return {"ok": True}


@app.get("/api/phone/mic/status")
def phone_mic_status(request: Request, session=Depends(_phone_session)) -> dict[str, Any]:
    if "remote_audio_send" not in set(json.loads(session["scopes"])):
        raise HTTPException(403, "REMOTE_AUDIO_SEND capability required.")
    from reyes_agent.remote_mic import get_remote_mic_runtime
    return get_remote_mic_runtime().status()

@app.post("/api/phone/command")
def phone_command(req: PhoneCommandRequest, request: Request, session=Depends(_phone_session)) -> dict[str, Any]:
    if "talk" not in json.loads(session["scopes"]):
        raise HTTPException(403, "This phone is not permitted to talk to ZENO.")
    if not req.command_id or not req.nonce or abs(time.time() - req.timestamp) > 60 or len(req.message) > 4000:
        raise HTTPException(400, "Invalid, expired, or oversized command.")
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_access import policy
    rate = policy.check_rate("command", session["device_id"])
    if not rate.allowed:
        raise HTTPException(429, f"Too many commands; retry in {rate.retry_after:.0f}s.")
    decision = policy.evaluate(req.message, scopes=set(json.loads(session["scopes"])))
    if not decision.allowed:
        return {"command_id": req.command_id, "blocked": True,
                "category": decision.category, "response": {"reply": decision.reason}}
    if not get_phone_security().claim_command(session["device_id"], req.command_id, req.nonce):
        raise HTTPException(409, "Duplicate or replayed command.")
    from reyes_agent import event_bus
    event_bus.publish("phone.command_received", {"command_id": req.command_id, "device_id": session["device_id"]}, source="phone")
    # Reuse the established bounded worker-backed conversation endpoint; the
    # mobile client receives a compact final reply rather than desktop SSE.
    result = chat(ChatRequest(message=req.message.strip()))
    return {"command_id": req.command_id, "response": result}

@app.websocket("/ws/phone")
async def phone_events(websocket: WebSocket) -> None:
    """Small authenticated event feed; revocation is checked at every beat."""
    from reyes_agent import event_bus
    from reyes_agent.phone_security import get_phone_security
    from reyes_agent.remote_access import domains, policy
    from reyes_agent.remote_access.boundary import decision as remote_boundary

    allowed, _, _ = remote_boundary(
        websocket.url.path, websocket.headers,
        enabled=bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)),
        client_host=(websocket.client.host if websocket.client else ""),
        local_enabled=bool(getattr(config, "PHONE_COMPANION_LOCAL_ENABLED", False)),
    )
    if not allowed:
        await websocket.close(code=4403)
        return

    # ORIGIN CHECK. A WebSocket upgrade is not protected by CORS -- the
    # browser performs it regardless of origin -- so without this any page
    # the owner visits could open a socket that rides on the ambient session
    # cookie. Same-origin (no Origin header, e.g. the local phone page or a
    # native client) is allowed; a cross-origin upgrade must be on the
    # allow-list.
    origin = websocket.headers.get("origin", "")
    if origin:
        from urllib.parse import urlsplit

        parsed = urlsplit(origin)
        expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
        same_origin = (parsed.scheme == expected_scheme and
                       parsed.hostname == websocket.url.hostname and
                       (parsed.port or (443 if parsed.scheme == "https" else 80)) ==
                       (websocket.url.port or (443 if expected_scheme == "https" else 80)))
        if not same_origin and not domains.is_allowed_origin(origin):
            await websocket.close(code=4403)
            return
    # Reconnect storms are bounded per client.
    client = websocket.client.host if websocket.client else "unknown"
    if not policy.check_rate("ws_connect", client).allowed:
        await websocket.close(code=4429)
        return

    # A Bearer token is accepted so a cross-origin companion (whose
    # SameSite=strict cookie would never be sent) can connect at all.
    token = websocket.cookies.get("zeno_phone_session", "")
    header = websocket.headers.get("authorization", "")
    if not token and header.lower().startswith("bearer "):
        token = header[7:].strip()
    try:
        session = get_phone_security().session(token)
    except PermissionError:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    subscription = event_bus.subscribe()
    try:
        await websocket.send_json({"type": "connected", "device_id": session["device_id"]})
        import asyncio
        while True:
            try:
                # A short timeout creates a bounded revocation/health check and
                # avoids any timer or polling loop on the desktop UI thread.
                event = await asyncio.wait_for(asyncio.to_thread(subscription.get, True, 10.0), timeout=11.0)
                if event.type.startswith(("mission.", "agent.", "task.", "phone.")):
                    await websocket.send_json({"type": event.type, "payload": event.payload})
            except (queue.Empty, TimeoutError):
                get_phone_security().session(token)  # locked/revoked closes now
                await websocket.send_json({"type": "heartbeat"})
    except (PermissionError, WebSocketDisconnect):
        try: await websocket.close(code=4403)
        except Exception: pass
    finally:
        event_bus.unsubscribe(subscription)


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
    from reyes_agent.runtime_environment import require_safe_startup

    require_safe_startup()

    # ONE RUNTIME. Observed on this machine: three ZENO processes at once.
    # Only one held the ports; the others had still opened the microphone and
    # the speech queue, so the owner heard TWO VOICES answering one sentence
    # and heard "Checking" while sitting in silence. A port check could not
    # catch it -- the duplicate never reached the bind.
    #
    # This reuses the EXISTING SingleInstanceGuard (a Windows kernel mutex,
    # with an atomic O_EXCL file lock off Windows) rather than adding a second
    # mechanism. It takes its OWN name, because desktop_app.py spawns this
    # module as a child and holds the guard for the WINDOW: sharing one name
    # would make the server refuse to start for its own parent.
    from reyes_agent.single_instance import SingleInstanceGuard

    runtime_guard = SingleInstanceGuard(f"{config.ASSISTANT_NAME}-runtime",
                                        config.PROJECT_ROOT)
    if not runtime_guard.acquire():
        print(f"{config.ASSISTANT_NAME} is already running.")
        print("  Stop that one first, or use it -- two runtimes would both")
        print("  listen and both speak.")
        raise SystemExit(1)

    print(f"{config.ASSISTANT_NAME} panel:")
    print(f"  this machine -> http://127.0.0.1:8765")
    sockets: list[socket.socket] = []

    def bind(host: str, port: int) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(2048)
        listener.set_inheritable(True)
        return listener

    try:
        sockets.append(bind("127.0.0.1", 8765))
        if bool(getattr(config, "PHONE_COMPANION_LOCAL_ENABLED", False)):
            try:
                sockets.append(bind("0.0.0.0", int(config.PHONE_COMPANION_PORT)))
                print(f"  local phone -> http://<Wi-Fi-or-hotspot-IP>:{config.PHONE_COMPANION_PORT}")
                print("  phone boundary -> authenticated companion routes only")
            except OSError as exc:
                # A companion-port conflict must not take down the desktop.
                print(f"  local phone -> DEGRADED ({type(exc).__name__}: {exc})")
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        server.run(sockets=sockets)
    finally:
        for listener in sockets:
            try:
                listener.close()
            except OSError:
                pass
        # Hand the runtime back, so a clean stop does not leave a lock that
        # makes the NEXT start think ZENO is still running.
        runtime_guard.release()


if __name__ == "__main__":
    main()
