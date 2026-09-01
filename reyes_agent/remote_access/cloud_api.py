"""Authenticated API between the web client and ZENO.

THE RULE THIS FILE EXISTS TO ENFORCE
------------------------------------
The browser never talks to a Windows automation tool. It talks to these
routes, which check a session, classify the request, and put a COMMAND on a
queue. The desktop pulls its own work. Nothing here executes anything.

Read the flow for "open Chrome on my laptop":

    POST /api/owner/command   -> session verified
                              -> policy.evaluate() classifies it
                              -> FINANCIAL/SENSITIVE refused outright
                              -> otherwise enqueued, status QUEUED
    (desktop) POST /claim     -> device token verified, status IN_FLIGHT
    (desktop) POST /ack       -> status ACKNOWLEDGED
    (desktop) POST /complete  -> status DONE or FAILED, with the real result
    GET /api/owner/command/id -> the owner sees whichever of those is true

At no point does the phone name a Python function, a shell command or a file
path that the desktop will run verbatim. It names a registered ACTION, and
the desktop decides what that means.

TWO SEPARATE IDENTITIES
-----------------------
`require_owner` authenticates a PERSON holding a session token.
`_device` authenticates a MACHINE holding a device token.
They are different tables, different lifetimes and different privileges. A
device token cannot read the owner's chat; an owner session cannot claim
another device's queue.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import (APIRouter, Body, Depends, File, Form, Header,
                     HTTPException, Request, UploadFile)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from urllib.parse import quote, urlsplit

from reyes_agent.auth import get_owner_auth
from reyes_agent.remote_access import (android_pairing, attachment_store,
                                       device_link, domains, live_desktop, media_store,
                                       policy, realtime, web_push)

router = APIRouter(prefix="/api/owner", tags=["owner"])
logger = logging.getLogger(__name__)


def _owner_activity_entries(limit: int, *, workspace_service: Any = None,
                            fallback: Any = None) -> list[dict[str, Any]]:
    """Prefer compact local workspace evidence, retaining cloud/device fallback."""
    count = max(1, min(int(limit), 100))
    try:
        if workspace_service is None:
            from reyes_agent.workspace import get_workspace_service

            workspace_service = get_workspace_service()
        compact = workspace_service.phone_snapshot()
        activities = compact.get("activities", []) if isinstance(compact, dict) else []
        entries = []
        for item in activities[:count]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "activity")[:40].casefold()
            category = "_".join(category.replace("-", " ").split()) or "activity"
            status = str(item.get("status") or "")[:40].upper()
            entries.append({
                "event": f"workspace_{category}",
                "summary": str(item.get("title") or "ZENO activity")[:240],
                "outcome": status.casefold(),
                "state": status,
                "at": float(item.get("updated_at") or 0.0),
            })
        if entries:
            return entries
    except Exception:  # local workspace is optional in a cloud gateway process
        pass
    if fallback is not None:
        return list(fallback(count))
    return device_link.get_link().activity(limit=count)

# Actions the desktop agent is willing to perform. The browser may name only
# these. An action outside this set is refused before it reaches a queue --
# so a compromised frontend cannot invent "run_shell".
REGISTERED_ACTIONS: dict[str, str] = {
    "ask": "READ_ONLY",             # put a question to ZENO
    "status": "READ_ONLY",          # read system status
    "memory_recall": "READ_ONLY",   # read memory
    "agent_status": "READ_ONLY",    # read the agent roster
    "task_status": "READ_ONLY",
    "conversation_snapshot": "READ_ONLY",
    "voice_turn": "READ_ONLY",
    "analyze_attachment": "READ_ONLY",
    "android_action": "STANDARD_DEVICE",
    "open_app": "STANDARD_DEVICE",  # open a named application
    "close_app": "SENSITIVE_DEVICE",
    "run_automation": "SENSITIVE_DEVICE",
}


def _client_identity(request: Request) -> str:
    client = getattr(request, "client", None)
    return (getattr(client, "host", "") or "unknown")[:80]


def _bearer(authorization: str | None, request: Request) -> str:
    """Session token from the Authorization header, or the cookie."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("zeno_session", "")


def _session_response(result, request: Request) -> JSONResponse:
    if not result.ok or result.session is None:
        raise HTTPException(status_code=401, detail=result.as_dict())
    session = result.session
    body = {"ok": True, "csrf": session.csrf, "expires_at": session.expires_at,
            "device": session.device_label, "device_id": session.device_id,
            "device_state": session.device_state,
            "trusted": session.device_state == "APPROVED"}
    response = JSONResponse(body)
    # A production reverse proxy normally terminates TLS before forwarding to
    # Uvicorn, so request.url.scheme may be ``http`` inside the container.
    # Production must still emit Secure cookies.  Only explicit development
    # mode permits cleartext localhost cookies.
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    secure = (not domains.dev_mode() or request.url.scheme == "https" or
              forwarded == "https")
    same_site = "none" if secure else "lax"
    # Cookie lifetimes track the auth service's own TTLs, so extending the
    # sign-in window is a one-place change (owner.REFRESH_TTL_S) and the cookie
    # never outlives, or dies before, the token it carries.
    from reyes_agent.auth import owner as _owner

    response.set_cookie("zeno_session", session.token, httponly=True, secure=secure,
                        samesite=same_site, max_age=_owner.ACCESS_TTL_S, path="/")
    response.set_cookie("zeno_refresh", session.refresh, httponly=True, secure=secure,
                        samesite=same_site, max_age=_owner.REFRESH_TTL_S,
                        path="/api/owner/auth")
    response.headers["Cache-Control"] = "no-store"
    return response


