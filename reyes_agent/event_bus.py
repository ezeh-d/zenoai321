"""The Event Bus: one typed, persistent record of everything ZENO does.

Phase 1 of the roadmap, and the dependency several later subsystems sit on
(Timeline replay, Activity Stream, Mission history, Evolution/experience
tracking all need "what happened, in order, durably" -- which nothing in
this build had until now).

RELATIONSHIP TO notification_bus.py
-----------------------------------
`notification_bus` is a 30-line in-process pub/sub with no types, no
persistence, and no history -- fine for its one job (push a live event to
whatever browser tab is connected) and still doing exactly that. It now
also forwards everything it publishes into this bus so those events are
persisted and replayable, rather than being duplicated or rewritten. That
keeps every existing caller (show_map, workspace overlays, the
notification listener, the SSE endpoint) working untouched.

DESIGN NOTES
------------
* Persistence goes in the same shared state.db every other subsystem uses
  (heartbeat, activity_monitor, work, calendar, missions, investing) --
  one local SQLite file, not a database per feature.
* Fan-out to live subscribers is non-blocking and bounded: a subscriber
  that stops draining its queue gets events dropped rather than growing
  the process's memory without limit.
* Publishing never raises. An event bus that can break the thing it is
  observing is worse than no event bus; failures are swallowed after the
  durable write is attempted.
* Events are pruned to MAX_STORED_EVENTS so a long-lived install doesn't
  grow state.db unboundedly.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

# Keep the most recent N events. At a few hundred events a day this is
# months of history in a file measured in low single-digit megabytes.
MAX_STORED_EVENTS = 20000

# Per-subscriber backlog before we start dropping for that subscriber.
_SUBSCRIBER_MAXSIZE = 500

# Prune every N publishes rather than on every write.
_PRUNE_EVERY = 500


@dataclass
class Event:
    type: str                       # dotted, e.g. "tool.completed", "mission.updated"
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""                # which subsystem emitted it
    correlation_id: str = ""        # groups events belonging to one turn/task
    ts: float = field(default_factory=time.time)
    id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts_human"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))
        return d


_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_publish_count = 0
_recent_publish_times: deque[float] = deque(maxlen=2000)
_persist_queue: queue.Queue[tuple[Event, Path]] = queue.Queue(maxsize=5000)
_writer_thread: threading.Thread | None = None
_writer_stop = threading.Event()
_writer_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready: set[str] = set()
_persisted_count = 0
_dropped_persistence = 0


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    key = str(path.resolve())
    with _schema_lock:
        if key not in _schema_ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, type TEXT, source TEXT, "
                "correlation_id TEXT, payload TEXT)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")
            conn.commit()
            _schema_ready.add(key)
    return conn


def _start_writer() -> None:
    global _writer_thread
    if _writer_thread is not None and _writer_thread.is_alive():
        return
    with _writer_lock:
        if _writer_thread is None or not _writer_thread.is_alive():
            _writer_stop.clear()
            _writer_thread = threading.Thread(target=_writer_loop, name="zeno-event-writer", daemon=True)
            _writer_thread.start()


def _writer_loop() -> None:
    while not _writer_stop.is_set() or not _persist_queue.empty():
        try:
            first = _persist_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        batch = [first]
        while len(batch) < 100:
            try:
                batch.append(_persist_queue.get_nowait())
            except queue.Empty:
                break
        try:
            _persist_batch(batch)
        except Exception:  # noqa: BLE001 -- telemetry persistence never breaks runtime work
            pass
        finally:
            for _ in batch:
                _persist_queue.task_done()


def _persist_batch(batch: list[tuple[Event, Path]]) -> None:
    global _persisted_count
    by_path: dict[Path, list[Event]] = {}
    for event, path in batch:
        by_path.setdefault(path, []).append(event)
    for path, events in by_path.items():
        conn = _connect(path)
        try:
            with conn:
                conn.executemany(
                    "INSERT INTO events (ts, type, source, correlation_id, payload) VALUES (?, ?, ?, ?, ?)",
                    [
                        (event.ts, event.type, event.source, event.correlation_id,
                         json.dumps(event.payload, default=str))
                        for event in events
                    ],
                )
        finally:
            conn.close()
    _persisted_count += len(batch)
    if _persisted_count % _PRUNE_EVERY < len(batch):
        for path in by_path:
            _prune(path)


def flush(timeout: float = 5.0) -> bool:
    """Wait for queued durability work (used by orderly shutdown and tests)."""
    deadline = time.monotonic() + max(0.0, timeout)
    while _persist_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    return _persist_queue.unfinished_tasks == 0


def shutdown() -> None:
    _writer_stop.set()
    flush(5.0)
    if _writer_thread is not None:
        _writer_thread.join(timeout=2.0)


def subscribe() -> queue.Queue:
    """Live feed of events as they happen. Remember to unsubscribe."""
    q: queue.Queue = queue.Queue(maxsize=_SUBSCRIBER_MAXSIZE)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(event_type: str, payload: dict | None = None, source: str = "",
            correlation_id: str = "") -> Event:
    """Record an event durably, then hand it to live subscribers.

    Never raises -- see the module docstring.
    """
    global _publish_count, _dropped_persistence
    event = Event(type=event_type, payload=payload or {}, source=source,
                  correlation_id=correlation_id)
    _publish_count += 1
    _recent_publish_times.append(event.ts)
    _start_writer()
    try:
        _persist_queue.put_nowait((event, _DB_PATH))
    except queue.Full:
        # Durable history is best effort under an event storm; foreground work
        # and live subscribers remain responsive and the drop is observable.
        _dropped_persistence += 1

    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass  # slow consumer: drop for that subscriber only
    return event


def history(limit: int = 100, event_type: str = "", since: float = 0.0,
            correlation_id: str = "") -> list[dict[str, Any]]:
    """Most-recent-first slice of the durable record. This is what a
    Timeline / Activity Stream reads."""
    sql = "SELECT id, ts, type, source, correlation_id, payload FROM events"
    clauses, params = [], []
    if event_type:
        # prefix match so "mission" returns mission.created, mission.updated...
        clauses.append("(type = ? OR type LIKE ?)")
        params.extend([event_type, event_type + ".%"])
    if since:
        clauses.append("ts >= ?")
        params.append(since)
    if correlation_id:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(2000, int(limit))))
    try:
        conn = _connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for eid, ts, etype, source, corr, payload in rows:
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        out.append({
            "id": eid,
            "ts": ts,
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "type": etype,
            "source": source,
            "correlation_id": corr,
            "payload": parsed,
        })
    return out


def stats() -> dict[str, Any]:
    """Counts by type -- feeds the dev/performance panel."""
    try:
        conn = _connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_type = conn.execute(
                "SELECT type, COUNT(*) FROM events GROUP BY type ORDER BY COUNT(*) DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {"total": 0, "by_type": {}, "subscribers": len(_subscribers)}
    return {
        "total": total,
        "by_type": {t: c for t, c in by_type},
        "subscribers": len(_subscribers),
    }


def runtime_stats() -> dict[str, Any]:
    """Cheap in-memory health used by the live profiler.

    ``stats()`` intentionally queries durable history for the Timeline. This
    path avoids a SQLite query on every performance-panel refresh.
    """
    now = time.time()
    with _lock:
        one_minute = sum(1 for ts in _recent_publish_times if ts >= now - 60)
        return {
            "published_total_process": _publish_count,
            "rate_per_minute": one_minute,
            "subscribers": len(_subscribers),
            "subscriber_backlogs": [q.qsize() for q in _subscribers],
            "subscriber_capacity": _SUBSCRIBER_MAXSIZE,
            "persistence_queue_depth": _persist_queue.qsize(),
            "persistence_queue_capacity": _persist_queue.maxsize,
            "persistence_dropped": _dropped_persistence,
        }


def _prune(path: Path | None = None) -> None:
    try:
        conn = _connect(path)
        try:
            with conn:
                conn.execute(
                    "DELETE FROM events WHERE id <= ("
                    "  SELECT MAX(id) - ? FROM events"
                    ")",
                    (MAX_STORED_EVENTS,),
                )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass
