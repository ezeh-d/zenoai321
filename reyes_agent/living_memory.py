"""Versioned, file-backed living memory.

Canonical memory records and immutable version snapshots live in the vault.
SQLite's old ``facts`` table is imported once for compatibility, then remains
only a legacy source -- it is never the authority for new changes.  Search,
embeddings and the knowledge graph are derived views and may be rebuilt.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from reyes_agent import config

ROOT = config.VAULT_PATH / "07-System" / "memory"
RECORDS = ROOT / "records"
VERSIONS = ROOT / "versions"
TRANSACTIONS = ROOT / "transactions"
INDEX = ROOT / "index.json"
MIGRATION = ROOT / "legacy_facts_migrated.json"
LEGACY_DB = ROOT / "reyes.db"
_lock = threading.RLock()
_tag = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{1,40})")
STATES = {"active", "archived", "deleted_pending_purge"}


class MemoryError(ValueError):
    pass


def _now() -> float:
    return time.time()


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _record_path(memory_id: str) -> Path:
    return RECORDS / f"{memory_id}.json"


def _version_path(memory_id: str, version: int) -> Path:
    return VERSIONS / memory_id / f"v{version:06d}.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryError(f"Memory data is unreadable: {path.name}: {exc}") from exc


def _recover() -> None:
    """Finish an atomic record update left between journal and replace."""
    if not TRANSACTIONS.exists():
        return
    for journal_path in TRANSACTIONS.glob("*.json"):
        try:
            journal = _read(journal_path)
            after = journal["after"]
            target = _record_path(after["id"])
            current = _read(target) if target.exists() else {}
            if current.get("version", 0) < after.get("version", 0):
                _atomic(target, after)
            journal_path.unlink(missing_ok=True)
        except Exception:
            # Keep a broken journal for human inspection; do not delete data.
            continue


def _save_index() -> None:
    entries = []
    for path in sorted(RECORDS.glob("*.json")) if RECORDS.exists() else []:
        try:
            r = _read(path)
            entries.append({k: r.get(k) for k in (
                "id", "title", "type", "status", "created_at", "updated_at", "mission_id",
                "agents", "tags", "recall_count", "confidence", "verification_state", "version",
            )})
        except MemoryError:
            continue
    _atomic(INDEX, entries)


def _publish(event_type: str, record: dict[str, Any], *, actor: str, summary: str,
             correlation_id: str = "") -> None:
    try:
        from reyes_agent import event_bus
        event_bus.publish(event_type, {
            "memory_id": record["id"], "version": record["version"], "actor": actor,
            "mission_id": record.get("mission_id", ""), "summary": summary,
        }, source="living_memory", correlation_id=correlation_id)
    except Exception:
        pass


def _refresh_derived(record: dict[str, Any], *, correlation_id: str = "") -> None:
    """Update only this memory's search representation; failures stay visible."""
    embedding = "unavailable"
    try:
        from reyes_agent.tools import rag
        embedding = rag.refresh_memory_embedding(record["id"], record["content"], record["status"])
    except Exception as exc:  # durable record must not depend on a provider
        embedding = f"deferred: {type(exc).__name__}"
    _save_index()
    _publish("memory.index_updated", record, actor="system",
             summary=f"Index refreshed; embedding {embedding}", correlation_id=correlation_id)
    # The graph is computed from source files on demand. Import/build validates
    # the affected source is visible without introducing a stale graph cache.
    try:
        from reyes_agent import knowledge_graph
        knowledge_graph.build()
    except Exception:
        pass


