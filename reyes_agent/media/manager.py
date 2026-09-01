"""MediaManager -- the brain of the media engine.

Resolves what the user MEANS ("pause it", "skip this", "turn spotify down",
"what's playing") to a concrete session, dispatches to the right adapter,
re-reads the truth, and publishes an event so the live panel updates.

Conversational resolution
--------------------------
- an explicit source in the phrase ("spotify", "youtube", "vlc") wins;
- otherwise "it"/"that"/"this"/"the music"/None resolve to the session the
  user is most plausibly talking about: the current/playing one, or the last
  one we acted on or reported;
- with a single session, that session -- no ambiguity.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from reyes_agent.media import sessions as _sessions
from reyes_agent.media import events as _events
from reyes_agent.media.adapters import (
    WindowsMediaAdapter, SystemAudioAdapter, SpotifyAdapter)

# spoken action -> transport verb
_TRANSPORT = {
    "play": "play", "resume": "play", "unpause": "play",
    "pause": "pause", "stop": "stop", "halt": "pause",
    "toggle": "toggle", "playpause": "toggle", "play_pause": "toggle",
    "next": "next", "skip": "next", "forward": "next",
    "previous": "previous", "prev": "previous", "back": "previous",
    "seek": "seek",
}

# words that name a source, mapped to the friendly_source() value
_SOURCE_WORDS = {
    "spotify": "spotify", "youtube": "youtube", "chrome": "chrome",
    "edge": "edge", "firefox": "firefox", "brave": "brave", "opera": "opera",
    "vlc": "vlc", "groove": "groove", "apple music": "apple music",
    "itunes": "itunes", "windows media": "windows media player",
}


class MediaManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_app_id: str | None = None
        self._last_track_key: str | None = None
        self._win = WindowsMediaAdapter()
        self._audio = SystemAudioAdapter()
        self._spotify = SpotifyAdapter()
        self._bus = _events.get_event_bus()
        # live poller (runs only while a UI is watching)
        self._poll_lock = threading.Lock()
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._poll_refs = 0
        self._poll_interval = 1.5

    # -- state -------------------------------------------------------------
    def state(self, *, with_art: bool = False) -> _events.MediaPanelState:
        snaps, current = _sessions.snapshot_sessions()
        if with_art:
            for s in snaps:
                if s.title:
                    s.art_path = _sessions.fetch_album_art(s.app_id, s.title, s.artist)
        st = _events.MediaPanelState.from_snapshots(snaps, current)
        # remember an active session for later "it"/"that"
        active = st.active
        if active and active.get("app_id"):
            with self._lock:
                self._last_app_id = active["app_id"]
        return st

    def _emit_if_changed(self, st: _events.MediaPanelState) -> None:
        active = st.active or {}
        key = f"{active.get('app_id')}|{active.get('title')}|{active.get('artist')}"
        with self._lock:
            changed = key != self._last_track_key
            self._last_track_key = key
        if changed:
            self._bus.publish(_events.TRACK_CHANGED, {"active": active})
        self._bus.publish(_events.STATE, st.to_dict())

    # -- target resolution -------------------------------------------------
    def resolve_target(self, reference: str | None) -> str | None:
        """Best app_id for a phrase like 'it', 'that song', 'spotify'."""
        snaps, current = _sessions.snapshot_sessions()
        if not snaps:
            return None
        by_id = {s.app_id: s for s in snaps}
        ref = (reference or "").strip().lower()

        # 1. explicit source name in the phrase
        for word, src in _SOURCE_WORDS.items():
            if word in ref:
                for s in snaps:
                    if s.source == src or word in s.app_id.lower():
                        return s.app_id

        # 2. single session -> unambiguous
        if len(snaps) == 1:
            return snaps[0].app_id

        # 3. "it"/"that"/"the music"/empty -> current, else playing, else last
        if current and current in by_id:
            return current
        for s in snaps:
            if s.playing:
                return s.app_id
        with self._lock:
            if self._last_app_id in by_id:
                return self._last_app_id
        return snaps[0].app_id

    # -- describe ("what's playing") --------------------------------------
    def describe(self) -> str:
        st = self.state()
        if not st.sessions:
            return "Nothing is playing right now."
        playing = [s for s in st.sessions if s.get("playing")]
        pool = playing or st.sessions
        parts = [s.get("label", "") for s in pool[:3]]
        if len(pool) == 1:
            return parts[0].capitalize() if parts[0] else "Something is playing."
        return "Currently: " + "; ".join(p for p in parts if p)

    # -- the one command entry point --------------------------------------
    def command(self, action: str, *, reference: str | None = None,
                level: float | None = None, position_s: float | None = None,
                query: str | None = None) -> dict[str, Any]:
        action = (action or "").strip().lower()

        # what's playing?
        if action in ("status", "now_playing", "what", "whats_playing"):
            st = self.state(with_art=True)
            self._last_app_id = st.active_app_id or self._last_app_id
            return {"ok": True, "detail": self.describe(),
                    "state": st.to_dict(), "action": "status"}

        # per-app / master volume
        if action in ("volume", "set_volume", "volume_app", "louder", "quieter",
                      "volume_up", "volume_down", "mute", "unmute"):
            return self._volume(action, reference, level)

        # search-and-play a named song (Spotify Web API when connected)
        if action in ("play_query", "play_song", "search_play") or (
                action == "play" and query):
            return self._play_query(query or reference or "")

        # transport
        verb = _TRANSPORT.get(action)
        if not verb:
            return {"ok": False, "detail": f"unknown media action '{action}'",
                    "action": action}
        app_id = self.resolve_target(reference)
        with self._lock:
            if app_id:
                self._last_app_id = app_id
        res = self._win.command(verb, app_id=app_id,
                                position_s=float(position_s or 0.0))
        # Windows accepts a transport control instantly, but a player (Spotify,
        # a browser tab) can take up to ~1s to reflect it in its session info.
        # Briefly read back so the state we return/publish is the TRUTH, not a
        # pre-change snapshot -- returns as soon as it settles.
        if res.get("ok"):
            self._read_back(app_id, verb)
        st = self.state(with_art=True)
        self._emit_if_changed(st)
        out = dict(res)
        out.update({"action": verb, "target": app_id, "state": st.to_dict()})
        return out

    def _read_back(self, app_id: str | None, verb: str,
                   timeout_s: float = 1.2) -> None:
        """Poll briefly until the target session reflects `verb`, or timeout."""
        expect_playing = {"play": True, "pause": False, "stop": False}.get(verb)
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            snaps, _ = _sessions.snapshot_sessions()
            target = None
            for s in snaps:
                if app_id and s.app_id == app_id:
                    target = s
                    break
            if target is None:
                return
            if expect_playing is None:
                # toggle/next/previous: no boolean to await -- one short settle
                time.sleep(0.25)
                return
            if target.playing == expect_playing:
                return
            time.sleep(0.13)

    # -- helpers -----------------------------------------------------------
    def _volume(self, action: str, reference: str | None,
                level: float | None) -> dict[str, Any]:
        # relative nudges
        delta = {"louder": +0.15, "volume_up": +0.15,
                 "quieter": -0.15, "volume_down": -0.15}.get(action)
        if action in ("mute", "unmute"):
            level = 0.0 if action == "mute" else (level if level is not None else 0.5)

        app_id = self.resolve_target(reference) if reference else None
        # a named app -> per-app volume; otherwise the master
        target_app = None
        ref = (reference or "").lower()
        if any(w in ref for w in _SOURCE_WORDS) and app_id:
            target_app = app_id

        if delta is not None:
            # nudge relative to the app's current or master; simplest correct
            # behaviour: nudge master unless an app was named.
            base = 0.5 if level is None else level
            level = max(0.0, min(1.0, base + delta))

        if level is None:
            return {"ok": False, "detail": "no volume level given", "action": "volume"}

        if target_app:
            res = self._audio.set_app_volume(target_app, level)
        else:
            res = self._audio.set_master_volume(level)
        self._bus.publish(_events.VOLUME_CHANGED,
                          {"app_id": target_app, "level": level})
        out = dict(res)
        out.update({"action": "volume", "target": target_app or "master",
                    "level": level})
        return out

    def _play_query(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"ok": False, "detail": "no song named", "action": "play_query"}
        # richer path first: Spotify Web API, only if the user connected it
        if self._spotify.available() and self._spotify.connected():
            res = self._spotify.play_query(query)
            if res.get("ok"):
                st = self.state(with_art=True)
                self._emit_if_changed(st)
                out = dict(res)
                out.update({"action": "play_query", "via": "spotify_api",
                            "state": st.to_dict()})
                return out
        # fall back: we can't search without the API, but we can resume the
        # current session so "play <song>" at least starts the player.
        app_id = self.resolve_target("spotify")
        res = self._win.command("play", app_id=app_id)
        st = self.state(with_art=True)
        self._emit_if_changed(st)
        out = dict(res)
        out.update({"action": "play_query", "via": "windows_fallback",
                    "note": ("named-song search needs Spotify connected; "
                             "resumed the current player instead"),
                    "target": app_id, "state": st.to_dict()})
        return out

    # -- live polling (external changes -> events, only while watched) -----
    def poll_tick(self) -> bool:
        """Snapshot once; emit only if the active track changed. Returns True
        if it emitted. This is how a track changed *in Spotify itself* reaches
        the panel without the user touching ZENO."""
        st = self.state()
        active = st.active or {}
        key = f"{active.get('app_id')}|{active.get('title')}|{active.get('artist')}"
        with self._lock:
            changed = key != self._last_track_key
        if not changed:
            return False
        st = self.state(with_art=True)   # only fetch art when something changed
        self._emit_if_changed(st)
        return True

    def _poll_loop(self) -> None:
        while not self._poll_stop.wait(self._poll_interval):
            try:
                self.poll_tick()
            except Exception:  # noqa: BLE001 -- polling never crashes the app
                continue

    def add_live_watcher(self) -> None:
        """A UI started watching -> ensure the poller runs."""
        with self._poll_lock:
            self._poll_refs += 1
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_stop.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop, name="zeno-media-poll", daemon=True)
            self._poll_thread.start()

    def remove_live_watcher(self) -> None:
        """A UI stopped watching -> stop the poller when the last one leaves."""
        with self._poll_lock:
            self._poll_refs = max(0, self._poll_refs - 1)
            if self._poll_refs == 0:
                self._poll_stop.set()
                self._poll_thread = None

    def status(self) -> dict[str, Any]:
        return {
            "sessions_available": _sessions.available(),
            "audio_available": self._audio.available(),
            "spotify_available": self._spotify.available(),
            "spotify_connected": self._spotify.connected(),
            "subscribers": self._bus.subscriber_count(),
            "live_watchers": self._poll_refs,
            "last_app_id": self._last_app_id,
        }


_manager: MediaManager | None = None
_manager_lock = threading.Lock()
_bridge_installed = False


def _install_event_bus_bridge(mgr: "MediaManager") -> None:
    """Forward media events onto the app-wide event_bus so the existing UI
    consumers (the desktop HUD, the companion web UI) react to media changes
    through the same pipeline they already use for `agent.speaking` etc.

    Installed only on the shared singleton (not on directly-constructed
    instances in tests), and fully guarded -- a missing event_bus never
    breaks media control.
    """
    global _bridge_installed
    if _bridge_installed:
        return
    try:
        from reyes_agent import event_bus
    except Exception:  # noqa: BLE001
        return

    def _forward(evt) -> None:
        try:
            event_bus.publish(f"media.{evt.type}", evt.payload,
                              source="media_manager")
        except Exception:  # noqa: BLE001 -- UI telemetry never breaks playback
            pass

    try:
        mgr._bus.subscribe(_forward)
        _bridge_installed = True
    except Exception:  # noqa: BLE001
        pass


def get_media_manager() -> MediaManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = MediaManager()
                _install_event_bus_bridge(_manager)
    return _manager
