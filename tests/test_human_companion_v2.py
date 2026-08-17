"""Focused regressions for the Human Companion V2 realtime path.

These tests verify architecture and measured local behavior.  They do not
invent owner/impostor accuracy or conversational latency without real Divine
recordings and an interactive WebView2 session.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_shared_audio_manager_is_bounded_reusable_and_stops_cleanly() -> None:
    from reyes_agent.audio.manager import AudioManager

    manager = AudioManager(capacity=8)
    manager.unsubscribe("wake")
    entered = threading.Event()
    release = threading.Event()

    def slow_consumer(_frame) -> None:
        entered.set()
        release.wait(1.0)

    manager.subscribe("test", slow_consumer)
    assert manager.publish(b"\0\0" * 1_280)
    assert entered.wait(1.0)
    for _ in range(40):
        assert manager.publish(b"\0\0" * 1_280)
    status = manager.status()
    assert status["worker_count"] == 1
    assert status["queue_depth"] <= status["queue_capacity"] == 8
    assert status["dropped"] > 0
    assert status["opens_microphone"] is False
    release.set()
    manager.shutdown()
    assert manager.publish(b"\0\0" * 1_280) is False


def test_turn_detector_handles_finished_unfinished_wait_and_pidgin() -> None:
    from reyes_agent.voice.turn import detect

    assert detect("ZENO open Chrome.")["state"] == "FINISHED"
    assert detect("ZENO I want you to")["state"] == "UNFINISHED"
    assert detect("abeg wait first")["state"] == "WAIT"
    assert detect("abeg open my project")["state"] == "FINISHED"


def test_latency_summary_uses_real_marks_and_reports_p90() -> None:
    from reyes_agent import latency

    latency.reset()
    latency.record_wake_ack(detected_at=10.0, audio_started_at=10.2, phrase="I'm here.", source="test")
    latency.record_wake_ack(detected_at=20.0, audio_started_at=20.35, phrase="Yeah?", source="test")
    latency.record_barge_in(detected_at=30.0, audio_stopped_at=30.12, source="test")
    result = latency.summary()
    assert result["wake_ack"]["samples"] == 2
    assert result["wake_ack"]["p90_s"] is not None
    assert result["wake_ack"]["worst_s"] == 0.35
    assert result["barge_in"]["samples"] == 1
    assert result["barge_in"]["worst_s"] == 0.12
    latency.reset()


def test_wake_ack_route_is_strictly_cache_only() -> None:
    from reyes_agent import voice_manager, web

    original_dir = voice_manager._CACHE_DIR
    original_synthesize = voice_manager.synthesize
    with tempfile.TemporaryDirectory() as temp_dir:
        voice_manager._CACHE_DIR = Path(temp_dir)

        def forbidden_provider_call(*_args, **_kwargs):
            raise AssertionError("wake acknowledgement route called the TTS provider")

        voice_manager.synthesize = forbidden_provider_call
        try:
            response = web.cached_wake_ack()
            assert response.status_code == 204
            assert response.headers["X-Zeno-Ack-State"] == "CACHE_EMPTY"
        finally:
            voice_manager.synthesize = original_synthesize
            voice_manager._CACHE_DIR = original_dir


def test_repository_decisions_and_heavy_defaults_are_explicit() -> None:
    from reyes_agent.human_companion import FEATURE_FLAGS, REPOSITORIES

    assert len(REPOSITORIES) == 20
    assert len({row["repo"] for row in REPOSITORIES}) == 20
    assert {row["decision"] for row in REPOSITORIES} <= {
        "PRIMARY", "FALLBACK", "EXPERIMENTAL", "ARCHITECTURAL_REFERENCE", "REJECTED",
    }
    assert next(row for row in REPOSITORIES if row["repo"] == "modelscope/3D-Speaker")["decision"] == "PRIMARY"
    assert next(row for row in REPOSITORIES if row["repo"] == "TEN-framework/ten-turn-detection")["decision"] == "REJECTED"
    for name, default in FEATURE_FLAGS.items():
        if name not in {"ZENO_OWNER_VOICE_ENABLED", "ZENO_3DSPEAKER_ENABLED", "ZENO_WINDOWS_AEC_ENABLED"}:
            assert default is False


def test_stt_vocabulary_and_event_reporting_never_fake_streaming() -> None:
    from reyes_agent.voice.stt import status
    from reyes_agent.voice.vocabulary import terms

    values = terms()
    assert {"ZENO", "Divine", "Codex", "Claude", "Netlify", "OmniParser", "LiveKit"} <= set(values)
    stt = status()
    assert stt["actual_current_events"] == ["STT_FINAL"]
    assert "partial" in stt["honesty"].lower()


def test_language_context_needs_repeated_evidence_and_preserves_transcript() -> None:
    from reyes_agent.voice import language_context

    language_context.reset()
    first = language_context.observe("ZENO abeg open Chrome")
    assert first["current_language"] == "Nigerian English"
    assert first["transcript_changed"] is False
    language_context.observe("abeg wetin we dey do yesterday")
    third = language_context.observe("abeg wetin you dey think")
    assert third["current_language"] == "Nigerian Pidgin / mixed English"


def test_webviews_reuse_one_capture_and_consume_real_turn_state() -> None:
    vad = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    frame_client = (ROOT / "reyes_agent" / "static" / "audio_frames.js").read_text(encoding="utf-8")
    assert "onPcmFrame" in vad and "beginPcmCapture" in vad
    assert "navigator.mediaDevices.getUserMedia" not in frame_client
    assert "result.turn?.state" in dashboard
    assert "data.turn?.state" in mini
    assert "pending_text" in mini
    assert "runVoiceEnrollmentSequence" in dashboard
    assert "I don't recognize your voice. What's your name and surname?" in dashboard
    assert "createStreamingSpeech" in dashboard
    assert "speechFetchController.abort()" in dashboard


def test_model_status_does_not_rehash_the_model_on_every_poll() -> None:
    from reyes_agent.identity.speaker.embeddings import SherpaOnnx3DSpeakerBackend

    backend = SherpaOnnx3DSpeakerBackend()
    first = backend.status()
    if first["model_exists"]:
        cached = backend._checksum_cache
        assert cached is not None
        backend.status()
        assert backend._checksum_cache is cached


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
