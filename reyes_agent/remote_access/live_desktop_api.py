"""Authenticated signalling routes for the ZENO Anywhere live desktop.

The owner endpoints use the same trusted browser session/CSRF gate as every
other ZENO Anywhere action.  The Windows endpoints use the existing paired
device credential.  No route returns a screenshot or a raw desktop frame.
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from reyes_agent.auth import get_owner_auth
from reyes_agent.remote_access import device_link, live_desktop, realtime
from reyes_agent.remote_access.cloud_api import require_trusted_owner


def _device(payload: dict[str, Any]) -> str:
    device_id = str(payload.get("device_id", ""))
    token = str(payload.get("token", ""))
    if not device_link.get_link().authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Invalid or revoked Windows device credential.")
    return device_id


def _owner_browser(token: str) -> str:
    info = get_owner_auth().session_info(token)
    if not info or not info.get("trusted"):
        raise HTTPException(status_code=403, detail="Trusted owner browser required.")
    return str(info.get("device_id", ""))


def _ice_servers() -> tuple[list[dict[str, Any]], str]:
    """Return authenticated ICE configuration without ever logging it.

    TURN credentials are necessarily disclosed to the two authenticated
    WebRTC peers. They come only from an operator secret and are never placed
    in the public PWA bundle or an unauthenticated response.
    """
    raw = os.environ.get("ZENO_WEBRTC_ICE_SERVERS_JSON", "").strip()
    if not raw:
        return [], "DIRECT_ONLY"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], "INVALID_CONFIGURATION"
    servers: list[dict[str, Any]] = []
    has_turn = False
    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict) or len(servers) >= 6:
            continue
        urls = item.get("urls")
        values = [urls] if isinstance(urls, str) else urls if isinstance(urls, list) else []
        clean_urls = [str(url)[:300] for url in values[:8]
                      if str(url).startswith(("stun:", "turn:", "turns:"))]
        if not clean_urls:
            continue
        has_turn = has_turn or any(url.startswith(("turn:", "turns:")) for url in clean_urls)
        server: dict[str, Any] = {"urls": clean_urls}
        if item.get("username") is not None:
            server["username"] = str(item.get("username"))[:256]
        if item.get("credential") is not None:
            server["credential"] = str(item.get("credential"))[:512]
        servers.append(server)
    return servers, "TURN_READY" if has_turn else "STUN_ONLY" if servers else "INVALID_CONFIGURATION"


def _publish(event_type: str, device_id: str, *, status: str = "") -> None:
    realtime.publish({"type": event_type, "target_device": device_id,
                      "status": status})


def register(app) -> None:
    owner = APIRouter(
        prefix="/api/owner", tags=["owner-live-desktop"],
        dependencies=[Depends(require_trusted_owner)],
    )
    node = APIRouter(prefix="/api/owner/device", tags=["windows-live-desktop"])

    @owner.get("/live-desktop/capabilities")
    def owner_capabilities(device_id: str,
                           _token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        state = device_link.get_link().device_state(device_id)
        caps = live_desktop.get_live_desktop().capabilities(device_id)
        ice, ice_state = _ice_servers()
        return {"device": state, "capabilities": caps,
                "ice_state": ice_state, "relay_configured": ice_state == "TURN_READY"}

    @owner.post("/live-desktop/sessions")
    def create_session(payload: dict = Body(...),
                       token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        browser = _owner_browser(token)
        target = str(payload.get("device_id", ""))
        state = device_link.get_link().device_state(target)
        if not state.get("known"):
            raise HTTPException(status_code=404, detail="Unknown Windows device.")
        if state.get("state") not in {device_link.ONLINE, device_link.BUSY}:
            raise HTTPException(status_code=409, detail="The Windows device is offline.")
        caps = live_desktop.get_live_desktop().capabilities(target)
        if not caps.get("available") or not caps.get("streaming_enabled"):
            raise HTTPException(status_code=409, detail=(
                caps.get("detail") or "Screen streaming is disabled on the Windows device."))
        mode = str(payload.get("mode", "VIEW_ONLY")).upper()
        if mode == "REMOTE_CONTROL":
            elevated = bool(getattr(get_owner_auth(), "session_elevated", lambda _token: False)(token))
            if not elevated:
                raise HTTPException(status_code=403,
                                    detail="A recent owner fingerprint step-up is required for remote control.")
            if not device_link.get_link().remote_control_enabled():
                raise HTTPException(status_code=403,
                                    detail="The ZENO remote-control kill switch is off.")
            if not caps.get("control_enabled"):
                raise HTTPException(status_code=403,
                                    detail="Remote input is disabled by the local Windows control switch.")
        monitor = str(payload.get("monitor", "display-1"))
        valid_monitors = {str(item.get("id")) for item in caps.get("monitors", [])}
        if monitor not in valid_monitors:
            raise HTTPException(status_code=400, detail="Selected display is unavailable.")
        if bool(payload.get("stream_audio")) and not caps.get("audio_available"):
            raise HTTPException(status_code=409,
                                detail="Computer-audio streaming is not available on this Windows node.")
        try:
            session = live_desktop.get_live_desktop().create(
                browser_device=browser, target_device=target, mode=mode,
                monitor=monitor, quality=str(payload.get("quality", "BALANCED")),
                show_cursor=bool(payload.get("show_cursor", True)),
                stream_audio=bool(payload.get("stream_audio", False)),
                ttl_s=float(payload.get("ttl_s", live_desktop.SESSION_TTL_S) or
                            live_desktop.SESSION_TTL_S),
            )
        except live_desktop.SessionCapacityExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ice, ice_state = _ice_servers()
        _publish("live_desktop.session_requested", target, status=session.state)
        return {**session.owner_view(), "ice_servers": ice,
                "ice_state": ice_state, "media_transport": "WEBRTC_DTLS_SRTP"}

    @owner.get("/live-desktop/sessions/{session_id}")
    def session_status(session_id: str,
                       token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        try:
            return live_desktop.get_live_desktop().session_for_owner(
                session_id, _owner_browser(token)).owner_view()
        except live_desktop.SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @owner.post("/live-desktop/sessions/{session_id}/signals")
    def owner_signal(session_id: str, payload: dict = Body(...),
                     token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        try:
            return live_desktop.get_live_desktop().owner_signal(
                session_id, _owner_browser(token), payload)
        except live_desktop.SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @owner.get("/live-desktop/sessions/{session_id}/signals")
    def owner_signals(session_id: str, after: int = 0, wait_s: float = 20.0,
                      token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        try:
            return live_desktop.get_live_desktop().owner_signals(
                session_id, _owner_browser(token), after=after, wait_s=wait_s)
        except live_desktop.SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @owner.post("/live-desktop/sessions/{session_id}/end")
    def owner_end(session_id: str, payload: dict = Body(default={}),
                  token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        browser = _owner_browser(token)
        try:
            session = live_desktop.get_live_desktop().session_for_owner(session_id, browser)
            ok = live_desktop.get_live_desktop().end_owner(
                session_id, browser, str(payload.get("reason") or "owner ended session"))
        except live_desktop.SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        _publish("live_desktop.session_ended", session.target_device, status="ENDED")
        return {"ok": ok, "state": "ENDED"}

    @owner.get("/agent-presence")
    def owner_presence(device_id: str,
                       _token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        return live_desktop.get_live_desktop().presence(device_id)

    @node.post("/live-desktop/register")
    def node_register(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        caps = live_desktop.get_live_desktop().register_capabilities(device, payload)
        return {"ok": True, "capabilities": caps}

    @node.post("/live-desktop/claim")
    def node_claim(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        session = live_desktop.get_live_desktop().claim(
            device, wait_s=float(payload.get("wait_s", 20) or 20))
        ice, ice_state = _ice_servers()
        return {"session": session, "ice_servers": ice, "ice_state": ice_state}

    @node.post("/live-desktop/signal")
    def node_signal(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        try:
            return live_desktop.get_live_desktop().device_signal(
                str(payload.get("session_id", "")), device,
                payload.get("signal") if isinstance(payload.get("signal"), dict) else {})
        except live_desktop.SessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @node.post("/live-desktop/status")
    def node_status(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        try:
            result = live_desktop.get_live_desktop().device_status(
                str(payload.get("session_id", "")), device,
                state=str(payload.get("state", "DEGRADED")),
                fps=float(payload.get("fps", 0) or 0),
                quality=str(payload.get("quality", "")),
                error=str(payload.get("error", "")),
            )
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        _publish("live_desktop.session_changed", device, status=str(result.get("state", "")))
        return result

    @node.post("/live-desktop/end")
    def node_end(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        try:
            ok = live_desktop.get_live_desktop().end_device(
                str(payload.get("session_id", "")), device,
                str(payload.get("reason") or "Windows node ended session"))
        except live_desktop.SessionAccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        _publish("live_desktop.session_ended", device, status="ENDED")
        return {"ok": ok}

    @node.post("/agent-presence")
    def node_presence(payload: dict = Body(...)) -> dict[str, Any]:
        device = _device(payload)
        projection = live_desktop.get_live_desktop().update_presence(device, payload)
        _publish("agent.presence_changed", device, status="CURRENT")
        return {"ok": True, "active": len(projection["active_agents"]),
                "at": projection["at"]}

    app.include_router(owner)
    app.include_router(node)
