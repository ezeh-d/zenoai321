"""Fast local device-command router: exact-phrase matches execute directly
and speak the tool's real outcome; anything else -- including a longer
sentence that merely contains one of these words -- falls through to the
real agent untouched."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.voice import local_command_router as router  # noqa: E402


def test_media_phrases_call_media_control_with_the_right_action() -> None:
    cases = {
        "mute": "mute", "pause music": "play_pause", "resume": "play_pause",
        "next song": "next", "skip": "next", "previous track": "previous",
        "volume up": "volume_up", "turn it down": "volume_down",
    }
    for phrase, expected_action in cases.items():
        with patch("reyes_agent.tools.system.media_control", return_value="ok") as mc:
            result = router.route(phrase)
            assert result is not None, f"{phrase!r} should have matched"
            mc.assert_called_once_with(expected_action)
            assert result.tool == "media_control"
            assert result.text  # a real spoken confirmation, never blank


def test_volume_number_calls_set_volume_clamped() -> None:
    with patch("reyes_agent.tools.utility.set_volume", return_value="ok") as sv:
        result = router.route("set volume to 150")  # out of range input
        assert result is not None
        sv.assert_called_once_with(100)  # clamped, never passed through raw
        assert "100" in result.text

    with patch("reyes_agent.tools.utility.set_volume", return_value="ok") as sv:
        result = router.route("volume 30")
        assert result is not None
        sv.assert_called_once_with(30)


def test_open_app_speaks_the_tools_real_return_value() -> None:
    with patch("reyes_agent.tools.system.open_app",
               return_value="Couldn't find an app matching 'zzznotarealapp'.") as oa:
        result = router.route("open zzznotarealapp")
        assert result is not None
        oa.assert_called_once_with("zzznotarealapp")
        # The router must speak the TOOL's real outcome, not invent "Opening X".
        assert result.text == "Couldn't find an app matching 'zzznotarealapp'."


def test_open_app_excludes_ambiguous_generic_words() -> None:
    for phrase in ("open my documents", "open the door", "open a"):
        with patch("reyes_agent.tools.system.open_app") as oa:
            assert router.route(phrase) is None
            oa.assert_not_called()


def test_a_longer_sentence_never_hijacks_the_fast_path() -> None:
    """The whole message must match, not a substring -- a real request that
    happens to contain one of these words still needs the real agent."""
    sentences = [
        "can you open my email and check for anything from my boss",
        "please mute the notifications for this app only, not the whole system",
        "what does it mean to open your mind to new ideas",
        "remind me to pause the subscription next month",
    ]
    for sentence in sentences:
        with patch("reyes_agent.tools.system.media_control") as mc, \
             patch("reyes_agent.tools.system.open_app") as oa, \
             patch("reyes_agent.tools.utility.set_volume") as sv:
            assert router.route(sentence) is None, f"{sentence!r} should NOT match"
            mc.assert_not_called()
            oa.assert_not_called()
            sv.assert_not_called()


def test_a_tool_exception_falls_through_instead_of_claiming_success() -> None:
    """A fast path that silently 'succeeds' while the tool actually raised
    would be worse than no fast path at all."""
    with patch("reyes_agent.tools.system.media_control", side_effect=RuntimeError("boom")):
        assert router.route("mute") is None


def test_disabled_by_config_flag() -> None:
    from reyes_agent import config

    original = config.FAST_LOCAL_COMMANDS_ENABLED
    try:
        config.FAST_LOCAL_COMMANDS_ENABLED = False
        with patch("reyes_agent.tools.system.media_control") as mc:
            assert router.route("mute") is None
            mc.assert_not_called()
    finally:
        config.FAST_LOCAL_COMMANDS_ENABLED = original


def test_empty_and_unrelated_messages_return_none() -> None:
    for phrase in ("", "   ", "what time is it", "tell me a joke", "hello zeno"):
        assert router.route(phrase) is None
