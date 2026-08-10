"""Secrets from the OS credential store first, environment second."""

from __future__ import annotations

from reyes_agent.security.secrets import manager

__all__ = ["manager", "get", "put", "forget", "describe", "status"]

get = manager.get
put = manager.put
forget = manager.forget
describe = manager.describe
status = manager.status
