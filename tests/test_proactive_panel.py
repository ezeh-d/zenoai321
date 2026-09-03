from pathlib import Path


def test_proactive_panel_is_registered_in_both_shared_panel_catalogues() -> None:
    from reyes_agent import panels
    from reyes_agent.workspace.defaults import default_panel_registry

    definition = default_panel_registry().get("proactive")
    assert definition is not None
    assert definition.component == "module:/static/proactive_view.js#createProactiveView"
    assert definition.singleton is True
    assert panels.PANELS["proactive"]["persistent"] is True


def test_proactive_panel_uses_real_status_and_notice_endpoints() -> None:
    source = Path("reyes_agent/static/proactive_view.js").read_text(encoding="utf-8")
    assert "/api/proactive/status" in source
    assert "/api/notices" in source
