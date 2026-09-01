from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class _SessionVolume:
    volume: object
    original_level: float
    original_muted: bool


_lock = threading.RLock()
_saved_sessions: list[_SessionVolume] = []
_ducked = False
# How many independent holders currently want audio ducked. Mic capture and
# speech playback duck independently; the actual restore happens only when the
# LAST holder releases, so one releasing never un-ducks for the other. Balanced
# 1:1 callers (the mic listen/finish pair) behave exactly as before.
_duck_refcount = 0

# Keep system sounds and REYES audible. Everything else with an active audio
# session is lowered while REYES captures a command.
EXCLUDED_PROCESS_NAMES = {
    "python.exe",
    "pythonw.exe",
    "system sounds",
}


def _load_audio_utilities():
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        return AudioUtilities, ISimpleAudioVolume
    except Exception:
        return None, None


def duck_music(level: float = 0.12) -> bool:
    """Lower active application audio sessions and remember their volumes.

    Refcounted: repeated calls stack. The first call performs the duck; later
    calls only register another holder so a single restore can't un-duck while
    another holder still wants it down.
    """
    global _ducked, _saved_sessions, _duck_refcount
    level = max(0.0, min(1.0, float(level)))

    with _lock:
        _duck_refcount += 1
        if _ducked:
            return True

        AudioUtilities, ISimpleAudioVolume = _load_audio_utilities()
        if AudioUtilities is None:
            print("[Audio Ducking] pycaw is unavailable; continuing without ducking.")
            return False

        saved: list[_SessionVolume] = []
        try:
            for session in AudioUtilities.GetAllSessions():
                process_name = ""
                try:
                    if session.Process:
                        process_name = session.Process.name().lower()
                    elif session.DisplayName:
                        process_name = str(session.DisplayName).lower()
                except Exception:
                    process_name = ""

                if process_name in EXCLUDED_PROCESS_NAMES:
                    continue

                try:
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    original = float(volume.GetMasterVolume())
                    muted = bool(volume.GetMute())
                    saved.append(_SessionVolume(volume, original, muted))
                    if not muted and original > level:
                        volume.SetMasterVolume(level, None)
                except Exception:
                    continue

            _saved_sessions = saved
            _ducked = bool(saved)
            if _ducked:
                print(f"[Audio Ducking] Lowered {len(saved)} audio session(s).")
            return _ducked
        except Exception as error:
            print(f"[Audio Ducking Error] {error}")
            _saved_sessions = []
            _ducked = False
            return False


def restore_music() -> bool:
    """Release one duck holder; restore audio only when the last one releases."""
    global _ducked, _saved_sessions, _duck_refcount
    with _lock:
        if _duck_refcount > 0:
            _duck_refcount -= 1
        # Another holder still wants audio down -- don't restore yet.
        if _duck_refcount > 0:
            return False

        if not _saved_sessions:
            _ducked = False
            return False

        restored = 0
        for item in _saved_sessions:
            try:
                item.volume.SetMasterVolume(item.original_level, None)
                item.volume.SetMute(item.original_muted, None)
                restored += 1
            except Exception:
                continue

        _saved_sessions = []
        _ducked = False
        print(f"[Audio Ducking] Restored {restored} audio session(s).")
        return restored > 0


def is_ducked() -> bool:
    with _lock:
        return _ducked


def duck_depth() -> int:
    """How many holders currently want audio ducked (0 = restored)."""
    with _lock:
        return _duck_refcount
