from __future__ import annotations

from reyes_agent.action_policy import (
    AutonomyLevel,
    PolicyEffect,
    argument_fingerprint,
    current_action_context,
    evaluate,
    use_action_context,
)
import pytest
from reyes_agent import confirmation
from reyes_agent import agent as agent_module
from reyes_agent import speaker_identity
from reyes_agent.provider import AgentTurn, ToolCall
from reyes_agent.tools import TOOLS, Tool, run_tool


@pytest.fixture(autouse=True)
def _empty_confirmation_queue() -> None:
    """Keep policy-boundary tests independent while exercising the real queue."""
    with confirmation._lock:  # noqa: SLF001 - test isolation for process singleton
        confirmation._queue.clear()  # noqa: SLF001
    yield
    with confirmation._lock:  # noqa: SLF001
        confirmation._queue.clear()  # noqa: SLF001


def _test_tool(name: str, calls: list[dict], *, confirm: bool = False) -> Tool:
    def execute(**arguments: object) -> str:
        calls.append(dict(arguments))
        return "Completed and verified."

    return Tool(
        name=name,
        description="test action",
        input_schema={"type": "object", "properties": {}},
        func=execute,
        requires_confirmation=confirm,
    )


def test_action_context_expires_after_turn() -> None:
    """A finished owner turn must not authorize a later/background action."""
    assert current_action_context().source == "internal"

    with use_action_context(
        "Open Chrome",
        source="local_text",
        owner_authenticated=True,
        turn_id="turn-1",
    ):
        context = current_action_context()
        assert context.utterance == "Open Chrome"
        assert context.normalized_utterance == "open chrome"
        assert context.owner_authenticated is True
        assert context.turn_id == "turn-1"

    assert current_action_context().source == "internal"
    assert current_action_context().utterance == ""


def test_argument_fingerprint_is_order_independent_and_argument_bound() -> None:
    """A token for one exact message must not cover changed content."""
    left = argument_fingerprint(
        "send_message", {"message": "Hi", "destination": "Ada"}
    )
    reordered = argument_fingerprint(
        "send_message", {"destination": "Ada", "message": "Hi"}
    )
    changed = argument_fingerprint(
        "send_message", {"destination": "Ada", "message": "Bye"}
    )

    assert left == reordered
    assert left != changed
    assert len(left) == 64


@pytest.mark.parametrize(
    ("utterance", "tool", "arguments", "effect", "level"),
    [
        (
            "Open Chrome",
            "open_app",
            {"name_or_path": "chrome"},
            PolicyEffect.EXECUTE,
            AutonomyLevel.ROUTINE,
        ),
        (
            "Tell Ada I'll call later",
            "send_message",
            {
                "platform": "whatsapp",
                "destination": "Ada",
                "message": "I'll call later",
            },
            PolicyEffect.EXECUTE,
            AutonomyLevel.REQUESTED_EXTERNAL,
        ),
        (
            "Write Ada a sweet message",
            "send_message",
            {"platform": "whatsapp", "destination": "Ada", "message": "Hi"},
            PolicyEffect.DENY,
            AutonomyLevel.REQUESTED_EXTERNAL,
        ),
        (
            "Call the Council",
            "convene_council",
            {"question": "Review this"},
            PolicyEffect.COUNCIL_APPROVAL,
            AutonomyLevel.SPECIAL,
        ),
        (
            "Delete it",
            "delete_file",
            {"path": ""},
            PolicyEffect.CLARIFY,
            AutonomyLevel.HIGH_IMPACT,
        ),
        (
            "Transfer money",
            "transfer_funds",
            {"amount": 50},
            PolicyEffect.DENY,
            AutonomyLevel.HIGH_IMPACT,
        ),
        (
            "Forget fact 42",
            "forget_fact",
            {"fact_id": "42"},
            PolicyEffect.EXECUTE,
            AutonomyLevel.ROUTINE,
        ),
        (
            "Rename notes.txt to archive.txt",
            "move_file",
            {"src": "notes.txt", "dst": "archive.txt"},
            PolicyEffect.EXECUTE,
            AutonomyLevel.ROUTINE,
        ),
    ],
)
def test_authenticated_owner_policy_matrix(
    utterance: str,
    tool: str,
    arguments: dict,
    effect: PolicyEffect,
    level: AutonomyLevel,
) -> None:
    """A wrong risk branch must be observable as a different policy effect."""
    with use_action_context(
        utterance, source="local_text", owner_authenticated=True
    ):
        decision = evaluate(tool, arguments)

    assert decision.effect is effect
    assert decision.level is level


