"""Lazy local-model discovery; importing this package starts no model."""
from reyes_agent.models.local.registry import local_status

__all__ = ["local_status"]
