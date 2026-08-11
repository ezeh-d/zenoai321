"""Lazy entry points for Phase 5's real local services."""
from __future__ import annotations

import json

from reyes_agent.tools import register


@register("phase5_status", "Show truthful Phase 5 integration, networking, sandbox, push and analytics availability.",
          {"type": "object", "properties": {}}, light=True)
def phase5_status() -> str:
    from reyes_agent.phase5 import status
    return json.dumps(status(), default=str)


@register("inspect_dataset", "Inspect the real schema, row count and a five-row sample of a CSV, JSON or Parquet dataset.",
          {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
def inspect_dataset(path: str) -> str:
    from reyes_agent.analytics import get_manager
    try:
        return json.dumps(get_manager().inspect(path), default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "state": "FAILED", "reason": f"{type(exc).__name__}: {exc}"})


@register("query_dataset", "Run one bounded read-only DuckDB query against the loaded dataset view named dataset. Returns calculated rows as evidence.",
          {"type": "object", "properties": {"path": {"type": "string"}, "sql": {"type": "string"},
           "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, "required": ["path", "sql"]})
def query_dataset(path: str, sql: str, limit: int = 200) -> str:
    from reyes_agent.analytics import get_manager
    try:
        return json.dumps(get_manager().query(path, sql, limit), default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "state": "FAILED", "reason": f"{type(exc).__name__}: {exc}"})


@register("private_network_status", "Show actual Tailscale/private-network and authorized-peer status without exposing keys.",
          {"type": "object", "properties": {}})
def private_network_status() -> str:
    from reyes_agent.network.private import status
    return json.dumps(status(), default=str)


@register("notification_summary", "Summarize real unread and action-required Notification Center entries; never invent alerts.",
          {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}})
def notification_summary(limit: int = 25) -> str:
    from reyes_agent import notifications
    rows = notifications.history(limit=max(1, min(int(limit), 100)))
    pending = [row for row in rows if row.get("state") in {notifications.NEW, notifications.ACTION_REQUIRED}]
    return json.dumps({"ok": True, "state": "RETURNED", "unread": len(pending),
                       "notifications": pending}, default=str)
