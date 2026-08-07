"""The versioned mobile API: `/api/v1/...`.

WHY BEARER TOKENS AS WELL AS THE COOKIE
---------------------------------------
The existing `/phone` page is same-origin, so its `zeno_phone_session`
cookie is set `SameSite=strict` -- correct there, and deliberately NOT sent
on a cross-origin request. The planned architecture puts the companion on
`app.zenoassitant.com` calling `api.zenoassitant.com`, which IS cross-origin,
so that cookie would never arrive and every request would 401.

So this router accepts the SAME session token either way:
  * `Authorization: Bearer <session>` -- what the companion should use
  * the existing cookie -- so the current phone page keeps working

The token itself, its issuance and its revocation are unchanged: they remain
`phone_security`'s job. This module adds no new credential type.

Everything here is read-through: the API never reaches into ZENO's
internals, it asks the same subsystems the desktop asks and returns a
trimmed view.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from reyes_agent.remote_access import domains, gateway, policy, protocol

router = APIRouter(prefix="/api/v1", tags=["remote"])


# --- auth ----------------------------------------------------------------

def _client(request: Request) -> str:
    return (request.client.host if request.client else "unknown")


def _session(request: Request, authorization: str | None, cookie: str | None):
    """Resolve a device session, or raise 401. Rate-limited on failure."""
    from reyes_agent import config

    if not bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)):
        raise HTTPException(503, "Remote access is disabled on this ZENO.")
    if not bool(getattr(config, "REMOTE_API_ENABLED", True)):
        raise HTTPException(503, "The remote API is disabled on this ZENO.")

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or (cookie or "")
    if not token:
        _note_auth_failure(request)
        raise HTTPException(401, "No session. Pair this device first.")

    from reyes_agent.phone_security import get_phone_security

    try:
        # CSRF is required for cookie-borne writes only. A Bearer token is
        # not sent automatically by a browser, so it is not CSRF-able.
        require_csrf = bool(cookie) and not authorization and request.method not in {"GET", "HEAD"}
        return get_phone_security().session(
            token, request.headers.get("x-zeno-csrf", ""), require_csrf)
    except PermissionError as exc:
        _note_auth_failure(request)
        raise HTTPException(401, str(exc)) from exc


def _note_auth_failure(request: Request) -> None:
    result = policy.check_rate("auth_failure", _client(request))
    if not result.allowed:
        raise HTTPException(429, "Too many failed attempts. Try again later.")


def _scopes(session) -> set[str]:
    import json

    try:
        return set(json.loads(session["scopes"]))
    except Exception:  # noqa: BLE001
        return set()


# --- models --------------------------------------------------------------

class CommandBody(BaseModel):
    request_id: str = ""
    type: str = protocol.COMMAND
    message: str = ""
    timestamp: str = ""


class DeviceAction(BaseModel):
    device_id: str = ""


class WebsiteAction(BaseModel):
    request_id: str = ""
    action: str
    project: str = ""
    label: str = ""


# --- endpoints -----------------------------------------------------------

@router.get("/status")
def remote_status(request: Request, authorization: str | None = Header(default=None),
                  zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Is the desktop reachable, and what is it doing."""
    session = _session(request, authorization, zeno_phone_session)
    gateway.mark_seen(session["device_id"])
    return {"version": protocol.VERSION, "device": session["name"],
            "device_id": session["device_id"], "scopes": sorted(_scopes(session)),
            **gateway.connection_status()}


@router.post("/command")
def remote_command(body: CommandBody, request: Request,
                   authorization: str | None = Header(default=None),
                   zeno_phone_session: str | None = Cookie(default=None)) -> JSONResponse:
    """The main entry point. Routed to the SAME brain the desktop uses."""
    session = _session(request, authorization, zeno_phone_session)
    parsed, error = protocol.Request.parse(body.model_dump(), device_id=session["device_id"])
    if parsed is None:
        response = protocol.failed(body.request_id or protocol.new_request_id(), error)
        return JSONResponse(response.as_dict(), status_code=response.http_status)
    result = gateway.handle(parsed, scopes=_scopes(session), identity=session["device_id"])
    return JSONResponse(result.as_dict(), status_code=result.http_status)


