"""Humor as a modular capability: intent classification, battle state
machinery (round/score/max_rounds), joke-repetition prevention, and the
dark-humor content-safety boundary staying present regardless of intensity.
Never asserts on actual generated joke TEXT -- that comes from the model and
is exercised live, not here (see the session's verified live checks)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from reyes_agent import humor


@pytest.fixture(autouse=True)
def _reset_humor_state():
    humor.stop_battle()
    humor._last_joke_signatures.clear()  # noqa: SLF001 -- test-only direct reset
    yield
    humor.stop_battle()
    humor._last_joke_signatures.clear()  # noqa: SLF001


# --- intent classification --------------------------------------------------
def test_classifies_every_documented_trigger_phrase() -> None:
    cases = {
        "tell me a joke": "joke",
        "give me a dark joke": "dark_joke",
        "dark humor battle": "dark_battle",
        "roast me": "roast",
        "let's do a comeback battle": "comeback_battle",
        "that joke was terrible": "feedback_bad",
        "another one": "another",
        "give me a dad joke": "dad_joke",
        "tell me a programming joke": "programming_joke",
    }
    for phrase, expected in cases.items():
        assert humor.classify_intent(phrase) == expected, phrase


def test_unrelated_messages_never_match() -> None:
    for phrase in ("what is the weather", "open spotify", "what time is it", ""):
        assert humor.classify_intent(phrase) is None


def test_a_longer_sentence_never_hijacks_humor_mode() -> None:
    """Exact-phrase discipline, same as the local command router: a real
    request that happens to contain 'joke' must not force humor framing
    onto an unrelated serious turn."""
    assert humor.classify_intent("my code has a joke variable name in it, is that bad practice") is None


# --- battle state machinery --------------------------------------------------
def test_battle_starts_with_clean_state() -> None:
    state = humor.start_battle("dark_battle", intensity="mild", max_rounds=3)
    assert state.active is True
    assert state.mode == "dark_battle"
    assert state.round == 1
    assert state.score_user == 0 and state.score_zeno == 0
    assert state.max_rounds == 3


def test_max_rounds_is_bounded_even_if_asked_for_more() -> None:
    state = humor.start_battle("comeback_battle", max_rounds=999)
    assert state.max_rounds <= 20


def test_round_result_updates_score_and_advances_round() -> None:
    humor.start_battle("comeback_battle", max_rounds=5)
    state = humor.record_round_result("user")
    assert state.score_user == 1 and state.score_zeno == 0
    assert state.round == 2
    state = humor.record_round_result("zeno")
    assert state.score_zeno == 1 and state.round == 3
    state = humor.record_round_result("tie")
    assert state.score_user == 1 and state.score_zeno == 1 and state.round == 4


def test_an_invalid_who_won_value_counts_as_a_tie_not_a_crash() -> None:
    humor.start_battle("comeback_battle", max_rounds=5)
    state = humor.record_round_result("nonsense-value")
    assert state.score_user == 0 and state.score_zeno == 0  # a tie changes neither score
    assert state.round == 2


def test_battle_ends_automatically_at_max_rounds() -> None:
    humor.start_battle("comeback_battle", max_rounds=2)
    humor.record_round_result("user")
    state = humor.record_round_result("zeno")
    assert state.round > state.max_rounds
    assert state.active is False


def test_recording_a_result_with_no_active_battle_is_a_safe_noop() -> None:
    humor.stop_battle()
    state = humor.record_round_result("user")
    assert state.active is False
    assert state.score_user == 0


def test_stop_battle_resets_to_defaults() -> None:
    humor.start_battle("dark_battle")
    humor.stop_battle()
    state = humor.get_battle_state()
    assert state.active is False
    assert state.round == 0


# --- joke repetition prevention ---------------------------------------------
def test_a_noted_joke_is_detected_as_a_repeat() -> None:
    humor.note_joke_used("Why did the chicken cross the road?")
    assert humor.is_repeat("Why did the chicken cross the road?") is True


def test_near_identical_phrasing_still_counts_as_the_same_joke() -> None:
    humor.note_joke_used("Why did the chicken cross the road")
    assert humor.is_repeat("why did the chicken cross the road?") is True  # case/punctuation only


def test_a_genuinely_different_joke_is_not_flagged() -> None:
    humor.note_joke_used("Why did the chicken cross the road?")
    assert humor.is_repeat("A programmer's wife asks him to buy a loaf of bread") is False


def test_recent_jokes_list_stays_bounded() -> None:
    for i in range(50):
        humor.note_joke_used(f"a completely unique joke number {i} about something else entirely")
    assert len(humor._last_joke_signatures) <= humor._PREVIOUS_JOKES_MAX  # noqa: SLF001


def test_battle_state_tracks_its_own_previous_jokes_separately() -> None:
    state = humor.start_battle("dark_battle")
    state.note_used("a battle-specific joke")
    assert state.is_repeat("a battle-specific joke") is True


# --- prompt addendum: modular (empty on ordinary turns), safety boundary present ---
def test_no_addendum_on_an_ordinary_non_humor_turn() -> None:
    state = humor.get_battle_state()
    assert humor.build_context("", state) == ""


def test_addendum_present_for_an_explicit_joke_request() -> None:
    state = humor.get_battle_state()
    ctx = humor.build_context("joke", state)
    assert ctx and "HUMOR MODE" in ctx


def test_dark_content_boundary_is_present_for_dark_intents_regardless_of_intensity() -> None:
    for intensity in ("mild", "medium", "spicy"):
        state = humor.start_battle("dark_battle", intensity=intensity)
        ctx = humor.build_context("dark_battle", state)
        assert "hateful" in ctx and "self-harm" in ctx
        humor.stop_battle()

    state = humor.get_battle_state()
    ctx = humor.build_context("dark_joke", state)
    assert "hateful" in ctx and "self-harm" in ctx


def test_comeback_battle_addendum_has_no_dark_content_boundary_bleed() -> None:
    """A comeback battle is roast-style, not dark humor -- it should not
    carry the dark-content boundary text (which would be a strange non
    sequitur there), only its own playful-not-mean framing."""
    state = humor.start_battle("comeback_battle")
    ctx = humor.build_context("comeback_battle", state)
    assert "HUMOR MODE" in ctx
    assert "hateful" not in ctx


def test_active_battle_addendum_includes_live_round_and_score() -> None:
    state = humor.start_battle("comeback_battle", max_rounds=5)
    humor.record_round_result("user")
    state = humor.get_battle_state()
    ctx = humor.build_context("", state)
    assert "round 2 of 5" in ctx
    assert "1-0" in ctx or "0-1" in ctx  # zeno-user score, either order is fine to assert loosely


def test_addendum_asks_the_model_to_avoid_repeats_once_something_was_used() -> None:
    humor.note_joke_used("an already-told joke")
    state = humor.get_battle_state()
    ctx = humor.build_context("joke", state)
    assert "not repeat" in ctx.casefold() or "already used" in ctx.casefold()
