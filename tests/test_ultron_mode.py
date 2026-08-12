"""Serious mode: a mode of ZENO, not a second assistant."""

from __future__ import annotations

import pytest

from reyes_agent import modes


@pytest.fixture(autouse=True)
def _normal():
    modes.set_mode(modes.NORMAL, source="test setup")
    yield
    modes.set_mode(modes.NORMAL, source="test teardown")


class TestZenoRemainsMaster:
    def test_master_is_constant(self):
        """There is no code path that makes ULTRON the master."""
        modes.set_mode(modes.ULTRON)
        assert modes.MASTER == "ZENO"
        assert modes.status()["master"] == "ZENO"
        assert modes.runtime_state().master == "ZENO"

    def test_no_second_ultron_identity_is_created(self):
        """TEST 11: ULTRON already exists as the Chief Strategy Officer.

        Serious mode reuses that registered agent. Creating a second ULTRON
        would be the duplicate the brief forbids.
        """
        from reyes_agent.agents import identity

        modes.set_mode(modes.ULTRON)
        roster = identity.roster()
        ultrons = [a for a in roster if a["id"] == "ultron"]
        assert len(ultrons) == 1
        assert ultrons[0]["role"] == "Chief Strategy Officer"
        assert modes.style()["delegates_strategy_to"] == "ultron"

    def test_the_agent_roster_does_not_change_with_mode(self):
        from reyes_agent.agents import identity

        before = {a["id"] for a in identity.roster()}
        modes.set_mode(modes.ULTRON)
        assert {a["id"] for a in identity.roster()} == before


class TestActivation:
    @pytest.mark.parametrize("said", [
        "ULTRON", "ZENO, activate Ultron", "activate serious mode",
        "serious mode", "ultron mode", "bring ultron online", "go serious",
    ])
    def test_activation_phrases(self, said):
        assert modes.detect(said) == "ACTIVATE"

    @pytest.mark.parametrize("said", [
        "return to zeno", "exit ultron", "normal mode",
        "deactivate serious mode", "Ultron, stand down", "zeno come back",
    ])
    def test_deactivation_phrases(self, said):
        assert modes.detect(said) == "DEACTIVATE"

    def test_stand_down_turns_it_off_not_on(self):
        """"Ultron, stand down" contains the activation word.

        Matching activation first would make the phrase that ends serious
        mode start it instead.
        """
        assert modes.detect("Ultron, stand down") == "DEACTIVATE"

    def test_ordinary_speech_changes_nothing(self):
        for said in ("what time is it", "open slack", "who are your agents"):
            assert modes.detect(said) == ""

    def test_the_greeting_is_short(self):
        """No dramatic speech. It stops being impressive the second time."""
        result = modes.set_mode(modes.ULTRON)
        assert result["say"]
        assert len(result["say"].split()) <= 8

    def test_activating_twice_is_harmless(self):
        modes.set_mode(modes.ULTRON)
        again = modes.set_mode(modes.ULTRON)
        assert again["ok"] and not again["changed"]

    def test_an_unknown_mode_is_refused(self):
        result = modes.set_mode("SKYNET")
        assert not result["ok"]
        assert modes.current() in modes.MODES


class TestSafetyIsUnchanged:
    """Serious mode means more serious reasoning, NOT fewer restrictions."""

    @pytest.mark.parametrize("forbidden", [
        "transfer 500 to my brother", "change my password",
        "disable the firewall",
    ])
    def test_serious_mode_does_not_unlock_anything(self, forbidden):
        from reyes_agent.phone_security import DEFAULT_SCOPES
        from reyes_agent.remote_access import policy

        scopes = set(DEFAULT_SCOPES)
        normal = policy.evaluate(forbidden, scopes=scopes).allowed
        modes.set_mode(modes.ULTRON)
        serious = policy.evaluate(forbidden, scopes=scopes).allowed
        assert normal is False and serious is False

    def test_the_status_says_so_plainly(self):
        assert "never permissions" in modes.status()["safety"]


class TestStyle:
    def test_normal_mode_adds_no_guidance(self):
        assert modes.style()["guidance"] == ""

    def test_serious_mode_is_calm_not_theatrical(self):
        modes.set_mode(modes.ULTRON)
        guidance = modes.style()["guidance"].lower()
        assert "calm" in guidance and "precise" in guidance
        assert "never be threatening" in guidance
        assert "not a separate being" in guidance

    def test_it_reduces_filler_and_increases_verification(self):
        modes.set_mode(modes.ULTRON)
        style = modes.style()
        assert "jokes" in style["reduce"]
        assert "verification" in style["increase"]


class TestRestart:
    def test_a_restart_returns_to_normal_by_default(self, monkeypatch):
        """A crash while serious should not bring the machine back serious."""
        monkeypatch.delenv("RESTORE_LAST_MODE", raising=False)
        modes.set_mode(modes.ULTRON)
        assert modes.restore_on_start() == modes.NORMAL

    def test_unless_explicitly_configured(self, monkeypatch):
        monkeypatch.setenv("RESTORE_LAST_MODE", "true")
        modes.set_mode(modes.ULTRON)
        assert modes.restore_on_start() == modes.ULTRON


class TestRuntimeStateIsReal:
    def test_no_active_task_reports_empty_not_invented(self):
        """TEST 5: the HUD must show NO ACTIVE MISSION, not a fake one."""
        modes.set_mode(modes.ULTRON)
        state = modes.runtime_state().as_dict()
        assert state["current_task"] == ""
        assert state["active_agent"] in ("", None) or isinstance(
            state["active_agent"], str)
        # No progress percentage is invented anywhere in the payload.
        assert "progress" not in state

    def test_mode_change_is_announced_on_the_bus(self):
        """The frontend reacts to this; it never decides the mode itself."""
        import time

        from reyes_agent import event_bus

        started = time.time()
        modes.set_mode(modes.ULTRON, source="test")
        found = [e for e in event_bus.history(limit=50, since=started - 1)
                 if (e.get("type") if isinstance(e, dict) else e.type)
                 == "assistant.mode_changed"]
        assert found
