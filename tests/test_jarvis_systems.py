"""Regression coverage for the on-demand JARVIS systems component."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_jarvis_is_one_real_lazy_specialist() -> None:
    from reyes_agent import agent_runtime
    from reyes_agent.tools.subagents import _SPECIALISTS

    assert agent_runtime.AGENT_ROLES["jarvis"] == "Systems Integration Director"
    spec = _SPECIALISTS["jarvis"]
    assert "evidence" in spec["prompt"].lower()
    assert "permission" in spec["prompt"].lower()
    assert {"system_health", "current_situation", "browser_open"} <= spec["tools"]


def test_jarvis_workers_are_bounded_and_cannot_escalate() -> None:
    from reyes_agent import agent_teams
    from reyes_agent.tools.subagents import _SPECIALISTS

    workers = agent_teams.workers_for("jarvis")
    assert {worker.name for worker in workers} == {"telemetry", "conduit", "flightdeck"}
    parent_tools = set(_SPECIALISTS["jarvis"]["tools"])
    assert all(worker.tools <= parent_tools for worker in workers)
    assert len(workers) <= agent_teams.MAX_WORKERS_PER_TASK


def test_jarvis_has_a_safe_configurable_voice_profile() -> None:
    from reyes_agent import voice_manager

    profile = voice_manager.get_profile("jarvis")
    assert profile.agent == "jarvis"
    assert "original" in profile.description.lower()
    assert 0.0 <= profile.stability <= 1.0
    assert 0.0 <= profile.similarity <= 1.0


def test_hud_is_lazy_live_and_fully_disposable() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    hud = (ROOT / "reyes_agent" / "static" / "jarvis_hud.js").read_text(encoding="utf-8")

    assert "import('/static/jarvis_hud.js?v=1')" in dashboard
    assert "JARVIS Systems HUD" in dashboard
    assert '<script src="/static/jarvis_hud.js' not in dashboard
    assert 'fetch("/api/situation"' in hud
    assert 'new EventSource("/api/events/stream")' in hud
    assert "setInterval" in hud and "clearInterval" in hud
    assert "current.source.close()" in hud
    assert "current.ui.overlay.remove()" in hud
    assert "WebGL" not in hud
    assert "requestAnimationFrame" not in hud
    assert "Math.random" not in hud


def test_hud_never_claims_fictional_or_unmeasured_status() -> None:
    hud = (ROOT / "reyes_agent" / "static" / "jarvis_hud.js").read_text(encoding="utf-8")
    specialist = (ROOT / "reyes_agent" / "tools" / "subagents.py").read_text(encoding="utf-8")

    assert "no agent activity is being implied" in hud
    assert "LIVE EVIDENCE" in hud
    assert "fictional suit hardware" in specialist
    assert "UNKNOWN" in hud


def test_jarvis_identity_reaches_dashboard_and_mini_presence() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    presence = (ROOT / "reyes_agent" / "static" / "agent_presence.js").read_text(encoding="utf-8")

    assert "jarvis:" in dashboard and "Systems Integration Intelligence" in dashboard
    assert 'jarvis:' in presence and 'role: "Systems Integration"' in presence


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
