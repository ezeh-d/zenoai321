"""Noticing that a network died, and saying so without overpromising.

    "Do NOT pretend an existing WebRTC session can magically move networks
     if the browser/network connection has died."

That instruction is the design. When the router drops, the phone's socket is
gone -- there is no handover to perform, because the far end of the
connection no longer exists. A peer connection is bound to the addresses it
negotiated; it cannot be carried to a different network any more than a phone
call can be carried to a different phone.

So this does exactly two things: it WATCHES, and it TELLS. It does not
reconnect anything, it does not switch routes behind the owner's back, and it
does not touch the hotspot. When Wi-Fi disappears and the hotspot is up, the
owner is told the hotspot is available -- and reconnecting is their decision,
made by scanning a fresh code.

WHAT SURVIVES A NETWORK CHANGE, AND WHAT DOES NOT
-------------------------------------------------
SURVIVES: the trusted device. The phone was paired, and pairing is a property
of the device, not of the address it had at the time. Moving from Wi-Fi to
hotspot does not make it a stranger, so it does not pair again.

DOES NOT SURVIVE: the session and the WebRTC peer connection. A new session
token is issued for the new connection. That is not ceremony -- the old
session was established over a network that is gone, and a session should not
outlive the channel that authenticated it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent.remote_mic import routes

# How often to look. Adapter enumeration is a warm in-process call, so this is
# cheap; the interval is about not spamming the owner, not about cost.
WATCH_EVERY_S = 6.0

# Do not announce anything until a route has been missing for this long. Wi-Fi
# blinks. An announcement per blink would train the owner to ignore them.
CONFIRM_AFTER_S = 12.0


@dataclass
class Change:
    at: float = 0.0
    lost: str = ""
    lost_ip: str = ""
    alternative: str = ""
    alternative_ip: str = ""
    was_carrying_audio: bool = False

    def say(self) -> str:
        """What ZENO tells the owner. Only ever about what is true now."""
        which = ("The Wi-Fi connection" if self.lost == routes.LAN_WIFI
                 else "My laptop hotspot")
        if not self.alternative:
            if self.was_carrying_audio:
                return (f"{which} was lost, so your phone microphone has "
                        "dropped. I have no other local network available "
                        "right now.")
            return f"{which} is no longer available."
        other = ("my laptop hotspot" if self.alternative == routes.HOTSPOT
                 else "the normal Wi-Fi network")
        if self.was_carrying_audio:
            return (f"{which} was lost, so your phone microphone dropped. "
                    f"{other.capitalize()} is available if you want to "
                    "reconnect the phone there -- I can show a new code.")
        return (f"{which} was lost. {other.capitalize()} is available if you "
                "want to connect the phone there.")

    def as_dict(self) -> dict[str, Any]:
        return {"at": self.at, "lost": self.lost, "lost_ip": self.lost_ip,
                "alternative": self.alternative,
                "alternative_ip": self.alternative_ip,
                "was_carrying_audio": self.was_carrying_audio,
                "spoken": self.say()}


class RouteWatcher:
    """Watches the route list and reports losses once each."""

    def __init__(self, announce: Callable[[Change], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._announce = announce
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._seen: dict[str, str] = {}          # mode -> ipv4 last seen up
        self._missing_since: dict[str, float] = {}
        self._history: list[Change] = []

    # -- inspection -------------------------------------------------------
    def inspect(self) -> list[Change]:
        """One pass. Returns changes worth announcing, and remembers them."""
        now = time.time()
        live = {r.mode: r.ipv4 for r in routes.selector().routes(probe=False)}
        changes: list[Change] = []

        with self._lock:
            for mode, ip in live.items():
                self._seen[mode] = ip
                self._missing_since.pop(mode, None)

            for mode in list(self._seen):
                if mode in live:
                    continue
                first = self._missing_since.setdefault(mode, now)
                if now - first < CONFIRM_AFTER_S:
                    continue          # still inside the blink window
                lost_ip = self._seen.pop(mode, "")
                self._missing_since.pop(mode, None)
                other = next((m for m in live if m != mode), "")
                change = Change(at=now, lost=mode, lost_ip=lost_ip,
                                alternative=other, alternative_ip=live.get(other, ""),
                                was_carrying_audio=self._carrying(lost_ip))
                self._history.append(change)
                changes.append(change)

        for change in changes:
            if self._announce is not None:
                try:
                    self._announce(change)
                except Exception:  # noqa: BLE001
                    pass
        return changes

    def _carrying(self, lost_ip: str) -> bool:
        """Was the phone's audio actually arriving over the route that died.

        Read from the live peer address, so "your microphone dropped" is
        never said about a network the phone was not using.
        """
        if not lost_ip:
            return False
        try:
            from reyes_agent.remote_mic import get_remote_mic_runtime

            live = get_remote_mic_runtime().status()
            peer = str(live.get("peer_ip") or "")
            if not peer:
                return False
            return peer.rsplit(".", 1)[0] == lost_ip.rsplit(".", 1)[0]
        except Exception:  # noqa: BLE001
            return False

    # -- lifecycle --------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="zeno-route-watch",
                                            daemon=True)
            self._thread.start()
            return True

    def _run(self) -> None:
        # Seed first so the very first pass does not report every route as
        # newly discovered -- and never announces a loss for a network that
        # was already down when ZENO started.
        try:
            self.inspect()
        except Exception:  # noqa: BLE001
            pass
        while not self._stop.wait(WATCH_EVERY_S):
            try:
                self.inspect()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=3)

    def status(self) -> dict[str, Any]:
        with self._lock:
            watching = self._thread is not None and self._thread.is_alive()
            return {
                "state": "ONLINE" if watching else "STANDBY",
                "known_routes": dict(self._seen),
                "pending_confirmation": {m: round(time.time() - t, 1)
                                         for m, t in self._missing_since.items()},
                "confirm_after_s": CONFIRM_AFTER_S,
                "recent": [c.as_dict() for c in self._history[-5:]],
                "does_not": ("switch networks by itself, move a live WebRTC "
                             "session, or alter the hotspot"),
            }


_watcher: RouteWatcher | None = None


def get_watcher() -> RouteWatcher:
    global _watcher
    if _watcher is None:
        _watcher = RouteWatcher(announce=_speak)
    return _watcher


def _speak(change: Change) -> None:
    """Say it out loud, if the desktop voice is up. Never fatal."""
    try:
        from reyes_agent.voice_manager import speak_queued

        speak_queued(change.say())
    except Exception:  # noqa: BLE001
        pass


def status() -> dict[str, Any]:
    return get_watcher().status()
