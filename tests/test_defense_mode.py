"""Defense / presentation mode: activation, readiness, and the tool contract."""

from __future__ import annotations

import json

import pytest

from reyes_agent import defense_mode as dm


@pytest.fixture(autouse=True)
def _no_warm(monkeypatch):
    # Don't fire a real brain warm-up (model call) inside tests.
    monkeypatch.setattr(dm, "_warm_brain_async", lambda: None)
    yield
    dm.deactivate(source="test-cleanup")     # leave the flag off


def test_readiness_shape_and_never_raises():
    r = dm.readiness()
    assert isinstance(r["ready"], bool) and isinstance(r["checks"], dict)
    for key in ("tools", "mic", "stt", "tts", "local_ai", "cloud_ai", "memory", "agents"):
        assert key in r["checks"] and isinstance(r["checks"][key], str)


def test_activate_then_deactivate():
    res = dm.activate(source="test")
    assert res["ok"] and res["defense_mode"] is True
    assert dm.is_active() is True
    assert "readiness" in res
    off = dm.deactivate(source="test")
    assert off["defense_mode"] is False and dm.is_active() is False


def test_enters_presentation_conversation_mode():
    from reyes_agent.conversation import targets

    dm.activate()
    assert targets.current().mode == targets.PRESENTATION_MODE
    dm.deactivate()
    assert targets.current().mode == targets.OWNER_MODE


def test_tool_on_off_status_return_valid_json():
    import reyes_agent.tools.system  # noqa: F401 -- registers defense_tools
    from reyes_agent.tools import defense_tools

    on = json.loads(defense_tools.defense_mode("on"))
    assert on["defense_mode"] is True and "readiness" in on
    status = json.loads(defense_tools.defense_mode("status"))
    assert "readiness" in status and "defense_mode" in status
    off = json.loads(defense_tools.defense_mode("off"))
    assert off["defense_mode"] is False


def test_tool_is_registered_and_core():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS, tool_definitions

    assert "defense_mode" in TOOLS
    assert "defense_mode" in {t["name"] for t in tool_definitions(groups=set())}


def test_defense_command_routes():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.routing.capability import tools_for

    for phrase in ("defense mode", "presentation mode", "get ready for my defense"):
        assert "defense_mode" in tools_for(phrase).tools
