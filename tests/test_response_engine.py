"""NaturalResponseEngine: it decides whether/how ZENO speaks and generates the
words from facts -- no fixed phrases. Model generation is injected, so these are
deterministic and never hit the network.
"""

from __future__ import annotations

import pytest

from reyes_agent.conversation import response_engine as nre
from reyes_agent.conversation.response_engine import (
    ASK, CRITICAL, NOTHING, QUIET, SHOW, SPEAK, WAIT, Event, NaturalResponseEngine,
)


def _eng(generate=None):
    return NaturalResponseEngine(generate=generate or (lambda ev, p, r: ""))


# --- #3 no fixed phrases ----------------------------------------------------
def test_message_is_naturalised_never_the_stock_phrase():
    eng = _eng(lambda ev, p, r: "Ayomide's asking if you're coming tomorrow.")
    d = eng.respond(Event(kind="message_received", app="WhatsApp",
                          sender="Ayomide", message="are you coming tomorrow?"))
    assert d.action in (SPEAK, ASK) and d.speech.strip()
    low = d.speech.lower()
    for banned in ("you have a new message", "what is your reply",
                   "what's your reply", "how may i assist"):
        assert banned not in low


def test_a_stock_phrase_from_the_generator_is_rejected():
    # Even if a backend slips, the engine refuses to speak a stock line.
    eng = _eng(lambda ev, p, r: "You have a new message. What's your reply, sir?")
    d = eng.respond(Event(kind="message_received", app="WhatsApp",
                          sender="X", message="hi"))
    assert "what's your reply" not in d.speech.lower()
    assert "you have a new message" not in d.speech.lower()


# --- #2 decide whether to speak ---------------------------------------------
def test_track_change_shows_a_panel_not_speech():
    d = _eng().respond(Event(kind="track_changed",
                             data={"title": "Last Last", "artist": "Burna Boy"}))
    assert d.action == SHOW and d.speech == ""
    assert d.visual.get("panel") == "now_playing"


def test_slider_moving_stays_silent():
    d = _eng().respond(Event(kind="volume_changed", data={"level": 40}))
    assert d.action in (QUIET, SHOW) and d.speech == ""


# --- #8 privacy -------------------------------------------------------------
def test_otp_is_never_read_aloud():
    d = _eng(lambda ev, p, r: "Your code is 381922.").respond(
        Event(kind="message_received", app="Bank", message="Your OTP is 381922"))
    assert "381922" not in d.speech


# --- #17 fast path: no model call for trivial events ------------------------
def test_simple_event_never_calls_the_model():
    called = []
    eng = _eng(lambda ev, p, r: called.append(1) or "MODEL")
    d = eng.respond(Event(kind="app_opened", app="Chrome"))
    assert not called, "app_opened must be phrased locally, not via the model"
    assert d.action == SPEAK and "Chrome" in d.speech


# --- #16 anti-repetition ----------------------------------------------------
def test_repeated_events_do_not_repeat_the_wording():
    eng = _eng()  # force local constructor
    seen = set()
    for i in range(4):
        d = eng.respond(Event(kind="app_opened", app="Chrome", message=str(i)))
        if d.speech:
            seen.add(d.speech)
    assert len(seen) > 1, "wording should vary across repeated events"


# --- #2/#15 batching --------------------------------------------------------
def test_a_burst_of_notifications_coalesces_into_one_line(monkeypatch):
    monkeypatch.setattr(nre, "_zeno_busy", lambda: True)  # in conversation -> queue
    eng = _eng()
    for i in range(5):
        d = eng.ingest(Event(kind="message_received", sender=f"P{i}", message=f"m{i}"))
        assert d.action == WAIT
    flushed = eng.flush()
    assert flushed is not None and flushed.action == SPEAK
    low = flushed.speech.lower()
    assert "few" in low or "notification" in low or "5" in low


# --- #15 priority + interruption --------------------------------------------
def test_critical_interrupts_even_mid_conversation(monkeypatch):
    monkeypatch.setattr(nre, "_zeno_busy", lambda: True)
    d = _eng(lambda ev, p, r: "Disk is almost full.").respond(
        Event(kind="system_critical", message="disk at 98%"))
    assert d.priority == CRITICAL and d.action == SPEAK


def test_normal_event_waits_while_zeno_is_busy(monkeypatch):
    monkeypatch.setattr(nre, "_zeno_busy", lambda: True)
    d = _eng(lambda ev, p, r: "x").respond(
        Event(kind="message_received", sender="X", message="hey"))
    assert d.action == WAIT


# --- duplicate suppression --------------------------------------------------
def test_identical_event_within_the_window_is_dropped():
    eng = _eng(lambda ev, p, r: "line")
    eng.respond(Event(kind="message_received", sender="X", message="same"))
    d2 = eng.respond(Event(kind="message_received", sender="X", message="same"))
    assert d2.action == NOTHING


# --- #11 tool-result naturalisation -----------------------------------------
def test_tool_data_is_naturalised_by_the_engine_not_the_tool():
    eng = _eng(lambda ev, p, r: f"It's {ev.data['temperature']} and raining.")
    d = eng.respond(Event(kind="weather",
                          data={"temperature": 24, "condition": "rain"}))
    assert "24" in d.speech and "sir" not in d.speech.lower()


# --- #18 fallback -----------------------------------------------------------
def test_local_fallback_when_the_model_returns_nothing():
    d = _eng(lambda ev, p, r: "").respond(
        Event(kind="message_received", app="WhatsApp", sender="Ayo", message="hi"))
    assert d.action in (SPEAK, ASK) and d.speech.strip()
    assert "Ayo" in d.speech or "message" in d.speech.lower()


# --- never raises -----------------------------------------------------------
def test_engine_never_raises_even_on_a_bad_generator():
    def boom(ev, p, r):
        raise RuntimeError("model exploded")
    d = _eng(boom).respond(Event(kind="email_received", sender="Z", message="hi"))
    # generator error -> local fallback, still a usable decision
    assert d.action in (SPEAK, ASK, QUIET, WAIT, NOTHING, SHOW)