def _webauthn_context(request: Request) -> tuple[str, str]:
    from reyes_agent.remote_access import domains

    origin = str(request.headers.get("origin", "")).rstrip("/")
    if not domains.is_allowed_origin(origin):
        raise HTTPException(status_code=403, detail="WebAuthn origin is not allowed.")
    rp_id = domains.public_domain()
    if not rp_id and domains.dev_mode():
        host = (urlsplit(origin).hostname or "").casefold()
        if host in {"localhost", "127.0.0.1"}:
            rp_id = "localhost"
    if not rp_id:
        raise HTTPException(status_code=503, detail="WebAuthn RP ID is not configured.")
    return origin, rp_id


def require_owner(request: Request, authorization: str | None = Header(None),
                  x_zeno_csrf: str | None = Header(None)) -> str:
    """FastAPI dependency: a valid owner session, or 401.

    CSRF is required for state-changing methods only. A GET carrying a cookie
    cannot change anything, and demanding a header on every read would break
    ordinary navigation without buying protection.
    """
    token = _bearer(authorization, request)
    auth = get_owner_auth()
    needs_csrf = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    ok, reason = auth.verify(token, csrf=(x_zeno_csrf or ""), require_csrf=needs_csrf)
    if not ok:
        raise HTTPException(status_code=401, detail=reason or "Authentication required.")
    return token


def require_trusted_owner(request: Request,
                          authorization: str | None = Header(None),
                          x_zeno_csrf: str | None = Header(None)) -> str:
    token = require_owner(request, authorization, x_zeno_csrf)
    info = get_owner_auth().session_info(token)
    if not info or not info.get("trusted"):
        raise HTTPException(status_code=403,
                            detail="PENDING DEVICE: approve this browser from ZENO Windows.")
    return token


# --- auth ---------------------------------------------------------------
@router.get("/auth/status")
def auth_status() -> dict[str, Any]:
    """Unauthenticated on purpose: the login page must know whether an owner
    exists before anyone can log in. Reveals no secret -- only whether setup
    has been done."""
    return get_owner_auth().status()


@router.post("/auth/login")
def auth_login(request: Request, payload: dict = Body(...)) -> JSONResponse:
    nonce = str(payload.get("nonce", ""))
    if len(nonce) < 16:
        raise HTTPException(status_code=400, detail="A fresh login nonce is required.")
    result = get_owner_auth().login(
        str(payload.get("email", "")), str(payload.get("password", "")),
        identity=_client_identity(request),
        device_label=str(payload.get("device", ""))[:80],
        user_agent=str(request.headers.get("user-agent", ""))[:200],
        nonce=nonce, device_id=str(payload.get("device_id", ""))[:96])
    if not result.ok:
        # 429 when it is a rate limit, 401 when it is a wrong password. The
        # client needs to tell "wait" apart from "try again".
        raise HTTPException(status_code=429 if result.retry_after else 401,
                            detail=result.as_dict())
    return _session_response(result, request)


