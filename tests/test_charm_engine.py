from __future__ import annotations

import json

import pytest

from reyes_agent.charm.models import (
    CharmFeature,
    CharmMode,
    CharmRequest,
    Recommendation,
)
from reyes_agent.charm.styles import get_style, list_styles
from reyes_agent.charm.context import analyze_conversation
from reyes_agent.charm.routing import is_charm_request
from reyes_agent.charm.memory import CharmSessionStore, MemoryAdapter
from reyes_agent.charm.critic import rank_candidates, score_candidate
from reyes_agent.charm.generator import CharmGenerationError, ResponseGenerator
from reyes_agent.charm.engine import CharmEngine


EXPECTED_MODES = {
    "Natural",
    "Smooth",
    "Sweet",
    "Flirty",
    "Playful",
    "Funny",
    "Witty",
    "Romantic",
    "Confident",
    "Gentleman",
    "Cheeky",
    "Deep",
    "Serious",
    "Pidgin Smooth",
}


def test_all_requested_charm_modes_are_supported() -> None:
    """Removing or misspelling a requested mode must break the public contract."""
    assert {mode.value for mode in CharmMode} == EXPECTED_MODES
    assert set(list_styles()) == EXPECTED_MODES


@pytest.mark.parametrize("mode", sorted(EXPECTED_MODES))
def test_each_charm_mode_has_a_non_canned_style_profile(mode: str) -> None:
    """Every selectable mode must carry constraints, not fixed reply lines."""
    profile = get_style(mode)
    assert profile.mode.value == mode
    assert profile.guidance
    assert 0 <= profile.warmth <= 100
    assert 0 <= profile.humor <= 100
    assert 0 <= profile.flirt <= 100
    assert 0 <= profile.directness <= 100
    assert "pickup line" not in profile.guidance.casefold()


def test_charm_request_normalizes_mode_feature_and_bounds_work() -> None:
    """A caller cannot create an unbounded candidate/model workload."""
    request = CharmRequest(
        instruction="Give me options",
        conversation=["Me: Hi", "Them: Hello"],
        mode="pidgin smooth",
        feature="reply",
        count=99,
        intensity=-5,
    )
    assert request.mode is CharmMode.PIDGIN_SMOOTH
    assert request.feature is CharmFeature.REPLY
    assert request.count == 5
    assert request.intensity == 0
    assert request.conversation == ("Me: Hi", "Them: Hello")


def test_charm_request_bounds_instruction_and_each_conversation_message() -> None:
    request = CharmRequest(
        instruction="x" * 5000,
        conversation=["y" * 10000 for _ in range(30)],
    )
    assert len(request.instruction) == 1000
    assert len(request.conversation) == 20
    assert all(len(message) <= 2000 for message in request.conversation)


def test_charm_request_rejects_unknown_mode_and_feature() -> None:
    """Silent fallback would make the UI claim a mode that was not applied."""
    with pytest.raises(ValueError, match="mode"):
        CharmRequest(instruction="reply", mode="aggressive")
    with pytest.raises(ValueError, match="feature"):
        CharmRequest(instruction="reply", feature="mass_message")


def test_recommendation_vocabulary_is_bounded() -> None:
    assert {item.value for item in Recommendation} == {
        "CONTINUE",
        "WAIT",
        "MATCH",
        "PULL_BACK",
        "ABORT",
    }


def test_context_analyzer_detects_reciprocal_momentum() -> None:
    """Removing speaker-aware balance should lower the observable engagement."""
    signals = analyze_conversation(
        [
            "Me: How did the presentation go?",
            "Them: It went really well, I was nervous at first though 😄",
            "Me: I knew you would smash it. What was the best part?",
            "Them: The questions after. I actually enjoyed answering them!",
        ]
    )
    assert signals.recommendation is Recommendation.CONTINUE
    assert signals.reciprocity >= 60
    assert signals.momentum >= 60
    assert signals.engagement >= 60
    assert signals.tone in {"positive", "warm", "playful"}


def test_context_analyzer_matches_low_energy_dry_replies() -> None:
    """Several observable one-word replies should not invite escalation."""
    signals = analyze_conversation(
        [
            "Me: How was your day?",
            "Them: fine",
            "Me: Anything interesting happen?",
            "Them: nah",
            "Me: Want to talk later?",
            "Them: k",
        ]
    )
    assert signals.dry_reply_ratio >= 0.66
    assert signals.engagement < 50
    assert signals.recommendation in {Recommendation.MATCH, Recommendation.PULL_BACK}