def _legacy_migrate() -> None:
    if MIGRATION.exists() or not LEGACY_DB.exists():
        return
    try:
        with sqlite3.connect(LEGACY_DB) as conn:
            rows = conn.execute("SELECT id, text, category, created_at FROM facts ORDER BY id").fetchall()
    except sqlite3.Error:
        rows = []
    for legacy_id, text, category, created_at in rows:
        mid = f"legacy-{legacy_id}"
        if _record_path(mid).exists():
            continue
        stamp = _now()
        record = _new_record(str(text), title=str(text)[:80], memory_type="fact", category=str(category or ""),
                             actor="migration", reason="Imported legacy durable fact", memory_id=mid,
                             created_at=stamp, legacy_id=int(legacy_id))
        _create(record, change_type="created", source="legacy_sqlite")
    _atomic(MIGRATION, {"migrated_at": _now(), "legacy_db": str(LEGACY_DB), "count": len(rows)})


def _ensure() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    _recover()
    _legacy_migrate()


def health() -> dict[str, Any]:
    """Probe the canonical store with a real write/read/delete cycle.

    The probe is not a memory record and never reaches the index, graph, or
    embeddings. It proves the current process can durably write and read the
    configured store instead of reporting ONLINE because an import worked.
    """
    started = time.perf_counter()
    probe = ROOT / ".healthcheck.json"
    marker = uuid.uuid4().hex
    unreadable = 0
    try:
        with _lock:
            _ensure()
            _atomic(probe, {"marker": marker, "written_at": _now()})
            observed = _read(probe)
            if observed.get("marker") != marker:
                raise MemoryError("Memory health probe did not read back the written marker.")
            probe.unlink(missing_ok=True)
            records = list(RECORDS.glob("*.json")) if RECORDS.exists() else []
            # Validate a bounded recent sample. A corrupt old record remains
            # visible through the count without making health itself unbounded.
            for path in records[-50:]:
                try:
                    _read(path)
                except MemoryError:
                    unreadable += 1
        state = "ONLINE" if unreadable == 0 else "DEGRADED"
        return {
            "state": state,
            "readable": True,
            "writable": True,
            "records": len(records),
            "sampled": min(50, len(records)),
            "unreadable_in_sample": unreadable,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "path": str(ROOT),
        }
    except Exception as exc:  # noqa: BLE001 -- health is a typed result
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "state": "FAILED",
            "readable": False,
            "writable": False,
            "records": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "path": str(ROOT),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _new_record(content: str, *, title: str = "", memory_type: str = "fact", category: str = "",
                actor: str = "user", reason: str = "", mission_id: str = "", agents: list[str] | None = None,
                tags: list[str] | None = None, source_ids: list[str] | None = None, original_id: str = "",
                memory_id: str = "", created_at: float | None = None, legacy_id: int | None = None) -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise MemoryError("Memory content cannot be empty.")
    stamp = _now() if created_at is None else created_at
    inferred_tags = sorted(set(_tag.findall(content)))
    return {
        "id": memory_id or f"mem-{uuid.uuid4().hex[:12]}", "title": (title.strip() or content.splitlines()[0])[:160],
        "content": content, "type": memory_type.strip() or "fact", "category": category.strip(),
        "status": "active", "created_at": stamp, "updated_at": stamp, "mission_id": mission_id.strip(),
        "agents": sorted(set(agents or [])), "tags": sorted(set(tags or inferred_tags)), "recall_count": 0,
        "confidence": "unverified", "verification_state": "unverified", "version": 1,
        "owner": "user" if actor == "user" else actor, "source_ids": list(source_ids or []),
        "original_id": original_id, "legacy_id": legacy_id, "last_reason": reason.strip(),
    }


def _version(change_type: str, before: dict[str, Any] | None, after: dict[str, Any], *,
             actor: str, source: str, reason: str) -> dict[str, Any]:
    return {"memory_id": after["id"], "version": after["version"], "timestamp": _now(),
            "change_type": change_type, "previous_content": before.get("content", "") if before else "",
            "updated_content": after["content"], "source": source, "actor": actor,
            "mission_id": after.get("mission_id", ""), "reason": reason, "previous_record": before,
            "updated_record": after}


