"""Lazy local inference acceleration."""
from .detector import status
from .session_manager import get_session_manager

__all__ = ["status", "get_session_manager"]
