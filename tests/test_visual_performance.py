"""Offline regressions for ZENO's lightweight visual runtime."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "reyes_agent" / "static"


def test_orb_uses_one_bounded_canvas_particle_pool() -> None:
    source = (STATIC / "orb.js").read_text(encoding="utf-8")
    assert 'class="orb-particles"' in source
    assert "Array.from({ length: 40 }" in source
    assert "setInterval(" not in source
    # The one rAF is aligned to the compositor so hidden/minimized WebView2
    # windows stop producing frames; this is intentionally not a perpetual
    # JavaScript animation loop.
    assert "requestAnimationFrame(drawParticles)" in source
    # The permanent Mini Orb keeps particles visible but caps idle canvas
    # work at 4fps and meaningful active states at 20fps.
    assert 'const gap = lowMotion ? 250 : 50' in source
    assert "orb-motion" in source
    assert 'getContext("webgl")' not in source
    assert 'getContext("webgl2")' not in source


def test_dashboard_uses_event_stream_and_does_not_resume_camera() -> None:
    source = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "new EventSource('/api/events/stream')" in source
    assert "restorePersistedToggles" not in source
    assert "setInterval(refreshAgentMonitor" not in source
    assert "setInterval(refreshSituation" not in source
    assert "setMini(true);  // real work started" not in source


def test_startup_does_not_send_a_provider_warmup_or_refresh_on_heartbeats() -> None:
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    dashboard = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "warmup.start_background_keepalive()" not in web
    assert "type.startsWith('heartbeat.') || type.startsWith('notification.')" not in dashboard


def test_mini_orb_is_a_separate_lightweight_document() -> None:
    mini = (STATIC / "mini.html").read_text(encoding="utf-8")
    assert "/api/mini-status" in mini
    assert "/api/status" not in mini
    assert "agent-dashboard" not in mini
    assert "situation-overlay" not in mini
    assert "show_dashboard" in mini
    assert "snap_orb" in mini


def test_web_exposes_bounded_companion_status_and_event_stream() -> None:
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert '@app.get("/mini")' in source
    assert '@app.get("/api/mini-status")' in source
    assert '@app.get("/api/events/stream")' in source
    assert "event_bus.unsubscribe(subscriber)" in source


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
