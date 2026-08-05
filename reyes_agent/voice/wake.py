"""Open-mic wake-word listening: REYES as an always-on second brain
instead of a push-a-key (or type-a-message) assistant.

Listens continuously, wakes on a phrase ("Reyes", "Bro", "Yo", "Hello
bro" -- configurable) or two sharp claps close together, then runs
whatever you say next through the exact same agent core as every other
front door. This is genuinely always-listening, so it's a deliberate,
separate opt-in (`python -m reyes_agent.wake_cli`) from push-to-talk
(`voice_cli.py`) -- the two shouldn't run at once, they'd fight over the
mic.

Doesn't listen to itself: the loop is strictly sequential (listen, then
process, then speak, then listen again) -- it is never capturing audio
while REYES is talking, so there's no feedback path to guard against
separately.
"""

from __future__ import annotations

import io
import re
import wave

import numpy as np
import speech_recognition as sr

from reyes_agent import config
from reyes_agent.voice.audio_utils import normalize_gain
from reyes_agent.voice.stt import STTError, transcribe

# Word-boundary matching -- "yo" and "bro" are short enough that a naive
# substring check would false-positive on "yoga", "embrocation", etc.
# Longest phrase first: "hello bro" must be tried before "bro" alone, or
# "bro" matches inside it first and the rest of the match logic never
# sees the full phrase.
_WAKE_PATTERNS = [
    re.compile(r"\b" + re.escape(phrase.lower()) + r"\b")
    for phrase in sorted(config.WAKE_PHRASES, key=len, reverse=True)
]

# Clap heuristic: two sharp energy peaks, close together, in an otherwise
# short/quiet clip. Approximate on purpose -- claps vary a lot by mic and
# room. Tune via WAKE_CLAP_THRESHOLD in .env if it's over/under-firing.
_CLAP_MIN_GAP_S = 0.12
_CLAP_MAX_GAP_S = 1.0
_CLAP_MAX_CLIP_S = 1.8


def _find_wake_match(transcript: str) -> re.Match | None:
    for pattern in _WAKE_PATTERNS:
        match = pattern.search(transcript.lower())
        if match:
            return match
    return None


def _looks_like_claps(audio: sr.AudioData) -> bool:
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    duration_s = len(samples) / 16000
    if duration_s > _CLAP_MAX_CLIP_S or len(samples) < 400:
        return False

    window = 400  # 25ms at 16kHz
    envelope = np.array(
        [np.abs(samples[i : i + window]).mean() for i in range(0, len(samples) - window, window)]
    )
    if envelope.max() < config.WAKE_CLAP_THRESHOLD:
        return False

    threshold = envelope.max() * 0.5
    peak_times = []
    above = False
    for i, v in enumerate(envelope):
        if v >= threshold and not above:
            peak_times.append(i * window / 16000)
            above = True
        elif v < threshold * 0.4:
            above = False

    if len(peak_times) != 2:
        return False
    gap = peak_times[1] - peak_times[0]
    return _CLAP_MIN_GAP_S <= gap <= _CLAP_MAX_GAP_S


def _boosted_wav(audio: sr.AudioData) -> bytes:
    """Re-encode the captured clip with quiet (whispered) audio boosted
    toward a usable level before it reaches Deepgram -- see audio_utils.py."""
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    samples = normalize_gain(np.frombuffer(raw, dtype=np.int16))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def listen_for_wake(recognizer: sr.Recognizer, source: sr.AudioSource) -> str | None:
    """Block until a wake trigger fires, then return the command text to
    run (possibly empty, meaning "just acknowledge and listen again").
    Returns None on a captured phrase that wasn't a wake trigger at all.
    """
    try:
        audio = recognizer.listen(source, phrase_time_limit=8)
    except sr.WaitTimeoutError:
        return None

    if _looks_like_claps(audio):
        return ""

    try:
        transcript = transcribe(_boosted_wav(audio))
    except STTError:
        return None

    match = _find_wake_match(transcript)
    if not match:
        return None
    return transcript[match.end() :].strip(" ,.-!?")
