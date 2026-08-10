"""Safe legacy-to-Mem0 indexing with preview-first semantics."""

from __future__ import annotations

from typing import Any


def preview() -> dict[str, Any]:
    from reyes_agent import living_memory

    records = living_memory.list_memories(status="active")
    return {
        "records": len(records),
        "types": sorted({str(item.get("type", "fact")) for item in records}),
        "deletes_legacy": False,
        "note": "Migration indexes copies in Mem0; Living Memory remains authoritative.",
    }


def migrate(backend, *, dry_run: bool = True, limit: int = 500) -> dict[str, Any]:
    from reyes_agent import living_memory

    records = living_memory.list_memories(status="active")[: max(0, min(5000, int(limit)))]
    if dry_run:
        return {**preview(), "dry_run": True, "would_index": len(records)}
    indexed = 0
    errors: list[str] = []
    for record in records:
        try:
            backend.add(record.get("content", ""), category=record.get("category", ""),
                        source="living_memory_migration", memory_id=record.get("id", ""))
            indexed += 1
        except Exception as exc:  # one bad record must not abort the migration
            errors.append(f"{record.get('id', '?')}: {type(exc).__name__}")
    return {"dry_run": False, "indexed": indexed, "errors": errors[:20],
            "legacy_deleted": False}
