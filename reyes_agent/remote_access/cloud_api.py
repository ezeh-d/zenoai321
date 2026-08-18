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

import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from urllib.parse import urlsplit

from reyes_agent.auth import get_owner_auth
from reyes_agent.remote_access import device_link, domains, policy

router = APIRouter(prefix="/api/owner", tags=["owner"])

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
    response.set_cookie("zeno_session", session.token, httponly=True, secure=secure,
                        samesite=same_site, max_age=30 * 60, path="/")
    response.set_cookie("zeno_refresh", session.refresh, httponly=True, secure=secure,
                        samesite=same_site, max_age=14 * 24 * 3600,
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


@router.post("/auth/refresh")
def auth_refresh(request: Request, payload: dict = Body(default={})) -> JSONResponse:
    result = get_owner_auth().refresh_session(
        str(payload.get("refresh", "") or request.cookies.get("zeno_refresh", "")),
        identity=_client_identity(request))
    if not result.ok:
        raise HTTPException(status_code=401, detail=result.as_dict())
    return _session_response(result, request)


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


@router.post("/device/complete")
def device_complete(payload: dict = Body(...)) -> dict[str, Any]:
    """The agent reports the REAL outcome. ZENO reports whatever this says."""
    link = device_link.get_link()
    device_id = _device(str(payload.get("device_id", "")), str(payload.get("token", "")))
    result = payload.get("result")
    return {"ok": link.complete(
        str(payload.get("command_id", "")), device_id,
        ok=bool(payload.get("success", False)),
        result=result if isinstance(result, dict) else {"detail": str(result)[:500]},
        error=str(payload.get("error", "")))}


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
            return {"ok": True, "revoked": auth.revoke_all()}
        return {"ok": auth.revoke(str(payload.get("id", "")))}

    @protected.get("/devices")
    def devices() -> dict[str, Any]:
        return {"devices": device_link.get_link().devices()}

    @protected.get("/browser-devices")
    def browser_devices() -> dict[str, Any]:
        return {"devices": get_owner_auth().browser_devices()}

    @protected.post("/browser-devices/rename")
    def rename_browser_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": get_owner_auth().rename_browser_device(
            str(payload.get("device_id", "")), str(payload.get("label", "")))}

    @protected.post("/browser-devices/state")
    def browser_device_state(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": get_owner_auth().set_browser_device_state(
            str(payload.get("device_id", "")), str(payload.get("state", "")))}

    @protected.post("/devices/register")
    def register_device(payload: dict = Body(...)) -> dict[str, Any]:
        """Returns the device secret ONCE. It is never retrievable again."""
        return device_link.get_link().register(
            label=str(payload.get("label", "Windows"))[:80],
            platform=str(payload.get("platform", "windows"))[:32])

    @protected.post("/devices/revoke")
    def revoke_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": device_link.get_link().revoke_device(str(payload.get("device_id", "")))}

    @protected.post("/devices/approve")
    def approve_device(payload: dict = Body(...)) -> dict[str, Any]:
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
        return {"ok": device_link.get_link().approve_device(
            str(payload.get("device_id", "")), scopes=scopes)}

    @protected.post("/devices/rename")
    def rename_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": device_link.get_link().rename_device(
            str(payload.get("device_id", "")), str(payload.get("label", "")))}

    @protected.post("/devices/block")
    def block_device(payload: dict = Body(...)) -> dict[str, Any]:
        return {"ok": device_link.get_link().block_device(
            str(payload.get("device_id", "")))}

    @protected.post("/command")
    def enqueue_command(request: Request, payload: dict = Body(...)) -> dict[str, Any]:
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

        command = link.enqueue(
            device_id, action,
            payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            category=REGISTERED_ACTIONS[action],
            idempotency_key=str(payload.get("idempotency_key", "")),
            requesting_device="owner-web",
            requires_approval=(decision.needs_local_approval or
                               REGISTERED_ACTIONS[action] == "SENSITIVE_DEVICE"),
            expires_in_s=float(payload.get("expires_in_s", 900) or 900))
        body = command.as_dict()
        # The owner must be able to tell "waiting for a laptop that is asleep"
        # apart from "sent". Saying "done" here would be the exact lie the
        # brief forbids.
        body["device_state"] = state.get("state")
        body["note"] = ("Queued. The desktop is offline and will receive this when it "
                        "reconnects." if state.get("state") == "OFFLINE"
                        else "Queued for the connected desktop.")
        body["needs_local_approval"] = command.status == device_link.PENDING_APPROVAL
        return {"ok": True, **body}

    @protected.post("/command/{command_id}/cancel")
    def cancel_command(command_id: str) -> dict[str, Any]:
        return {"ok": device_link.get_link().cancel(
            command_id, requesting_device="owner-web")}

    @protected.get("/approvals")
    def approvals(state: str = "pending", limit: int = 100) -> dict[str, Any]:
        return {"approvals": device_link.get_link().approvals(state=state, limit=limit)}

    @protected.post("/approvals/{approval_id}/decision")
    def decide_approval(approval_id: str, payload: dict = Body(...)) -> dict[str, Any]:
        decision = str(payload.get("decision", "")).casefold()
        if decision not in {"approve", "deny"}:
            raise HTTPException(status_code=400, detail="Decision must be approve or deny.")
        return {"ok": device_link.get_link().decide_approval(
            approval_id, approve=decision == "approve", requesting_device="owner-web",
            evidence=str(payload.get("evidence", "owner session")))}

    @protected.post("/remote-control")
    def remote_control(payload: dict = Body(...)) -> dict[str, Any]:
        if "enabled" not in payload:
            raise HTTPException(status_code=400, detail="enabled is required")
        return device_link.get_link().set_remote_control(
            bool(payload.get("enabled")), requesting_device="owner-web")

    @protected.post("/kill-switch")
    def kill_switch() -> dict[str, Any]:
        link = device_link.get_link()
        result = link.set_remote_control(False, requesting_device="owner-web")
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
        return {"entries": device_link.get_link().activity(limit=limit)}

    # Unauthenticated routes first (login must work before a session exists),
    # then everything else behind the dependency.
    app.include_router(router)
    app.include_router(protected)
