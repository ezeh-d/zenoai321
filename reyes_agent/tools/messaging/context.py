"""Resolves a bare follow-up reference ("him", "her", "tell them...") back to
the last verified messaging destination, so "send Ayodeji 'I'll be there
soon'" followed by "also tell him I'll meet him later" does not need the
name repeated. Mirrors content.working_context's Reference-resolution shape.

SAFE BY CONSTRUCTION: this module only ever widens a bare/pronoun destination
into a concrete name. router.send() still re-opens, re-navigates to, and
re-verifies that concrete destination on every single call regardless of
this context (see tools/messaging/router.py) -- so a stale or wrong guess
here can only fail to resolve or fail to find the destination in the app; it
can never make a message land on the wrong person silently. If the user
switches to a different conversation in between, the NEXT explicit send to a
named person still opens and verifies that exact person fresh.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

# Phrasing that means "the person/place I was just messaging", not a literal
# app destination named "him".
_REFERENCE = {
    "", "him", "her", "them", "him again", "her again", "them again",
    "same person", "the same person", "same chat", "the same chat",
    "that person", "that chat", "there", "him too", "her too",
}


@dataclass
class Target:
    platform: str
    destination: str
    destination_type: str = ""
    at: float = 0.0


@dataclass
class Resolution:
    ok: bool
    platform: str = ""
    destination: str = ""
    destination_type: str = ""
    reason: str = ""


class MessagingContext:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last: Target | None = None

    def record(self, platform: str, destination: str, destination_type: str = "") -> None:
        """Called only after a VERIFIED send -- never after a guess."""
        with self._lock:
            self._last = Target(
                platform=str(platform or "").strip().lower(),
                destination=str(destination or "").strip(),
                destination_type=str(destination_type or ""),
                at=time.time(),
            )

    def resolve(self, platform: str, destination: str) -> Resolution:
        text = str(destination or "").strip().casefold()
        if text not in _REFERENCE:
            return Resolution(True, platform, destination)
        with self._lock:
            last = self._last
        if last is None:
            return Resolution(False, reason="there is no previous messaging destination to refer back to")
        requested_platform = str(platform or "").strip().lower()
        if requested_platform and requested_platform != last.platform:
            return Resolution(False, reason=(
                f"the last destination I have was on {last.platform}, not {requested_platform} -- "
                "say who explicitly"))
        return Resolution(True, last.platform, last.destination, last.destination_type)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            last = self._last
        if last is None:
            return {"active": False}
        return {"active": True, "platform": last.platform,
                "destination": last.destination, "at": last.at}

    def clear(self) -> None:
        with self._lock:
            self._last = None


_context = MessagingContext()


def get_context() -> MessagingContext:
    return _context
