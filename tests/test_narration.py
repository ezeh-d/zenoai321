"""Saying what you're doing -- without becoming "Processing..."."""

from __future__ import annotations

import time

import pytest

from reyes_agent.voice import narration


@pytest.fixture(autouse=True)
def _fresh():
    narration.begin_turn("test")
    yield


class TestItSaysWhatIsActuallyHappening:
    @pytest.mark.parametrize("tool,kind", [
        ("web_search", "web"),
        ("open_app", "app"),
        ("send_message", "message"),
        ("list_calendar_events", "calendar"),
        ("read_email", "mail"),
        ("agent_roster", "agent"),
        ("take_screenshot", "vision"),
        ("build_project", "build"),
        ("search_notes", "memory"),
        ("system_health", "system"),
    ])
    def test_the_phrase_matches_the_work(self, tool, kind):
        assert narration.kind_of(tool) == kind
        assert narration.line_for(tool) in narration._PHRASES[kind]

    def test_an_unknown_tool_still_gets_something_natural(self):
        """A tool added next week must not produce silence or a crash."""
        assert narration.kind_of("frobnicate_widgets") == "generic"
        assert narration.line_for("frobnicate_widgets")

    def test_it_never_says_processing(self):
        """The banned words say nothing, and grate after the second time."""
        every = [line.lower() for lines in narration._PHRASES.values()
                 for line in lines]
        for banned in ("processing", "analyzing", "analysing", "please wait",
                       "as an ai", "i am programmed"):
            assert not any(banned in line for line in every), banned

    def test_lines_stay_under_a_breath(self):
        """This is filler while the real answer comes. Long filler delays it."""
        for lines in narration._PHRASES.values():
            for line in lines:
                assert len(line.split()) <= 6, line

    def test_wording_varies(self):
        """Hearing it twice in a minute must not sound like a recording."""
        seen = {narration.line_for("web_search") for _ in range(40)}
        assert len(seen) > 1


class TestItKnowsWhenToStayQuiet:
    def test_a_fast_answer_is_not_announced(self):
        """An answer that beats the filler is not improved by the filler."""
        assert narration.should_narrate("web_search")[0] is False

    def test_slow_work_is_announced(self, monkeypatch):
        real = time.monotonic()
        monkeypatch.setattr(narration.time, "monotonic",
                            lambda: real + narration.NARRATE_AFTER_S + 0.3)
        due, line = narration.should_narrate("web_search")
        assert due and line

    def test_only_once_per_turn(self, monkeypatch):
        """Six tools in a turn must not produce six announcements."""
        real = time.monotonic()
        monkeypatch.setattr(narration.time, "monotonic",
                            lambda: real + narration.NARRATE_AFTER_S + 0.3)
        assert narration.should_narrate("web_search")[0] is True
        for tool in ("open_app", "read_email", "build_project", "agent_roster"):
            assert narration.should_narrate(tool)[0] is False

    def test_a_new_turn_allows_it_again(self, monkeypatch):
        real = time.monotonic()
        monkeypatch.setattr(narration.time, "monotonic",
                            lambda: real + narration.NARRATE_AFTER_S + 0.3)
        assert narration.should_narrate("web_search")[0] is True
        narration.begin_turn("next")
        monkeypatch.setattr(narration.time, "monotonic",
                            lambda: real + (narration.NARRATE_AFTER_S * 2) + 1)
        assert narration.should_narrate("web_search")[0] is True

    def test_typed_turns_are_never_narrated(self, monkeypatch):
        """Nobody wants "let me check" typed at them."""
        real = time.monotonic()
        monkeypatch.setattr(narration.time, "monotonic",
                            lambda: real + narration.NARRATE_AFTER_S + 0.3)
        assert narration.should_narrate("web_search", spoken_turn=False)[0] is False


class TestItCannotBreakTheTurn:
    def test_a_speech_failure_does_not_raise(self, monkeypatch):
        """Failing to say "one moment" must not fail the work it narrated."""
        import reyes_agent.voice_manager as vm

        real = time.monotonic()      # BEFORE patching, or the lambda calls itself
        monkeypatch.setattr(narration.time, "monotonic", lambda: real + 60)
        monkeypatch.setattr(vm, "speak_queued",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("no audio device")))
        monkeypatch.setattr(vm, "cached_audio", lambda text: None)
        assert narration.narrate("web_search") == ""
