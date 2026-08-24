"""Consent & privacy state for listening/meeting features (pack6 #120-129).

LISTENING is not RECORDING. Each sensitive capability is gated by an explicit
flag that defaults to the privacy-preserving choice; a feature must call
``allowed()`` before doing anything sensitive. Consent can be revoked at any
time, and the whole session's consent can be cleared in one call.
"""

from __future__ import annotations

import threading
from typing import Any

# Consent flags (pack6 #121). Conservative defaults: live audio may be processed
# in a session the owner started, but nothing is retained, enrolled, recorded, or
# camera-captured without an explicit grant.
AUDIO_PROCESSING = "audio_processing"
TRANSCRIPT_RETENTION = "transcript_retention"
SPEAKER_ENROLLMENT = "speaker_enrollment"
RECORDING = "recording"
CAMERA = "camera"

_DEFAULTS = {
    AUDIO_PROCESSING: True,
    TRANSCRIPT_RETENTION: False,
    SPEAKER_ENROLLMENT: False,
    RECORDING: False,
    CAMERA: False,
}

# Privacy modes (pack6 #128) apply a consistent set of flags.
NO_TRANSCRIPT_STORAGE = "NO_TRANSCRIPT_STORAGE"
NO_LONG_TERM_MEMORY = "NO_LONG_TERM_MEMORY"
LOCAL_PROCESSING_ONLY = "LOCAL_PROCESSING_ONLY"


class ConsentStateManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._flags: dict[str, bool] = dict(_DEFAULTS)
        self._mode: str = "NORMAL"

    def allowed(self, flag: str) -> bool:
        with self._lock:
            return bool(self._flags.get(str(flag or "").strip(), False))

    def grant(self, flag: str) -> bool:
        return self._set(flag, True)

    def revoke(self, flag: str) -> bool:
        return self._set(flag, False)

    def _set(self, flag: str, value: bool) -> bool:
        key = str(flag or "").strip()
        if key not in _DEFAULTS:
            return False
        with self._lock:
            self._flags[key] = bool(value)
            return True

    def set_privacy_mode(self, mode: str) -> None:
        """Apply a coherent privacy posture (pack6 #128)."""
        m = str(mode or "").strip().upper()
        with self._lock:
            self._mode = m or "NORMAL"
            if m == NO_TRANSCRIPT_STORAGE:
                self._flags[TRANSCRIPT_RETENTION] = False
            elif m == LOCAL_PROCESSING_ONLY:
                # Nothing leaves the machine; retention/enrollment stay off too.
                self._flags[TRANSCRIPT_RETENTION] = False
                self._flags[RECORDING] = False

    def clear(self) -> None:
        """Forget this session's consent -- back to conservative defaults."""
        with self._lock:
            self._flags = dict(_DEFAULTS)
            self._mode = "NORMAL"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"mode": self._mode, "flags": dict(self._flags),
                    # A single honest line for a consent banner (pack6 #122, #129).
                    "listening": self._flags[AUDIO_PROCESSING],
                    "recording": self._flags[RECORDING]}
