"""Loopback-only FastAPI adapter for the ZENO live workspace."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

_ACTIONS = {"show", "hide", "toggle", "minimize", "expand", "focus", "dock", "close"}


class PanelActionRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    position: str = ""


class HealthRefreshRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


def _loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = host.casefold() == "localhost"
    if not allowed:
        raise HTTPException(403, "Workspace API is available only on loopback.")


def create_router(*, service: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/workspace", tags=["workspace"])

    def current_service():
        if service is not None:
            return service
        from reyes_agent.workspace import get_workspace_service

        return get_workspace_service(start=True)

    def state() -> dict[str, Any]:
        return current_service().snapshot()

    @router.get("/state")
    def workspace_state(request: Request) -> dict[str, Any]:
        _loopback(request)
        return state()

    @router.get("/panels")
    def workspace_panels(request: Request) -> dict[str, Any]:
        _loopback(request)
        snapshot = state()
        return {"revision": snapshot.get("revision", 0),
                "panels": snapshot.get("panels", []),
                "definitions": snapshot.get("panel_definitions", [])}

    @router.post("/panels/{panel_id}/{action}")
    def panel_action(panel_id: str, action: str, payload: PanelActionRequest,
                     request: Request) -> dict[str, Any]:
        _loopback(request)
        if action not in _ACTIONS:
            raise HTTPException(400, "Unsupported panel action.")
        try:
            return current_service().panel_action(
                panel_id, action, payload.context, payload.correlation_id, payload.position)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/activities")
    def activities(request: Request) -> dict[str, Any]:
        _loopback(request)
        snapshot = state()
        return {"revision": snapshot.get("revision", 0),
                "activities": snapshot.get("activities", [])}

    @router.post("/activities/{activity_id}/dismiss")
    def dismiss_activity(activity_id: str, request: Request) -> dict[str, Any]:
        _loopback(request)
        return {"dismissed": bool(current_service().dismiss_activity(activity_id)),
                "activity_id": activity_id}

    @router.get("/history")
    def history(request: Request) -> dict[str, Any]:
        _loopback(request)
        snapshot = state()
        return {"revision": snapshot.get("revision", 0),
                "history": snapshot.get("history", [])}

    @router.post("/history/{task_id}/retry")
    def retry(task_id: str, request: Request) -> dict[str, Any]:
        _loopback(request)
        try:
            return current_service().retry_task(task_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/history/{task_id}/resume")
    def resume(task_id: str, request: Request) -> dict[str, Any]:
        _loopback(request)
        try:
            return current_service().resume_task(task_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/health")
    def health(request: Request) -> dict[str, Any]:
        _loopback(request)
        snapshot = state()
        return {"revision": snapshot.get("revision", 0),
                "health": snapshot.get("health", [])}

    @router.post("/health/refresh")
    def refresh_health(payload: HealthRefreshRequest, request: Request) -> dict[str, Any]:
        _loopback(request)
        records = current_service().health.check_many(payload.names or None, force=True)
        return {"revision": state().get("revision", 0),
                "health": [row.as_dict() if hasattr(row, "as_dict") else row for row in records]}

    @router.get("/search")
    def search(q: str, request: Request, limit: int = 12) -> dict[str, Any]:
        _loopback(request)
        bounded_limit = max(1, min(int(limit), 25))
        return {"revision": state().get("revision", 0),
                "results": current_service().search.search(q, bounded_limit),
                "search_health": current_service().search.health()}

    return router
