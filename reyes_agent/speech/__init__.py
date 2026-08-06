"""Speech layer abstraction -- the seam between ZENO and whatever engine
actually does listening.

WHY THIS EXISTS
---------------
The browser owns one processed microphone stream. Its adaptive VAD gates
recording, and those bounded clips go to Deepgram through the server-side
STT seam. Wake-word matching remains string comparison in index.html.
Those choices are contained here so a native pipeline (Whisper/
faster-whisper, Silero VAD, openWakeWord, RNNoise) can replace them
without changing the rest of ZENO.

So the CONTRACTS live here, and the current browser behaviour is
registered as one implementation of them. Swapping engines becomes
"register a different provider", not "rewrite the listening code".

WHAT IS AND IS NOT IMPLEMENTED
------------------------------
Implemented and in use today:
  * WakeWordDetector -> `PhraseWakeWord`, the real matching rules the
    browser path already uses (longest-phrase-first, the "my Zeno"
    mention heuristic, standby phrases, self-echo rejection). These are
    genuine, tested rules lifted into one testable place rather than a
    stub.
  * BrowserEnergyVAD -- a real adaptive RMS detector with a rolling noise
    floor, hysteresis and hangover, running against that same processed
    browser stream. It is energy-based, not a neural speech classifier.
  * DeepgramRecognizer -- clips are transcribed in bounded voice workers;
    the VAD does not invoke an agent turn itself.

Nothing here fabricates capability. `capabilities()` reports exactly
which parts are real, and the GUI/diagnostics read from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class WakeResult:
    matched: bool
    phrase: str = ""
    start: int = -1
    end: int = -1
    remainder: str = ""          # command spoken in the same breath
    reason: str = ""             # why it did NOT match, when it didn't


class VoiceActivityDetector(Protocol):
    """Is this audio frame speech? Implement when a real VAD is wired in."""

    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class NullVAD:
    """No voice activity detection.

    This is not a placeholder pretending to work -- it is the honest
    statement that this build has no VAD, so every frame is treated as
    speech. Swapping in Silero/WebRTC VAD means registering a real
    implementation here; nothing else in ZENO changes.
    """

    name = "null"
    real = False

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:  # noqa: ARG002
        return True


class BrowserEnergyVAD:
    """Marker for the real browser VAD used by the persistent listener.

    Analysis is intentionally kept beside ``getUserMedia`` in JavaScript:
    moving raw microphone frames through the WebView bridge would add
    latency and risk blocking the desktop host. The browser exposes its
    measured noise floor and applied WebRTC settings to the UI diagnostics.
    """

    name = "browser-energy-adaptive"
    real = True
    runs_in = "browser"

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:  # noqa: ARG002
        raise NotImplementedError(
            "VAD runs on ZENO's processed browser MediaStream, not Python frames."
        )


class SpeechRecognizer(Protocol):
    def transcribe(self, audio: bytes, sample_rate: int) -> str: ...


class BrowserSpeechRecognizer:
    """Marker for the engine actually in use.

    Recognition runs in the browser (Web Speech API) inside
    static/index.html, not in Python. This class exists so the Python side
    can REPORT that truthfully rather than exposing a transcribe() that
    quietly returns nothing.
    """

    name = "browser-webspeech"
    real = True
    runs_in = "browser"

    def transcribe(self, audio: bytes, sample_rate: int) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Recognition runs in the browser (Web Speech API), not in Python. "
            "Use the /api/transcribe endpoint (Deepgram) for server-side audio."
        )


class DeepgramRecognizer:
    """Server-side recognition, already implemented in voice/stt.py and
    used by the audio-upload endpoint."""

    name = "deepgram"
    real = True
    runs_in = "server"

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str:  # noqa: ARG002
        from reyes_agent.voice.stt import transcribe as _t

        return _t(audio)


# --- wake word ---------------------------------------------------------
MENTION_PRECEDERS = ("my", "the", "our", "his", "her", "their", "a", "an")

STANDBY_PHRASES = (
    "zeno standby", "standby zeno", "standby", "go to sleep", "sleep now",
    "stop listening", "goodbye zeno", "goodbye",
)


@dataclass
class PhraseWakeWord:
    """The real wake-word rules, in one testable place.

    Mirrors what the browser path does today: longest phrase first (so
    "hey zeno" wins over "zeno"), and a mention heuristic so "my Zeno is
    fast" or "my assistant Zeno" does NOT wake it.
    """

    phrases: list[str] = field(default_factory=lambda: ["wake up zeno", "hey zeno", "zeno", "bro"])
    name = "phrase-match"
    real = True

    def __post_init__(self) -> None:
        self.phrases = sorted((p.lower() for p in self.phrases), key=len, reverse=True)

    def detect(self, text: str) -> WakeResult:
        low = (text or "").lower()
        for phrase in self.phrases:
            idx = low.find(phrase)
            while idx != -1:
                if not self._is_mention(low, idx):
                    remainder = (text[:idx] + text[idx + len(phrase):]).strip(" ,.?!")
                    return WakeResult(True, phrase, idx, idx + len(phrase), remainder)
                idx = low.find(phrase, idx + 1)
        return WakeResult(False, reason="no wake phrase found")

    @staticmethod
    def _is_mention(low: str, hit_start: int) -> bool:
        """True when the name is being TALKED ABOUT rather than addressed.

        Checks the two preceding words, because "my assistant Zeno" puts a
        noun between the determiner and the name -- a one-word lookback
        misses it (real bug, fixed 2026-07-31).
        """
        before = low[:hit_start].strip().split()
        return any(w.strip(",.") in MENTION_PRECEDERS for w in before[-2:])

    @staticmethod
    def is_standby(text: str) -> bool:
        t = "".join(c for c in (text or "").lower() if c.isalpha() or c == " ").strip()
        return any(t == p or t.endswith(" " + p) or t.startswith(p + " ") for p in STANDBY_PHRASES)

    @staticmethod
    def is_self_echo(heard: str, last_spoken: str) -> bool:
        """Did ZENO just hear its own voice through the speakers?"""
        if not last_spoken:
            return False
        said = "".join(c for c in last_spoken.lower() if c.isalnum() or c == " ")
        got = "".join(c for c in (heard or "").lower() if c.isalnum() or c == " ")
        if len(got) < 4:
            return False
        return said in got or got in said or got in said[:40] or said[:40] in got


# --- active registry ---------------------------------------------------
_vad: object = BrowserEnergyVAD()
_recognizer: object = DeepgramRecognizer()
_wake: PhraseWakeWord = PhraseWakeWord()


def register_vad(impl) -> None:
    global _vad
    _vad = impl


def register_recognizer(impl) -> None:
    global _recognizer
    _recognizer = impl


def register_wake_word(impl) -> None:
    global _wake
    _wake = impl


def vad():
    return _vad


def recognizer():
    return _recognizer


def wake_word() -> PhraseWakeWord:
    return _wake


def capabilities() -> dict:
    """Exactly what is real right now. No optimistic reporting."""
    try:
        from reyes_agent import speaker_identity

        speaker = speaker_identity.enrollment_status()
    except Exception as exc:  # noqa: BLE001 -- diagnostics must stay available
        speaker = {"enrolled": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "wake_word": {"engine": _wake.name, "implemented": getattr(_wake, "real", False),
                      "phrases": list(_wake.phrases)},
        "recognition": {"engine": _recognizer.name, "implemented": getattr(_recognizer, "real", False),
                        "runs_in": getattr(_recognizer, "runs_in", "unknown"),
                        "streaming": False,
                        "note": "VAD-bounded browser clips are transcribed in a bounded "
                                "voice worker before wake-word or command handling."},
        "vad": {"engine": _vad.name, "implemented": getattr(_vad, "real", False),
                "runs_in": getattr(_vad, "runs_in", "unknown"),
                "note": "Adaptive energy floor, hysteresis and hangover. It cannot "
                        "reliably distinguish a person from TV speech."},
        "echo_cancellation": {"implemented": True,
                              "note": "Requested on ZENO's browser MediaStream. The UI "
                                      "reports the browser's actual applied setting."},
        "noise_suppression": {"implemented": True,
                              "note": "Requested on ZENO's browser MediaStream. The UI "
                                      "reports the browser's actual applied setting."},
        "speaker_identity": {
            "implemented": True,
            "engine": "local acoustic speaker similarity",
            "profile": speaker,
            "note": "Separate from STT confidence. Raw recordings are discarded; voice evidence is never authentication.",
        },
        "upgrade_path": "register_vad() / register_recognizer() / register_wake_word()",
    }
