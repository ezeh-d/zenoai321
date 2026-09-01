"""GSMTC reader -- the live truth of what Windows is playing.

Windows exposes every media app that registers transport controls (Spotify,
Chrome/YouTube, Edge, VLC, Groove, ...) through the Global System Media
Transport Controls (GSMTC). This reads them: title, artist, album, play state,
position, and album art, normalised into one `MediaSnapshot` shape.

WinRT discipline: GSMTC objects are async and COM-thread-affine. Calling
``asyncio.run`` per poll leaks native handles (the same failure the
notification listener hit). So all GSMTC work runs on ONE dedicated daemon
event loop, and wrappers are released with an explicit gc on that loop --
mirroring reyes_agent/notification_listener.py deliberately.

Degrades: if winsdk (or the GSMTC namespace) isn't importable, ``available()``
is False and ``snapshot_sessions()`` returns ``([], None)`` -- callers fall
back to blind media keys unchanged.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

_WINRT_TIMEOUT_S = float(os.environ.get("ZENO_MEDIA_WINRT_TIMEOUT_S", "3.0"))

# GSMTC playback_status enum -> a plain word. Values are stable in WinRT:
# 0 Closed, 1 Opened, 2 Changing, 3 Stopped, 4 Playing, 5 Paused.
_STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped",
           4: "playing", 5: "paused"}


@dataclass
class MediaSnapshot:
    """One media session, normalised. Everything a panel or the brain needs."""
    app_id: str                       # source_app_user_model_id, e.g. "Spotify.exe"
    source: str                       # friendly: "spotify", "chrome", "vlc", ...
    title: str = ""
    artist: str = ""
    album: str = ""
    status: str = "unknown"           # playing/paused/stopped/...
    is_current: bool = False          # the OS "current" session
    position_s: float = 0.0
    duration_s: float = 0.0
    can_play: bool = False
    can_pause: bool = False
    can_next: bool = False
    can_previous: bool = False
    art_path: str = ""                # local cached album-art file, if fetched
    updated_at: float = 0.0

    @property
    def playing(self) -> bool:
        return self.status == "playing"

    def label(self) -> str:
        """A one-line human description: 'Spotify -- Song by Artist (paused)'."""
        who = self.source.title() if self.source else (self.app_id or "media")
        what = self.title or "something"
        if self.artist:
            what = f"{what} by {self.artist}"
        state = "" if self.status in ("playing", "unknown") else f" ({self.status})"
        return f"{who} -- {what}{state}"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "app_id": self.app_id, "source": self.source, "title": self.title,
            "artist": self.artist, "album": self.album, "status": self.status,
            "is_current": self.is_current, "position_s": round(self.position_s, 2),
            "duration_s": round(self.duration_s, 2), "playing": self.playing,
            "can_play": self.can_play, "can_pause": self.can_pause,
            "can_next": self.can_next, "can_previous": self.can_previous,
            "art_path": self.art_path, "updated_at": self.updated_at,
            "label": self.label(),
        }
        return d


# --- friendly source naming -------------------------------------------------
# app_id examples: "Spotify.exe", "chrome.exe", "msedge.exe", "vlc.exe",
# "308046B0AF4A39CB.CanaryChannel..." (Store apps), a Firefox hex AUMID, etc.
_SOURCE_HINTS = (
    ("spotify", "spotify"), ("chrome", "chrome"), ("msedge", "edge"),
    ("edge", "edge"), ("firefox", "firefox"), ("vlc", "vlc"),
    ("zenmedia", "vlc"), ("groove", "groove"), ("music.ui", "apple music"),
    ("apple", "apple music"), ("brave", "brave"), ("opera", "opera"),
    ("mpc", "media player classic"), ("wmplayer", "windows media player"),
    ("foobar", "foobar2000"), ("itunes", "itunes"), ("youtube", "youtube"),
)


def friendly_source(app_id: str) -> str:
    low = (app_id or "").lower()
    for needle, name in _SOURCE_HINTS:
        if needle in low:
            return name
    # strip ".exe" and any AUMID suffix for a readable fallback
    base = low.split("!")[0].split(".exe")[0].split("\\")[-1]
    return base or "media"


# --- the dedicated WinRT loop (mirrors notification_listener.py) -------------
_loop_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_ready = threading.Event()


def _loop_main() -> None:
    global _loop, _loop_thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with _loop_lock:
        _loop = loop
        _loop_ready.set()
    try:
        loop.run_forever()
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            with _loop_lock:
                if _loop is loop:
                    _loop = None
                    _loop_thread = None
                _loop_ready.clear()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop_thread
    with _loop_lock:
        if _loop is not None and _loop_thread is not None and _loop_thread.is_alive():
            return _loop
        _loop_ready.clear()
        _loop_thread = threading.Thread(
            target=_loop_main, name="zeno-media-winrt", daemon=True)
        _loop_thread.start()
    if not _loop_ready.wait(timeout=2.0):
        raise TimeoutError("Media WinRT loop did not start.")
    with _loop_lock:
        if _loop is None:
            raise RuntimeError("Media WinRT loop stopped during startup.")
        return _loop


def run_winrt(factory: Callable[[], Awaitable[Any]], *,
              timeout: float | None = None) -> Any:
    """Run a WinRT coroutine on the dedicated loop and return its result.

    `factory` is a no-arg callable returning the awaitable, so the coroutine is
    created on the owning loop's thread (WinRT objects are thread-affine).
    Raises on timeout or failure; callers catch and degrade.
    """
    timeout = _WINRT_TIMEOUT_S if timeout is None else timeout
    loop = _ensure_loop()

    async def invoke() -> Any:
        try:
            return await factory()
        finally:
            gc.collect()  # release WinRT wrapper cycles on their owning thread

    coro = invoke()
    try:
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception:
        coro.close()
        raise
    try:
        return fut.result(timeout=timeout + 2.0)
    except TimeoutError:
        fut.cancel()
        raise


# --- availability ------------------------------------------------------------
_available: bool | None = None


def available() -> bool:
    """True when the GSMTC namespace is importable on this machine."""
    global _available
    if _available is None:
        try:
            from winsdk.windows.media.control import (  # noqa: F401
                GlobalSystemMediaTransportControlsSessionManager)
            _available = True
        except Exception:  # noqa: BLE001 -- optional; degrade to media keys
            _available = False
    return _available


# --- the reader --------------------------------------------------------------
async def _session_manager():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Mgr)
    return await Mgr.request_async()


def _timedelta_seconds(value: Any) -> float:
    try:
        return max(0.0, float(value.total_seconds()))
    except Exception:  # noqa: BLE001
        try:
            return max(0.0, float(value))
        except Exception:  # noqa: BLE001
            return 0.0


async def _read_one(session, current_id: str) -> MediaSnapshot:
    app_id = ""
    try:
        app_id = str(session.source_app_user_model_id or "")
    except Exception:  # noqa: BLE001
        app_id = ""

    snap = MediaSnapshot(app_id=app_id, source=friendly_source(app_id),
                         updated_at=time.time())
    # playback info + controls
    try:
        info = session.get_playback_info()
        snap.status = _STATUS.get(int(info.playback_status), "unknown")
        controls = info.controls
        snap.can_play = bool(getattr(controls, "is_play_enabled", False))
        snap.can_pause = bool(getattr(controls, "is_pause_enabled", False))
        snap.can_next = bool(getattr(controls, "is_next_enabled", False))
        snap.can_previous = bool(getattr(controls, "is_previous_enabled", False))
    except Exception:  # noqa: BLE001
        pass
    # media properties (title/artist/album)
    try:
        props = await session.try_get_media_properties_async()
        snap.title = str(getattr(props, "title", "") or "")
        snap.artist = str(getattr(props, "artist", "") or "")
        snap.album = str(getattr(props, "album_title", "") or "")
    except Exception:  # noqa: BLE001
        pass
    # timeline (position / duration)
    try:
        tl = session.get_timeline_properties()
        snap.position_s = _timedelta_seconds(tl.position)
        snap.duration_s = _timedelta_seconds(tl.end_time)
    except Exception:  # noqa: BLE001
        pass
    snap.is_current = bool(app_id and app_id == current_id)
    return snap


async def _snapshot_async() -> tuple[list[MediaSnapshot], str | None]:
    mgr = await _session_manager()
    current_id = ""
    try:
        cur = mgr.get_current_session()
        if cur is not None:
            current_id = str(cur.source_app_user_model_id or "")
    except Exception:  # noqa: BLE001
        current_id = ""

    out: list[MediaSnapshot] = []
    try:
        sessions = list(mgr.get_sessions())
    except Exception:  # noqa: BLE001
        sessions = []
    for s in sessions:
        try:
            out.append(await _read_one(s, current_id))
        except Exception:  # noqa: BLE001 -- one bad session never sinks the read
            continue
    return out, (current_id or None)


def snapshot_sessions() -> tuple[list[MediaSnapshot], str | None]:
    """All current media sessions + the current session's app_id.

    Returns ``([], None)`` if GSMTC is unavailable or the read fails -- never
    raises, so it is safe on the hot path and off-Windows.
    """
    if not available():
        return [], None
    try:
        return run_winrt(_snapshot_async)
    except Exception:  # noqa: BLE001 -- degrade to "nothing known"
        return [], None


# --- album art (lazy, cached) ------------------------------------------------
def _art_cache_dir() -> str:
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
            or os.path.expanduser("~"))
    path = os.path.join(base, "ZENO", "media_art")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return path


def _art_key(app_id: str, title: str, artist: str) -> str:
    raw = f"{app_id}|{title}|{artist}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()[:20]


async def _read_thumbnail_bytes(session) -> bytes:
    props = await session.try_get_media_properties_async()
    ref = getattr(props, "thumbnail", None)
    if ref is None:
        return b""
    from winsdk.windows.storage.streams import DataReader
    stream = await ref.open_read_async()
    size = int(stream.size)
    if size <= 0:
        return b""
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(size)
    buf = bytearray(size)
    reader.read_bytes(buf)
    return bytes(buf)


async def _fetch_art_async(app_id: str) -> bytes:
    mgr = await _session_manager()
    target = None
    for s in mgr.get_sessions():
        try:
            if str(s.source_app_user_model_id or "") == app_id:
                target = s
                break
        except Exception:  # noqa: BLE001
            continue
    if target is None:
        try:
            target = mgr.get_current_session()
        except Exception:  # noqa: BLE001
            target = None
    if target is None:
        return b""
    return await _read_thumbnail_bytes(target)


def _art_extension(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".img"


def fetch_album_art(app_id: str, title: str = "", artist: str = "") -> str:
    """Cache the album art for a session to a local file; return its path ('' on failure).

    Cached by (app_id, title, artist) so the same track isn't re-read; the
    extension matches the real image format so a UI can serve it correctly.
    Best effort: any failure returns ''.
    """
    if not available():
        return ""
    key = _art_key(app_id, title, artist)
    cache = _art_cache_dir()
    # any previously cached format for this key
    for ext in (".png", ".jpg", ".webp", ".gif", ".img"):
        existing = os.path.join(cache, f"{key}{ext}")
        if os.path.exists(existing) and os.path.getsize(existing) > 0:
            return existing
    try:
        data = run_winrt(lambda: _fetch_art_async(app_id))
    except Exception:  # noqa: BLE001
        return ""
    if not data:
        return ""
    path = os.path.join(cache, f"{key}{_art_extension(data)}")
    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except Exception:  # noqa: BLE001
        return ""
    return path


# --- targeted control (GSMTC transport controls) ----------------------------
async def _find_session(mgr, app_id: str | None):
    if app_id:
        for s in mgr.get_sessions():
            try:
                if str(s.source_app_user_model_id or "") == app_id:
                    return s
            except Exception:  # noqa: BLE001
                continue
    try:
        return mgr.get_current_session()
    except Exception:  # noqa: BLE001
        return None


async def _control_async(app_id: str | None, verb: str, position_s: float) -> bool:
    mgr = await _session_manager()
    target = await _find_session(mgr, app_id)
    if target is None:
        return False
    if verb == "play":
        return bool(await target.try_play_async())
    if verb == "pause":
        return bool(await target.try_pause_async())
    if verb == "toggle":
        return bool(await target.try_toggle_play_pause_async())
    if verb == "next":
        return bool(await target.try_skip_next_async())
    if verb == "previous":
        return bool(await target.try_skip_previous_async())
    if verb == "stop":
        return bool(await target.try_stop_async())
    if verb == "seek":
        # WinRT expects 100-ns ticks
        ticks = int(max(0.0, position_s) * 10_000_000)
        return bool(await target.try_change_playback_position_async(ticks))
    return False


def control_session(verb: str, *, app_id: str | None = None,
                    position_s: float = 0.0) -> bool:
    """Drive a SPECIFIC session's transport controls via GSMTC.

    verb: play | pause | toggle | next | previous | stop | seek. Targets the
    session whose app_id matches, else the OS current session. Returns True on
    a confirmed success from Windows, False otherwise (caller may fall back to
    blind media keys). Never raises.
    """
    if not available():
        return False
    try:
        return bool(run_winrt(lambda: _control_async(app_id, verb, position_s)))
    except Exception:  # noqa: BLE001
        return False


def status() -> dict[str, Any]:
    return {"available": available(), "winrt_timeout_s": _WINRT_TIMEOUT_S,
            "art_cache": _art_cache_dir()}
