"""Browser tab awareness: list real open tabs, resolve a close reference
honestly (never guessing), and reuse-not-duplicate app launching (open_app).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestListPages:
    def test_no_session_returns_an_empty_list_not_a_stale_one(self):
        from reyes_agent import browser_controller as bc

        prior = bc._context
        try:
            bc._context = None
            assert bc.list_pages() == []
        finally:
            bc._context = prior

    def test_lists_every_page_with_the_last_one_active(self):
        from reyes_agent import browser_controller as bc

        class FakePage:
            def __init__(self, title, url):
                self._title, self.url = title, url
            def title(self):
                return self._title

        pages = [FakePage("GitHub", "https://github.com"), FakePage("ChatGPT", "https://chat.openai.com")]

        class FakeContext:
            pass

        fake = FakeContext()
        fake.pages = pages
        prior = bc._context
        try:
            bc._context = fake
            tabs = bc.list_pages()
            assert [t["title"] for t in tabs] == ["GitHub", "ChatGPT"]
            assert tabs[0]["active"] is False
            assert tabs[1]["active"] is True
        finally:
            bc._context = prior


class TestClosePage:
    def test_no_session_is_reported_honestly(self):
        from reyes_agent import browser_controller as bc

        prior = bc._context
        try:
            bc._context = None
            ok, detail = bc.close_page(0)
            assert ok is False
            assert "no browser session" in detail
        finally:
            bc._context = prior

    def test_out_of_range_index_is_refused(self):
        from reyes_agent import browser_controller as bc

        class FakeContext:
            pages = []

        prior = bc._context
        try:
            bc._context = FakeContext()
            ok, detail = bc.close_page(3)
            assert ok is False
            assert "no tab at index 3" in detail
        finally:
            bc._context = prior


class TestResolveTabReference:
    """Pure resolution logic -- see tools/browser.py -- covering the
    honest-refusal cases the spec asks for ('Close that tab' must resolve
    from context, verify, close the CORRECT tab, never guess)."""

    TABS = [
        {"index": 0, "title": "GitHub", "url": "https://github.com", "active": False},
        {"index": 1, "title": "ChatGPT", "url": "https://chat.openai.com", "active": True},
        {"index": 2, "title": "ChatGPT Plus pricing", "url": "https://openai.com/pricing", "active": False},
    ]

    def test_resolves_by_index(self):
        from reyes_agent.tools.browser import resolve_tab_reference

        assert resolve_tab_reference(self.TABS, "0")["title"] == "GitHub"

    def test_resolves_current_active_tab(self):
        from reyes_agent.tools.browser import resolve_tab_reference

        for reference in ("current", "active", "this one", ""):
            assert resolve_tab_reference(self.TABS, reference)["title"] == "ChatGPT"

    def test_resolves_a_unique_substring_match(self):
        from reyes_agent.tools.browser import resolve_tab_reference

        assert resolve_tab_reference(self.TABS, "github")["title"] == "GitHub"

    def test_refuses_an_ambiguous_substring_rather_than_guessing(self):
        from reyes_agent.tools.browser import _TabAmbiguous, resolve_tab_reference

        with pytest.raises(_TabAmbiguous) as excinfo:
            resolve_tab_reference(self.TABS, "chatgpt")
        assert "matches more than one" in excinfo.value.message

    def test_refuses_a_no_match_reference_rather_than_guessing(self):
        from reyes_agent.tools.browser import _TabAmbiguous, resolve_tab_reference

        with pytest.raises(_TabAmbiguous) as excinfo:
            resolve_tab_reference(self.TABS, "spotify")
        assert "no open tab matches" in excinfo.value.message.casefold()

    def test_refuses_when_no_tabs_are_open_at_all(self):
        from reyes_agent.tools.browser import _TabAmbiguous, resolve_tab_reference

        with pytest.raises(_TabAmbiguous):
            resolve_tab_reference([], "anything")

    def test_out_of_range_index_is_refused(self):
        from reyes_agent.tools.browser import _TabAmbiguous, resolve_tab_reference

        with pytest.raises(_TabAmbiguous):
            resolve_tab_reference(self.TABS, "9")


def test_browser_tab_tools_are_registered_and_routed_to_the_browser_panel():
    from reyes_agent import panels
    from reyes_agent.tools import TOOLS

    assert "browser_tabs" in TOOLS
    assert "browser_close_tab" in TOOLS
    assert panels.route_tool("browser_tabs") == "browser"
    assert panels.route_tool("browser_close_tab") == "browser"
