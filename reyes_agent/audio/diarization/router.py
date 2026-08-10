"""Who spoke when -- and an honest line between two different questions.

TWO PROBLEMS THAT LOOK LIKE ONE
-------------------------------
    TURN SEGMENTATION   where does one stretch of speech end and the next
                        begin? Answerable from energy and silence. No model.
    SPEAKER ATTRIBUTION which of those turns came from the SAME person?
                        Needs learned speaker embeddings. Not answerable
                        without a model, at all.

Conflating them is the failure mode: a segmenter that labels turns
"Speaker 1 / Speaker 2" by alternating them looks exactly like diarization
and is wrong about half the time. So this module does segmentation properly
and REFUSES to invent speaker identities, saying which question it answered.

pyannote-audio is the right tool for the second question. It needs torch,
which is not installed here, so attribution reports UNAVAILABLE rather than
guessing.

AND IT IS NOT FOR NORMAL COMMANDS
---------------------------------
The brief is explicit: no heavyweight diarization for one-user commands.
`should_diarize()` is the gate -- a five-second "ZENO, open Chrome" has one
speaker and does not go near any of this.
"""

from __future__ import annotations

import importlib.util as finder
import os
import time
from dataclasses import dataclass, field
from typing import Any

ENABLED_FLAG = "ZENO_DIARIZATION_ENABLED"

# Below this, it is a command, not a meeting.
MIN_MEETING_S = 20.0

# Silence long enough to end a turn. Shorter gaps are pauses within a turn.
TURN_GAP_S = 0.65

# Energy below this fraction of the speech level counts as silence.
SILENCE_RATIO = 0.16

FRAME_S = 0.02


@dataclass
class Turn:
    start: float
    end: float
    speaker: str = ""            # "" means genuinely unknown, not "Speaker 1"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "end": round(self.end, 2),
                "duration": round(self.duration, 2), "speaker": self.speaker or None}


@dataclass
class Diarization:
    turns: list[Turn] = field(default_factory=list)
    speakers_identified: bool = False
    backend: str = "energy_segmentation"
    reason: str = ""
    duration_ms: float = 0.0

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def as_dict(self) -> dict[str, Any]:
        return {"turns": [t.as_dict() for t in self.turns],
                "turn_count": self.turn_count,
                "speakers_identified": self.speakers_identified,
                "backend": self.backend, "reason": self.reason,
                "duration_ms": round(self.duration_ms, 2)}

    def transcript_shape(self) -> str:
        if not self.turns:
            return "no speech found"
        if not self.speakers_identified:
            return (f"{self.turn_count} speaking turns found. I cannot tell you WHO "
                    "spoke each one -- that needs a speaker model this machine does "
                    "not have, and guessing would be worse than not saying.")
        return f"{self.turn_count} turns across identified speakers"


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def pyannote_available() -> bool:
    return (finder.find_spec("pyannote") is not None
            and finder.find_spec("torch") is not None)


def should_diarize(duration_s: float, *, multi_speaker_expected: bool = False) -> tuple[bool, str]:
    """The gate. Most audio ZENO hears is one person giving one instruction."""
    if duration_s < MIN_MEETING_S and not multi_speaker_expected:
        return False, (f"this is {duration_s:.0f}s of audio -- a command, not a meeting; "
                       "running diarization on it would be waste")
    if not enabled():
        return False, f"diarization is off; set {ENABLED_FLAG}=1 for meetings"
    return True, "long enough to be worth separating into turns"


def segment(samples: Any, sample_rate: int = 16000) -> Diarization:
    """Find speaking turns from energy. Never assigns a speaker identity."""
    started = time.perf_counter()
    result = Diarization()

    try:
        import numpy
    except Exception:  # noqa: BLE001
        result.reason = "numpy is unavailable"
        return result

    audio = numpy.asarray(samples, dtype=numpy.float32)
    if audio.ndim != 1 or len(audio) < sample_rate // 2:
        result.reason = "too little audio to segment"
        return result

    frame = max(1, int(FRAME_S * sample_rate))
    count = len(audio) // frame
    if count < 4:
        result.reason = "too few frames to segment"
        return result

    energy = numpy.sqrt(numpy.mean(
        numpy.square(audio[:count * frame].reshape(count, frame)), axis=1))
    speech_level = float(numpy.percentile(energy, 90))
    threshold = max(speech_level * SILENCE_RATIO, 1e-4)
    voiced = energy > threshold

    gap_frames = max(1, int(TURN_GAP_S / FRAME_S))
    turns: list[Turn] = []
    start = None
    silence = 0
    for index, is_voice in enumerate(voiced):
        if is_voice:
            if start is None:
                start = index
            silence = 0
        elif start is not None:
            silence += 1
            if silence >= gap_frames:
                turns.append(Turn((start * frame) / sample_rate,
                                  ((index - silence) * frame) / sample_rate))
                start, silence = None, 0
    if start is not None:
        turns.append(Turn((start * frame) / sample_rate, len(audio) / sample_rate))

    result.turns = [t for t in turns if t.duration >= 0.3]
    result.speakers_identified = False
    result.reason = ("turns found from silence boundaries; speaker identity needs a "
                     "model and was not guessed")
    result.duration_ms = (time.perf_counter() - started) * 1000
    return result


def diarize(samples: Any, sample_rate: int = 16000, *,
            multi_speaker_expected: bool = False) -> Diarization:
    """Segment, and attribute speakers only if a real speaker model exists."""
    try:
        duration = len(samples) / float(sample_rate or 16000)
    except Exception:  # noqa: BLE001
        duration = 0.0

    worth_it, why = should_diarize(duration, multi_speaker_expected=multi_speaker_expected)
    if not worth_it:
        result = Diarization(backend="skipped", reason=why)
        return result

    result = segment(samples, sample_rate)

    if pyannote_available():
        # The seam. Not reached on this machine, and deliberately not faked.
        result.backend = "pyannote (available)"
        result.reason += "; a speaker model is installed and can attribute these turns"
    else:
        result.backend = "energy_segmentation"
        result.reason += "; pyannote is not installed, so no speaker labels are assigned"
    return result


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE" if enabled() else "DISABLED",
        "enabled": enabled(),
        "flag": ENABLED_FLAG,
        "answers": "turn segmentation (where speech starts and stops)",
        "does_not_answer": "speaker attribution (which turns are the same person)",
        "backends": {
            "energy_segmentation": {"available": True, "needs": "numpy only"},
            "sherpa": {"available": finder.find_spec("sherpa_onnx") is not None,
                       "role": "existing local audio backend"},
            "pyannote": {"available": pyannote_available(),
                         "needs": "torch + pyannote.audio",
                         "adds": "real speaker embeddings, so turns can be attributed"},
        },
        "gate": f"skipped below {MIN_MEETING_S:.0f}s unless multiple speakers are expected",
        "honesty": ("Alternating labels between turns would look like diarization and "
                    "be wrong about half the time. Turns are reported without speaker "
                    "identities until a speaker model exists."),
    }
