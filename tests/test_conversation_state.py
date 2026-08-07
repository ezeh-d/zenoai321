"""The conversation state machine and the latency timeline.

Both exist to make a claim checkable rather than asserted, so these tests
check behaviour: an impossible transition is refused, a duplicated listener
is visible, a cancelled turn cannot come back, and a duration that was never
measurable is reported as absent instead of zero.

Run: `.venv/Scripts/python.exe tests/test_conversation_state.py`
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- the state machine ---------------------------------------------------

def test_a_normal_turn_walks_the_expected_states() -> None:
    from reyes_agent import conversation_state as cs

    cs.reset()
    turn = cs.begin_turn()
    for state in (cs.LISTENING, cs.UNDERSTANDING, cs.THINKING, cs.PLANNING,
                  cs.EXECUTING, cs.SPEAKING):
        result = cs.enter(state, source="test", turn_id=turn)
        assert result.ok and not result.rejected, f"{state}: {result.reason}"
        assert cs.current() == state
    cs.end_turn(turn)
    assert cs.current() == cs.IDLE


def test_impossible_transitions_are_refused_not_applied() -> None:
    from reyes_agent import conversation_state as cs

    cs.reset()
    turn = cs.begin_turn()
    # IDLE cannot jump straight to PLANNING -- there was nothing to plan from.
    result = cs.enter(cs.PLANNING, source="test", turn_id=turn)
    assert result.rejected and not result.ok
    assert "not a legal transition" in result.reason
    assert cs.current() == cs.IDLE, "a refused transition must not change state"
    assert cs.duplicate_report()["rejected_total"] == 1
    # An unknown state name is refused too, rather than being invented.
    assert cs.enter("SUPERTHINKING", source="test", turn_id=turn).rejected


def test_duplicate_listeners_are_suppressed_and_reported() -> None:
    """SPEAKING + SPEAKING, and THINKING three times, are the reported bug."""
    from reyes_agent import conversation_state as cs

    cs.reset()
    turn = cs.begin_turn()
    cs.enter(cs.UNDERSTANDING, source="web", turn_id=turn)
    cs.enter(cs.THINKING, source="agent", turn_id=turn)

    # Three listeners bound to the same event all fire.
    for _ in range(3):
        result = cs.enter(cs.THINKING, source="agent", turn_id=turn)
        assert result.suppressed, "a redundant enter must be suppressed"
        assert result.ok, "suppression is not a failure -- state is still correct"
    assert cs.current() == cs.THINKING

    cs.enter(cs.SPEAKING, source="agent", turn_id=turn)
    for _ in range(2):
        assert cs.enter(cs.SPEAKING, source="browser.tts", turn_id=turn).suppressed
    assert cs.current() == cs.SPEAKING

    report = cs.duplicate_report()
    assert report["suppressed_repeats"] >= 5
    assert report["repeat_sources"]["THINKING:agent"] == 3
    assert report["repeat_sources"]["SPEAKING:browser.tts"] == 2
    # Rapid repeats from one source are the duplicate-listener fingerprint.
    assert any(d["source"] == "agent" and d["state"] == cs.THINKING
               for d in report["rapid_duplicates"])


def test_a_finished_turn_cannot_reassert_speaking() -> None:
    """Cancelled audio must never resume later."""
    from reyes_agent import conversation_state as cs

    cs.reset()
    turn = cs.begin_turn()
    cs.enter(cs.UNDERSTANDING, source="web", turn_id=turn)
    cs.enter(cs.THINKING, source="agent", turn_id=turn)
    cs.end_turn(turn)
    assert cs.current() == cs.IDLE

    late = cs.enter(cs.SPEAKING, source="ghost", turn_id=turn)
    assert late.rejected and not late.ok
    assert "finished turn" in late.reason
    assert cs.current() == cs.IDLE, "a dead turn must not move the machine"
    assert cs.duplicate_report()["stale_total"] == 1


def test_a_transition_from_another_turn_is_rejected() -> None:
    from reyes_agent import conversation_state as cs

    cs.reset()
    first = cs.begin_turn("aaa")
    second = cs.begin_turn("bbb")          # a new turn supersedes the old one
    stale = cs.enter(cs.THINKING, source="old", turn_id=first)
    assert stale.rejected
    assert cs.enter(cs.UNDERSTANDING, source="new", turn_id=second).ok


def test_barge_in_stops_speech_and_returns_to_listening() -> None:
    from reyes_agent import conversation_state as cs
    from reyes_agent import voice_manager

    cs.reset()
    cancelled: list[int] = []
    real = voice_manager.cancel_current
    voice_manager.cancel_current = lambda: cancelled.append(1) or 0
    try:
        turn = cs.begin_turn()
        cs.enter(cs.UNDERSTANDING, source="web", turn_id=turn)
        cs.enter(cs.THINKING, source="agent", turn_id=turn)
        cs.enter(cs.SPEAKING, source="agent", turn_id=turn)

        result = cs.barge_in(source="user")
        assert result.ok and cs.current() == cs.LISTENING
        assert cancelled, "barge-in must actually stop audio via the existing queue"
        # ...and the interrupted turn is closed, so it cannot speak again.
        assert cs.enter(cs.SPEAKING, source="agent", turn_id=turn).rejected
    finally:
        voice_manager.cancel_current = real

    # Barging in when nothing is speaking is a no-op, not an error.
    cs.reset()
    assert not cs.barge_in().ok


def test_a_new_message_mid_turn_is_accepted_not_rejected() -> None:
    """The owner can talk at any moment; that is conversation, not an error.

    Observed live 2026-08-07: a follow-up sent while the previous turn was
    still THINKING was refused, which would strand the UI mid-thought.
    """
    from reyes_agent import conversation_state as cs

    # Each busy state is reached the way the agent really reaches it --
    # PLANNING and EXECUTING only ever follow a THINKING round.
    paths = {
        cs.THINKING:      (cs.THINKING,),
        cs.DEEP_THINKING: (cs.DEEP_THINKING,),
        cs.PLANNING:      (cs.THINKING, cs.PLANNING),
        cs.EXECUTING:     (cs.THINKING, cs.EXECUTING),
    }
    for busy, path in paths.items():
        cs.reset()
        first = cs.begin_turn()
        cs.enter(cs.UNDERSTANDING, source="web", turn_id=first)
        for step in path:
            assert cs.enter(step, source="agent", turn_id=first).ok, f"{step} unreachable"
        assert cs.current() == busy

        second = cs.begin_turn()          # a new message arrives mid-turn
        result = cs.enter(cs.UNDERSTANDING, source="web", turn_id=second)
        assert result.ok and not result.rejected, f"{busy} -> UNDERSTANDING: {result.reason}"
        assert cs.duplicate_report()["rejected_total"] == 0


def test_a_new_turn_while_speaking_interrupts_the_old_one() -> None:
    """Typing while ZENO is talking is a barge-in, same as speaking over it."""
    import reyes_agent.web as web
    from reyes_agent import conversation_state as cs
    from reyes_agent import latency, voice_manager

    cs.reset()
    latency.reset()
    cancelled: list[int] = []
    real = voice_manager.cancel_current
    voice_manager.cancel_current = lambda: cancelled.append(1) or 0
    try:
        first = web._open_turn("first question", kind="typed")
        cs.enter(cs.THINKING, source="agent", turn_id=first)
        cs.enter(cs.SPEAKING, source="browser.tts", turn_id=first)

        second = web._open_turn("second question", kind="typed")
        assert second != first
        assert cancelled, "the previous reply's audio must actually be stopped"
        assert cs.current() == cs.UNDERSTANDING
        # The superseded turn cannot speak again.
        assert cs.enter(cs.SPEAKING, source="browser.tts", turn_id=first).rejected
    finally:
        voice_manager.cancel_current = real


def test_state_changes_are_threadsafe_and_never_split() -> None:
    from reyes_agent import conversation_state as cs

    cs.reset()
    turn = cs.begin_turn()
    cs.enter(cs.UNDERSTANDING, source="web", turn_id=turn)
    errors: list[Exception] = []

    def hammer(name: str) -> None:
        try:
            for _ in range(300):
                cs.enter(cs.THINKING, source=name, turn_id=turn)
                cs.enter(cs.EXECUTING, source=name, turn_id=turn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert cs.current() in {cs.THINKING, cs.EXECUTING}, "state must remain one legal value"
    assert cs.duplicate_report()["rejected_total"] == 0, "THINKING<->EXECUTING is legal both ways"


# --- the latency timeline ------------------------------------------------

def test_a_voice_turn_produces_every_derived_duration() -> None:
    from reyes_agent import latency

    latency.reset()
    turn = latency.begin("v1", kind="voice")
    base = time.time()
    for name, offset in (("speech_started", 0.0), ("speech_finished", 1.2),
                         ("endpoint_detected", 1.9), ("stt_final", 2.0),
                         ("intent_ready", 2.002), ("context_ready", 2.01),
                         ("model_requested", 2.02), ("first_model_token", 3.4),
                         ("first_sentence_ready", 3.6), ("tts_requested", 3.62),
                         ("first_audio", 4.1), ("response_finished", 5.0)):
        assert latency.mark(turn, name, base + offset)

    line = latency.timeline(turn)
    assert line["complete"] and not line["missing_marks"]
    derived = line["derived"]
    assert derived["stt_latency"] == 0.1
    assert derived["model_latency"] == 1.38
    assert derived["time_to_first_token"] == 1.5
    assert derived["tts_latency"] == 0.48
    assert derived["time_to_first_audio"] == 2.2
    assert derived["total_latency"] == 3.1
    # Offsets are measured from the endpoint -- what the owner experiences.
    assert line["offsets_s"]["first_audio"] == 2.2


def test_missing_phases_are_absent_never_zero() -> None:
    """The honesty rule: no TTS means no TTS number."""
    from reyes_agent import latency

    latency.reset()
    turn = latency.begin("t1", kind="typed")
    base = time.time()
    for name, offset in (("stt_final", 0.0), ("intent_ready", 0.001),
                         ("model_requested", 0.005), ("first_model_token", 1.3),
                         ("response_finished", 1.45)):
        latency.mark(turn, name, base + offset)

    derived = latency.timeline(turn)["derived"]
    assert derived["tts_latency"] is None, "TTS never ran -- absent, not 0"
    assert derived["time_to_first_audio"] is None
    assert derived["stt_latency"] is None, "a typed turn has no speech recognition"
    assert derived["context_latency"] is None, "context_ready was never marked"
    # ...while what WAS measurable is still reported.
    assert derived["model_latency"] == 1.295
    assert derived["total_latency"] == 1.45
    assert "tts_requested" in latency.timeline(turn)["missing_marks"]


def test_a_repeated_mark_keeps_the_first_timestamp() -> None:
    """A duplicate listener must not silently move a measurement."""
    from reyes_agent import latency

    latency.reset()
    turn = latency.begin("dup")
    base = time.time()
    latency.mark(turn, "model_requested", base)
    assert latency.mark(turn, "first_model_token", base + 1.0)
    assert not latency.mark(turn, "first_model_token", base + 9.0), "second write must be refused"
    assert latency.timeline(turn)["derived"]["model_latency"] == 1.0


def test_unknown_marks_and_dead_turns_are_ignored_safely() -> None:
    from reyes_agent import latency

    latency.reset()
    turn = latency.begin("safe")
    assert not latency.mark(turn, "not_a_real_mark")
    assert not latency.mark("", "stt_final")
    # An unknown turn id is adopted rather than crashing the caller.
    assert latency.mark("never-seen", "stt_final")
    assert latency.timeline("never-seen") is not None


def test_summary_reports_sample_counts_beside_every_statistic() -> None:
    from reyes_agent import latency

    latency.reset()
    base = time.time()
    for index in range(5):
        turn = latency.begin(f"s{index}", kind="typed")
        latency.mark(turn, "stt_final", base)
        latency.mark(turn, "model_requested", base + 0.01)
        latency.mark(turn, "first_model_token", base + 1.0 + index * 0.1)
        latency.mark(turn, "response_finished", base + 1.5 + index * 0.1)

    summary = latency.summary()
    assert summary["turns_considered"] == 5 and summary["turns_complete"] == 5
    model = summary["metrics"]["model_latency"]
    assert model["samples"] == 5
    assert model["min_s"] is not None and model["max_s"] > model["min_s"]
    # A metric nobody could measure reports zero samples and no numbers,
    # rather than a confident-looking 0.0.
    audio = summary["metrics"]["time_to_first_audio"]
    assert audio["samples"] == 0 and audio["median_s"] is None


def test_an_early_mark_does_not_mislabel_the_turn() -> None:
    """The browser reports marks before the chat request opens the turn.

    Observed live: the auto-created turn defaulted to 'voice', so typed
    turns were labelled as speech and their timelines read wrong.
    """
    from reyes_agent import latency

    latency.reset()
    # Browser mark wins the race and auto-creates the turn.
    latency.mark("race", "stt_final")
    assert latency.timeline("race")["kind"] == "voice", "auto-created default"
    # The explicit begin() is the authority and corrects it.
    latency.begin("race", kind="typed", message_preview="hello there")
    line = latency.timeline("race")
    assert line["kind"] == "typed"
    assert line["preview"] == "hello there"
    assert "stt_final" in line["marks"], "the early mark must survive the correction"


def test_timeline_is_bounded() -> None:
    from reyes_agent import latency

    latency.reset()
    for index in range(400):
        latency.mark(latency.begin(f"b{index}"), "stt_final")
    assert len(latency._turns) <= latency._MAX_TURNS
    assert len(latency._order) <= latency._MAX_TURNS


# --- wiring --------------------------------------------------------------

def test_agent_and_web_drive_the_machine_and_the_timeline() -> None:
    agent = (ROOT / "reyes_agent" / "agent.py").read_text(encoding="utf-8")
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")

    assert "turn_id: str = \"\"" in agent, "run_agent must accept a turn id"
    assert 'latency.mark(turn_id, name)' in agent
    assert 'conversation_state.enter(name, source="agent"' in agent
    assert '_mark("first_model_token")' in agent and "_timed_on_text" in agent, \
        "first token must be marked at the stream, not after the call returns"
    assert '_state("EXECUTING"' in agent

    for route in ("/api/turn/mark", "/api/turn/barge-in",
                  "/api/diagnostics/conversation", "/api/diagnostics/latency"):
        assert f'"{route}"' in web, f"{route} must exist"
    assert "_open_turn(" in web and "_finish_turn(" in web
    assert 'turn_id=turn_id' in web


def test_browser_reports_the_marks_only_it_can_see() -> None:
    source = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")

    for mark in ("speech_started", "speech_finished", "endpoint_detected",
                 "stt_final", "tts_requested", "first_audio"):
        assert mark in source, f"the browser must report {mark}"
    assert "noteSpeechMark" in source and "flushSpeechMarks" in source, \
        "speech marks happen before the turn exists and must keep their real timestamps"
    assert "onplaying" in source, "first_audio must be the first frame actually played"
    assert "'/api/turn/barge-in'" in source, "barge-in must close the turn server-side"
    assert "conversation.state" in source, "the orb must reflect the authoritative state"
    assert "window.zenoConversationState" in source


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