def _create(record: dict[str, Any], *, change_type: str = "created", source: str = "ui",
            reason: str = "", correlation_id: str = "") -> dict[str, Any]:
    if _record_path(record["id"]).exists():
        raise MemoryError(f"Memory '{record['id']}' already exists.")
    _atomic(_record_path(record["id"]), record)
    _atomic(_version_path(record["id"], record["version"]), _version(change_type, None, record,
            actor=record.get("owner", "user"), source=source, reason=reason or record.get("last_reason", "")))
    _refresh_derived(record, correlation_id=correlation_id)
    _publish("memory.created", record, actor=record.get("owner", "user"), summary=record["title"], correlation_id=correlation_id)
    return record


def _load(memory_id: str) -> dict[str, Any]:
    _ensure()
    path = _record_path(str(memory_id))
    if not path.exists():
        raise MemoryError(f"No memory '{memory_id}'.")
    return _read(path)


def _assert_actor(record: dict[str, Any], actor: str) -> None:
    if actor != "user" and record.get("owner") == "user":
        raise MemoryError("Agent changes to human-owned memory require a user-reviewed UI action.")


def _change(memory_id: str, *, change_type: str, actor: str, source: str, reason: str,
            correlation_id: str = "", **changes: Any) -> dict[str, Any]:
    with _lock:
        before = _load(memory_id)
        _assert_actor(before, actor)
        after = dict(before)
        after.update(changes)
        if after.get("status") not in STATES:
            raise MemoryError("Invalid memory status.")
        after["version"] = int(before["version"]) + 1
        after["updated_at"] = _now()
        after["last_reason"] = reason.strip()
        journal = TRANSACTIONS / f"{memory_id}-{after['version']}.json"
        _atomic(journal, {"before": before, "after": after})
        _atomic(_version_path(memory_id, after["version"]), _version(change_type, before, after,
                actor=actor, source=source, reason=reason))
        _atomic(_record_path(memory_id), after)
        journal.unlink(missing_ok=True)
        _refresh_derived(after, correlation_id=correlation_id)
        event = "memory.updated" if change_type == "edited" else f"memory.{change_type}"
        _publish(event, after, actor=actor, summary=reason or change_type, correlation_id=correlation_id)
        return after


def create(content: str, *, title: str = "", memory_type: str = "fact", category: str = "",
           actor: str = "user", reason: str = "", mission_id: str = "", agents: list[str] | None = None,
           tags: list[str] | None = None, source_ids: list[str] | None = None, original_id: str = "",
           source: str = "ui", correlation_id: str = "") -> dict[str, Any]:
    with _lock:
        _ensure()
        record = _new_record(content, title=title, memory_type=memory_type, category=category, actor=actor,
                             reason=reason, mission_id=mission_id, agents=agents, tags=tags,
                             source_ids=source_ids, original_id=original_id)
        return _create(record, source=source, reason=reason, correlation_id=correlation_id)


def edit(memory_id: str, content: str, *, title: str = "", actor: str = "user", reason: str = "",
         mission_id: str | None = None, tags: list[str] | None = None, source: str = "ui", correlation_id: str = "") -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise MemoryError("Memory content cannot be empty.")
    changes: dict[str, Any] = {"content": content, "title": (title.strip() or content.splitlines()[0])[:160]}
    changes["tags"] = sorted(set(tags if tags is not None else _tag.findall(content)))
    if mission_id is not None:
        changes["mission_id"] = mission_id
    return _change(memory_id, change_type="edited", actor=actor, source=source, reason=reason,
                   correlation_id=correlation_id, **changes)


def get(memory_id: str, *, count_recall: bool = False) -> dict[str, Any]:
    with _lock:
        record = _load(memory_id)
        if count_recall:
            record["recall_count"] = int(record.get("recall_count", 0)) + 1
            _atomic(_record_path(memory_id), record)
            _save_index()
        return record


