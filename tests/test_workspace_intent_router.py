from __future__ import annotations

import pytest

from reyes_agent.workspace.defaults import (
    default_command_registry,
    default_panel_registry,
)
from reyes_agent.workspace.intent_router import PanelIntentRouter
from reyes_agent.workspace.models import PresentationMode


@pytest.mark.parametrize(("message", "mode", "panel"), [
    ("what time is it", PresentationMode.NO_UI, ""),
    ("pause", PresentationMode.NO_UI, ""),
    ("find my CV", PresentationMode.FULL, "files"),
    ("search for my assignment", PresentationMode.FULL, "files"),
    ("check the news", PresentationMode.FULL, "news"),
    ("show my system performance", PresentationMode.FULL, "system"),
    ("ask the council", PresentationMode.FULL, "agents"),
    ("download this report", PresentationMode.CARD, "downloads"),
    ("open calculator", PresentationMode.CARD, ""),
    ("show what is playing", PresentationMode.FULL, "media"),
    ("thanks for your help", PresentationMode.NO_UI, ""),
])
def test_route_examples_choose_one_quiet_presentation(message, mode, panel) -> None:
    result = PanelIntentRouter(default_panel_registry()).route(
        message, correlation_id="turn-1")

    assert result.mode is mode
    assert result.primary_panel == panel
    assert result.correlation_id == "turn-1"


def test_existing_panel_is_reused_instead_of_requesting_another_instance() -> None:
    result = PanelIntentRouter(default_panel_registry()).route(
        "find my assignment",
        correlation_id="turn-2",
        active_panels=("files", "activity"),
    )

    assert result.mode is PresentationMode.FULL
    assert result.primary_panel == "files"
    assert result.context["reuse_existing"] is True


@pytest.mark.parametrize("state", [
    "AUTH_REQUIRED", "DEPENDENCY_MISSING", "DISCONNECTED", "UNAVAILABLE", "ERROR",
])
def test_unhealthy_capability_downgrades_full_panel_to_actionable_card(state: str) -> None:
    result = PanelIntentRouter(default_panel_registry()).route(
        "show what is playing",
        correlation_id="turn-3",
        capability_states={"media": state},
    )

    assert result.mode is PresentationMode.CARD
    assert result.primary_panel == "media"
    assert result.card_kind == "capability"
    assert result.reason_code == state.casefold()


def test_background_wording_does_not_force_a_full_workspace() -> None:
    result = PanelIntentRouter(default_panel_registry()).route(
        "check the news in the background", correlation_id="turn-4")

    assert result.mode is PresentationMode.BACKGROUND
    assert result.primary_panel == "news"


def test_default_registries_are_complete_fresh_and_declarative() -> None:
    first = default_panel_registry()
    second = default_panel_registry()
    panel_ids = {panel.id for panel in first.all()}

    assert first is not second
    assert {
        "media", "files", "browser", "news", "weather", "messages", "calls",
        "calendar", "tasks", "downloads", "terminal", "coding", "agents",
        "system", "notifications", "search", "documents", "images", "activity",
        "history", "tool-health",
    } <= panel_ids
    assert all(panel.component.startswith(("builtin:", "dom:", "module:"))
               for panel in first.all())

    commands = default_command_registry().all()
    assert {command.action for command in commands} >= {"show_panel", "search"}
    assert all(command.target for command in commands)
