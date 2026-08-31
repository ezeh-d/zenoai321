from __future__ import annotations

from reyes_agent.conversation_coordinator import ConversationCoordinator, session_key


def test_turn_context_is_session_scoped() -> None:
    coordinator = ConversationCoordinator(max_sessions=2, max_turns=4)
    coordinator.begin_turn(
        "t1",
        session_key="desktop",
        source="local_text",
        utterance="Open Notepad",
        owner_authenticated=True,
    )
    coordinator.begin_turn(
        "t2",
        session_key="phone",
        source="paired_phone",
        utterance="Open Chrome",
        owner_authenticated=True,
    )
    coordinator.record_route("t1", ("desktop",), "clear")
    coordinator.record_route("t2", ("browser",), "clear")

    assert coordinator.active_surface("desktop") == "desktop"
    assert coordinator.active_surface("phone") == "browser"


def test_new_turn_supersedes_only_its_session() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn(
        "old",
        session_key="owner",
        source="local_text",
        utterance="first",
        owner_authenticated=True,
    )
    coordinator.begin_turn(
        "other",
        session_key="guest",
        source="voice",
        utterance="hello",
        owner_authenticated=False,
    )
    coordinator.begin_turn(
        "new",
        session_key="owner",
        source="local_text",
        utterance="second",
        owner_authenticated=True,
    )

    assert coordinator.snapshot("owner")["active_turn_id"] == "new"
    assert coordinator.turn("old").status == "SUPERSEDED"
    assert coordinator.snapshot("guest")["active_turn_id"] == "other"


def test_guest_never_inherits_owner_reference() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn(
        "o",
        session_key="owner",
        source="local_text",
        utterance="Open my private report",
        owner_authenticated=True,
    )
    coordinator.record_reference("o", "target", "private report")
    coordinator.begin_turn(
        "g",
        session_key="guest",
        source="voice",
        utterance="open it",
        owner_authenticated=False,
    )

    assert "private report" not in str(coordinator.snapshot("guest"))


def test_clarification_resumes_only_the_same_authenticated_session() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn(
        "t1",
        session_key="owner",
        source="local_text",
        utterance="Send hello",
        owner_authenticated=True,
    )
    coordinator.set_pending_clarification("t1", "Which recipient?", "recipient")

    effective = coordinator.authorization_utterance(
        "owner", "Ada", owner_authenticated=True
    )

    assert "Send hello" in effective
    assert "Ada" in effective
    assert coordinator.authorization_utterance(
        "guest", "Ada", owner_authenticated=False
    ) == "Ada"


def test_pending_clarification_expires(monkeypatch) -> None:
    coordinator = ConversationCoordinator(clarification_ttl_s=120)
    coordinator.begin_turn(
        "t1",
        session_key="owner",
        source="local_text",
        utterance="Send hello",
        owner_authenticated=True,
    )
    coordinator.set_pending_clarification("t1", "Which recipient?", "recipient")
    initial = coordinator._now()
    monkeypatch.setattr(coordinator, "_now", lambda: initial + 121)

    assert coordinator.authorization_utterance(
        "owner", "Ada", owner_authenticated=True
    ) == "Ada"


def test_finish_cancel_and_reset_are_bounded_terminal_operations() -> None:
    coordinator = ConversationCoordinator(max_sessions=2, max_turns=2)
    coordinator.begin_turn(
        "done",
        session_key="one",
        source="local_text",
        utterance="one",
        owner_authenticated=True,
        manage_lifecycle=False,
    )
    coordinator.record_tool_result(
        "done", tool="open_app", outcome="VERIFIED", evidence="Notepad window"
    )
    coordinator.finish_turn("done")
    assert coordinator.turn("done").status == "COMPLETED"
    assert coordinator.snapshot("one")["last_verified_outcome"] == "Notepad window"

    coordinator.begin_turn(
        "cancelled",
        session_key="two",
        source="voice",
        utterance="two",
        owner_authenticated=True,
        manage_lifecycle=False,
    )
    coordinator.cancel_turn("cancelled", reason="owner interrupted")
    assert coordinator.turn("cancelled").status == "CANCELLED"

    coordinator.begin_turn(
        "newest",
        session_key="three",
        source="local_text",
        utterance="three",
        owner_authenticated=True,
        manage_lifecycle=False,
    )
    assert coordinator.turn("done") is None
    assert coordinator.snapshot("one") == {}

    coordinator.reset()
    assert coordinator.snapshot("three") == {}


def test_session_keys_isolate_phone_and_guest_voice_without_authenticating() -> None:
    assert session_key(source="local_text") == "desktop-owner"
    assert session_key(source="paired_phone", device_id="abc") == "phone:abc"
    assert session_key(source="voice", device_id="mic", owner=False) == "guest-voice:mic"
