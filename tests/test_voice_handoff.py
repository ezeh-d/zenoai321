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


def test_vad_retries_only_the_unsupported_optional_constraint() -> None:
    vad = (ROOT / "reyes_agent" / "static" / "vad.js").read_text(encoding="utf-8")
    assert 'err && err.name === "OverconstrainedError"' in vad
    assert "channelCount: 1" in vad
    assert "audio: {\n            noiseSuppression: true" in vad
    assert "NotAllowedError" not in vad  # Errors stay observable to microphone.py.


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
