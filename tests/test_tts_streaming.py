"""Streaming TTS + prosody + speech preparation wired into voice/tts.py.

The backend is monkeypatched, so these verify the ORCHESTRATION (prep ->
sentence chunks -> per-clause dispatch with prosody, honoring stop_event) with
no audio hardware."""

from __future__ import annotations

import threading

import pytest

from reyes_agent.voice import tts
from reyes_agent.voice import speech_prep


# --- speech preparation -----------------------------------------------------
def test_prep_strips_markdown_and_code_and_urls():
    out = speech_prep.prepare_for_speech(
        "# Heading\n\n- one\n- two\n\nSee **bold** and `x = 1` at https://site.com/p")
    assert "#" not in out and "**" not in out and "`" not in out
    assert "bold" in out and "x = 1" in out
    assert "the link site.com" in out and "https" not in out


def test_prep_voices_common_symbols():
    assert "and" in speech_prep.prepare_for_speech("cats & dogs")
    assert "percent" in speech_prep.prepare_for_speech("up 50%")


def test_prep_never_returns_markdown_fences():
    out = speech_prep.prepare_for_speech("```python\nprint(1)\n```\nDone.")
    assert "```" not in out and "Done." in out


def test_prep_empty_is_empty():
    assert speech_prep.prepare_for_speech("   ") == ""


# --- capabilities -----------------------------------------------------------
def test_capabilities_per_backend():
    assert tts.capabilities("elevenlabs")["streaming"] is True
    assert tts.capabilities("sapi")["streaming"] is False
    assert tts.capabilities("sapi")["rate"] is True
    assert tts.capabilities("nonexistent")["streaming"] is False


# --- speak(): prep + sentence chunking + prosody passthrough ----------------
@pytest.fixture()
def spoken(monkeypatch):
    calls: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(tts, "_speak_one",
                        lambda text, stop, delivery=None: calls.append((text, delivery)))
    return calls


def test_speak_strips_markdown_and_chunks_into_sentences(spoken):
    tts.speak("## Report\n\nI found it. It's the newer one.",
              threading.Event(), delivery={"rate": 1.0, "style": "neutral"})
    joined = " ".join(t for t, _ in spoken)
    assert "#" not in joined and "found it" in joined and "newer one" in joined
    assert len(spoken) >= 2                       # spoken sentence-by-sentence
    assert all(d == {"rate": 1.0, "style": "neutral"} for _, d in spoken)


def test_speak_stops_on_a_set_event_before_speaking(spoken):
    ev = threading.Event(); ev.set()
    tts.speak("Anything here.", ev)
    assert spoken == []                            # already interrupted


def test_speak_halts_partway_on_barge_in(monkeypatch):
    ev = threading.Event()
    said: list[str] = []

    def fake(text, stop, delivery=None):
        said.append(text)
        ev.set()                                   # user barges in after clause 1
    monkeypatch.setattr(tts, "_speak_one", fake)
    tts.speak("First one. Second one. Third one.", ev)
    assert len(said) == 1                          # stopped after the first clause


# --- speak_stream(): clause-by-clause over a token stream -------------------
def test_speak_stream_speaks_clauses_as_they_complete(spoken):
    tokens = ["Open ", "Spotify. ", "Then ", "play ", "jazz."]
    tts.speak_stream(iter(tokens), threading.Event())
    said = [t for t, _ in spoken]
    assert said == ["Open Spotify.", "Then play jazz."]


def test_speak_stream_respects_barge_in(monkeypatch):
    ev = threading.Event()
    said: list[str] = []

    def fake(text, stop, delivery=None):
        said.append(text); ev.set()
    monkeypatch.setattr(tts, "_speak_one", fake)
    tts.speak_stream(iter(["First. ", "Second. ", "Third."]), ev)
    assert len(said) == 1