def test_context_analyzer_waits_after_unanswered_streak() -> None:
    signals = analyze_conversation(
        [
            "Them: talk later",
            "Me: alright",
            "Me: are you free now?",
            "Me: just checking in again",
        ]
    )
    assert signals.unanswered_streak == 3
    assert signals.recommendation is Recommendation.WAIT


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (["Me: Can I call?", "Them: Please stop messaging me"], Recommendation.ABORT),
        (["Me: You look good", "Them: This is making me uncomfortable"], Recommendation.PULL_BACK),
        (["Them: no", "Me: please?", "Them: I said no"], Recommendation.ABORT),
    ],
)
def test_context_analyzer_respects_stop_discomfort_and_repeated_no(
    messages: list[str], expected: Recommendation
) -> None:
    signals = analyze_conversation(messages)
    assert signals.recommendation is expected
    assert signals.stop_requested or signals.discomfort_detected or signals.repeated_rejection


@pytest.mark.parametrize(
    "message",
    [
        "Leave me alone",
        "Jane: Leave me alone",
        "Don't text me again",
        "Do not message me again",
        "Never text me again",
    ],
)
def test_context_analyzer_treats_ambiguous_single_reply_as_the_other_speaker(
    message: str,
) -> None:
    """A missing or unknown label must fail safe on an incoming stop request."""
    signals = analyze_conversation([message])
    assert signals.recommendation is Recommendation.ABORT
    assert signals.stop_requested is True


def test_pidgin_is_treated_as_normal_language_not_low_quality() -> None:
    signals = analyze_conversation(
        [
            "Me: How your day dey go?",
            "Them: E dey go well o, you nko?",
            "Me: I dey alright. Wetin make you smile today?",
            "Them: Your message sef make me laugh 😂",
        ]
    )
    assert signals.recommendation is Recommendation.CONTINUE
    assert signals.confidence >= 0.7
    assert signals.engagement >= 60


@pytest.mark.parametrize(
    "text",
    [
        "Give me a smooth reply",
        "Make that sweeter",
        "Give me something playful",
        "Make it funny",
        "Give me three options",
        "Make it sound natural",
        "Make it sound like me",
        "What should I text her?",
        "Help me reply to her message",
        "She's giving dry replies, what should I do?",
        "Give me three Pidgin Smooth options",
        "Don't make me sound desperate",
    ],
)
def test_hybrid_router_recognizes_clear_charm_requests(text: str) -> None:
    assert is_charm_request(text) is True


@pytest.mark.parametrize(
    "text", ["hello ZENO", "smooth the orb animation", "run my tests", "open Chrome"]
)
def test_hybrid_router_does_not_hijack_normal_zeno_requests(text: str) -> None:
    assert is_charm_request(text) is False


def test_callback_memory_is_bounded_and_evicts_old_suggestions() -> None:
    """A long-running wingman session must not retain unbounded reply objects."""
    store = CharmSessionStore(max_sessions=2, max_candidates=3, max_messages=4)
    first_id = store.record_candidates("chat-1", ["one"])[0]
    store.record_candidates("chat-1", ["two", "three", "four"])
    store.record_conversation("chat-1", ["m1", "m2", "m3", "m4", "m5"])

    assert len(store.recent_hashes("chat-1")) == 3
    assert store.resolve_candidate("chat-1", first_id) is None
    assert store.snapshot("chat-1")["message_count"] == 4
    assert store.recent_conversation("chat-1") == ("m2", "m3", "m4", "m5")


def test_feedback_only_applies_to_a_known_candidate() -> None:
    """Feedback must not create invented candidate history."""
    store = CharmSessionStore(max_candidates=4)
    candidate_id = store.record_candidates("chat", ["A real candidate"])[0]
    assert store.record_feedback("chat", "missing", "liked") is False
    assert store.record_feedback("chat", candidate_id, "liked") is True
    assert store.snapshot("chat")["feedback_count"] == 1


def test_session_limit_evicts_least_recent_charm_session() -> None:
    store = CharmSessionStore(max_sessions=2)
    store.record_candidates("one", ["a"])
    store.record_candidates("two", ["b"])
    store.record_candidates("three", ["c"])
    assert store.snapshot("one")["exists"] is False
    assert store.snapshot("two")["exists"] is True
    assert store.snapshot("three")["exists"] is True


