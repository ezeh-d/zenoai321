"""Regression checks for the dashboard's one-owner microphone controller.

These are intentionally browser-independent: WebView2 permission/capture is
an integration concern, while the races fixed here are deterministic source
and lifecycle contracts.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")


def test_mic_control_is_a_real_accessible_button() -> None:
    assert '<button id="mic-indicator" type="button"' in SOURCE
    assert 'aria-label="Start listening"' in SOURCE
    assert "micIndicator.addEventListener('click'" in SOURCE


def test_startup_has_one_inflight_owner_and_stop_invalidates_it() -> None:
    active = SOURCE.split("function startAmbientListening(options = {})", 1)[1].split("// Auto-start", 1)[0]
    assert "let micStartPromise = null, micSessionGeneration = 0, micWanted = false;" in SOURCE
    assert "if (micStartPromise) return micStartPromise;" in active
    assert "generation !== micSessionGeneration || !micWanted" in active
    assert "micSessionGeneration += 1;" in active
    assert "if (ambientEnabled || micStartPromise) stopAmbientListening();" in active


def test_listening_is_not_announced_before_a_live_stream_exists() -> None:
    active = SOURCE.split("async function openAmbientListening", 1)[1].split("function stopAmbientListening", 1)[0]
    assert "compactMicStatus('MIC OFF', 'opening microphone');" in active
    assert "const capabilities = await voiceVAD.start" in active
    assert active.index("const capabilities = await voiceVAD.start") < active.index("ambientEnabled = true;")
    assert "compactMicStatus('LISTENING'" in active


def test_voice_turn_waits_for_tts_and_exposes_true_states() -> None:
    assert "await speakInBrowser(fullReply);" in SOURCE
    assert "compactMicStatus('HEARING SPEECH'" in SOURCE
    assert "compactMicStatus('TRANSCRIBING'" in SOURCE
    assert "compactMicStatus('THINKING'" in SOURCE
    assert "compactMicStatus('SPEAKING'" in SOURCE
    assert "compactMicStatus('LISTENING'" in SOURCE


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 -- standalone test runner
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