def resolve_id(value: str) -> str:
    """Accept a stable record ID or a pre-Phase-23 SQLite integer ID."""
    value = str(value).strip().lstrip("#")
    try:
        return _load(value)["id"]
    except MemoryError:
        for record in list_memories(status="", include_archived=True):
            if str(record.get("legacy_id", "")) == value:
                return record["id"]
    raise MemoryError(f"No memory '{value}'.")


def list_memories(*, query: str = "", status: str = "active", memory_type: str = "",
                  include_archived: bool = False, sort: str = "updated") -> list[dict[str, Any]]:
    with _lock:
        _ensure()
        query = query.strip().lower()
        states = STATES if include_archived or not status else {status}
        records = []
        for path in RECORDS.glob("*.json") if RECORDS.exists() else []:
            try:
                r = _read(path)
            except MemoryError:
                continue
            if r.get("status") not in states or (memory_type and r.get("type") != memory_type):
                continue
            haystack = " ".join([r.get("title", ""), r.get("content", ""), " ".join(r.get("tags", []))]).lower()
            if query and query not in haystack:
                continue
            records.append(r)
        key = "created_at" if sort == "created" else ("title" if sort == "title" else "updated_at")
        return sorted(records, key=lambda r: r.get(key, ""), reverse=key != "title")


def versions(memory_id: str) -> list[dict[str, Any]]:
    _load(memory_id)
    out = []
    for path in sorted((VERSIONS / memory_id).glob("v*.json")):
        out.append(_read(path))
    return out


