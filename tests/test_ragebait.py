"""Behaviour tests for ZENO's local, consent-scoped Ragebait state."""

from __future__ import annotations

import json


def test_activation_and_intensity_changes_are_bounded() -> None:
    from reyes_agent import ragebait

    ragebait.reset()
    assert ragebait.handle("ZENO, ragebait me.")["enabled"] is True
    assert ragebait.status()["intensity"] == 1
    for _ in range(10):
        ragebait.handle("Go harder.")
    assert ragebait.status()["intensity"] == 5
    for _ in range(10):
        ragebait.handle("Tone it down.")
    assert ragebait.status()["intensity"] == 0
    assert ragebait.status()["enabled"] is False


def test_stop_and_serious_context_disable_before_a_reply_is_directed() -> None:
    from reyes_agent import ragebait

    ragebait.reset()
    ragebait.handle("ragebait battle")
    assert ragebait.directive("Enough.", audience="owner_conversation") == ""
    assert ragebait.status()["enabled"] is False

    ragebait.handle("ragebait me")
    assert ragebait.directive("I have a medical emergency", audience="owner_conversation") == ""
    assert ragebait.status()["enabled"] is False


def test_external_actions_never_inherit_ragebait_context() -> None:
    from reyes_agent import ragebait

    ragebait.reset()
    ragebait.handle("ragebait me")
    assert ragebait.directive("send Ada a message", audience="external_action") == ""


def test_battle_lifecycle_and_recent_line_history_are_bounded() -> None:
    from reyes_agent import ragebait

    ragebait.reset()
    battle = ragebait.handle("ragebait battle")
    assert battle["battle"]["active"] is True
    for index in range(12):
        ragebait.record_reply(f"Fresh comeback {index}")
    details = ragebait.status()
    assert details["recent_lines"] == 8
    assert ragebait.directive("That's weak", audience="owner_conversation")
    ragebait.handle("stop")
    assert ragebait.status()["battle"]["active"] is False


def test_motion_is_local_cooldown_limited_and_events_are_redacted() -> None:
    from reyes_agent import ragebait

    events: list[tuple[str, dict]] = []
    ragebait.configure_for_test(publish=lambda name, payload: events.append((name, payload)))
    ragebait.handle("ragebait me")
    assert ragebait.on_motion("motion.shake", now=1000.0) is not None
    assert ragebait.on_motion("motion.shake", now=1001.0) is None
    ragebait.handle("ragebait battle")
    encoded = json.dumps(events)
    assert "password" not in encoded.casefold()
    assert "ragebait.battle_started" in [name for name, _ in events]
    ragebait.reset()
