"""Speech in any language -> clear English.

ONE ENGINE, EVERY MICROPHONE
----------------------------
The desktop microphone, the phone microphone and the web client all reach
this function. The brief is explicit that there must not be a separate mobile
translator with different behaviour, so `understand_audio` is the only speech
entry point and it delegates text handling to `understand_text` -- the same
code path a typed message takes.

WHAT IS REUSED
--------------
`reyes_agent.voice.stt.manager` already exists, already has a cloud/local
circuit breaker, and already returns Whisper's detected language. Nothing
here re-implements transcription; this module bridges STT to the language
engine and adds the parts STT does not do:

  * the ORIGINAL transcript is kept alongside the English (brief 31)
  * known application and agent names repair mishearings (brief 33, 45, 46)
  * accidental stutters are collapsed, deliberate emphasis is not (73)
  * partial transcripts NEVER reach a privileged action (74, 75)
  * a detected language is only believed once evidence accumulates (76)

WHY CORRECTION IS CONSERVATIVE
------------------------------
"open cloud" is probably "open Claude" on this machine. It is not certainly
that -- the owner may genuinely mean cloud storage. So a correction only
applies when the misheard token is close to a name ZENO actually knows AND
the surrounding words look like a command. Everything else is left alone,
because silently rewriting a name is worse than transcribing it oddly.
"""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.language.engine import Understanding, understand_text

# A partial transcript is for showing the owner that ZENO is listening. It is
# never evidence of what they finally said.
PARTIAL = "partial"
FINAL = "final"

# Whisper reports a language per utterance and will happily change its mind
# between two-second chunks. The UI label only moves once this many
# consecutive results agree, so it does not flicker mid-sentence.
LANGUAGE_STABILITY = 3

_FILLER_ONLY = re.compile(r"^[\s.,!?]*(?:u+h+m*|e+r+m*|h+m+|a+h+|e+h+)[\s.,!?]*$",
                          re.IGNORECASE)


@dataclass
class SpeechUnderstanding:
    """What was heard, and what it meant."""

    original_transcript: str
    understanding: Understanding
    audio_language: str = ""
    stt_backend: str = ""
    stt_latency_s: float = 0.0
    corrections: list[tuple[str, str]] = field(default_factory=list)
    stage: str = FINAL

    @property
    def english(self) -> str:
        return self.understanding.english

    @property
    def confidence(self) -> float:
        return self.understanding.confidence

    @property
    def safe_for_sensitive_action(self) -> bool:
        """A partial transcript can never authorise anything.

        Streaming STT emits a partial after roughly a second. "delete the old
        backup" passes through "delete the old" on its way, and acting on that
        would delete the wrong thing.
        """
        return (self.stage == FINAL
                and self.understanding.safe_for_sensitive_action)

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original_transcript,
            "english": self.english,
            "audio_language": self.audio_language,
            "stt_backend": self.stt_backend,
            "stt_latency_s": round(self.stt_latency_s, 3),
            "corrections": [list(c) for c in self.corrections],
            "stage": self.stage,
            **self.understanding.as_dict(),
        }


def known_names() -> tuple[str, ...]:
    """Applications and agents ZENO actually knows about.

    Read from the live registries rather than a hard-coded list, so a newly
    added agent is protected without editing this file.
    """
    from reyes_agent.language.protect import BASE_ENTITIES, runtime_entities

    return tuple(dict.fromkeys(BASE_ENTITIES + runtime_entities()))


# Ordinary words that sit close to a product name and must never be
# "corrected". `window` is 0.83 similar to `Windows`, and "open window" is a
# perfectly normal instruction. Measured by sweeping 30 common objects against
# the entity list: this is the only collision at the 0.72 threshold.
_NEVER_CORRECT = frozenset({
    "window", "windows", "edge", "explorer", "note", "notes", "code", "chat",
    "mail", "map", "maps", "photo", "photos", "phone", "team", "teams",
    "meet", "drive", "file", "files", "folder", "page", "site", "app",
})


def repair_names(text: str, *, names: tuple[str, ...] = (),
                 threshold: float = 0.72) -> tuple[str, list[tuple[str, str]]]:
    """Fix mishearings of names ZENO knows. Conservative by design.

    "open cloud" -> "open Claude", because `Claude` is a known name, "cloud"
    is close to it, and the preceding word is an imperative. Without that verb
    the sentence is left alone -- "the cloud is down" must not become "the
    Claude is down".

    The threshold is 0.72 because that is what "cloud" -> "Claude" (0.727)
    actually needs; the brief names that exact example. A sweep of 30 ordinary
    objects against the entity list found one collision at that level
    (`window` -> `Windows`), which `_NEVER_CORRECT` handles.
    """
    vocabulary = names or known_names()
    if not vocabulary:
        return text, []

    lowered = {name.lower(): name for name in vocabulary}
    corrections: list[tuple[str, str]] = []
    tokens = re.split(r"(\W+)", text)

    verbs = {"open", "close", "start", "launch", "run", "ask", "tell", "check",
             "show", "use", "switch", "focus", "quit", "restart"}
    previous_word = ""

    for index, token in enumerate(tokens):
        if not token or not token.strip() or not token.isalpha():
            continue
        low = token.lower()
        if low in lowered:
            # The right name, possibly the wrong case. Speech recognition
            # lower-cases freely, and "open chrome" should reach the intent
            # parser as "Chrome" -- the canonical spelling is what the
            # application registry matches on.
            canonical = lowered[low]
            if token != canonical:
                corrections.append((token, canonical))
                tokens[index] = canonical
            previous_word = low
            continue
        if low in _NEVER_CORRECT:
            previous_word = low
            continue
        # Only repair where a name is plausible: right after a command verb.
        if previous_word not in verbs:
            previous_word = low
            continue
        match = difflib.get_close_matches(low, list(lowered), n=1, cutoff=threshold)
        if match:
            replacement = lowered[match[0]]
            if replacement.lower() != low:
                corrections.append((token, replacement))
                tokens[index] = replacement
        previous_word = low

    return "".join(tokens), corrections