@router.get("/devices")
def remote_devices(request: Request, authorization: str | None = Header(default=None),
                   zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """'Show my connected devices.'"""
    _session(request, authorization, zeno_phone_session)
    from reyes_agent.phone_security import get_phone_security

    return {"devices": get_phone_security().devices()}


@router.post("/devices/revoke")
def remote_revoke(body: DeviceAction, request: Request,
                  authorization: str | None = Header(default=None),
                  zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """'Remove this phone.' A device may always revoke itself."""
    session = _session(request, authorization, zeno_phone_session)
    from reyes_agent.phone_security import get_phone_security

    target = (body.device_id or "").strip() or session["device_id"]
    get_phone_security().set_device(target, state="REVOKED")
    gateway.record(session["device_id"], protocol.new_request_id(), policy.SENSITIVE,
                   f"revoke {target}", "success")
    return {"ok": True, "revoked": target}


@router.post("/logout-all")
def remote_logout_all(request: Request, authorization: str | None = Header(default=None),
                      zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """'Log out all devices.' Sessions only -- pairings survive."""
    session = _session(request, authorization, zeno_phone_session)
    from reyes_agent.phone_security import get_phone_security

    get_phone_security().end_sessions()
    gateway.record(session["device_id"], protocol.new_request_id(), policy.SENSITIVE,
                   "logout all devices", "success")
    return {"ok": True}


@router.get("/tasks")
def remote_tasks(request: Request, authorization: str | None = Header(default=None),
                 zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Active work, in phone-facing states -- not internal task objects."""
    _session(request, authorization, zeno_phone_session)
    from reyes_agent import task_engine

    mapping = {"PLANNING": "thinking", "RUNNING": "working", "VERIFYING": "testing",
               "RETRYING": "working", "WAITING_FOR_APPROVAL": "waiting",
               "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}
    tasks = []
    for snapshot in task_engine.active()[-10:]:
        tasks.append(protocol.task_event(
            snapshot["task_id"], mapping.get(snapshot["current_status"], "working"),
            snapshot.get("current_step", {}).get("label", "") if snapshot.get("current_step") else "",
            snapshot.get("progress_percent")))
    return {"tasks": tasks}


@router.get("/agents")
def remote_agents(request: Request, authorization: str | None = Header(default=None),
                  zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Lightweight sub-agent state. Names and status only."""
    _session(request, authorization, zeno_phone_session)
    try:
        from reyes_agent import agent_runtime

        health = agent_runtime.health()
        working = set(health.get("working_now", []) or [])
        names = health.get("agents", []) or sorted(working)
    except Exception:  # noqa: BLE001 -- agent runtime issues never 500 the phone
        return {"agents": []}
    agents = []
    for name in (names if isinstance(names, list) else [])[:20]:
        label = name if isinstance(name, str) else str(name.get("name", ""))
        agents.append({"name": label, "status": "working" if label in working else "idle",
                       "task": None})
    return {"agents": agents}


@router.get("/memory/recent")
def remote_memory(request: Request, limit: int = 10,
                  authorization: str | None = Header(default=None),
                  zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Controlled memory view.

    Deliberately narrow: recent conversation turns only, trimmed. The full
    memory store is NOT exposed -- a phone session is not a database login.
    """
    _session(request, authorization, zeno_phone_session)
    from reyes_agent import web

    turns = []
    for entry in list(getattr(web, "_history", []))[-max(1, min(limit, 30)) * 2:]:
        role = entry.get("role")
        content = entry.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            turns.append({"role": role, "text": content[:600]})
    return {"conversation": turns[-max(1, min(limit, 30)):]}


@router.get("/website/projects")
def remote_website_projects(request: Request, authorization: str | None = Header(default=None),
                            zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Website Studio status for the companion."""
    _session(request, authorization, zeno_phone_session)
    try:
        from reyes_agent import website_builder

        projects = [{"name": p["project_name"], "framework": p["framework"],
                     "status": p["status"], "project_id": p["project_id"]}
                    for p in website_builder.projects()[:20]]
    except Exception:  # noqa: BLE001
        projects = []
    return {"projects": projects}


# Website actions a phone may trigger. Anything not on this list is refused
# -- the phone never gets arbitrary Website Studio control, and never a shell.
_WEBSITE_ACTIONS = {
    "status": "Show me the status of my website projects.",
    "checkpoint": "Create a checkpoint for the website project {project}.",
    "check": "Check and fix the website project {project}.",
    "preview": "Preview the website project {project}.",
    "continue": "Continue working on the website project {project}.",
}


@router.post("/website/action")
def remote_website_action(body: WebsiteAction, request: Request,
                          authorization: str | None = Header(default=None),
                          zeno_phone_session: str | None = Cookie(default=None)) -> JSONResponse:
    """Safe, named Website Studio commands -- phrased and routed as normal
    ZENO requests so every Website Studio rule still applies."""
    session = _session(request, authorization, zeno_phone_session)
    request_id = body.request_id or protocol.new_request_id()
    template = _WEBSITE_ACTIONS.get(str(body.action or "").strip().lower())
    if template is None:
        response = protocol.denied(
            request_id, f"'{body.action}' is not an allowed website action. "
                        f"Allowed: {', '.join(sorted(_WEBSITE_ACTIONS))}.")
        return JSONResponse(response.as_dict(), status_code=response.http_status)

    message = template.format(project=(body.project or "").strip() or "the current project")
    parsed = protocol.Request(request_id=request_id, device_id=session["device_id"],
                              type=protocol.COMMAND, message=message)
    result = gateway.handle(parsed, scopes=_scopes(session), identity=session["device_id"])
    return JSONResponse(result.as_dict(), status_code=result.http_status)


@router.get("/audit")
def remote_audit(request: Request, limit: int = 50,
                 authorization: str | None = Header(default=None),
                 zeno_phone_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    _session(request, authorization, zeno_phone_session)
    return {"entries": gateway.audit_log(limit)}


@router.get("/meta")
def remote_meta() -> dict[str, Any]:
    """Unauthenticated, and deliberately contentless.

    Lets a companion discover the protocol version and whether remote access
    is even on, without revealing anything about the machine.
    """
    from reyes_agent import config

    return {"version": protocol.VERSION,
            "remote_access_enabled": bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)),
            "pairing_enabled": bool(getattr(config, "REMOTE_PAIRING_ENABLED", True)),
            "passkey_enabled": bool(getattr(config, "REMOTE_PASSKEY_ENABLED", True)),
            "domain_configured": domains.configured(),
            "events": list(protocol.EVENTS),
            "task_states": list(protocol.TASK_STATES),
            "website_states": list(protocol.WEBSITE_STATES)}
