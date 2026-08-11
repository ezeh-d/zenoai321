"""Explaining real work to a real person.

Facts come from git history, the capability registry and the roadmap's own
labels -- not from a script. Every feature carries WORKING / PARTIAL /
EXPERIMENTAL / NOT_IMPLEMENTED, and Presentation Mode is a REAL
conversational mode: a guest in the room never enables demo mode.
"""

from __future__ import annotations

from reyes_agent.presentation import facts

__all__ = ["facts", "refresh", "load", "status"]

refresh = facts.refresh
load = facts.load
status = facts.status
