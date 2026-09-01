"""How a media command actually reaches the machine.

Three adapters, tried/selected by the manager:

- WindowsMediaAdapter  : GSMTC transport controls for a SPECIFIC session
                         (targeted play/pause/next/seek), with a fall-back to
                         the blunt system media keys (tools/system.media_control)
                         when a targeted control is unavailable.
- SystemAudioAdapter   : per-application volume via pycaw (turn Spotify down
                         without touching the master), plus master volume.
- SpotifyAdapter       : the Spotify Web API for the richer things GSMTC can't
                         do (search-and-play, playlists, device transfer).
                         Optional and gated on credentials; see media/spotify.py.

Each adapter answers ``available()`` and never raises out of a command -- it
returns a small result dict ``{ok, detail, ...}`` so the manager can report and,
where sensible, fall back.
"""

from __future__ import annotations

from typing import Any

from reyes_agent.media import sessions as _sessions


def _result(ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"ok": bool(ok), "detail": detail}
    out.update(extra)
    return out


# --- Windows transport controls ---------------------------------------------
class WindowsMediaAdapter:
    """Targeted transport control through GSMTC, media-keys as the safety net."""

    name = "windows"

    def available(self) -> bool:
        return _sessions.available()

    def _media_key_fallback(self, verb: str) -> dict[str, Any]:
        """Blunt system media key -- reuses the existing tool, no duplication."""
        key_verb = {"play": "play_pause", "pause": "play_pause",
                    "toggle": "play_pause", "next": "next",
                    "previous": "previous"}.get(verb)
        if not key_verb:
            return _result(False, f"no media-key equivalent for '{verb}'")
        try:
            from reyes_agent.tools.system import media_control
            msg = media_control(key_verb)
            return _result(True, f"media key ({key_verb}): {msg}", method="media_key")
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"media key failed: {exc}")

    def command(self, verb: str, *, app_id: str | None = None,
                position_s: float = 0.0) -> dict[str, Any]:
        # Try the targeted GSMTC control first -- it drives the exact session
        # and confirms success.
        if self.available():
            ok = _sessions.control_session(verb, app_id=app_id, position_s=position_s)
            if ok:
                return _result(True, f"{verb} via Windows session controls",
                               method="gsmtc", app_id=app_id)
        # Fall back to the hardware media key for the transport verbs it covers.
        if verb in ("play", "pause", "toggle", "next", "previous"):
            return self._media_key_fallback(verb)
        return _result(False, f"'{verb}' not available (no session accepted it)")


# --- per-application + master volume (pycaw) ---------------------------------
class SystemAudioAdapter:
    """Per-app and master volume. Mirrors audio_control.py's pycaw session walk."""

    name = "audio"

    def available(self) -> bool:
        try:
            import pycaw.pycaw  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _proc_name(app_id: str) -> str:
        # GSMTC app_id is usually the exe ("Spotify.exe"); pycaw matches on it.
        return (app_id or "").split("!")[0].split("\\")[-1].lower()

    @staticmethod
    def _match(want: str, pname: str) -> bool:
        if not want or not pname:
            return False
        return want in pname or pname in want

    def _walk_default(self, want: str, level: float) -> tuple[int, float | None]:
        """Fast path: sessions on the default render endpoint (like pycaw does)."""
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        matched, observed = 0, None
        for session in AudioUtilities.GetAllSessions():
            pname = ""
            try:
                if session.Process:
                    pname = session.Process.name().lower()
                elif session.DisplayName:
                    pname = str(session.DisplayName).lower()
            except Exception:  # noqa: BLE001
                pname = ""
            if not self._match(want, pname):
                continue
            try:
                vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                vol.SetMasterVolume(level, None)
                observed = round(float(vol.GetMasterVolume()), 3)
                matched += 1
            except Exception:  # noqa: BLE001
                continue
        return matched, observed

    def set_app_volume(self, app_id: str, level: float) -> dict[str, Any]:
        """Set one application's volume (0.0-1.0). Matches by process name.

        Uses pycaw's managed session enumeration -- the same safe path the
        existing audio ducker (audio_control.py) relies on. (A raw multi-
        endpoint COM walk was tried and rejected: comtypes released the
        interface pointers unsafely on GC, raising access violations that
        could destabilise the long-running process. Correctness over reach.)
        The app must have an ACTIVE audio session on the default output; an app
        rendering silently or to a disconnected device won't be found.
        """
        if not self.available():
            return _result(False, "pycaw unavailable")
        level = max(0.0, min(1.0, float(level)))
        want = self._proc_name(app_id)
        try:
            matched, observed = self._walk_default(want, level)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"session walk failed: {exc}")
        if not matched:
            return _result(False, f"no active audio session for '{app_id}' "
                                  "(the app may not be rendering audio right now)")
        return _result(True, f"{want} volume -> {int(level * 100)}%",
                       matched=matched, observed=observed)

    def get_master_volume(self) -> float | None:
        """Current system master volume (0.0-1.0), or None if unreadable.
        Lets relative nudges ('turn it up') work from the REAL level."""
        if not self.available():
            return None
        try:
            from pycaw.pycaw import AudioUtilities
            vol = AudioUtilities.GetSpeakers().EndpointVolume
            return round(float(vol.GetMasterVolumeLevelScalar()), 3)
        except Exception:  # noqa: BLE001
            return None

    def set_master_volume(self, level: float) -> dict[str, Any]:
        """System master volume via the existing verified tool (no duplication)."""
        level = max(0.0, min(1.0, float(level)))
        try:
            from reyes_agent.tools.utility import set_volume
            msg = set_volume(int(round(level * 100)))
            ok = "verified" in msg.lower() or "set to" in msg.lower()
            return _result(ok, msg, method="set_volume")
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"master volume failed: {exc}")


# --- Spotify Web API (optional, gated) --------------------------------------
class SpotifyAdapter:
    """Richer Spotify ops (search-and-play, playlists, devices) via the Web API.

    Fully optional: needs SPOTIFY credentials and a one-time OAuth (PKCE). When
    unconfigured, ``available()`` is False and the manager routes Spotify through
    the Windows session path like any other player.
    """

    name = "spotify"

    def __init__(self) -> None:
        self._client = None

    def _get(self):
        if self._client is None:
            from reyes_agent.media.spotify import SpotifyClient
            self._client = SpotifyClient()
        return self._client

    def available(self) -> bool:
        try:
            return self._get().available()
        except Exception:  # noqa: BLE001
            return False

    def connected(self) -> bool:
        try:
            return self._get().connected()
        except Exception:  # noqa: BLE001
            return False

    def play_query(self, query: str) -> dict[str, Any]:
        try:
            return self._get().play_query(query)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"spotify play failed: {exc}")

    def now_playing(self) -> dict[str, Any]:
        try:
            return self._get().now_playing()
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"spotify status failed: {exc}")
