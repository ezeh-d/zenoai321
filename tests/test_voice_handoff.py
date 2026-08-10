"""Regression guardrails for the persistent Mini Orb microphone handoff."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_miniorb_reacquires_after_dashboard_hides_and_keeps_persistent_profile() -> None:
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    desktop = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert "desktop.dashboard_hidden" in mini
    assert "setTimeout(()=>{if(!wakeActive)void startWakeListener();},700)" in mini
    assert "wakeRecoveryAttempts<2" in mini
    assert "capabilities.error==='NotReadableError'" in mini
    assert "desktop.dashboard_opened" in desktop
    assert "private_mode=False, storage_path=str(_WEBVIEW_STORAGE)" in desktop
    assert "type === 'desktop.dashboard_hidden' && ambientEnabled" in dashboard


def test_miniorb_executes_a_wake_word_command_without_showing_the_dashboard() -> None:
    """The Mini Orb is the normal voice surface, not just a dashboard opener."""
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    assert "function miniWakeCommand(transcript)" in mini
    assert "fetch('/api/chat'" in mini
    assert "fetch('/api/tts'" in mini
    assert "voiceVAD.pauseDetection()" in mini
    assert "await runMiniCommand(command,data)" in mini
    # The old behavior discarded the command by doing only this after STT.
    assert "test(String(data.transcript||'')))openDashboard()" not in mini


def test_vad_retries_only_the_unsupported_optional_constraint() -> None:
    vad = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    assert 'err && err.name === "OverconstrainedError"' in vad
    assert "channelCount: 1" in vad
    assert "audio: {\n            noiseSuppression: true" in vad
    assert "NotAllowedError" not in vad  # Errors stay observable to microphone.py.


def test_plain_browser_cannot_compete_for_the_desktop_microphone() -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException
    from reyes_agent import web

    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    desktop = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    assert "ZENO_DESKTOP_MIC_TOKEN" in desktop
    assert "X-Zeno-Mic-Token" in mini and "X-Zeno-Mic-Token" in dashboard
    assert "listening stays with the native Mini Orb" in dashboard

    original = web._DESKTOP_MIC_TOKEN
    web._DESKTOP_MIC_TOKEN = "native-only"
    try:
        try:
            web._require_desktop_mic_token(SimpleNamespace(headers={}))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("an unowned browser microphone must be refused")
        web._require_desktop_mic_token(
            SimpleNamespace(headers={"X-Zeno-Mic-Token": "native-only"})
        )
    finally:
        web._DESKTOP_MIC_TOKEN = original


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
