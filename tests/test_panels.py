"""Universal Live Panel System -- backend registry + decision engine.

The PanelDecisionEngine maps ZENO's real tools/capabilities onto panels. These
lock the routing that the browser side depends on, and that conversational
actions surface NO panel.
"""

from __future__ import annotations

import pytest

from reyes_agent import panels as P


def test_registry_shape():
    reg = P.registry()
    assert set(reg) >= {"panels", "capability_panel", "tool_panel", "version"}
    assert "media" in reg["panels"] and "system" in reg["panels"]
    # every capability target and tool target names a real panel
    for target in reg["capability_panel"].values():
        assert target in reg["panels"], target
    for target in reg["tool_panel"].values():
        assert target in reg["panels"], target


@pytest.mark.parametrize("tool,panel", [
    ("media_command", "media"),
    ("run_command", "terminal"),
    ("read_file", "editor"),
    ("list_dir", "files"),
    ("browser_open", "browser"),
    ("web_search", "browser"),
    ("take_screenshot", "image"),
    ("system_health", "system"),
    ("convene_council", "agents"),
    ("live_news", "news"),
])
def test_tool_routes_to_expected_panel(tool, panel):
    assert P.decide(tool=tool)["panel"] == panel


def test_conversational_tool_has_no_panel():
    assert P.decide(tool="get_datetime")["panel"] is None


def test_unknown_tool_has_no_panel():
    assert P.decide(tool="totally_made_up_tool_xyz")["panel"] is None


@pytest.mark.parametrize("cap,panel", [
    ("media", "media"), ("files", "files"), ("coding", "editor"),
    ("agents", "agents"), ("council", "agents"), ("security", "security"),
    ("vision", "image"), ("web", "browser"), ("memory", "memory"),
])
def test_capability_fallback(cap, panel):
    assert P.decide(capability=cap)["panel"] == panel


def test_tool_wins_over_capability():
    # run_command's capability (desktop) maps to system, but the tool override
    # sends it to the terminal.
    assert P.decide(tool="run_command", capability="desktop")["panel"] == "terminal"


def test_every_panel_has_honest_support_level():
    for pid, d in P.PANELS.items():
        assert d["support"] in ("live", "state", "planned"), pid