@router.post("/android/pairing/claim")
def android_pairing_claim(request: Request,
                          payload: dict = Body(...)) -> dict[str, Any]:
    """Consume a temporary QR/manual credential and register one phone.

    The returned permanent token is shown exactly once and the Android app
    seals it with Android Keystore. The device remains PENDING until a trusted
    owner session approves the android_control scope.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if (request.url.scheme != "https" and forwarded != "https" and
            not domains.dev_mode()):
        raise HTTPException(status_code=400, detail="Android pairing requires HTTPS.")
    rate = policy.check_rate("pair", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    try:
        android_pairing.get_store().consume(str(payload.get("credential", "")))
        registered = device_link.get_link().register(
            label=str(payload.get("label", "Android phone"))[:80],
            platform="android", approved=False, scopes=[],
            protocol_version=str(payload.get("protocol_version", "1.0.0"))[:32])
    except android_pairing.PairingError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        web_push.get_service().enqueue(
            "New Android companion", "Open ZENO Devices to approve the phone.",
            kind="security")
    except Exception as exc:
        # Pairing and one-time token delivery must not become unrecoverable
        # merely because an optional notification provider is unavailable.
        logger.warning("Android pairing notification unavailable: %s",
                       type(exc).__name__)
    return {
        "ok": True,
        "device_id": registered["device_id"],
        "token": registered["token"],
        "approval_state": registered["approval_state"],
    }


@router.post("/auth/refresh")
def auth_refresh(request: Request, payload: dict = Body(default={})) -> JSONResponse:
    result = get_owner_auth().refresh_session(
        str(payload.get("refresh", "") or request.cookies.get("zeno_refresh", "")),
        identity=_client_identity(request))
    if not result.ok:
        raise HTTPException(status_code=401, detail=result.as_dict())
    return _session_response(result, request)


@router.get("/auth/unlock/status")
def auth_unlock_status() -> dict[str, Any]:
    """Whether an unlock phrase exists, so the pending screen can offer it.
    Reveals nothing but a boolean."""
    from reyes_agent.auth import unlock as _unlock

    return _unlock.status()


@router.post("/auth/unlock")
def auth_unlock(request: Request, payload: dict = Body(...),
                authorization: str | None = Header(None),
                x_zeno_csrf: str | None = Header(None)) -> dict[str, Any]:
    """Approve THIS browser with the owner's unlock phrase, instead of walking
    to the PC. Requires an already password-authenticated session -- this is
    not a login bypass, it is the approval step done by a shared secret."""
    token = _bearer(authorization, request)
    auth = get_owner_auth()
    ok, reason = auth.verify(token, csrf=(x_zeno_csrf or ""), require_csrf=True)
    if not ok:
        raise HTTPException(status_code=401, detail=reason or "Sign in first.")
    info = auth.session_info(token)
    if not info:
        raise HTTPException(status_code=401, detail="Sign in first.")
    if info.get("trusted"):
        return {"ok": True, "trusted": True, "note": "already trusted"}

    from reyes_agent.auth import unlock as _unlock

    good, why = _unlock.get_unlock().verify(
        str(payload.get("phrase", "")), identity=_client_identity(request))
    if not good:
        # 429 for lockout so the client shows "wait"; 403 for a wrong phrase.
        code = 429 if "Wait" in why else 403
        raise HTTPException(status_code=code, detail=why)
    changed = auth.approve_browser_device(info["device_id"])
    updated = auth.session_info(token) or {}
    if not changed or not updated.get("trusted"):
        raise HTTPException(
            status_code=409,
            detail="This browser could not be approved in its current state.")
    return {"ok": True, "trusted": True}


@router.post("/auth/logout")
def auth_logout(request: Request, authorization: str | None = Header(None)) -> JSONResponse:
    # Deliberately no CSRF requirement: logging out is safe to over-trigger,
    # and refusing a logout because a header was missing leaves a live
    # session that the owner believes is closed.
    response = JSONResponse({"ok": get_owner_auth().logout(_bearer(authorization, request))})
    response.delete_cookie("zeno_session", path="/")
    response.delete_cookie("zeno_refresh", path="/api/owner/auth")
    return response


@router.get("/auth/session")
def auth_session(request: Request,
                 authorization: str | None = Header(None)) -> dict[str, Any]:
    token = _bearer(authorization, request)
    info = get_owner_auth().session_info(token)
    if info is None:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    return info


@router.post("/auth/passkey/options")
def passkey_login_options(request: Request) -> dict[str, Any]:
    rate = policy.check_rate("login", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    _origin, rp_id = _webauthn_context(request)
    try:
        return get_owner_auth().passkey_authentication_options(rp_id=rp_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/auth/passkey/complete")
def passkey_login_complete(request: Request, payload: dict = Body(...)) -> JSONResponse:
    rate = policy.check_rate("login", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    origin, rp_id = _webauthn_context(request)
    result = get_owner_auth().finish_passkey_authentication(
        payload.get("credential") if isinstance(payload.get("credential"), dict) else {},
        challenge=str(payload.get("challenge", "")), origin=origin, rp_id=rp_id,
        identity=_client_identity(request), device_label=str(payload.get("device", ""))[:80],
        user_agent=str(request.headers.get("user-agent", ""))[:200],
        device_id=str(payload.get("device_id", ""))[:96])
    return _session_response(result, request)


# --- fingerprint step-up: unlock desktop actions on THIS phone --------------
# A consequential action does not walk the owner back to the PC to approve it.
# On a signed-in, trusted phone the owner scans a fingerprint (a WebAuthn
# assertion, exactly like passkey login) and this session is elevated for a
# short window, during which the executor runs consequential tools directly.
@router.post("/auth/stepup/options")
def stepup_options(request: Request,
                   _token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
    rate = policy.check_rate("login", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    _origin, rp_id = _webauthn_context(request)
    try:
        return get_owner_auth().passkey_stepup_options(rp_id=rp_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/auth/stepup/complete")
def stepup_complete(request: Request, payload: dict = Body(...),
                    token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
    rate = policy.check_rate("login", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    origin, rp_id = _webauthn_context(request)
    ok, reason = get_owner_auth().finish_passkey_stepup(
        token,
        payload.get("credential") if isinstance(payload.get("credential"), dict) else {},
        challenge=str(payload.get("challenge", "")), origin=origin, rp_id=rp_id)
    if not ok:
        raise HTTPException(status_code=403, detail=reason or "Fingerprint step-up failed.")
    return {"ok": True, **get_owner_auth().elevation_status(token)}


@router.get("/auth/stepup/status")
def stepup_status(_request: Request,
                  token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
    return get_owner_auth().elevation_status(token)


@router.post("/auth/stepup/phrase")
def stepup_phrase(request: Request, payload: dict = Body(...),
                  token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
    """Unlock actions with the owner's unlock phrase -- the step-up's fallback
    where WebAuthn can't run (an ephemeral tunnel origin has no stable RP ID).
    The phone's own device lock still gates entry; this is the app-level secret,
    rate-limited and lockout-protected exactly like the browser-approval phrase."""
    from reyes_agent.auth import unlock

    rate = policy.check_rate("login", _client_identity(request))
    if not rate.allowed:
        raise HTTPException(status_code=429, detail=rate.as_dict())
    phrases = unlock.get_unlock()
    if not phrases.configured():
        raise HTTPException(status_code=409,
                            detail="No unlock phrase is set. Set one, or register a passkey.")
    ok, reason = phrases.verify(str(payload.get("phrase", "")),
                                identity=_client_identity(request))
    if not ok:
        raise HTTPException(status_code=403, detail=reason or "Incorrect unlock phrase.")
    get_owner_auth().elevate(token)
    return {"ok": True, **get_owner_auth().elevation_status(token)}


# --- devices ------------------------------------------------------------
def _device(device_id: str, token: str) -> str:
    if not device_link.get_link().authenticate(device_id, token):
        raise HTTPException(status_code=401, detail="Device authentication failed.")
    return device_id


@router.post("/device/heartbeat")
def device_heartbeat(payload: dict = Body(...)) -> dict[str, Any]:
    """The desktop agent says it is alive. Also its reconnect landing point."""
    link = device_link.get_link()
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    link.heartbeat(device_id, state=str(payload.get("state", "ONLINE")),
                   detail=str(payload.get("detail", "")))
    return {"ok": True, "state": link.device_state(device_id)}


@router.post("/device/claim")
def device_claim(payload: dict = Body(...)) -> dict[str, Any]:
    """The agent pulls queued work. This is the ONLY way work reaches it."""
    link = device_link.get_link()
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    link.heartbeat(device_id, state="ONLINE")
    commands = link.claim(device_id, limit=int(payload.get("limit", 5) or 5))
    return {"ok": True, "commands": [c.as_dict() for c in commands]}


@router.post("/device/ack")
def device_ack(payload: dict = Body(...)) -> dict[str, Any]:
    link = device_link.get_link()
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    return {"ok": link.acknowledge(str(payload.get("command_id", "")), device_id)}


def _voice_command(command_id: str, device_id: str):
    command = device_link.get_link().command(command_id)
    if (command is None or command.device_id != device_id or
            command.action != "voice_turn" or command.status not in {
                device_link.IN_FLIGHT, device_link.ACKNOWLEDGED}):
        raise HTTPException(status_code=403,
                            detail="Voice media is not bound to an active device command.")
    return command


def _attachment_command(command_id: str, device_id: str):
    command = device_link.get_link().command(command_id)
    if (command is None or command.device_id != device_id or
            command.action != "analyze_attachment" or command.status not in {
                device_link.IN_FLIGHT, device_link.ACKNOWLEDGED}):
        raise HTTPException(
            status_code=403,
            detail="Attachment is not bound to an active device command.")
    return command


@router.post("/device/media/read")
def device_media_read(payload: dict = Body(...)) -> Response:
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    command_id = str(payload.get("command_id", ""))
    command = _voice_command(command_id, device_id)
    media_id = str(payload.get("media_id", ""))
    if str(command.payload.get("media_id", "")) != media_id:
        raise HTTPException(status_code=403, detail="Voice media does not match the command.")
    try:
        blob = media_store.get_media_store().read_input(
            media_id, target_device=device_id, command_id=command_id)
    except media_store.MediaStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except media_store.MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (media_store.MediaAccessDenied, ValueError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(blob.data, media_type=blob.content_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/device/attachment/read")
def device_attachment_read(payload: dict = Body(...)) -> Response:
    """Return one command-bound attachment to its authenticated desktop."""
    device_id = _device(str(payload.get("device_id", "")),
                        str(payload.get("token", "")))
    command_id = str(payload.get("command_id", ""))
    command = _attachment_command(command_id, device_id)
    attachment_id = str(payload.get("attachment_id", ""))
    if str(command.payload.get("attachment_id", "")) != attachment_id:
        raise HTTPException(
            status_code=403, detail="Attachment does not match the command.")
    try:
        blob = attachment_store.get_attachment_store().read(
            attachment_id, target_device=device_id, command_id=command_id)
    except attachment_store.AttachmentStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except attachment_store.AttachmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (attachment_store.AttachmentAccessDenied, ValueError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(
        blob.data, media_type=blob.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-ZENO-Attachment-Name": quote(blob.filename, safe=""),
            "X-ZENO-Attachment-Purpose": blob.purpose,
        })


@router.post("/device/media/write")
async def device_media_write(device_id: str = Form(...), token: str = Form(...),
                             command_id: str = Form(...), media_id: str = Form(...),
                             audio: UploadFile = File(...)) -> dict[str, Any]:
    authenticated = _device(device_id, token)
    command = _voice_command(command_id, authenticated)
    if str(command.payload.get("media_id", "")) != media_id:
        raise HTTPException(status_code=403, detail="Voice media does not match the command.")
    data = await audio.read(media_store.MAX_OUTPUT_BYTES + 1)
    if len(data) > media_store.MAX_OUTPUT_BYTES:
        raise HTTPException(status_code=413, detail="Voice response is too large.")
    try:
        media_store.get_media_store().write_output(
            media_id, target_device=authenticated, command_id=command_id,
            data=data, content_type=str(audio.content_type or ""))
    except media_store.MediaStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except media_store.MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (media_store.MediaAccessDenied, ValueError,
            media_store.MediaCapacityExceeded) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "media_id": media_id}


@router.post("/device/complete")
def device_complete(payload: dict = Body(...)) -> dict[str, Any]:
    """The agent reports the REAL outcome. ZENO reports whatever this says."""
    link = device_link.get_link()
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    command_id = str(payload.get("command_id", ""))
    command = link.command(command_id)
    result = payload.get("result")
    ok = link.complete(
        command_id, device_id,
        ok=bool(payload.get("success", False)),
        result=result if isinstance(result, dict) else {"detail": str(result)[:500]},
        error=str(payload.get("error", "")))
    if ok:
        if command and command.action == "voice_turn":
            try:
                media_store.get_media_store().release_input(
                    str(command.payload.get("media_id", "")), target_device=device_id,
                    command_id=command_id)
            except Exception:
                pass  # TTL cleanup remains the fail-safe; completion must survive cleanup.
        if command and command.action == "analyze_attachment":
            try:
                attachment_store.get_attachment_store().release(
                    str(command.payload.get("attachment_id", "")),
                    target_device=device_id, command_id=command_id)
            except Exception:
                pass  # Short TTL cleanup remains the fail-safe.
        web_push.get_service().enqueue(
            "ZENO task finished" if bool(payload.get("success", False)) else "ZENO task failed",
            "Open ZENO to see the verified result.", kind="task")
    return {"ok": ok}


# --- status -------------------------------------------------------------
def register(app) -> None:
    """Attach the router with owner authentication on the protected routes.

    Applied here rather than per-route so that a route added later WITHOUT a
    dependency is still protected -- forgetting the decorator is the classic
    way an unauthenticated endpoint ships.
    """
    protected = APIRouter(prefix="/api/owner", tags=["owner"],
                          dependencies=[Depends(require_trusted_owner)])

    @protected.get("/status")
    def owner_status() -> dict[str, Any]:
        link = device_link.get_link()
        return {"devices": link.devices(), "queue": link.stats(),
                "auth": get_owner_auth().status(), "at": time.time()}

    @protected.get("/diagnostics")
    def owner_diagnostics(token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        """One honest health snapshot of the shared brain, memory, knowledge,
        tools and the laptop node -- same for phone and laptop. Also reports
        this session's fingerprint action-unlock state so the UI can show it."""
        from reyes_agent.remote_access import diagnostics

        report = diagnostics.snapshot()
        report["elevation"] = get_owner_auth().elevation_status(token)
        return report

    @protected.post("/conversation/plan")
    def owner_conversation_plan(payload: dict = Body(...)) -> dict[str, Any]:
        """Pack 6 conversation diagnostics (#283): given a spoken line and its
        setting, explain how ZENO would handle it -- who it is addressed to,
        whether ZENO would speak, and in what register/detail. Read-only: it
        PLANS a turn, it runs nothing and stores nothing."""
        from reyes_agent.conversation.planner import get_planner

        def _names(key: str) -> tuple[str, ...]:
            value = payload.get(key)
            return tuple(str(x)[:60] for x in value[:12]) if isinstance(value, list) else ()

        plan = get_planner().plan(
            str(payload.get("text", ""))[:2000],
            mode=str(payload.get("mode", "normal"))[:20],
            relationship=str(payload.get("relationship", ""))[:40],
            setting=str(payload.get("setting", ""))[:40],
            audience_level=str(payload.get("audience_level", "UNKNOWN"))[:20],
            agents=_names("agents"), humans=_names("humans"),
            detail=str(payload.get("detail", ""))[:20],
            proactive=bool(payload.get("proactive", False)),
            ambiguous_reference=bool(payload.get("ambiguous_reference", False)))
        return {"ok": True, "plan": plan.as_dict()}

    @protected.get("/capabilities/truth")
    def owner_capability_truth() -> dict[str, Any]:
        """Pack 5 capability-truth dashboard (#246-251): advertised vs. actually
        implemented / tested / healthy / available, plus a production-readiness
        score and current resource admission. Read-only. Health and lifecycle
        are read live; the no-fake rule means only PROVEN capabilities show
        ACTIVE."""
        from reyes_agent import admission, capability_snapshot, capability_truth

        capability_truth.seed_baseline()
        return {"ok": True,
                "capabilities": capability_truth.get_truth().dashboard(),
                "resources": admission.get_admission().snapshot(),
                # The JARVIS/ULTRON "what can you do?" answer, read live from the
                # real tool registry -- honest, never fabricated (#89, #91, #108).
                "inventory": capability_snapshot.what_can_i_do(),
                "system": capability_snapshot.system_status()}

    @protected.get("/control-plane")
    def owner_control_plane() -> dict[str, Any]:
        """Authenticated phone projection of the same laptop control plane.

        No raw evidence targets or traces cross this boundary; the owner phone
        gets coordinated state and aggregate truth, while detailed developer
        diagnostics remain loopback-only.
        """
        from reyes_agent.capability_truth import get_truth, seed_baseline, seed_tool_registry
        from reyes_agent.evidence_ledger import get_evidence_ledger
        from reyes_agent.quality_score import get_quality_score
        from reyes_agent.unified_session import get_session_state
        seed_baseline()
        seed_tool_registry()
        return {"ok": True, "session": get_session_state().snapshot(),
                "capabilities": get_truth().dashboard(),
                "evidence": get_evidence_ledger().stats(),
                "quality": get_quality_score().score()}

    @protected.get("/events")
    def owner_events(token: str = Depends(require_trusted_owner)) -> StreamingResponse:
        """Authenticated, bounded SSE invalidation feed for the owner PWA.

        It carries no command payload or result. The PWA fetches authoritative
        state from the normal protected endpoints and keeps polling as a
        recovery fallback. Trust is rechecked while the connection is open so
        session revocation and browser blocking take effect without a restart.
        """
        try:
            subscription = realtime.subscribe()
        except realtime.SubscriberLimitError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        def still_trusted() -> bool:
            info = get_owner_auth().session_info(token)
            return bool(info and info.get("trusted"))

        return StreamingResponse(
            realtime.iter_sse(subscription, still_trusted),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @protected.get("/sessions")
    def sessions() -> dict[str, Any]:
        return {"sessions": get_owner_auth().sessions()}

    @protected.post("/passkeys/register/options")
    def passkey_register_options(request: Request,
                                 payload: dict = Body(default={})) -> dict[str, Any]:
        _origin, rp_id = _webauthn_context(request)
        return get_owner_auth().passkey_registration_options(
            rp_id=rp_id, label=str(payload.get("label", "Owner passkey"))[:80])

    @protected.post("/passkeys/register/complete")
    def passkey_register_complete(request: Request,
                                  payload: dict = Body(...)) -> dict[str, Any]:
        origin, rp_id = _webauthn_context(request)
        return get_owner_auth().finish_passkey_registration(
            payload.get("credential") if isinstance(payload.get("credential"), dict) else {},
            challenge=str(payload.get("challenge", "")), origin=origin, rp_id=rp_id,
            label=str(payload.get("label", "Owner passkey"))[:80])

    @protected.get("/passkeys")
    def passkeys() -> dict[str, Any]:
        return {"passkeys": get_owner_auth().passkey_credentials()}

    @protected.post("/passkeys/revoke")
    def revoke_passkey(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": get_owner_auth().revoke_passkey(str(payload.get("id", "")))}

    @protected.post("/sessions/revoke")
    def revoke(payload: dict = Body(...)) -> dict[str, Any]:
        auth = get_owner_auth()
        if payload.get("all"):
            revoked = auth.revoke_all()
            ended = live_desktop.get_live_desktop().end_all("owner sessions revoked")
            return {"ok": True, "revoked": revoked, "live_sessions_ended": ended}
        return {"ok": auth.revoke(str(payload.get("id", "")))}

    @protected.get("/devices")
    def devices() -> dict[str, Any]:
        return {"devices": device_link.get_link().devices()}

    @protected.post("/android/pairings")
    def create_android_pairing(
            request: Request,
            token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        info = get_owner_auth().session_info(token)
        if not info or not info.get("trusted"):
            raise HTTPException(status_code=403, detail="Trusted browser required.")
        origin = str(request.headers.get("origin", "") or request.base_url).rstrip("/")
        if not domains.is_allowed_origin(origin):
            raise HTTPException(status_code=403, detail="Pairing origin is not allowed.")
        try:
            offer = android_pairing.get_store().create(
                browser_device=str(info["device_id"]), gateway=origin)
            # The QR already contains the one-time high-entropy token. Do not
            # duplicate it as readable JSON fields in the browser response.
            return {"ok": True, **{key: offer[key] for key in (
                "id", "manual_code", "expires_at", "gateway", "qr_png")}}
        except android_pairing.PairingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @protected.get("/browser-devices")
    def browser_devices() -> dict[str, Any]:
        return {"devices": get_owner_auth().browser_devices()}

    @protected.post("/browser-devices/rename")
    def rename_browser_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": get_owner_auth().rename_browser_device(
            str(payload.get("device_id", "")), str(payload.get("label", "")))}

    @protected.post("/browser-devices/state")
    def browser_device_state(payload: dict = Body(...)) -> dict[str, Any]:
        browser_id = str(payload.get("device_id", ""))
        state = str(payload.get("state", ""))
        ok = get_owner_auth().set_browser_device_state(browser_id, state)
        if ok and state.upper() in {"BLOCKED", "REVOKED"}:
            web_push.get_service().unregister_browser(browser_id)
        return {"ok": ok}

    @protected.get("/push/status")
    def push_status() -> dict[str, Any]:
        return web_push.get_service().status()

    @protected.post("/push/subscriptions")
    def register_push(payload: dict = Body(...),
                      token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        info = get_owner_auth().session_info(token)
        if not info or not info.get("trusted"):
            raise HTTPException(status_code=403, detail="Trusted browser required.")
        try:
            return web_push.get_service().register(str(info["device_id"]), payload)
        except web_push.PushConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @protected.delete("/push/subscriptions/current")
    def unregister_push(token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        info = get_owner_auth().session_info(token)
        if not info:
            raise HTTPException(status_code=401, detail="Session expired.")
        return {"ok": True, "removed": web_push.get_service().unregister_browser(
            str(info["device_id"]))}

    @protected.post("/devices/register")
    def register_device(payload: dict = Body(...)) -> dict[str, Any]:
        """Returns the device secret ONCE. It is never retrievable again."""
        platform = str(payload.get("platform", "windows")).strip().casefold()
        if platform not in {"windows", "android"}:
            raise HTTPException(status_code=400, detail="Unsupported device platform.")
        return device_link.get_link().register(
            label=str(payload.get("label", "Windows"))[:80],
            platform=platform)

    @protected.post("/devices/revoke")
    def revoke_device(payload: dict = Body(...)) -> dict[str, Any]:
        device_id = str(payload.get("device_id", ""))
        ok = device_link.get_link().revoke_device(device_id)
        ended = (live_desktop.get_live_desktop().end_all(
            "Windows device revoked", target_device=device_id) if ok else 0)
        return {"ok": ok, "live_sessions_ended": ended}

    @protected.post("/devices/approve")
    def approve_device(payload: dict = Body(...)) -> dict[str, Any]:
        device_id = str(payload.get("device_id", ""))
        state = device_link.get_link().device_state(device_id)
        scopes = (["android_control"] if state.get("platform") == "android" else
                  (payload.get("scopes") if isinstance(payload.get("scopes"), list) else []))
        return {"ok": device_link.get_link().approve_device(
            device_id, scopes=scopes)}

    @protected.post("/devices/rename")
    def rename_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": device_link.get_link().rename_device(
            str(payload.get("device_id", "")), str(payload.get("label", "")))}

    @protected.post("/devices/block")
    def block_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": device_link.get_link().block_device(
            str(payload.get("device_id", "")))}

    @protected.post("/command")
    def enqueue_command(request: Request, payload: dict = Body(...),
                        token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        """Queue one command for a device. Nothing executes in this process."""
        action = str(payload.get("action", "")).strip()
        if action not in REGISTERED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action. Registered: {sorted(REGISTERED_ACTIONS)}")

        link = device_link.get_link()
        device_id = str(payload.get("device_id", ""))
        state = link.device_state(device_id)
        if not state.get("known"):
            raise HTTPException(status_code=404, detail="Unknown device.")

        rate = policy.check_rate("command", _client_identity(request))
        if not rate.allowed:
            raise HTTPException(status_code=429, detail=rate.as_dict())

        # The natural-language text is classified by the SAME policy the
        # desktop uses. Remote access adds a gate; it never removes one.
        spoken = str(payload.get("text", "") or action.replace("_", " "))
        decision = policy.evaluate(spoken, allow_control=True)
        if not decision.allowed:
            return {"ok": False, "refused": True, "reason": decision.reason,
                    "category": decision.category}

        # Fingerprint model: a CONSEQUENTIAL action needs this phone session
        # elevated -- the owner scanned a fingerprint recently. If elevated, the
        # executor runs the tool directly (the fingerprint IS the approval); if
        # not, tell the phone to scan, never a walk to the PC. Conversation and
        # reads never require elevation.
        elevated = get_owner_auth().session_elevated(token)
        consequential = (decision.needs_local_approval or
                         REGISTERED_ACTIONS[action] in {"STANDARD_DEVICE", "SENSITIVE_DEVICE"})
        if consequential and not elevated:
            return {"ok": False, "needs_stepup": True, "category": decision.category,
                    "reason": "Scan your fingerprint to authorize this action."}

        extra = dict(payload.get("payload") if isinstance(payload.get("payload"), dict) else {})
        if elevated:
            # Lets the turn auto-approve consequential tools (send a message,
            # etc.). Set server-side only, only for an elevated trusted session.
            extra["_owner_elevated"] = True

        command = link.enqueue(
            device_id, action, extra,
            category=REGISTERED_ACTIONS[action],
            idempotency_key=str(payload.get("idempotency_key", "")),
            requesting_device="owner-web",
            # The fingerprint replaced the PC-approval step, so nothing here
            # still needs a walk to the desktop panel.
            requires_approval=False,
            expires_in_s=float(payload.get("expires_in_s", 900) or 900))
        body = command.as_dict()
        body["elevated"] = elevated
        # The owner must be able to tell "waiting for a laptop that is asleep"
        # apart from "sent". Saying "done" here would be the exact lie the
        # brief forbids.
        body["device_state"] = state.get("state")
        body["note"] = ("Queued. The desktop is offline and will receive this when it "
                        "reconnects." if state.get("state") == "OFFLINE"
                        else "Queued for the connected desktop.")
        body["needs_local_approval"] = command.status == device_link.PENDING_APPROVAL
        if body["needs_local_approval"]:
            web_push.get_service().enqueue(
                "ZENO approval required", "Open ZENO to review a waiting action.",
                kind="approval")
        return {"ok": True, **body}

    @protected.post("/voice")
    async def enqueue_voice(request: Request, device_id: str = Form(...),
                            clip: UploadFile = File(...),
                            token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        """Queue opaque voice media without treating browser trust as voice identity."""
        info = get_owner_auth().session_info(token)
        if not info or not info.get("trusted"):
            raise HTTPException(status_code=403, detail="Trusted browser required.")
        rate = policy.check_rate("command", _client_identity(request))
        if not rate.allowed:
            raise HTTPException(status_code=429, detail=rate.as_dict())
        data = await clip.read(media_store.MAX_INPUT_BYTES + 1)
        if len(data) > media_store.MAX_INPUT_BYTES:
            raise HTTPException(status_code=413, detail="Voice clip is too large.")
        store = None
        media_id = ""
        try:
            store = media_store.get_media_store()
            media_id = store.create_input(
                browser_device=str(info["device_id"]), target_device=device_id,
                data=data, content_type=str(clip.content_type or ""))
            command = device_link.get_link().enqueue(
                device_id, "voice_turn", {"media_id": media_id}, category="READ_ONLY",
                idempotency_key="", requesting_device=f"owner-web:{info['device_id']}",
                requires_approval=False, expires_in_s=media_store.DEFAULT_TTL_S)
            if not store.bind_command(media_id, command_id=command.id,
                                      target_device=device_id):
                device_link.get_link().cancel(command.id, requesting_device="owner-web")
                raise RuntimeError("Could not bind voice media to its command.")
        except media_store.MediaStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (media_store.MediaCapacityExceeded, ValueError) as exc:
            if store and media_id:
                store.discard(media_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (KeyError, PermissionError) as exc:
            if store and media_id:
                store.discard(media_id)
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception:
            if store and media_id:
                store.discard(media_id)
            raise
        body = command.as_dict()
        body.update(ok=True, media_id=media_id,
                    note="Encrypted voice turn queued for your ZENO desktop.")
        return body

    @protected.post("/attachment")
    async def enqueue_attachment(
            request: Request, device_id: str = Form(...),
            purpose: str = Form("file"), prompt: str = Form(""),
            upload: UploadFile = File(...),
            token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        """Queue a camera frame or intentional file without exposing a path."""
        info = get_owner_auth().session_info(token)
        if not info or not info.get("trusted"):
            raise HTTPException(status_code=403, detail="Trusted browser required.")
        link = device_link.get_link()
        state = link.device_state(device_id)
        if not state.get("known"):
            raise HTTPException(status_code=404, detail="Unknown device.")
        rate = policy.check_rate("command", _client_identity(request))
        if not rate.allowed:
            raise HTTPException(status_code=429, detail=rate.as_dict())

        question = " ".join(str(prompt or "").split())[:600]
        if not question:
            question = ("Describe this image and read visible text." if
                        str(purpose).casefold() == "camera" else
                        "Summarize this file and report important facts.")
        decision = policy.evaluate(question, allow_control=False)
        if not decision.allowed:
            return {"ok": False, "refused": True, "reason": decision.reason,
                    "category": decision.category}

        data = await upload.read(attachment_store.MAX_ATTACHMENT_BYTES + 1)
        if len(data) > attachment_store.MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Attachment is too large.")
        store = None
        attachment_id = ""
        try:
            store = attachment_store.get_attachment_store()
            attachment_id = store.create(
                browser_device=str(info["device_id"]), target_device=device_id,
                data=data, content_type=str(upload.content_type or ""),
                filename=str(upload.filename or "upload"), purpose=purpose)
            command = link.enqueue(
                device_id, "analyze_attachment",
                {"attachment_id": attachment_id, "prompt": question},
                category="READ_ONLY", idempotency_key="",
                requesting_device=f"owner-web:{info['device_id']}",
                requires_approval=False,
                expires_in_s=attachment_store.DEFAULT_TTL_S)
            if not store.bind_command(
                    attachment_id, command_id=command.id,
                    target_device=device_id):
                link.cancel(command.id, requesting_device="owner-web")
                raise RuntimeError("Could not bind the attachment to its command.")
        except attachment_store.AttachmentStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (attachment_store.AttachmentCapacityExceeded, ValueError) as exc:
            if store and attachment_id:
                store.discard(attachment_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (KeyError, PermissionError) as exc:
            if store and attachment_id:
                store.discard(attachment_id)
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception:
            if store and attachment_id:
                store.discard(attachment_id)
            raise
        body = command.as_dict()
        body.update(
            ok=True, attachment_id=attachment_id, device_state=state.get("state"),
            note=("Encrypted attachment queued. The desktop is offline and will "
                  "process it after reconnecting." if state.get("state") == "OFFLINE"
                  else "Encrypted attachment queued for the connected desktop."))
        return body

    @protected.get("/voice/{media_id}")
    def owner_voice(media_id: str,
                    token: str = Depends(require_trusted_owner)) -> Response:
        info = get_owner_auth().session_info(token)
        if not info or not info.get("trusted"):
            raise HTTPException(status_code=403, detail="Trusted browser required.")
        try:
            blob = media_store.get_media_store().read_output(
                media_id, browser_device=str(info["device_id"]))
        except media_store.MediaStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except media_store.MediaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (media_store.MediaAccessDenied, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return Response(blob.data, media_type=blob.content_type,
                        headers={"Cache-Control": "no-store",
                                 "Content-Disposition": "inline; filename=zeno-response.mp3",
                                 "X-Content-Type-Options": "nosniff"})

    @protected.post("/command/{command_id}/cancel")
    def cancel_command(command_id: str) -> dict[str, Any]:
        return {"ok": device_link.get_link().cancel(
            command_id, requesting_device="owner-web")}

    @protected.get("/approvals")
    def approvals(state: str = "pending", limit: int = 100) -> dict[str, Any]:
        return {"approvals": device_link.get_link().approvals(state=state, limit=limit)}

    @protected.post("/approvals/{approval_id}/decision")
    def decide_approval(approval_id: str, payload: dict = Body(...),
                        token: str = Depends(require_trusted_owner)) -> dict[str, Any]:
        decision = str(payload.get("decision", "")).casefold()
        if decision not in {"approve", "deny"}:
            raise HTTPException(status_code=400, detail="Decision must be approve or deny.")
        session = get_owner_auth().session_info(token) or {}
        browser_id = str(session.get("device_id", "unknown-browser"))
        ok = device_link.get_link().decide_approval(
            approval_id, approve=decision == "approve", requesting_device="owner-web",
            evidence=f"trusted-owner-browser:{browser_id}")
        if ok:
            web_push.get_service().enqueue(
                "ZENO approval updated", "Your decision was recorded.", kind="approval")
        return {"ok": ok}

    @protected.post("/remote-control")
    def remote_control(payload: dict = Body(...)) -> dict[str, Any]:
        if "enabled" not in payload:
            raise HTTPException(status_code=400, detail="enabled is required")
        enabled = bool(payload.get("enabled"))
        result = device_link.get_link().set_remote_control(
            enabled, requesting_device="owner-web")
        if not enabled:
            result["live_sessions_ended"] = live_desktop.get_live_desktop().end_all(
                "remote control disabled", modes={"REMOTE_CONTROL"})
        return result

    @protected.post("/kill-switch")
    def kill_switch() -> dict[str, Any]:
        link = device_link.get_link()
        result = link.set_remote_control(False, requesting_device="owner-web")
        result["live_sessions_ended"] = live_desktop.get_live_desktop().end_all(
            "remote kill switch activated")
        result["sessions_revoked"] = get_owner_auth().revoke_all(reason="remote_kill_switch")
        return result

    @protected.get("/command/{command_id}")
    def command_status(command_id: str) -> dict[str, Any]:
        command = device_link.get_link().command(command_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Unknown command.")
        return command.as_dict()

    @protected.get("/commands")
    def commands(device_id: str = "", limit: int = 25) -> dict[str, Any]:
        return {"commands": device_link.get_link().recent(
            device_id, max(1, min(int(limit), 100)))}

    @protected.get("/audit")
    def audit(limit: int = 50) -> dict[str, Any]:
        return {"entries": get_owner_auth().audit_log(limit)}

    @protected.get("/activity")
    def activity(limit: int = 100) -> dict[str, Any]:
        return {"entries": _owner_activity_entries(limit)}

    # Unauthenticated routes first (login must work before a session exists),
    # then everything else behind the dependency.
    app.include_router(router)
    app.include_router(protected)
