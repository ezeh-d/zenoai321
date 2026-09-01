"""Metadata-only search across the native ZENO workspace catalog."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from reyes_agent.universal_search import UniversalSearchService
from reyes_agent.workspace.redaction import safe_text

_FILE_TERMS = {"file", "files", "folder", "folders", "document", "documents", "find"}
_SETTING_DENY = ("key", "secret", "password", "token", "credential", "cookie")


class WorkspaceSearch:
    def __init__(
        self,
        *,
        panels: Any,
        commands: Any,
        tool_provider: Callable[[], Iterable[Any]] | None = None,
        agent_provider: Callable[[], Iterable[Any]] | None = None,
        setting_provider: Callable[[], Iterable[Any]] | None = None,
        history_provider: Callable[[], Iterable[Any]] | None = None,
    ) -> None:
        self._panels = panels
        self._commands = commands
        self._tool_provider = tool_provider or self._default_tools
        self._agent_provider = agent_provider or self._default_agents
        self._setting_provider = setting_provider or self._default_settings
        self._history_provider = history_provider or (lambda: ())
        self._engine = UniversalSearchService(index_name="zeno-workspace")
        self._counts: dict[str, int] = {}

    @staticmethod
    def _default_tools() -> Iterable[Any]:
        try:
            from reyes_agent.tools.universal_registry import get_global_tool_registry

            return get_global_tool_registry().all()
        except Exception:
            return ()

    @staticmethod
    def _default_agents() -> Iterable[Any]:
        try:
            from reyes_agent.agent_runtime import AGENT_ROLES

            return tuple(AGENT_ROLES.items())
        except Exception:
            return ()

    @staticmethod
    def _default_settings() -> Iterable[Any]:
        try:
            from reyes_agent import config

            return tuple(
                (name.casefold(), name.replace("_", " ").title())
                for name in vars(config)
                if name.isupper() and not any(part in name.casefold() for part in _SETTING_DENY)
            )[:200]
        except Exception:
            return ()

    @staticmethod
    def _pair(item: Any) -> tuple[str, str]:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            return safe_text(item[0], 80), safe_text(item[1], 300)
        if isinstance(item, dict):
            return safe_text(item.get("id") or item.get("name"), 80), safe_text(
                item.get("title") or item.get("role") or item.get("description"), 300)
        return safe_text(getattr(item, "id", "") or getattr(item, "name", ""), 80), safe_text(
            getattr(item, "title", "") or getattr(item, "role", "") or
            getattr(item, "description", ""), 300)

    @staticmethod
    def _history_row(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        converter = getattr(item, "as_dict", None)
        if callable(converter):
            value = converter()
            return value if isinstance(value, dict) else {}
        return {}

    def refresh_metadata(self) -> dict[str, int]:
        documents: list[dict[str, Any]] = []
        counts = {kind: 0 for kind in ("panels", "commands", "tools", "agents", "settings", "history")}

        for panel in self._panels.all()[:100]:
            documents.append({
                "id": f"panel:{panel.id}", "text": f"{panel.title} {panel.id}",
                "kind": "panel", "title": panel.title, "action": "show", "target": panel.id,
            })
            counts["panels"] += 1
        for command in self._commands.all()[:200]:
            documents.append({
                "id": f"command:{command.id}",
                "text": " ".join((command.title, command.description, *command.keywords)),
                "kind": "command", "title": command.title,
                "action": command.action, "target": command.target,
            })
            counts["commands"] += 1
        for tool in list(self._tool_provider())[:500]:
            try:
                metadata = tool.metadata()
            except Exception:
                continue
            name = safe_text(getattr(metadata, "name", ""), 80)
            if not name:
                continue
            title = name.replace("_", " ").title()
            documents.append({
                "id": f"tool:{name.casefold()}",
                "text": f"{name} {safe_text(getattr(metadata, 'description', ''), 300)} "
                        f"{safe_text(getattr(metadata, 'category', ''), 80)}",
                "kind": "tool", "title": title,
                "action": "inspect_tool", "target": name,
            })
            counts["tools"] += 1
        for item in list(self._agent_provider())[:200]:
            agent_id, role = self._pair(item)
            if not agent_id:
                continue
            documents.append({
                "id": f"agent:{agent_id.casefold()}", "text": f"{agent_id} {role}",
                "kind": "agent", "title": agent_id.replace("_", " ").title(),
                "action": "show_agent", "target": agent_id,
            })
            counts["agents"] += 1
        for item in list(self._setting_provider())[:200]:
            setting_id, label = self._pair(item)
            if not setting_id or any(part in setting_id.casefold() for part in _SETTING_DENY):
                continue
            documents.append({
                "id": f"setting:{setting_id.casefold()}", "text": f"{setting_id} {label}",
                "kind": "setting", "title": label or setting_id,
                "action": "open_settings", "target": setting_id,
            })
            counts["settings"] += 1
        history = list(self._history_provider())[-100:]
        for item in history:
            row = self._history_row(item)
            task_id = safe_text(row.get("task_id"), 80)
            summary = safe_text(row.get("request_summary"), 300)
            if not task_id or not summary:
                continue
            tools = row.get("tools") if isinstance(row.get("tools"), (tuple, list)) else ()
            documents.append({
                "id": f"history:{task_id}",
                "text": " ".join((summary, safe_text(row.get("status"), 40),
                                     *(safe_text(tool, 80) for tool in list(tools)[:20]))),
                "kind": "history", "title": summary,
                "action": "show_history", "target": task_id,
            })
            counts["history"] += 1

        self._engine = UniversalSearchService(index_name="zeno-workspace")
        self._engine.index_many(documents)
        self._counts = counts
        return dict(counts)

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        bounded = safe_text(query, 200).strip()
        if not bounded:
            return []
        self.refresh_metadata()
        count = max(1, min(int(limit), 25))
        rows: list[dict[str, Any]] = []
        for hit in self._engine.search(bounded, count):
            metadata = dict(hit.metadata)
            rows.append({
                "id": hit.id,
                "kind": safe_text(metadata.get("kind"), 40),
                "title": safe_text(metadata.get("title") or hit.text, 300),
                "action": safe_text(metadata.get("action"), 80),
                "target": safe_text(metadata.get("target"), 200),
                "score": round(float(hit.score), 4),
            })
        terms = set(bounded.casefold().split())
        if terms & _FILE_TERMS and len(rows) < count:
            rows.append({
                "id": "action:file-search", "kind": "action", "title": "Search files",
                "action": "start_file_search", "target": bounded, "score": 1.0,
            })
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped.setdefault(row["id"], row)
        return list(deduped.values())[:count]

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": self._engine.backend_name,
            "sources": ["panels", "commands", "tools", "agents", "settings", "history"],
            "documents": sum(self._counts.values()),
        }
