"""Capturing enrolment clips from whichever microphone is already live.

WHY NOT ASK THE OWNER TO RECORD FILES
--------------------------------------
Enrolment needs five separate recordings. Asking for five WAV files means a
recorder app, five saved files, and moving them to the right folder -- and at
the end of it the profile is built from a DIFFERENT microphone than the one
ZENO actually listens through. A voice model trained on the phone's recorder
app and used against a lav mic over WebRTC is comparing two different things.

So this listens where ZENO listens: the same AudioManager stream, the same
selected source, the same processing. Whatever microphone is live is the one
the profile is built from, which is the only way the comparison is fair.

WHAT COUNTS AS A CLIP
---------------------
A run of speech bounded by silence -- said, then paused. That matches what a
person naturally does when asked to say something five times, and it means
the owner is never asked to operate a timer while also talking.
"""

from __future__ import annotations

import io
import threading
import time
import wave
from array import array
from typing import Any

# Enrolment wants 5-8. Six gives one spare in case a clip is rejected for
# being too short, without making the owner talk for a minute.
# Collect more than the five required, so a short or noisy one can be
# discarded without asking the owner to start over.
WANT_CLIPS = 8

# A clip must be a sentence, not a cough. The enrolment analyser needs 1.2s
# of VOICED audio after it trims silence, so the raw clip has to be longer
# than that -- at 1.0s a perfectly good short sentence was captured and then
# rejected downstream, which failed the whole enrolment on the last recording.
MIN_CLIP_S = 1.8
MAX_CLIP_S = 6.0

# Speech versus room. Deliberately above the VAD's own floor: an enrolment
# clip full of background noise poisons the profile for every later
# comparison, and a bad profile is worse than none.
SPEECH_RMS = 600.0
SILENCE_S = 0.7


def _rms(pcm: bytes) -> float:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return 0.0
    return (sum(float(v) * v for v in samples) / len(samples)) ** 0.5


def _wav(pcm: bytes, rate: int = 16_000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return out.getvalue()


class EnrolmentCapture:
    """Collects spoken clips from the live microphone."""

    def __init__(self, want: int = WANT_CLIPS) -> None:
        self.want = want
        self._lock = threading.RLock()
        self._clips: list[bytes] = []
        self._buffer = bytearray()
        self._quiet = 0.0
        self._rate = 16_000
        self._done = threading.Event()
        self._loudest = 0.0

    def __call__(self, frame: Any) -> None:
        """One audio frame from AudioManager."""
        pcm = getattr(frame, "pcm16", b"")
        if not pcm:
            return
        self._rate = int(getattr(frame, "sample_rate", 16_000) or 16_000)
        level = _rms(pcm)
        seconds = len(pcm) / 2 / self._rate

        with self._lock:
            self._loudest = max(self._loudest, level)
            if level >= SPEECH_RMS:
                self._buffer.extend(pcm)
                self._quiet = 0.0
                # A clip that runs long is closed rather than dropped: the
                # owner may simply be a slow speaker.
                if len(self._buffer) / 2 / self._rate >= MAX_CLIP_S:
                    self._close_clip()
                return

            if self._buffer:
                self._quiet += seconds
                self._buffer.extend(pcm)      # keep the tail of the word
                if self._quiet >= SILENCE_S:
                    self._close_clip()

    def _close_clip(self) -> None:
        seconds = len(self._buffer) / 2 / self._rate
        pcm, self._buffer, self._quiet = bytes(self._buffer), bytearray(), 0.0
        if seconds < MIN_CLIP_S:
            return                              # a cough, not a sentence
        self._clips.append(_wav(pcm, self._rate))
        if len(self._clips) >= self.want:
            self._done.set()

    @property
    def collected(self) -> int:
        with self._lock:
            return len(self._clips)

    def wait(self, timeout_s: float) -> bool:
        return self._done.wait(timeout=timeout_s)

    def clips(self) -> list[bytes]:
        with self._lock:
            return list(self._clips)

    def loudest(self) -> float:
        with self._lock:
            return self._loudest


def enrol_from_live_microphone(*, want: int = WANT_CLIPS,
                               timeout_s: float = 75.0) -> dict[str, Any]:
    """Listen, collect spoken clips, and build the profile.

    Returns what actually happened rather than raising -- the owner is
    standing at a microphone, and an exception traceback is not an
    instruction he can act on.
    """
    from reyes_agent import speaker_identity
    from reyes_agent.audio.manager import get_audio_manager

    manager = get_audio_manager()
    capture = EnrolmentCapture(want=want)
    manager.subscribe("speaker-enrolment", capture)
    try:
        capture.wait(timeout_s)
        clips = capture.clips()
    finally:
        try:
            manager.unsubscribe("speaker-enrolment")
        except Exception:  # noqa: BLE001
            try:
                manager._consumers.pop("speaker-enrolment", None)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass

    if len(clips) < 5:
        heard = capture.loudest()
        return {
            "enrolled": False,
            "clips": len(clips),
            "loudest_rms": round(heard, 1),
            "say": (f"I only caught {len(clips)} clear recording(s); I need "
                    "five. Say a full sentence, pause, then say another --"
                    + ("" if heard >= SPEECH_RMS else
                       " and speak a little louder or closer to the mic, "
                       f"because the loudest I heard was {heard:.0f}.")),
        }

    # Longest first: a marginal recording should never be the one that
    # fails an otherwise good enrolment.
    clips.sort(key=len, reverse=True)
    try:
        result = speaker_identity.enroll(clips[:6])
    except Exception as exc:  # noqa: BLE001
        return {"enrolled": False, "clips": len(clips),
                "say": f"I captured {len(clips)} recordings but could not "
                       f"build the profile: {exc}"}

    return {"enrolled": True, "clips": len(clips), "profile": result,
            "say": (f"Done -- I've learned your voice from {len(clips)} "
                    "recordings. I can tell you from other people now.")}


def status() -> dict[str, Any]:
    from reyes_agent import speaker_identity

    state = speaker_identity.enrollment_status()
    return {"state": "ONLINE", "enrolled": bool(state.get("enrolled")),
            "backend": (state.get("backend") or {}).get("backend", ""),
            "wants_clips": WANT_CLIPS, "speech_rms": SPEECH_RMS,
            "captures_from": ("the live AudioManager stream -- the same "
                              "microphone ZENO listens through, so the "
                              "profile matches what it is compared against")}