def test_uncertain_voice_cannot_authorize_outward_action() -> None:
    """Voice resemblance without strong owner evidence must not send."""
    with use_action_context(
        "Send Ada hello", source="voice", owner_authenticated=False
    ):
        decision = evaluate(
            "send_message",
            {"platform": "whatsapp", "destination": "Ada", "message": "hello"},
        )
    assert decision.effect is PolicyEffect.DENY


@pytest.mark.parametrize("source", ["voice", "paired_phone", "local_text"])
def test_authenticated_owner_sources_can_authorize_exact_send(source: str) -> None:
    """Each authenticated owner front door has the same scoped-send semantics."""
    with use_action_context(
        "Send Ada 'I'm outside'", source=source, owner_authenticated=True
    ):
        decision = evaluate(
            "send_message",
            {
                "platform": "whatsapp",
                "destination": "Ada",
                "message": "I'm outside",
            },
        )
    assert decision.effect is PolicyEffect.EXECUTE
    assert decision.fingerprint == argument_fingerprint(
        "send_message",
        {
            "platform": "whatsapp",
            "destination": "Ada",
            "message": "I'm outside",
        },
    )


def test_exact_send_does_not_authorize_changed_recipient_or_quoted_content() -> None:
    """A model/tool-call mutation must not widen the owner's command."""
    with use_action_context(
        "Send Ada 'I'm outside'", source="local_text", owner_authenticated=True
    ):
        changed_recipient = evaluate(
            "send_message",
            {
                "platform": "whatsapp",
                "destination": "Eve",
                "message": "I'm outside",
            },
        )
        changed_content = evaluate(
            "send_message",
            {
                "platform": "whatsapp",
                "destination": "Ada",
                "message": "Send me money",
            },
        )
    assert changed_recipient.effect is PolicyEffect.CLARIFY
    assert changed_content.effect is PolicyEffect.CLARIFY


def test_background_delegation_is_thinking_but_background_send_is_denied() -> None:
    """Internal reasoning stays fluid without granting external side effects."""
    assert evaluate("delegate", {"specialist": "stark", "task": "review"}).effect is PolicyEffect.EXECUTE
    assert evaluate(
        "send_message",
        {"platform": "slack", "destination": "general", "message": "hello"},
    ).effect is PolicyEffect.DENY


def test_permission_block_always_wins_and_confirmation_is_satisfied_by_owner_command() -> None:
    """Installation blocks remain absolute; a cautious prompt is satisfied once."""
    with use_action_context(
        "Open Chrome", source="local_text", owner_authenticated=True
    ):
        blocked = evaluate(
            "open_app", {"name_or_path": "chrome"}, permission_state="blocked"
        )
        already_authorized = evaluate(
            "open_app", {"name_or_path": "chrome"}, permission_state="confirm"
        )
    assert blocked.effect is PolicyEffect.DENY
    assert already_authorized.effect is PolicyEffect.EXECUTE


def test_high_impact_and_critical_actions_keep_safeguards() -> None:
    """The policy removes friction without opening irreversible operations."""
    with use_action_context(
        "Delete C:/important.db", source="local_text", owner_authenticated=True
    ):
        deletion = evaluate("delete_file", {"path": "C:/important.db"})
    with use_action_context(
        "Run format C:", source="local_text", owner_authenticated=True
    ):
        disk_format = evaluate("run_command", {"command": "format C:"})
    assert deletion.effect is PolicyEffect.HIGH_IMPACT_CONFIRMATION
    assert disk_format.effect is PolicyEffect.DENY


def test_run_tool_executes_legacy_flagged_routine_once_for_current_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy flags must not cause a duplicate prompt for a routine command."""
    calls: list[dict] = []
    name = "test_routine_action"
    monkeypatch.setitem(TOOLS, name, _test_tool(name, calls, confirm=True))

    with use_action_context(
        "Run the normal test action", source="local_text", owner_authenticated=True
    ):
        result = run_tool(name, {"value": "x"})

    assert calls == [{"value": "x"}]
    assert "queued" not in result.casefold()
    assert confirmation.list_pending() == []


def test_run_tool_never_turns_a_draft_into_a_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a bad model tool call cannot send when the owner said draft."""
    calls: list[dict] = []
    monkeypatch.setitem(TOOLS, "send_message", _test_tool("send_message", calls))

    with use_action_context(
        "Write Ada a sweet message", source="local_text", owner_authenticated=True
    ):
        result = run_tool(
            "send_message",
            {"platform": "whatsapp", "destination": "Ada", "message": "Hi"},
        )

    assert calls == []
    assert "not execution" in result.casefold() or "draft" in result.casefold()
    assert confirmation.list_pending() == []