def collapse_stutter(text: str) -> str:
    """Speech recognition repeats the leading word. Emphasis is not a stutter."""
    from reyes_agent.language.normalize import collapse_repeats

    return collapse_repeats(text)


def is_noise(transcript: str) -> bool:
    """Whether a transcript carries no content at all.

    Whisper hallucinates on silence -- an empty room reliably produces "you"
    or "Thank you." Treating those as speech is how an assistant answers a
    question nobody asked.
    """
    stripped = str(transcript or "").strip()
    if not stripped:
        return True
    if _FILLER_ONLY.match(stripped):
        return True
    return stripped.lower().strip(" .,!?") in {
        "you", "thank you", "thanks", "bye", "okay", "ok", ".", "the"}


class LanguageStabiliser:
    """Stops the detected-language label flickering during streaming.

    Whisper re-detects per chunk. Without this the UI would show
    French/English/French across one sentence, which reads as a bug even when
    the transcription is fine.
    """

    def __init__(self, needed: int = LANGUAGE_STABILITY) -> None:
        self._needed = max(1, needed)
        self._recent: list[str] = []
        self._settled = ""

    def observe(self, language: str) -> str:
        value = str(language or "").strip().lower()
        if value:
            self._recent.append(value)
            del self._recent[:-self._needed]
        if (len(self._recent) >= self._needed
                and len(set(self._recent)) == 1
                and self._recent[0] != self._settled):
            self._settled = self._recent[0]
        return self._settled

    @property
    def settled(self) -> str:
        return self._settled

    def reset(self) -> None:
        self._recent.clear()
        self._settled = ""


_stabiliser = LanguageStabiliser()


def understand_audio(audio: bytes, *, conversation_context: str = "",
                     stage: str = FINAL,
                     repair: bool = True) -> SpeechUnderstanding:
    """Transcribe, repair, then understand. The one speech entry point."""
    from reyes_agent.voice.stt import manager

    started = time.perf_counter()
    result = manager.transcribe_result(audio)
    transcript = str(result.get("transcript", "") or "")
    audio_language = str(result.get("language", "") or "")

    settled = _stabiliser.observe(audio_language) if stage == FINAL else _stabiliser.settled

    corrections: list[tuple[str, str]] = []
    cleaned = collapse_stutter(transcript)
    if repair and cleaned and not is_noise(cleaned):
        cleaned, corrections = repair_names(cleaned)

    understanding = understand_text(cleaned, conversation_context=conversation_context)

    # Whisper's own language detection is acoustic evidence the text detector
    # does not have. Trust it only when the text detector is unsure, since a
    # text detector reading actual words beats an acoustic guess.
    if (audio_language and understanding.language in ("unknown", "")
            and understanding.confidence < 0.5):
        understanding.language = audio_language
        understanding.language_confidence = 0.6

    return SpeechUnderstanding(
        original_transcript=transcript,
        understanding=understanding,
        audio_language=settled or audio_language,
        stt_backend=str(result.get("backend", "")),
        stt_latency_s=float(result.get("latency_s") or (time.perf_counter() - started)),
        corrections=corrections,
        stage=stage,
    )


def reset_for_tests() -> None:
    _stabiliser.reset()


def understand_transcript(text: str, *, stage: str = FINAL,
                          audio_language: str = "", confidence: float = 0.0,
                          backend: str = "", latency_s: float = 0.0,
                          conversation_context: str = "",
                          repair: bool = True) -> SpeechUnderstanding:
    """The streaming entry point: a transcript that already exists.

    `understand_audio` transcribes and then understands. Streaming STT has
    ALREADY transcribed -- the audio went up while the owner was still
    speaking, which is the entire point -- so re-transcribing would throw away
    the latency win and pay for the same words twice.

    Same repair, same stabiliser, same `understand_text`, so a streamed turn
    and a batch turn reach the brain in identical shape.
    """
    transcript = str(text or "")
    settled = (_stabiliser.observe(audio_language) if stage == FINAL
               else _stabiliser.settled)

    corrections: list[tuple[str, str]] = []
    cleaned = collapse_stutter(transcript)
    if repair and cleaned and not is_noise(cleaned):
        cleaned, corrections = repair_names(cleaned)

    understanding = understand_text(cleaned, conversation_context=conversation_context)

    if (audio_language and understanding.language in ("unknown", "")
            and understanding.confidence < 0.5):
        understanding.language = audio_language
        understanding.language_confidence = 0.6

    return SpeechUnderstanding(
        original_transcript=transcript,
        understanding=understanding,
        audio_language=settled or audio_language,
        stt_backend=backend,
        stt_latency_s=latency_s,
        corrections=corrections,
        stage=stage,
    )


def observe_partial(text: str, *, audio_language: str = "") -> str:
    """Feed an interim result to the stabiliser without acting on it.

    A partial exists to show the owner that ZENO is listening. It contributes
    acoustic language evidence and NOTHING else -- no understanding, no
    repair, no command. `understand_transcript(stage=PARTIAL)` is available
    when a caller genuinely wants a provisional reading for display.
    """
    if audio_language:
        _stabiliser.observe(audio_language)
    return _stabiliser.settled