def test_memory_adapter_retrieves_only_non_sensitive_communication_preferences() -> None:
    """Charm must not turn generic project or private memory into a voice model."""
    class FakeManager:
        def __init__(self) -> None:
            self.queries: list[tuple[str, int]] = []
            self.writes = 0

        def retrieve(self, query: str, *, limit: int) -> list[dict]:
            self.queries.append((query, limit))
            return [
                {"memory": "Prefers short natural replies", "category": "preference"},
                {"memory": "Home address is 10 Example Street", "category": "user"},
                {"memory": "Project API password is hidden", "category": "project"},
                {"memory": "Likes light Pidgin code-switching", "category": "communication"},
            ]

        def consider(self, *_args, **_kwargs) -> None:
            self.writes += 1

    manager = FakeManager()
    adapter = MemoryAdapter(manager=manager)
    preferences = adapter.preferences("reply style")

    assert preferences == (
        "Prefers short natural replies",
        "Likes light Pidgin code-switching",
    )
    assert manager.queries == [("communication style preference reply style", 6)]
    assert manager.writes == 0


def test_candidate_scores_expose_all_requested_metrics_in_range() -> None:
    request = CharmRequest(
        instruction="Give me a natural reply",
        conversation=["Them: The presentation went well", "Me: Nice"],
        mode="Natural",
    )
    signals = analyze_conversation(request.conversation)
    scores = score_candidate(
        "That sounds like a win 😄 what part did you enjoy most?",
        request,
        signals,
    )
    values = scores.as_dict()
    assert set(values) == {
        "naturalness",
        "context_relevance",
        "confidence",
        "warmth",
        "humor",
        "flirt_level",
        "pressure_level",
        "desperation_risk",
        "cringe_risk",
        "repetition_risk",
        "rank_score",
    }
    assert all(0 <= value <= 100 for value in values.values())


def test_ranker_selects_contextual_reply_not_first_generated_line() -> None:
    request = CharmRequest(
        instruction="Reply naturally",
        conversation=[
            "Me: How did the presentation go?",
            "Them: It went well, I enjoyed the questions afterwards",
        ],
        mode="Natural",
    )
    signals = analyze_conversation(request.conversation)
    desperate = "Please please reply, I need you, don't ignore me!!!"
    contextual = "That sounds like a win 😄 which question did you enjoy answering most?"
    ranked = rank_candidates([desperate, contextual], request, signals)

    assert ranked[0].text == contextual
    assert ranked[0].eligible is True
    bad = next(item for item in ranked if item.text == desperate)
    assert bad.scores.pressure_level >= 60
    assert bad.scores.desperation_risk >= 70
    assert bad.eligible is False


def test_cringe_firewall_penalizes_overclaiming_and_spammy_punctuation() -> None:
    request = CharmRequest(
        instruction="Give me a smooth reply",
        conversation=["Them: hi"],
        relationship="we just met",
        mode="Smooth",
    )
    scores = score_candidate(
        "My perfect goddess, you are the love of my life!!!!! 😍😍😍😍😍",
        request,
        analyze_conversation(request.conversation),
    )
    assert scores.cringe_risk >= 75
    assert scores.naturalness <= 45


@pytest.mark.parametrize(
    "text",
    [
        "If you loved me, you would reply.",
        "I will keep messaging until you say yes.",
    ],
)
def test_critic_disqualifies_common_coercive_pressure(text: str) -> None:
    request = CharmRequest(instruction="reply", conversation=["Them: I had a nice day"])
    ranked = rank_candidates([text], request, analyze_conversation(request.conversation))
    assert ranked[0].eligible is False
    assert ranked[0].scores.pressure_level >= 60


def test_repetition_risk_detects_exact_recent_suggestion() -> None:
    import hashlib

    text = "Tell me the best part of your day"
    digest = hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()
    request = CharmRequest(instruction="reply", conversation=["Them: hello"])
    scores = score_candidate(
        text,
        request,
        analyze_conversation(request.conversation),
        recent_hashes=(digest,),
    )
    assert scores.repetition_risk == 100


def test_backoff_context_disqualifies_romantic_escalation() -> None:
    request = CharmRequest(
        instruction="Make it romantic",
        conversation=["Me: Can we talk?", "Them: Please stop messaging me"],
        mode="Romantic",
        intensity=90,
    )
    signals = analyze_conversation(request.conversation)
    ranked = rank_candidates(["You are all I need, please give me one chance"], request, signals)
    assert signals.recommendation is Recommendation.ABORT
    assert ranked[0].eligible is False
    assert "back-off" in " ".join(ranked[0].reasons).casefold()


class _Turn:
    def __init__(self, text: str, tool_calls: list | None = None) -> None:
        self.text = text
        self.tool_calls = tool_calls or []