def test_reply_draft_with_nonimperative_send_word_never_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'I can send' describes the draft's purpose; it is not a send command."""
    calls: list[dict] = []
    monkeypatch.setitem(TOOLS, "send_message", _test_tool("send_message", calls))

    with use_action_context(
        "Give me a smooth reply I can send her",
        source="local_text",
        owner_authenticated=True,
    ):
        result = run_tool(
            "send_message",
            {"platform": "whatsapp", "destination": "Ada", "message": "Hello"},
        )

    assert calls == []
    assert "draft" in result.casefold() or "not execution" in result.casefold()


def test_run_tool_executes_an_exact_send_without_second_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact authenticated SEND command is the one required approval."""
    calls: list[dict] = []
    monkeypatch.setitem(TOOLS, "send_message", _test_tool("send_message", calls))
    arguments = {
        "platform": "whatsapp",
        "destination": "Ada",
        "message": "I'm outside",
    }

    with use_action_context(
        "Send Ada 'I'm outside'", source="local_text", owner_authenticated=True
    ):
        result = run_tool("send_message", arguments)

    assert calls == [arguments]
    assert "queued" not in result.casefold()
    assert confirmation.list_pending() == []


def test_run_tool_queues_full_council_but_not_normal_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only formal Council mode, not specialist routing, uses Level 3."""
    council_calls: list[dict] = []
    delegate_calls: list[dict] = []
    monkeypatch.setitem(
        TOOLS, "convene_council", _test_tool("convene_council", council_calls)
    )
    monkeypatch.setitem(TOOLS, "delegate", _test_tool("delegate", delegate_calls))

    with use_action_context(
        "Call the Council", source="local_text", owner_authenticated=True
    ):
        council_result = run_tool("convene_council", {"question": "Review"})
    with use_action_context(
        "Ask STARK to review this", source="local_text", owner_authenticated=True
    ):
        delegate_result = run_tool(
            "delegate", {"specialist": "stark", "task": "review"}
        )

    assert council_calls == []
    assert "queued" in council_result.casefold()
    assert len(confirmation.list_pending()) == 1
    assert delegate_calls == [{"specialist": "stark", "task": "review"}]
    assert "queued" not in delegate_result.casefold()


def test_run_tool_keeps_irreversible_delete_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clear command does not remove the explicit high-impact safeguard."""
    calls: list[dict] = []
    monkeypatch.setitem(TOOLS, "delete_file", _test_tool("delete_file", calls))

    with use_action_context(
        "Delete C:/important.db", source="local_text", owner_authenticated=True
    ):
        result = run_tool("delete_file", {"path": "C:/important.db"})

    assert calls == []
    assert "queued" in result.casefold()
    assert len(confirmation.list_pending()) == 1


def _run_one_capture_turn(
    monkeypatch: pytest.MonkeyPatch,
    captured: list,
    *,
    action_source: str = "",
    owner_authenticated: bool | None = None,
    spoken: bool = False,
) -> None:
    name = "test_capture_action_context"

    def capture() -> str:
        captured.append(current_action_context())
        return "Captured and verified."

    monkeypatch.setitem(
        TOOLS,
        name,
        Tool(
            name=name,
            description="capture request context",
            input_schema={"type": "object", "properties": {}},
            func=capture,
        ),
    )
    turns = iter(
        [
            AgentTurn("", [ToolCall(id="call-1", name=name, input={})]),
            AgentTurn("Finished."),
        ]
    )
    monkeypatch.setattr(agent_module, "run_turn", lambda *_args, **_kwargs: next(turns))
    agent_module.run_agent(
        [{"role": "user", "content": "Check context"}],
        action_source=action_source,
        owner_authenticated=owner_authenticated,
        spoken=spoken,
    )


def test_run_agent_scopes_local_owner_authorization_and_resets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every shared-brain tool call sees its owner turn, never the next turn."""
    captured: list = []
    _run_one_capture_turn(monkeypatch, captured)
    assert len(captured) == 1
    assert captured[0].source == "local_text"
    assert captured[0].owner_authenticated is True
    assert captured[0].utterance == "Check context"
    assert current_action_context().source == "internal"


