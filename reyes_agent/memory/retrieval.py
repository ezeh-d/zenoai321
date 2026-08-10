"""Bounded relevant retrieval from Mem0, Living Memory and session state."""

from __future__ import annotations

import re
from typing import Any

from reyes_agent.memory.privacy import redact

_WORD = re.compile(r"[a-z0-9_-]{2,}", re.I)
_STOP = {"the", "and", "for", "this", "that", "with", "from", "what", "were", "you", "your"}


def _tokens(value: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(str(value or "")) if word.casefold() not in _STOP}


def legacy_search(query: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """Rank Living Memory locally; never inject the entire store."""
    from reyes_agent import living_memory

    wanted = _tokens(query)
    if not wanted:
        return []
    ranked: list[tuple[float, dict[str, Any]]] = []
    for record in living_memory.list_memories(status="active"):
        content = str(record.get("content", ""))
        title = str(record.get("title", ""))
        words = _tokens(title + " " + content)
        overlap = len(wanted & words)
        if not overlap:
            continue
        score = overlap / max(1, len(wanted))
        score += min(0.2, float(record.get("recall_count", 0)) * 0.01)
        ranked.append((score, {
            "id": record.get("id", ""), "memory": redact(content),
            "score": round(score, 4), "category": record.get("category", ""),
            "source": "living_memory",
        }))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _score, item in ranked[: max(1, min(10, int(limit)))]]


def merge_ranked(*groups: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            text = " ".join(str(item.get("memory", "")).casefold().split())
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(item)
    merged.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return merged[: max(1, min(10, int(limit)))]
