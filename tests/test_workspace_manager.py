from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from reyes_agent.workspace.manager import RevisionClock, WorkspaceManager
from reyes_agent.workspace.models import CommandDefinition, PanelDefinition, PanelState
from reyes_agent.workspace.registry import CommandRegistry, PanelRegistry


def _registry(*definitions: PanelDefinition) -> PanelRegistry:
    registry = PanelRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


def test_registries_reject_conflicting_ids_and_return_sorted_definitions() -> None:
    panels = _registry(
        PanelDefinition("system", "System", "builtin:health"),
        PanelDefinition("activity", "Activity", "builtin:activity"),
    )
    with pytest.raises(ValueError, match="duplicate panel"):
        panels.register(PanelDefinition("system", "Other", "builtin:activity"))
    assert [panel.id for panel in panels.all()] == ["activity", "system"]
    assert panels.unregister("activity") is True
    assert panels.get("activity") is None

    commands = CommandRegistry()
    command = CommandDefinition("health", "System Health", "show_panel", "tool-health")
    commands.register(command)
    assert commands.get("health") == command
    with pytest.raises(ValueError, match="duplicate command"):
        commands.register(CommandDefinition("health", "Different", "show_panel", "system"))


def test_singleton_show_is_idempotent_immutable_and_revisioned() -> None:
    events: list[dict] = []
    manager = WorkspaceManager(
        _registry(PanelDefinition("activity", "Activity", "builtin:activity")),
        publish=lambda kind, payload, correlation: events.append({
            "kind": kind, "payload": payload, "correlation": correlation}),
    )

    first = manager.show_panel("activity", {"task_id": "t1"}, correlation_id="t1")
    second = manager.show_panel("activity", {"task_id": "t2"}, correlation_id="t2")

    assert first.instance_id == second.instance_id == "activity"
    assert first.revision == 2 and second.revision == 3
    assert first.context == {"task_id": "t1"}
    assert second.context == {"task_id": "t2"}
    assert [event["payload"]["panel"]["state"] for event in events[:2]] == [
        "OPENING", "ACTIVE"]
    assert [event["payload"]["revision"] for event in events] == [1, 2, 3]


def test_all_panel_controls_produce_valid_logical_states() -> None:
    manager = WorkspaceManager(
        _registry(PanelDefinition("system", "System", "builtin:health")))

    assert manager.show_panel("system").state is PanelState.ACTIVE
    assert manager.dock_panel("system", "right").state is PanelState.DOCKED
    assert manager.minimize_panel("system").state is PanelState.MINIMIZED
    assert manager.expand_panel("system").state is PanelState.EXPANDED
    assert manager.hide_panel("system").state is PanelState.BACKGROUND
    assert manager.focus_panel("system").state is PanelState.ACTIVE
    assert manager.toggle_panel("system").state is PanelState.BACKGROUND
    assert manager.toggle_panel("system").state is PanelState.ACTIVE
    assert manager.close_panel("system").state is PanelState.CLOSED
    assert manager.get_panel_state("system") is PanelState.CLOSED
    assert manager.get_active_panels() == []


def test_unknown_panel_invalid_dock_and_missing_context_do_not_mutate_state() -> None:
    manager = WorkspaceManager(_registry(PanelDefinition(
        "files", "Files", "builtin:files", minimum_context=("query",))))

    with pytest.raises(KeyError, match="missing"):
        manager.show_panel("missing")
    with pytest.raises(ValueError, match="query"):
        manager.show_panel("files", {"topic": "CV"})
    assert manager.snapshot()["revision"] == 0
    assert manager.close_panel("missing") is None

    manager.show_panel("files", {"query": "CV"})
    with pytest.raises(ValueError, match="dock position"):
        manager.dock_panel("files", "diagonal")
    assert manager.get_panel_state("files") is PanelState.ACTIVE


def test_multi_instance_panels_are_capped_without_evicting_live_instances() -> None:
    manager = WorkspaceManager(_registry(PanelDefinition(
        "documents", "Documents", "builtin:documents", singleton=False)))

    instances = [manager.show_panel("documents", {"file": f"{i}.pdf"}) for i in range(4)]
    assert len({item.instance_id for item in instances}) == 4
    with pytest.raises(RuntimeError, match="instance limit"):
        manager.show_panel("documents", {"file": "fifth.pdf"})

    manager.close_panel(instances[0].instance_id)
    fifth = manager.show_panel("documents", {"file": "fifth.pdf"})
    assert fifth.state is PanelState.ACTIVE
    assert len(manager.get_active_panels()) == 4


def test_concurrent_commands_keep_revisions_unique_and_state_valid() -> None:
    events: list[int] = []
    manager = WorkspaceManager(
        _registry(PanelDefinition("activity", "Activity", "builtin:activity")),
        publish=lambda _kind, payload, _correlation: events.append(payload["revision"]),
    )

    def operate(index: int) -> None:
        if index % 3 == 0:
            manager.show_panel("activity", {"task_id": str(index)})
        elif index % 3 == 1:
            manager.minimize_panel("activity")
        else:
            manager.focus_panel("activity")

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(operate, range(150)))

    assert events == sorted(set(events))
    assert manager.snapshot()["revision"] == events[-1]
    assert manager.get_panel_state("activity") in {
        PanelState.ACTIVE, PanelState.MINIMIZED}


def test_revision_clock_is_shared_and_thread_safe() -> None:
    clock = RevisionClock()
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: clock.next(), range(100)))
    assert sorted(values) == list(range(1, 101))
    assert clock.current() == 100
