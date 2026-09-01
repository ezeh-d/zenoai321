"""Speech-aware audio ducking -- lower the music while ZENO talks.

Reuses the existing pycaw ducker (audio_control.py), which is now refcounted,
so this composes with the mic-capture duck instead of fighting it: whichever
of {listening, speaking} still wants audio down keeps it down, and the music
only comes back when both are done.

Gated by ZENO_DUCK_ON_SPEAK (default on). Never raises out into the speech path.
"""

from __future__ import annotations

import os


def _enabled() -> bool:
    return (os.environ.get("ZENO_DUCK_ON_SPEAK", "1").strip().casefold()
            not in ("0", "off", "false", "no"))


def _level() -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get("ZENO_SPEAK_DUCK_LEVEL", "0.18"))))
    except Exception:  # noqa: BLE001
        return 0.18


def duck_for_speech() -> bool:
    """Lower other apps' audio for the duration of ZENO speaking. Best effort."""
    if not _enabled():
        return False
    try:
        from audio_control import duck_music
        return bool(duck_music(_level()))
    except Exception:  # noqa: BLE001 -- ducking must never break speech
        return False


def unduck_after_speech() -> bool:
    """Release the speech duck holder (music returns if nothing else holds it)."""
    if not _enabled():
        return False
    try:
        from audio_control import restore_music
        return bool(restore_music())
    except Exception:  # noqa: BLE001
        return False
