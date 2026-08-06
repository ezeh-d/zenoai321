"""Regression coverage for the three re-enabled optional features."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import performance_features


def test_feature_preferences_persist_with_safe_defaults() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(performance_features, "_SETTINGS_PATH", Path(temp_dir) / "features.json"):
            settings = performance_features.save_settings(
                dream_mode=False, dashboard_updates=True, cursor_eye_tracking=True,
                eye_tracking_fps="15", performance_mode="low_power", dream_idle_only=False,
            )
            loaded = performance_features.load_settings()
    assert settings.dream_idle_only is True
    assert loaded.eye_tracking_fps == "15"
    assert loaded.performance_mode == "low_power"
    assert loaded.dream_mode is False


def test_load_guard_pauses_optional_work_when_core_is_busy() -> None:
    assert performance_features.under_load({"cpu": 20, "ram": 40, "active_workers": 0, "queue_depth": 0}) is False
    assert performance_features.under_load({"cpu": 76, "ram": 40, "active_workers": 0, "queue_depth": 0}) is True
    assert performance_features.under_load({"cpu": 20, "ram": 40, "active_workers": 1, "queue_depth": 0}) is False
    assert performance_features.under_load({"cpu": 20, "ram": 40, "active_workers": 2, "queue_depth": 0}) is True


def test_dream_mode_has_no_automatic_embedding_reindex_and_can_interrupt() -> None:
    source = (ROOT / "reyes_agent" / "dream_mode.py").read_text(encoding="utf-8")
    upkeep = source[source.index("def _pass_knowledge_upkeep"):source.index("_PASSES =")]
    assert "reindex_vault()" not in upkeep
    assert "should_continue" in source and "rep.interrupted = True" in source


def test_dashboard_and_orb_use_existing_bounded_schedulers() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    orb = (ROOT / "reyes_agent" / "static" / "orb.js").read_text(encoding="utf-8")
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    assert "scheduleStatusRefresh" in dashboard and "hidden ? 5000 : 2000" in dashboard
    assert "featureSettings.dashboard_updates" in dashboard
    assert "setEyeTracking" in orb and "setTimeout(applyCursorEyes" in orb
    assert "currentEyes !== \"closed\"" in orb and "pointermove" in orb
    assert "performance.features_changed" in dashboard and "performance.features_changed" in mini


def test_api_and_proactive_use_existing_scheduler_path() -> None:
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    proactive = (ROOT / "reyes_agent" / "proactive.py").read_text(encoding="utf-8")
    assert '"/api/performance-features/settings"' in web
    assert "performance_features.under_load" in proactive
    assert "DREAM_MODE_RUNNING" in proactive and "DREAM_MODE_PAUSED" in proactive


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
