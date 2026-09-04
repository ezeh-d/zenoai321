"""Contract checks for the disposable Ragebait battle panel."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ragebait_panel_is_live_but_not_persistent() -> None:
    from reyes_agent import panels

    panel = panels.registry()["panels"]["ragebait"]
    assert panel["support"] == "live"
    assert panel["persistent"] is False
    assert panel["kind"] == "ragebait"


def test_ragebait_panel_renderer_is_event_driven_and_disposable() -> None:
    renderers = (ROOT / "reyes_agent" / "static" / "panels" / "renderers.js").read_text(encoding="utf-8")
    manager = (ROOT / "reyes_agent" / "static" / "panels" / "manager.js").read_text(encoding="utf-8")
    assert "ragebait:" in renderers
    assert "ragebait.battle_started" in manager
    assert "ragebait.battle_finished" in manager
    ragebait_source = renderers[renderers.index("ragebait:"):]
    assert "setInterval(" not in ragebait_source
