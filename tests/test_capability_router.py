"""The router: fast, context-aware, and refuses to hand over sharp tools.

Measured before this existed: 105 schemas on every turn, and "what time is
it" took 10.05s. These tests exist so that cannot come back one well-meaning
addition at a time.
"""

from __future__ import annotations

import pytest

from reyes_agent.routing import capability as cap
from reyes_agent.tools import TOOLS


@pytest.fixture(autouse=True)
def _fresh():
    cap.clear_context()
    yield
    cap.clear_context()


class TestBudgetsHold:
    """The performance guard. These numbers are the whole point."""

    @pytest.mark.parametrize("message,ceiling", [
        ("Hello ZENO, how are you?", 3),
        ("How are you doing today?", 3),
        ("What time is it?", 14),
        ("Open Chrome", 16),
        ("Search YouTube for football highlights", 16),
        ("Remember that my test colour is blue", 18),
        ("Look at my screen", 12),
        ("Fix this Python traceback", 16),
    ])
    def test_a_request_never_gets_the_whole_registry(self, message, ceiling):
        route = cap.tools_for(message)
        assert route.exposed <= ceiling, (
            f"{message!r} exposed {route.exposed} tools "
            f"(ceiling {ceiling}) of {len(TOOLS)} registered")

    def test_nothing_ever_approaches_the_old_payload(self):
        """105 was the number that cost 10 seconds."""
        for message in ("hello", "what time is it", "open chrome",
                        "search for python tutorials", "remember this",
                        "build me a website", "ask the council"):
            assert cap.tools_for(message).exposed < 30

    def test_routing_itself_is_not_a_new_latency_source(self):
        """Solving schema overload with a slow classifier would be no fix."""
        route = cap.tools_for("search youtube for football highlights")
        assert route.latency_ms < 15.0


class TestMisroutingIsRefused:
    """The asymmetry: a missing tool costs a round, a sharp one cannot be undone."""

    def test_talking_about_deletion_does_not_arm_deletion(self):
        route = cap.tools_for("Tell me what deleting a folder means")
        assert "delete_file" not in route.tools
        assert "files_destructive" not in route.capabilities

    def test_asking_to_delete_does_arm_deletion(self):
        route = cap.tools_for("delete the old report file")
        assert "delete_file" in route.tools

    @pytest.mark.parametrize("message", [
        "How does PayPal work?",
        "What is a bank transfer?",
        "Explain how online payments work",
    ])
    def test_asking_about_money_offers_no_financial_action(self, message):
        route = cap.tools_for(message)
        for tool in ("paper_trade", "record_trade", "backtest_strategy"):
            assert tool not in route.tools

    def test_conversation_gets_no_desktop_or_browser_control(self):
        route = cap.tools_for("Hello ZENO, how are you today?")
        for tool in ("open_app", "run_command", "browser_open", "delete_file"):
            assert tool not in route.tools


class TestIntentRouting:
    @pytest.mark.parametrize("message,expected", [
        ("What time is it?", "utility"),
        ("Open Chrome", "browser"),
        ("Search YouTube for football", "browser"),
        ("Remember that my colour is blue", "memory"),
        ("What was my router test number?", "memory"),
        ("What colour did I tell you?", "memory"),
        ("Look at my screen", "vision"),
        ("Ask all my agents what they think", "council"),
        ("Send a message to John on Slack", "communication"),
        ("Fix this Python traceback", "coding"),
        ("Who is Apex?", "agents"),
    ])
    def test_intent_is_recognised(self, message, expected):
        assert expected in cap.tools_for(message).capabilities

    def test_plain_conversation_asks_for_nothing(self):
        route = cap.tools_for("How are you?")
        assert route.capabilities == ()
        assert route.exposed <= len(cap.ESSENTIAL)


class TestFollowUpContext:
    def test_a_follow_up_inherits_the_previous_capability(self):
        """"Search for it" after opening a browser is a BROWSER command.

        Judged alone it is a web search, and the browser context is lost --
        which is the failure the brief names directly.
        """
        first = cap.tools_for("Open Chrome")
        assert "browser" in first.capabilities

        second = cap.tools_for("search for it")
        assert "browser" in second.capabilities
        assert second.confidence == "inherited"

    def test_context_expires(self, monkeypatch):
        """An unrelated question later is judged on its own, not inherited.

        Checked with "open it" rather than "do that again": the latter is
        ALSO a workflow phrase, so it sets fresh context instead of
        inheriting -- correct behaviour, but it proves nothing about expiry.
        """
        cap.tools_for("Open Chrome")
        assert cap._inherited() == ("browser",)

        real = cap.time.time()
        monkeypatch.setattr(cap.time, "time",
                            lambda: real + cap.CONTEXT_TTL_S + 5)
        assert cap._inherited() == ()

        route = cap.tools_for("open it")
        assert route.confidence != "inherited"
        assert "browser" not in route.capabilities

    def test_a_new_explicit_request_replaces_context(self):
        cap.tools_for("Open Chrome")
        route = cap.tools_for("Remember that my colour is blue")
        assert "memory" in route.capabilities


class TestFallback:
    def test_low_confidence_expands_but_never_to_everything(self):
        route = cap.tools_for(
            "could you have a think about the thing we discussed at length "
            "yesterday and let me know", expand=True)
        assert route.exposed < 40
        assert route.exposed < len(TOOLS)

    def test_every_exposed_tool_is_actually_registered(self):
        for message in ("open chrome", "what time is it", "remember this",
                        "look at my screen", "delete the old file"):
            for tool in cap.tools_for(message).tools:
                assert tool in TOOLS, f"{tool} is routed but not registered"

    def test_essentials_are_always_present(self):
        """`enable_tools` is how a misroute repairs itself mid-turn."""
        for message in ("hello", "what time is it", "open chrome"):
            assert "enable_tools" in cap.tools_for(message).tools


class TestTelemetry:
    def test_a_route_can_explain_itself(self):
        route = cap.tools_for("Search YouTube for football")
        explanation = route.explain()
        assert "browser" in explanation
        assert str(route.exposed) in explanation

    def test_the_record_carries_what_an_audit_needs(self):
        record = cap.tools_for("open chrome").as_dict()
        for key in ("request_id", "capabilities", "tools_exposed",
                    "tools_registered", "confidence", "router_latency_ms"):
            assert key in record