def compare(memory_id: str, left: int, right: int) -> dict[str, Any]:
    import difflib
    by_version = {v["version"]: v for v in versions(memory_id)}
    if left not in by_version or right not in by_version:
        raise MemoryError("Both versions must exist.")
    a, b = by_version[left]["updated_content"], by_version[right]["updated_content"]
    return {"memory_id": memory_id, "left": left, "right": right,
            "diff": "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), fromfile=f"v{left}", tofile=f"v{right}", lineterm=""))}


def restore_version(memory_id: str, version: int, *, actor: str = "user", reason: str = "", source: str = "ui") -> dict[str, Any]:
    wanted = next((v for v in versions(memory_id) if v["version"] == int(version)), None)
    if wanted is None:
        raise MemoryError(f"No version {version} for '{memory_id}'.")
    target = wanted["updated_record"]
    return _change(memory_id, change_type="version_restored", actor=actor, source=source,
                   reason=reason or f"Restored version {version}", content=target["content"], title=target["title"],
                   status=target["status"], tags=target.get("tags", []), mission_id=target.get("mission_id", ""))


def archive(memory_id: str, *, actor: str = "user", reason: str = "", source: str = "ui") -> dict[str, Any]:
    return _change(memory_id, change_type="archived", actor=actor, source=source, reason=reason, status="archived")


def restore(memory_id: str, *, actor: str = "user", reason: str = "", source: str = "ui") -> dict[str, Any]:
    return _change(memory_id, change_type="restored", actor=actor, source=source, reason=reason, status="active")


def delete(memory_id: str, *, actor: str = "user", reason: str = "", source: str = "ui") -> dict[str, Any]:
    return _change(memory_id, change_type="deleted", actor=actor, source=source, reason=reason, status="deleted_pending_purge")


def purge(memory_id: str, *, confirmed: bool = False, actor: str = "user", reason: str = "", source: str = "ui") -> bool:
    if not confirmed:
        raise MemoryError("Permanent purge requires explicit confirmation.")
    with _lock:
        record = _load(memory_id)
        _assert_actor(record, actor)
        if record.get("status") != "deleted_pending_purge":
            raise MemoryError("Only deleted-pending-purge memories can be permanently purged.")
        # Keep immutable versions for audit/export; erase only active record.
        _record_path(memory_id).unlink(missing_ok=True)
        _save_index()
        _publish("memory.deleted", record, actor=actor, summary=reason or "Permanently purged", correlation_id="")
        return True


def merge_preview(memory_ids: list[str]) -> dict[str, Any]:
    selected = [get(mid) for mid in dict.fromkeys(memory_ids)]
    if len(selected) < 2:
        raise MemoryError("Select at least two memories to merge.")
    lines, seen, conflicts = [], set(), []
    labels: dict[str, str] = {}
    for r in selected:
        for line in r["content"].splitlines():
            norm = " ".join(line.lower().split())
            if norm in seen:
                continue
            seen.add(norm); lines.append(line)
            if ":" in line:
                key, value = line.split(":", 1); key = key.strip().lower(); value = value.strip()
                if key in labels and labels[key] != value:
                    conflicts.append({"field": key, "values": [labels[key], value], "memory_id": r["id"]})
                labels[key] = value
    return {"selected": selected, "duplicates_removed": sum(len(r["content"].splitlines()) for r in selected) - len(lines),
            "conflicts": conflicts, "proposed_content": "\n".join(lines), "source_ids": [r["id"] for r in selected]}


def merge(memory_ids: list[str], *, content: str = "", title: str = "", actor: str = "user", reason: str = "",
          confirm: bool = False, mission_id: str = "", source: str = "ui", correlation_id: str = "") -> dict[str, Any]:
    preview = merge_preview(memory_ids)
    if not confirm:
        return {"confirmation_required": True, **preview}
    merged = create(content or preview["proposed_content"], title=title or "Merged memory", memory_type="fact", actor=actor,
                    reason=reason or "Merged related memories", mission_id=mission_id, source=source, correlation_id=correlation_id)
    merged = _change(merged["id"], change_type="merged", actor=actor, source=source, reason=reason or "Merged",
                     correlation_id=correlation_id, source_ids=preview["source_ids"])
    for mid in preview["source_ids"]:
        _change(mid, change_type="merged", actor=actor, source=source, reason=f"Merged into {merged['id']}", status="archived", correlation_id=correlation_id)
    _publish("memory.merged", merged, actor=actor, summary=f"Merged {len(preview['source_ids'])} memories", correlation_id=correlation_id)
    return merged


def split_preview(memory_id: str) -> dict[str, Any]:
    record = get(memory_id)
    sections = [s.strip() for s in re.split(r"\n\s*\n", record["content"]) if s.strip()]
    if len(sections) < 2:
        sections = [line.strip() for line in record["content"].splitlines() if line.strip()]
    return {"original": record, "sections": sections}


def split(memory_id: str, sections: list[str] | None = None, *, actor: str = "user", reason: str = "", confirm: bool = False,
          source: str = "ui", correlation_id: str = "") -> dict[str, Any]:
    preview = split_preview(memory_id)
    chosen = [s.strip() for s in (sections or preview["sections"]) if s and s.strip()]
    if len(chosen) < 2:
        raise MemoryError("A split needs at least two non-empty sections.")
    if not confirm:
        return {"confirmation_required": True, "original": preview["original"], "sections": chosen}
    created = [create(s, title=s.splitlines()[0], memory_type=preview["original"]["type"], actor=actor,
                      reason=reason or f"Split from {memory_id}", mission_id=preview["original"].get("mission_id", ""),
                      agents=preview["original"].get("agents", []), original_id=memory_id, source=source,
                      correlation_id=correlation_id) for s in chosen]
    _change(memory_id, change_type="split", actor=actor, source=source, reason=reason or "Split into smaller memories",
            status="archived", correlation_id=correlation_id)
    for r in created:
        _publish("memory.split", r, actor=actor, summary=f"Split from {memory_id}", correlation_id=correlation_id)
    return {"original": memory_id, "created": created}


def graph_documents() -> list[dict[str, Any]]:
    """Active records exposed to the existing graph as first-class sources."""
    return [{"id": r["id"], "title": r["title"], "content": r["content"], "tags": r.get("tags", [])}
            for r in list_memories(status="active")]
