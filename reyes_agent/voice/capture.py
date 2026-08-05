"""Push-to-talk mic capture. Hold PTT_KEY, speak, release -- get back a WAV clip.

Push-to-talk means we never have to guess when speech started or stopped:
recording is bounded exactly by the key being held. This also solves
"don't listen to itself" for free -- REYES never records while it's the one
talking, only while the key is physically down.
"""

from __future__ import annotations

import io
import wave

import keyboard
import numpy as np
import sounddevice as sd

from reyes_agent import config
from reyes_agent.voice.audio_utils import normalize_gain

SAMPLE_RATE = 16000  # plenty for speech, keeps the clip small for Deepgram


def record_ptt() -> bytes:
    """Block until PTT_KEY is pressed, record while held, return WAV bytes on release.

    Empty bytes back means the key was tapped with no audio captured (e.g.
    released instantly) -- callers should treat that as "nothing to do."
    """
    keyboard.wait(config.PTT_KEY)

    frames: list[np.ndarray] = []

    def _on_audio(indata, _frame_count, _time_info, _status) -> None:
        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=_on_audio
    ):
        while keyboard.is_pressed(config.PTT_KEY):
            sd.sleep(20)

    if not frames:
        return b""

    audio = normalize_gain(np.concatenate(frames, axis=0))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()
