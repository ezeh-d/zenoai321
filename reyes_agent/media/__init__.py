"""ZENO Universal Media Intelligence.

A first-class media engine that KNOWS what is playing (not just fires media
keys blindly). It reads Windows' own media sessions -- Spotify, a YouTube tab,
VLC, anything that registers with the OS -- normalises them into one shape, and
controls the *specific* session the user means ("pause it", "skip this",
"turn spotify down").

Layers
------
- sessions.py : GSMTC reader -- the live "what's playing" truth from Windows.
- events.py   : MediaPanelState (the normalised UI shape) + MediaEventBus.
- adapters.py : how a command reaches the OS/provider (Windows transport
                controls, per-app volume via pycaw, optional Spotify Web API).
- manager.py  : MediaManager -- resolves "it"/"that"/"spotify" to a session,
                dispatches to the right adapter, re-reads, and publishes events.
- ducking.py  : speech-aware audio ducking, reusing the existing pycaw ducker.

REUSES, NEVER DUPLICATES
------------------------
This engine sits ON TOP of what ZENO already had:
- tools/system.py `media_control` (pyautogui media keys) -- the blunt fallback.
- tools/utility.py `set_volume` (pycaw master volume).
- audio_control.py (pycaw session ducking) -- reused by ducking.py.
- the WinRT async-loop discipline from notification_listener.py -- mirrored,
  so native WinRT handles don't leak.

DEGRADES, NEVER BREAKS
----------------------
Every layer works with no dependencies present: no winsdk -> no live sessions
(empty state, media keys still work); no pycaw -> no per-app volume; no Spotify
credentials -> the Spotify adapter reports "not connected" and the Windows path
still drives Spotify like any other session.
"""

from __future__ import annotations

__all__ = [
    "MediaSnapshot",
    "snapshot_sessions",
    "MediaPanelState",
    "MediaEvent",
    "MediaEventBus",
    "get_event_bus",
    "MediaManager",
    "get_media_manager",
]


def __getattr__(name: str):  # lazy re-exports; avoid importing winsdk/pycaw eagerly
    if name in ("MediaSnapshot", "snapshot_sessions"):
        from reyes_agent.media import sessions as _m
        return getattr(_m, name)
    if name in ("MediaPanelState", "MediaEvent", "MediaEventBus", "get_event_bus"):
        from reyes_agent.media import events as _m
        return getattr(_m, name)
    if name in ("MediaManager", "get_media_manager"):
        from reyes_agent.media import manager as _m
        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