@pytest.mark.parametrize(
    ("mode", "reply"),
    [
        ("Natural", "That sounds good. What happened next?"),
        ("Smooth", "You make that story sound effortless. Go on."),
        ("Sweet", "I'm glad it went well; you clearly put real work into it."),
        ("Funny", "Plot twist: the questions were the main event 😂"),
        ("Pidgin Smooth", "E sweet me say e go well. Which part you enjoy pass?"),
    ],
)
def test_generator_uses_selected_style_and_one_provider_call(mode: str, reply: str) -> None:
    calls: list[dict] = []

    def fake_provider(**kwargs):
        calls.append(kwargs)
        return _Turn(json.dumps({"candidates": [{"text": reply}]}))

    request = CharmRequest(
        instruction="Give me the best reply",
        conversation=["Them: My presentation went well"],
        mode=mode,
        count=1,
    )
    generated = ResponseGenerator(fake_provider).generate(
        request,
        analyze_conversation(request.conversation),
        preferences=("Prefers concise replies",),
    )

    assert generated == (reply,)
    assert len(calls) == 1
    assert calls[0]["tools"] == []
    assert mode.casefold() in calls[0]["system"].casefold()
    assert calls[0]["task_kind"] == "conversation"


def test_generator_parses_fenced_json_deduplicates_and_caps_output() -> None:
    def fake_provider(**_kwargs):
        return _Turn(
            "```json\n{\"candidates\":[\"one\",{\"text\":\"one\"},"
            "{\"text\":\"two\"},{\"text\":\"three\"}]}\n```"
        )

    request = CharmRequest(instruction="Give me two options", count=2)
    assert ResponseGenerator(fake_provider).generate(
        request, analyze_conversation(request.conversation)
    ) == ("one", "two")


def test_generator_rejects_underproduction_instead_of_ignoring_requested_count() -> None:
    generator = ResponseGenerator(
        lambda **_kwargs: _Turn('{"candidates":[{"text":"only one"}]}')
    )
    request = CharmRequest(instruction="Give me three options", count=3)
    with pytest.raises(CharmGenerationError, match="3"):
        generator.generate(request, analyze_conversation(request.conversation))


@pytest.mark.parametrize(
    "turn",
    [
        _Turn("not json"),
        _Turn('{"candidates": []}'),
        _Turn('{"candidates": [""]}'),
        _Turn('{"candidates": ["valid"]}', tool_calls=[object()]),
    ],
)
def test_generator_fails_honestly_instead_of_returning_canned_text(turn: _Turn) -> None:
    generator = ResponseGenerator(lambda **_kwargs: turn)
    with pytest.raises(CharmGenerationError):
        generator.generate(CharmRequest(instruction="reply"), analyze_conversation(()))


class _FakeGenerator:
    def __init__(self, values: tuple[str, ...] = (), error: Exception | None = None) -> None:
        self.values = values
        self.error = error
        self.calls: list[tuple] = []

    def generate(self, request, signals, *, preferences=(), cancel_check=None):
        self.calls.append((request, signals, preferences, cancel_check))
        if self.error:
            raise self.error
        return self.values


class _FakeMemory:
    def __init__(self, preferences: tuple[str, ...] = ()) -> None:
        self.values = preferences
        self.queries: list[str] = []

    def preferences(self, query: str) -> tuple[str, ...]:
        self.queries.append(query)
        return self.values


def test_engine_stops_before_generation_when_contact_should_stop() -> None:
    generator = _FakeGenerator(("Please give me another chance",))
    events: list[tuple[str, dict]] = []
    engine = CharmEngine(generator=generator, publish=lambda name, payload: events.append((name, payload)))
    request = CharmRequest(
        instruction="Make it romantic",
        conversation=["Me: Can we talk?", "Them: Leave me alone"],
        mode="Romantic",
    )

    result = engine.generate(request)

    assert result.signals.recommendation is Recommendation.ABORT
    assert result.generated is False
    assert result.candidates == ()
    assert "stop" in result.warning.casefold() or "back" in result.warning.casefold()
    assert generator.calls == []
    assert any(name == "charm.backoff" for name, _ in events)


def test_standalone_analysis_emits_metadata_without_starting_generation() -> None:
    generator = _FakeGenerator(("must not run",))
    events: list[tuple[str, dict]] = []
    engine = CharmEngine(
        generator=generator,
        publish=lambda name, payload: events.append((name, payload)),
    )
    signals = engine.analyze(
        ["Them: The event was good"], session_id="analysis-only", emit_event=True
    )
    assert signals.recommendation is Recommendation.CONTINUE
    assert generator.calls == []
    assert events == [(
        "charm.analyzed",
        {
            "session_id": "analysis-only",
            "recommendation": "CONTINUE",
            "tone": signals.tone,
            "engagement": signals.engagement,
            "confidence": signals.confidence,
        },
    )]


