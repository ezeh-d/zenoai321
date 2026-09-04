"""physical_state.py: the motion-engine -> personality bridge. Cooldown,
"important work overrides play" (interruption), invalid-event handling, and
that this module never touches TTS/audio itself -- only text generation,
reusing provider.run_turn (mocked here; the real model call is exercised
live, not in this file, matching test_groq_provider.py's own split between
mocked contract tests and separately-verified live behavior)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from reyes_agent import physical_state


@pytest.fixture(autouse=True)
def _reset_cooldown():
    physical_state._last_reaction_at = 0.0  # noqa: SLF001 -- test-only direct reset
    yield
    physical_state._last_reaction_at = 0.0  # noqa: SLF001


def _fake_turn(text: str):
    class _Turn:
        def __init__(self, t):
            self.text = t
    return _Turn(text)


# --- valid path --------------------------------------------------------------
def test_a_valid_event_reacts_and_returns_generated_text() -> None:
    with patch.object(physical_state, "_generate_line", return_value="Whoa, easy there."):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            result = physical_state.maybe_react("shake", dizziness=0.4, shake_intensity=0.8)
    assert result["reacted"] is True
    assert result["text"] == "Whoa, easy there."
    assert result["event"] == "shake"


def test_an_unknown_event_never_reacts() -> None:
    result = physical_state.maybe_react("somersault")
    assert result["reacted"] is False
    assert result["reason"] == "unknown_event"


# --- cooldown (never spam a reaction) ----------------------------------------
def test_cooldown_blocks_an_immediate_second_reaction() -> None:
    with patch.object(physical_state, "_generate_line", return_value="line one"):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            first = physical_state.maybe_react("shake")
            second = physical_state.maybe_react("dizzy")
    assert first["reacted"] is True
    assert second["reacted"] is False
    assert second["reason"] == "cooldown"


def test_cooldown_remaining_reports_a_real_bounded_value() -> None:
    with patch.object(physical_state, "_generate_line", return_value="line"):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            physical_state.maybe_react("shake")
    remaining = physical_state.cooldown_remaining_s()
    assert 0 < remaining <= physical_state._COOLDOWN_S  # noqa: SLF001


def test_after_cooldown_elapses_a_new_reaction_is_allowed() -> None:
    with patch.object(physical_state, "_generate_line", return_value="line"):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            first = physical_state.maybe_react("shake", now=1000.0)
            still_cooling = physical_state.maybe_react("dizzy", now=1005.0)
            after = physical_state.maybe_react("dizzy", now=1000.0 + physical_state._COOLDOWN_S + 1)  # noqa: SLF001
    assert first["reacted"] is True
    assert still_cooling["reacted"] is False
    assert after["reacted"] is True


# --- important work overrides play (interruption) ----------------------------
def test_important_work_active_suppresses_a_reaction() -> None:
    with patch.object(physical_state, "_important_work_active", return_value=True):
        result = physical_state.maybe_react("shake", dizziness=0.9, shake_intensity=0.9)
    assert result["reacted"] is False
    assert result["reason"] == "important_work_active"


def test_important_work_check_reuses_the_real_runtime_control_registry() -> None:
    """Not a second notion of 'busy' -- the same operation registry
    control.supersede()/the local command router already consult."""
    with patch("reyes_agent.intelligence.get_runtime_control") as mock_get:
        mock_get.return_value.active.return_value = [{"kind": "brain"}]
        assert physical_state._important_work_active() is True
        mock_get.return_value.active.return_value = [{"kind": "workflow"}]
        assert physical_state._important_work_active() is False
        mock_get.return_value.active.return_value = []
        assert physical_state._important_work_active() is False


def test_a_broken_health_check_fails_toward_silence_not_interruption() -> None:
    """If the busy-check itself errors, the safe default is to NOT react --
    a missed quip is nothing; forcing one through a broken check risks
    talking over the owner."""
    with patch("reyes_agent.intelligence.get_runtime_control", side_effect=RuntimeError("boom")):
        assert physical_state._important_work_active() is True


# --- generation failure never surfaces as an error ----------------------------
def test_a_generation_failure_is_reported_not_raised() -> None:
    with patch.object(physical_state, "_generate_line", side_effect=RuntimeError("provider down")):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            result = physical_state.maybe_react("shake")
    assert result["reacted"] is False
    assert result["reason"] == "generation_failed"


def test_an_empty_generation_does_not_count_as_a_reaction() -> None:
    with patch.object(physical_state, "_generate_line", return_value=""):
        with patch.object(physical_state, "_important_work_active", return_value=False):
            result = physical_state.maybe_react("shake")
    assert result["reacted"] is False
    assert result["reason"] == "empty_generation"


# --- this module never touches audio itself -----------------------------------
def test_generate_line_calls_run_turn_and_never_synthesizes_audio_itself() -> None:
    """The one real integration point is provider.run_turn -- reused, not
    duplicated. TTS synthesis is explicitly the CALLER's job (the /api/tts
    endpoint web.py already has); patching every audio-synthesis entry point
    this codebase has and asserting none of them fire is the real proof,
    stronger than a text search that a docstring's own prose could trip."""
    with patch("reyes_agent.provider.run_turn", return_value=_fake_turn("a real generated line")) as mock_run, \
         patch("reyes_agent.voice_manager.synthesize") as mock_synth, \
         patch("reyes_agent.voice.tts.synthesize_bytes") as mock_synth_bytes:
        text = physical_state._generate_line("shake", dizziness=0.5, shake_intensity=0.5)
    assert text == "a real generated line"
    mock_run.assert_called_once()
    mock_synth.assert_not_called()
    mock_synth_bytes.assert_not_called()
    _, kwargs = mock_run.call_args
    assert kwargs.get("tools") == []  # no tool loop for a one-shot aside
