"""Regression tests for the Panel Request API (master prompt s62-80):
agents request a workspace through the one authoritative Panel Manager
instead of inventing their own window, ownership is tracked so a leaving
agent's panels are cleaned up, and identity is inferred from the call
stack rather than trusted from a model-supplied parameter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clean_state():
    from reyes_agent import agent_presence, panels

    agent_presence.reset_for_tests()
    panels.reset_ownership_for_tests()
    yield
    agent_presence.reset_for_tests()
    panels.reset_ownership_for_tests()


class TestRequestPanel:
    def test_an_unregistered_panel_is_refused_not_silently_ignored(self):
        from reyes_agent import panels

        result = panels.request_panel("kate", "not_a_real_panel")
        assert result["granted"] is False
        assert "not_a_real_panel" in result["reason"]

    def test_a_registered_panel_is_granted_and_tracked(self):
        from reyes_agent import panels

        result = panels.request_panel("kate", "files", reason="showing the lesson notes")
        assert result["granted"] is True
        assert panels.owner_of("files") == "kate"

    def test_events_published_carry_the_real_agent_and_reason(self):
        from reyes_agent import event_bus, panels

        feed = event_bus.subscribe()
        try:
            panels.request_panel("hunter_x", "work", reason="tracking the analysis task")
            event = feed.get(timeout=1)
        finally:
            event_bus.unsubscribe(feed)
        assert event.type == "panel.requested"
        assert event.payload["agent"] == "hunter_x"
        assert event.payload["panel"] == "work"
        assert event.payload["reason"] == "tracking the analysis task"

    def test_agent_id_and_panel_type_are_normalized(self):
        from reyes_agent import panels

        result = panels.request_panel("  KATE  ", "  Files  ")
        assert result["granted"] is True
        assert result["agent"] == "kate"
        assert result["panel"] == "files"


class TestReleaseOnDismissal:
    def test_dismissing_an_agent_releases_only_its_own_panels(self):
        from reyes_agent import panels

        panels.request_panel("kate", "files")
        panels.request_panel("hunter_x", "work")
        released = panels.release_panels_for("kate")
        assert released == ["files"]
        assert panels.owner_of("files") == ""
        assert panels.owner_of("work") == "hunter_x"  # untouched

    def test_dismissing_kate_through_agent_presence_releases_her_panels(self):
        """Integration: agent_presence.dismiss() -- the real path a "Kate,
        you can go" command takes -- actually calls panels.release_panels_for,
        not a parallel/duplicate cleanup mechanism."""
        from reyes_agent import agent_presence, panels

        agent_presence.handle_command("Call Kate.")
        panels.request_panel("kate", "files", reason="lesson notes")
        assert panels.owner_of("files") == "kate"

        agent_presence.handle_command("Kate, you can go.")
        assert panels.owner_of("files") == ""

    def test_releasing_an_agent_with_no_panels_is_a_safe_no_op(self):
        from reyes_agent import panels

        assert panels.release_panels_for("nobody_home") == []


class TestRequestPanelToolIdentity:
    def test_zeno_is_the_default_agent_outside_a_specialist_call(self):
        from reyes_agent.tools.panel_tools import request_panel as request_panel_tool
        from reyes_agent import panels

        result = request_panel_tool("files", "checking a document")
        assert "Files" in result
        assert panels.owner_of("files") == "zeno"

    def test_identity_comes_from_the_call_stack_not_a_spoofable_argument(self, monkeypatch):
        """request_panel's tool signature has no agent_id parameter at all --
        this proves the identity genuinely comes from _active_specialist(),
        not something a model could pass as an argument to impersonate
        another agent."""
        import inspect

        from reyes_agent.tools.panel_tools import request_panel as request_panel_tool

        assert "agent_id" not in inspect.signature(request_panel_tool).parameters

        from reyes_agent.tools import subagents

        monkeypatch.setattr(subagents, "_active_specialist", lambda: "kate")
        from reyes_agent import panels

        result = request_panel_tool("browser", "researching")
        assert panels.owner_of("browser") == "kate"
        assert "Browser" in result

    def test_kate_can_use_the_tool_and_hunter_x_can_too(self):
        from reyes_agent.tools import subagents

        assert "request_panel" in subagents._SPECIALISTS["kate"]["tools"]
        assert "request_panel" in subagents._SPECIALISTS["hunter_x"]["tools"]


class TestPanelManagerFrontendWiring:
    def test_manager_js_routes_panel_requested_and_release_events(self):
        """The event names this module publishes must match what
        panels/manager.js actually listens for -- a silent rename on either
        side would leave the Panel Request API doing nothing visible."""
        source = (ROOT / "reyes_agent" / "static" / "panels" / "manager.js").read_text(encoding="utf-8")
        assert '"panel.requested"' in source
        assert '"panel.release_for_agent"' in source


def _run_all() -> int:
    import inspect

    failures = 0
    total = 0
    for name, cls in sorted(globals().items()):
        if not (isinstance(cls, type) and name.startswith("Test")):
            continue
        instance = cls()
        for method_name, method in inspect.getmembers(instance, predicate=inspect.ismethod):
            if not method_name.startswith("test_"):
                continue
            total += 1
            try:
                if "monkeypatch" in inspect.signature(method).parameters:
                    print(f"SKIP {name}.{method_name} (needs pytest monkeypatch fixture)")
                    continue
                from reyes_agent import agent_presence, panels
                agent_presence.reset_for_tests()
                panels.reset_ownership_for_tests()
                method()
                print(f"PASS {name}.{method_name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}.{method_name}: {type(exc).__name__}: {exc}")
    print(f"{total - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
