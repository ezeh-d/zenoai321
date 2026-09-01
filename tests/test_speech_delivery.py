"""Streaming sentence-TTS chunking and subtle prosody selection. Deterministic."""

from __future__ import annotations

import pytest

from reyes_agent.conversation.delivery import (
    CASUAL, FOCUSED, NEUTRAL, SERIOUS, URGENT, SentenceStreamer, delivery_for,
)


# --- streaming sentence chunking --------------------------------------------
def test_first_sentence_emits_before_the_rest_arrives():
    s = SentenceStreamer()
    out = s.feed("I found the document.")
    assert out == ["I found the document."]
    # the next sentence is still being generated
    assert s.feed(" It's the version Catherine sent") == []
    assert s.feed(" yesterday.") == ["It's the version Catherine sent yesterday."]


def test_token_by_token_stream():
    s = SentenceStreamer()
    emitted = []
    for tok in ["Open", " Spotify.", " Then", " play", " jazz."]:
        emitted += s.feed(tok)
    assert emitted == ["Open Spotify.", "Then play jazz."]


def test_tiny_fragment_is_not_spoken_alone():
    s = SentenceStreamer()
    # "OK." is below the min clause length -> held, merged with what follows
    assert s.feed("OK. ") == []
    out = s.feed("Opening it now.")
    assert out and "Opening it now." in out[-1]


def test_flush_returns_the_tail():
    s = SentenceStreamer()
    s.feed("First sentence here.")            # emitted
    assert s.feed(" a trailing thought") == []
    assert s.flush() == "a trailing thought"


def test_runaway_buffer_starts_speech_without_punctuation():
    s = SentenceStreamer(max_buffer=40)
    out = s.feed("this is a very long clause with no punctuation at all yet still going")
    assert out                                # emitted at a word boundary, not stuck


# --- prosody ----------------------------------------------------------------
def test_urgent_is_clear_and_a_touch_quicker():
    d = delivery_for(priority="CRITICAL", text="disk almost full")
    assert d["style"] == URGENT and 1.0 <= d["rate"] <= 1.1


def test_complex_answer_is_slightly_slower():
    d = delivery_for(complex_answer=True)
    assert d["style"] == FOCUSED and d["rate"] < 1.0


def test_casual_and_neutral_stay_natural():
    assert delivery_for(casual=True)["style"] == CASUAL
    n = delivery_for()
    assert n["style"] == NEUTRAL and n["rate"] == 1.0


def test_urgent_words_in_text_trigger_urgent_style():
    assert delivery_for(text="I need this right away")["style"] == URGENT


def test_rates_are_never_extreme():
    for kwargs in ({}, {"complex_answer": True}, {"serious": True},
                   {"priority": "CRITICAL"}, {"casual": True}):
        assert 0.9 <= delivery_for(**kwargs)["rate"] <= 1.1
