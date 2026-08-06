"""Regression coverage for ZENO's independent native Mini Orb overlay."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.desktop_app import _position_is_visible, _visible_or_default_position


def test_saved_position_keeps_a_visible_secondary_monitor_location() -> None:
    monitors = [(0, 0, 1920, 1040), (-1600, 0, 1600, 900)]
    assert _position_is_visible(-1500, 120, 210, 210, monitors)
    assert _visible_or_default_position(-1500, 120, 210, 210, monitors) == (-1500, 120)


def test_stale_position_is_recovered_to_a_visible_work_area() -> None:
    monitors = [(0, 0, 1920, 1040), (1920, 0, 1280, 1000)]
    x, y = _visible_or_default_position(9000, 9000, 210, 210, monitors)
    assert _position_is_visible(x, y, 210, 210, monitors)
    assert (x, y) == (1686, 806)


def test_overlay_is_native_topmost_and_never_uses_show_for_health_recovery() -> None:
    source = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    assert "on_top=True" in source
    assert "focus=False" in source
    assert "SetWindowPos" in source
    assert "SW_SHOWNOACTIVATE" in source
    assert "_OVERLAY_HEALTH_INTERVAL_S = 5.0" in source
    assert "self._overlay_repair.wait(_OVERLAY_HEALTH_INTERVAL_S)" in source
    assert ".on_top =" not in source


def test_dashboard_is_lazy_and_cannot_replace_the_mini_document() -> None:
    source = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    main = source[source.index("def main()") :]
    assert "url=_DASHBOARD_URL" not in main
    assert "_ensure_dashboard" in source
    assert "dashboard.events.closing += self._hide_dashboard_on_close" in source
    assert "mini.load_url(f\"{_URL}/mini\")" in source
    assert "self._window.load_url(_URL)" not in source


def test_mini_drag_uses_native_dpi_aware_bridge_and_all_required_states() -> None:
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    orb = (ROOT / "reyes_agent" / "static" / "orb.js").read_text(encoding="utf-8")
    assert "begin_orb_drag" in mini
    assert "move_orb_drag" in mini
    assert "end_orb_drag" in mini
    assert "localStorage.getItem('zeno_orb_pos')" not in mini
    for state in ("idle", "listening", "understanding", "thinking", "acting", "waiting", "success", "error"):
        assert f"{state}:" in orb


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
