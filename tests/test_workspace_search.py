from __future__ import annotations

from dataclasses import dataclass

from reyes_agent.workspace.defaults import default_command_registry, default_panel_registry
from reyes_agent.workspace.models import HistoryRecord
from reyes_agent.workspace.search import WorkspaceSearch


@dataclass(frozen=True)
class _ToolMetadata:
    name: str = "system_status"
    description: str = "Read current system status"
    category: str = "system"


class _Tool:
    def metadata(self) -> _ToolMetadata:
        return _ToolMetadata()


def _search(*, history=()) -> WorkspaceSearch:
    return WorkspaceSearch(
        panels=default_panel_registry(),
        commands=default_command_registry(),
        tool_provider=lambda: [_Tool()],
        agent_provider=lambda: [("system_agent", "System operations specialist")],
        setting_provider=lambda: [("appearance", "Appearance settings")],
        history_provider=lambda: list(history),
    )


def test_search_returns_typed_actionable_panel_tool_command_and_history_results() -> None:
    history = [HistoryRecord(
        task_id="task-1",
        request_summary="check system health",
        status="COMPLETED",
        tools=("system_status",),
        started_at=1,
    )]
    search = _search(history=history)

    rows = search.search("system", limit=25)
    kinds = {row["kind"] for row in rows}

    assert {"panel", "command", "tool", "agent", "history"} <= kinds
    assert all(row.get("action") and row.get("target") for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)


def test_refresh_is_idempotent_and_search_bounds_query_and_results() -> None:
    search = _search()
    first = search.refresh_metadata()
    second = search.refresh_metadata()

    assert first == second
    assert len(search.search("system " * 100, limit=999)) <= 25
    assert search.search("   ") == []


def test_search_never_indexes_file_contents_secret_history_or_locations() -> None:
    history = [HistoryRecord(
        task_id="task-secret",
        request_summary="find my CV",
        status="FAILED",
        safe_result="token=supersecret at C:/private/cv.txt",
        result_reference="C:/private/cv.txt",
        started_at=1,
    )]
    search = _search(history=history)

    secret_payload = repr(search.search("supersecret"))
    file_rows = search.search("find file")

    assert "supersecret" not in secret_payload
    assert all("C:/private" not in repr(row) for row in search.search("CV"))
    assert any(row["kind"] == "action" and row["action"] == "start_file_search"
               for row in file_rows)
    assert "path" not in search.health()["sources"]
