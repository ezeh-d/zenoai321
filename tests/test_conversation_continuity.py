"""Staying in a conversation: follow-ups without the name, and interruption."""

from __future__ import annotations

import pytest

from reyes_agent.voice import continuity


@pytest.fixture(autouse=True)
def _closed():
    continuity.close("test setup")
    yield
    continuity.close("test teardown")


class TestFollowUpWindow:
    def test_the_wake_word_is_required_before_any_conversation(self):
        decision = continuity.consider("what time is it", wake_matched=False)
        assert not decision.accept
        assert decision.needed_wake_word

    def test_being_named_always_works(self):
        decision = continuity.consider("zeno what time is it", wake_matched=True)
        assert decision.accept and decision.needed_wake_word

    def test_a_follow_up_needs_no_name(self):
        """The whole point: nobody says the name every sentence."""
        continuity.consider("zeno what time is it", wake_matched=True)
        decision = continuity.consider("and what about tomorrow",
                                       wake_matched=False)
        assert decision.accept
        assert not decision.needed_wake_word

    def test_each_exchange_extends_the_window(self):
        continuity.consider("zeno hello", wake_matched=True)
        first = continuity.seconds_left()
        continuity.consider("tell me more about that", wake_matched=False)
        assert continuity.seconds_left() >= first - 0.5

    def test_the_window_closes_and_the_name_is_needed_again(self, monkeypatch):
        continuity.consider("zeno hello", wake_matched=True)
        real = continuity.time.time
        monkeypatch.setattr(continuity.time, "time",
                            lambda: real() + continuity.FOLLOW_UP_WINDOW_S + 5)
        decision = continuity.consider("and tomorrow?", wake_matched=False)
        assert not decision.accept
        assert decision.needed_wake_word

    def test_a_visit_gets_a_longer_window(self):
        """People take longer to form a question when they are being hosted."""
        continuity.consider("zeno hello", wake_matched=True, visit=False)
        normal = continuity.seconds_left()
        continuity.close()
        continuity.consider("zeno hello", wake_matched=True, visit=True)
        assert continuity.seconds_left() > normal

    def test_noise_inside_the_window_is_not_a_command(self):
        """An open window must not turn a cough into an instruction."""
        continuity.consider("zeno hello", wake_matched=True)
        decision = continuity.consider("mm", wake_matched=False)
        assert not decision.accept
        assert "too short" in decision.reason

    def test_standby_shuts_it_immediately(self):
        continuity.consider("zeno hello", wake_matched=True)
        assert continuity.is_open()
        continuity.close("owner said standby")
        assert not continuity.is_open()
        assert not continuity.consider("hello?", wake_matched=False).accept

    def test_the_window_never_widens_permissions(self):
        """It decides whether the NAME was needed, never what may be DONE."""
        assert "never" in continuity.status()["rule"].lower()
        assert "permission" in continuity.status()["rule"].lower()


class TestBargeIn:
    def test_interrupting_while_silent_is_harmless(self, monkeypatch):
        import reyes_agent.conversation_state as state

        monkeypatch.setattr(state, "barge_in",
                            lambda source="user": type("T", (), {
                                "changed": False, "ok": False,
                                "reason": "not speaking"})())
        result = continuity.interrupted()
        assert result["stopped_speaking"] is False

    def test_interrupting_while_speaking_stops_the_speech(self, monkeypatch):
        import reyes_agent.conversation_state as state

        monkeypatch.setattr(state, "barge_in",
                            lambda source="user": type("T", (), {
                                "changed": True, "ok": True,
                                "reason": "interrupted"})())
        result = continuity.interrupted(source="phone")
        assert result["stopped_speaking"] is True

    def test_a_broken_barge_in_never_raises_into_the_audio_path(self, monkeypatch):
        """Audio frames must keep flowing even if interruption fails."""
        import reyes_agent.conversation_state as state

        monkeypatch.setattr(state, "barge_in",
                            lambda source="user": (_ for _ in ()).throw(
                                RuntimeError("boom")))
        result = continuity.interrupted()
        assert result["stopped_speaking"] is False
        assert "boom" in result["detail"]