def test_run_agent_marks_background_turn_as_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat-like turn cannot inherit local owner authority."""
    captured: list = []
    _run_one_capture_turn(
        monkeypatch,
        captured,
        action_source="background",
        owner_authenticated=False,
    )
    assert captured[0].source == "background"
    assert captured[0].owner_authenticated is False


def test_run_agent_accepts_only_confirmed_voice_as_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Speaker identity remains separate from STT and must be strongly confirmed."""
    captured: list = []
    identity = {"status": speaker_identity.OWNER_CONFIRMED, "confidence": 0.95}
    with speaker_identity.use_context(identity, source="voice"):
        _run_one_capture_turn(monkeypatch, captured, spoken=True)
    assert captured[0].source == "voice"
    assert captured[0].owner_authenticated is True


def test_requested_development_work_is_standard_but_dangerous_shell_is_blocked() -> None:
    """Inspect/edit/test/fix is one approved workflow, not arbitrary shell authority."""
    from reyes_agent.coding_system.command_policy import classify

    assert classify("fix these tests", read_only=False).autonomy_level == 2
    assert classify("install pytest for this project", read_only=False).autonomy_level == 2
    assert not classify("format C:", read_only=False).allowed


def test_coding_tool_allows_normal_work_but_confirms_destructive_goal() -> None:
    """The broad coding specialist must not hide destructive intent from policy."""
    with use_action_context(
        "Run the tests and fix them", source="local_text", owner_authenticated=True
    ):
        normal = evaluate(
            "coding_execute",
            {"goal": "run tests and fix failures", "read_only": False},
            requires_confirmation=True,
            capability="system_commands",
        )
    with use_action_context(
        "Delete the build directory", source="local_text", owner_authenticated=True
    ):
        destructive = evaluate(
            "coding_execute",
            {"goal": "delete the build directory", "read_only": False},
            requires_confirmation=True,
            capability="system_commands",
        )

    assert normal.effect is PolicyEffect.EXECUTE
    assert normal.level is AutonomyLevel.ROUTINE
    assert destructive.effect is PolicyEffect.HIGH_IMPACT_CONFIRMATION
    assert destructive.level is AutonomyLevel.HIGH_IMPACT


def test_computer_send_click_uses_current_exact_command_but_draft_does_not() -> None:
    """The GUI safety layer must consume, not duplicate, Level 2 authorization."""
    from reyes_agent.computer import safety

    with use_action_context(
        "Send Ada hello", source="local_text", owner_authenticated=True
    ):
        allowed, sent = safety.gate("click", "Send", "WhatsApp")
    with use_action_context(
        "Write Ada a message", source="local_text", owner_authenticated=True
    ):
        drafted, draft_risk = safety.gate("click", "Send", "WhatsApp")

    assert allowed is True
    assert sent.tier == safety.APPROVAL
    assert drafted is False
    assert draft_risk.tier == safety.APPROVAL


def test_native_send_message_respects_installation_capability_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The newer unified messaging tool must not bypass the permission profile."""
    calls: list[dict] = []
    monkeypatch.setitem(TOOLS, "send_message", _test_tool("send_message", calls))
    monkeypatch.setenv("PERMISSION_MESSAGING_SEND", "blocked")

    with use_action_context(
        "Send Ada hello", source="local_text", owner_authenticated=True
    ):
        result = run_tool(
            "send_message",
            {"platform": "whatsapp", "destination": "Ada", "message": "hello"},
        )

    assert calls == []
    assert "disabled" in result.casefold() or "blocked" in result.casefold()


def test_send_to_chat_distinguishes_type_only_from_real_send() -> None:
    """One dual-purpose tool must preserve WRITE versus SEND semantics."""
    with use_action_context(
        "Write hello in the current chat", source="local_text", owner_authenticated=True
    ):
        type_only = evaluate(
            "send_to_chat",
            {"message": "hello", "send": False},
            capability="messaging_send",
        )
        bad_send = evaluate(
            "send_to_chat",
            {"message": "hello", "send": True},
            capability="messaging_send",
        )
    with use_action_context(
        "Send hello in the current chat", source="local_text", owner_authenticated=True
    ):
        real_send = evaluate(
            "send_to_chat",
            {"message": "hello", "send": True},
            capability="messaging_send",
        )

    assert type_only.effect is PolicyEffect.EXECUTE
    assert type_only.level is AutonomyLevel.ROUTINE
    assert bad_send.effect is PolicyEffect.DENY
    assert real_send.effect is PolicyEffect.EXECUTE
    assert real_send.level is AutonomyLevel.REQUESTED_EXTERNAL