def test_engine_retrieves_preferences_generates_ranks_and_records() -> None:
    generator = _FakeGenerator((
        "Please please answer me, I need you!!!",
        "That sounds like a win 😄 which question did you enjoy most?",
    ))
    memory = _FakeMemory(("Prefers concise replies",))
    events: list[tuple[str, dict]] = []
    engine = CharmEngine(
        generator=generator,
        memory=memory,
        publish=lambda name, payload: events.append((name, payload)),
    )
    request = CharmRequest(
        instruction="Give me two natural options",
        conversation=["Them: I enjoyed the questions after my presentation"],
        count=2,
        session_id="chat-42",
    )

    result = engine.generate(request)

    assert result.generated is True
    assert result.best is not None
    assert result.best.text.startswith("That sounds")
    assert len(generator.calls) == 1
    assert generator.calls[0][2] == ("Prefers concise replies",)
    assert memory.queries == [request.instruction]
    assert engine.status("chat-42")["candidate_count"] == 2
    assert events[-1][0] == "charm.completed"
    assert [name for name, _ in events] == [
        "charm.started",
        "charm.analyzed",
        "charm.generated",
        "charm.ranked",
        "charm.completed",
    ]
    assert "conversation" not in events[-1][1]
    assert "text" not in events[-1][1]


@pytest.mark.parametrize("feature", [item.value for item in CharmFeature])
def test_every_coach_feature_uses_the_same_bounded_engine(feature: str) -> None:
    generator = _FakeGenerator(("One grounded option",))
    engine = CharmEngine(generator=generator)
    result = engine.coach(
        feature,
        "Help with this conversation",
        ["Them: The event was good"],
        count=1,
    )
    assert result.request.feature.value == feature
    assert len(generator.calls) == 1


def test_lazy_singleton_reuses_one_engine_instance(monkeypatch) -> None:
    import reyes_agent.charm.engine as engine_module

    monkeypatch.setattr(engine_module, "_instance", None)
    first = engine_module.get_charm_engine()
    second = engine_module.get_charm_engine()
    assert first is second


def test_engine_reports_provider_failure_without_fake_success() -> None:
    generator = _FakeGenerator(error=CharmGenerationError("provider unavailable"))
    engine = CharmEngine(generator=generator)
    result = engine.generate(CharmRequest(instruction="Give me a smooth reply"))
    assert result.generated is False
    assert result.best is None
    assert "provider unavailable" in result.error


def test_engine_degrades_when_optional_memory_retrieval_fails() -> None:
    class BrokenMemory:
        def preferences(self, _query: str):
            raise RuntimeError("memory unavailable")

    generator = _FakeGenerator(("A safe option",))
    result = CharmEngine(generator=generator, memory=BrokenMemory()).reply(
        "draft one", ["Them: hello"]
    )
    assert result.best is not None
    assert generator.calls[0][2] == ()


def test_engine_mode_status_and_candidate_feedback_are_session_scoped() -> None:
    generator = _FakeGenerator(("A calm contextual reply",))
    engine = CharmEngine(generator=generator)
    engine.set_mode("chat", "Witty", intensity=73)
    assert engine.status("chat")["mode"] == "Witty"
    assert engine.status("chat")["intensity"] == 73

    result = engine.reply("draft a reply", ["Them: hello"], session_id="chat")
    assert result.request.mode is CharmMode.WITTY
    assert result.best is not None
    assert engine.feedback("chat", result.best.id, "liked") is True
    assert engine.feedback("chat", "invented", "liked") is False

    engine.reply("draft another reply", ["Them: tell me more"], session_id="chat")
    assert any(
        "liked" in hint.casefold() and "calm contextual" in hint.casefold()
        for hint in generator.calls[-1][2]
    )

    engine.reply("make it sweeter", session_id="chat")
    assert generator.calls[-1][0].conversation[-1] == "Them: tell me more"


def test_feedback_event_does_not_persist_arbitrary_private_text() -> None:
    events: list[tuple[str, dict]] = []
    engine = CharmEngine(
        generator=_FakeGenerator(("A real option",)),
        publish=lambda name, payload: events.append((name, payload)),
    )
    result = engine.reply("draft one", ["Them: hello"], session_id="private-feedback")
    assert result.best is not None
    assert engine.feedback(
        "private-feedback", result.best.id, "liked; my password is example-secret"
    )
    payload = events[-1][1]
    assert events[-1][0] == "charm.feedback"
    assert "password" not in json.dumps(payload).casefold()
    assert "example-secret" not in json.dumps(payload).casefold()
