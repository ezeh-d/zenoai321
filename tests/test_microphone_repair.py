"""Offline guardrails for ZENO's evidence-based microphone repair path."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import microphone


_ALLOWED = {"readable": True, "user_global": "Allow", "machine_global": "Allow", "desktop_apps": "Allow"}
_DEVICE = {"available": True, "input_count": 1, "inputs": ["Built-in microphone"], "default": "Built-in microphone"}
_STT = {"deepgram_key": True, "model": "nova-3"}


def _diagnose(**kwargs):
    with patch.object(microphone, "_read_windows_consent", return_value=_ALLOWED), \
         patch.object(microphone, "_enumerate_devices", return_value=_DEVICE), \
         patch.object(microphone, "_stt_configured", return_value=_STT):
        return microphone.diagnose(**kwargs)


def test_windows_denial_wins_over_browser_error() -> None:
    denied = dict(_ALLOWED, user_global="Deny")
    with patch.object(microphone, "_read_windows_consent", return_value=denied), \
         patch.object(microphone, "_enumerate_devices", return_value=_DEVICE), \
         patch.object(microphone, "_stt_configured", return_value=_STT):
        report = microphone.diagnose("NotAllowedError")
    assert report.cause == microphone.WINDOWS_PERMISSION_DENIED


def test_webview2_denial_is_not_misreported_as_windows_denial() -> None:
    report = _diagnose(browser_error="NotAllowedError")
    assert report.cause == microphone.WEBVIEW2_PERMISSION_DENIED
    assert "Windows allows" in report.summary


def test_device_busy_and_missing_selected_device_have_distinct_states() -> None:
    assert _diagnose(browser_error="NotReadableError").cause == microphone.MICROPHONE_BUSY
    assert _diagnose(browser_error="NotFoundError", selected_device="old-headset").cause == microphone.MICROPHONE_DISABLED


def test_unasked_grant_and_runtime_capture_evidence_are_explicit() -> None:
    assert _diagnose(permission_state="prompt").cause == microphone.MIC_PERMISSION_NOT_REQUESTED
    microphone.report_runtime(microphone.MICROPHONE_READY, detail="audio", audio_received=True)
    assert microphone.runtime_status()["audio_received"] is True
    report = _diagnose()
    assert report.cause == microphone.MICROPHONE_READY


def test_frontend_uses_selected_device_meter_and_bounded_recovery() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    vad = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    assert "Enable microphone" in dashboard
    assert "mic-device-select" in dashboard and "mic-level-bar" in dashboard
    assert "voiceVAD.start({ deviceId: selectedMicrophoneId() })" in dashboard
    assert "voiceVAD.onLevel(noteMicLevel)" in dashboard
    assert "micRecoveryAttempts >= 2" in dashboard
    assert "voiceVAD.start({deviceId:selectedMicrophoneId()})" in mini
    assert "voiceVAD.onCaptureStopped" in mini
    assert "used_fallback_device" in vad and "onCaptureStopped" in vad


def test_api_keeps_runtime_evidence_and_diagnostic_parameters() -> None:
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert '"/api/microphone/runtime"' in source
    assert '"/api/microphone/status"' in source
    assert "permission_state: str" in source and "selected_device: str" in source


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
