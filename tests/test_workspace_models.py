from __future__ import annotations

import pytest

from reyes_agent.workspace.models import (
    ActivityRecord,
    ActivityStatus,
    CommandDefinition,
    HealthRecord,
    HistoryRecord,
    PanelDefinition,
    PanelInstance,
    PanelState,
    PresentationMode,
    PresentationPlan,
    ToolHealthState,
)
from reyes_agent.workspace.redaction import safe_text, sanitize_mapping, secret_free


def test_panel_definition_accepts_only_allowlisted_complete_context() -> None:
    panel = PanelDefinition(
        id="files",
        title="Files",
        component="builtin:files",
        minimum_context=("query",),
    )

    context = panel.validate_context({
        "query": "CV",
        "token": "do-not-return",
        "unexpected": "drop me",
    })

    assert context == {"query": "CV"}
    with pytest.raises(ValueError, match="query"):
        panel.validate_context({"topic": "wrong field"})


def test_recursive_redaction_removes_secret_fields_and_bounds_values() -> None:
    safe = sanitize_mapping({
        "authorization": "Bearer secret",
        "nested": {"password": "hidden", "label": "visible"},
        "result": "a" * 2_000,
        "rows": list(range(80)),
    })

    assert safe["nested"] == {"label": "visible"}
    assert "authorization" not in safe
    assert len(safe["result"]) == 500
    assert len(safe["rows"]) == 50
    assert secret_free(safe) is True


def test_safe_text_collapses_controls_and_obeys_exact_limit() -> None:
    assert safe_text("  hello\r\n\tworld  ", 20) == "hello world"
    assert safe_text("abcdef", 4) == "abcd"


def test_secret_free_rejects_secret_keys_and_bearer_values() -> None:
    assert secret_free({"token": "x"}) is False
    assert secret_free({"detail": "Bearer abc"}) is False
    assert secret_free({"detail": "ordinary status"}) is True


def test_public_records_serialize_enums_tuples_and_safe_context() -> None:
    panel = PanelInstance(
        panel_id="files",
        instance_id="files",
        state=PanelState.ACTIVE,
        context={"query": "CV"},
        revision=3,
    )
    plan = PresentationPlan(
        mode=PresentationMode.FULL,
        primary_panel="files",
        correlation_id="turn-1",
        context={"query": "CV"},
    )
    activity = ActivityRecord(
        activity_id="a1",
        correlation_id="turn-1",
        category="files",
        status=ActivityStatus.RUNNING,
        title="Searching files",
        revision=4,
    )
    history = HistoryRecord(
        task_id="turn-1",
        request_summary="find my CV",
        status="RUNNING",
        tools=("search_files",),
        started_at=1.0,
        revision=5,
    )
    health = HealthRecord(
        name="search_files",
        category="files",
        status=ToolHealthState.DEGRADED,
        available=False,
        supported_operations=("search",),
        revision=6,
    )
    command = CommandDefinition(
        id="open-files",
        title="Open Files",
        action="show_panel",
        target="files",
        keywords=("find", "search"),
    )

    assert panel.as_dict()["state"] == "ACTIVE"
    assert plan.as_dict()["mode"] == "FULL"
    assert activity.as_dict()["status"] == "RUNNING"
    assert history.as_dict()["tools"] == ["search_files"]
    assert health.as_dict()["supported_operations"] == ["search"]
    assert command.as_dict()["keywords"] == ["find", "search"]


def test_required_public_state_sets_are_exact() -> None:
    assert {state.value for state in PanelState} == {
        "CLOSED", "OPENING", "ACTIVE", "MINIMIZED", "EXPANDED",
        "DOCKED", "BACKGROUND", "CLOSING",
    }
    assert {state.value for state in ToolHealthState} == {
        "AVAILABLE", "DEGRADED", "UNAVAILABLE", "AUTH_REQUIRED",
        "DEPENDENCY_MISSING", "DISCONNECTED", "ERROR",
    }
