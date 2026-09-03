"""SQLite persistence for scheduled proactive checks and safe notice records."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from reyes_agent.proactive_models import (
    CheckResult,
    DeliveryState,
    Importance,
    OverlapPolicy,
    ProactiveNotice,
    ProactiveSettings,
    ScheduledCheck,
    VoicePolicy,
    bounded_text,
    safe_facts,
)


_TRANSITIONS = {
    DeliveryState.NEW: {DeliveryState.HELD, DeliveryState.SURFACED, DeliveryState.EXPIRED},
    DeliveryState.HELD: {DeliveryState.SURFACED, DeliveryState.DISMISSED, DeliveryState.EXPIRED},
    DeliveryState.SURFACED: {DeliveryState.SEEN, DeliveryState.ACKNOWLEDGED, DeliveryState.DISMISSED, DeliveryState.EXPIRED},
    DeliveryState.SEEN: {DeliveryState.ACKNOWLEDGED, DeliveryState.DISMISSED, DeliveryState.EXPIRED},
    DeliveryState.ACKNOWLEDGED: {DeliveryState.DISMISSED, DeliveryState.EXPIRED},
    DeliveryState.DISMISSED: set(),
    DeliveryState.EXPIRED: set(),
}


class ProactiveStore:
    def __init__(self, path: Path, *, clock: Any = time.time) -> None:
        self.path = Path(path)
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS proactive_schema (version INTEGER NOT NULL)")
            if conn.execute("SELECT COUNT(*) FROM proactive_schema").fetchone()[0] == 0:
                conn.execute("INSERT INTO proactive_schema(version) VALUES (1)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS proactive_checks ("
                "id TEXT PRIMARY KEY, description TEXT NOT NULL, enabled INTEGER NOT NULL, "
                "interval_s INTEGER NOT NULL, priority INTEGER NOT NULL, timeout_s INTEGER NOT NULL, "
                "overlap_policy TEXT NOT NULL, quiet_hours_policy TEXT NOT NULL, handler_id TEXT NOT NULL, "
                "event_types_json TEXT NOT NULL, next_due_at REAL NOT NULL, last_run_at REAL NOT NULL, "
                "last_success_at REAL NOT NULL, last_failure_at REAL NOT NULL, consecutive_failures INTEGER NOT NULL, "
                "last_result_fingerprint TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS proactive_notices ("
                "id TEXT PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL, source TEXT NOT NULL, "
                "subject TEXT NOT NULL, condition TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE, "
                "importance TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL, facts_json TEXT NOT NULL, "
                "delivery_state TEXT NOT NULL, voice_policy TEXT NOT NULL, panel_target TEXT NOT NULL, "
                "explanation TEXT NOT NULL, count INTEGER NOT NULL, surfaced_at REAL NOT NULL, seen_at REAL NOT NULL, "
                "acknowledged_at REAL NOT NULL, expires_at REAL NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proactive_notices_state ON proactive_notices(delivery_state, updated_at DESC)")
            conn.execute("CREATE TABLE IF NOT EXISTS proactive_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    @staticmethod
    def _row_to_check(row: sqlite3.Row) -> ScheduledCheck:
        return ScheduledCheck(
            id=row["id"], description=row["description"], enabled=bool(row["enabled"]),
            interval_s=row["interval_s"], priority=row["priority"], timeout_s=row["timeout_s"],
            overlap_policy=OverlapPolicy(row["overlap_policy"]), quiet_hours_policy=row["quiet_hours_policy"],
            handler_id=row["handler_id"], event_types=tuple(json.loads(row["event_types_json"])),
            next_due_at=row["next_due_at"], last_run_at=row["last_run_at"],
            last_success_at=row["last_success_at"], last_failure_at=row["last_failure_at"],
            consecutive_failures=row["consecutive_failures"], last_result_fingerprint=row["last_result_fingerprint"],
        )

    @staticmethod
    def _row_to_notice(row: sqlite3.Row) -> ProactiveNotice:
        return ProactiveNotice(
            id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"], source=row["source"],
            subject=row["subject"], condition=row["condition"], dedupe_key=row["dedupe_key"],
            importance=Importance(row["importance"]), title=row["title"], summary=row["summary"],
            facts=safe_facts(json.loads(row["facts_json"])), delivery_state=DeliveryState(row["delivery_state"]),
            voice_policy=VoicePolicy(row["voice_policy"]), panel_target=row["panel_target"], explanation=row["explanation"],
            count=row["count"], surfaced_at=row["surfaced_at"], seen_at=row["seen_at"],
            acknowledged_at=row["acknowledged_at"], expires_at=row["expires_at"],
        )

    def upsert_check(self, check: ScheduledCheck) -> ScheduledCheck:
        self.migrate()
        safe = replace(check, id=bounded_text(check.id, 80), description=bounded_text(check.description),
                       handler_id=bounded_text(check.handler_id, 80), quiet_hours_policy=bounded_text(check.quiet_hours_policy, 40))
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM proactive_checks WHERE id=?", (safe.id,)).fetchone()
            if existing is not None:
                current = self._row_to_check(existing)
                safe = replace(safe, next_due_at=current.next_due_at, last_run_at=current.last_run_at,
                               last_success_at=current.last_success_at, last_failure_at=current.last_failure_at,
                               consecutive_failures=current.consecutive_failures,
                               last_result_fingerprint=current.last_result_fingerprint)
            conn.execute(
                "INSERT INTO proactive_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET description=excluded.description, enabled=excluded.enabled, "
                "interval_s=excluded.interval_s, priority=excluded.priority, timeout_s=excluded.timeout_s, "
                "overlap_policy=excluded.overlap_policy, quiet_hours_policy=excluded.quiet_hours_policy, "
                "handler_id=excluded.handler_id, event_types_json=excluded.event_types_json, next_due_at=excluded.next_due_at, "
                "last_run_at=excluded.last_run_at, last_success_at=excluded.last_success_at, "
                "last_failure_at=excluded.last_failure_at, consecutive_failures=excluded.consecutive_failures, "
                "last_result_fingerprint=excluded.last_result_fingerprint",
                (safe.id, safe.description, int(safe.enabled), safe.interval_s, safe.priority, safe.timeout_s,
                 safe.overlap_policy.value, safe.quiet_hours_policy, safe.handler_id, json.dumps(safe.event_types),
                 safe.next_due_at, safe.last_run_at, safe.last_success_at, safe.last_failure_at,
                 safe.consecutive_failures, safe.last_result_fingerprint),
            )
        return safe

    def load_checks(self) -> list[ScheduledCheck]:
        self.migrate()
        with self._connect() as conn:
            return [self._row_to_check(row) for row in conn.execute("SELECT * FROM proactive_checks ORDER BY id")]

    def get_check(self, check_id: str) -> ScheduledCheck | None:
        """Return one persisted check without claiming or changing its schedule."""
        self.migrate()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_checks WHERE id=?", (bounded_text(check_id, 80),)
            ).fetchone()
        return self._row_to_check(row) if row is not None else None

    def claim_due(self, check_id: str, *, now: float | None = None) -> ScheduledCheck | None:
        self.migrate()
        now = self._clock() if now is None else float(now)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proactive_checks WHERE id=?", (bounded_text(check_id, 80),)).fetchone()
            if row is None:
                return None
            check = self._row_to_check(row)
            if not check.enabled or check.next_due_at > now:
                return None
            next_due = now + check.interval_s
            changed = conn.execute(
                "UPDATE proactive_checks SET next_due_at=?, last_run_at=? WHERE id=? AND next_due_at<=?",
                (next_due, now, check.id, now),
            ).rowcount
            if changed != 1:
                return None
        return replace(check, next_due_at=next_due, last_run_at=now)

    def claim_event(self, check_id: str, *, now: float | None = None) -> ScheduledCheck | None:
        """Claim an event-triggered run without creating an extra timer schedule."""
        self.migrate()
        now = self._clock() if now is None else float(now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_checks WHERE id=?", (bounded_text(check_id, 80),)
            ).fetchone()
            if row is None:
                return None
            check = self._row_to_check(row)
            if not check.enabled:
                return None
            conn.execute("UPDATE proactive_checks SET last_run_at=? WHERE id=?", (now, check.id))
        return replace(check, last_run_at=now)

    def record_check_success(self, check_id: str, result: CheckResult, *, now: float | None = None) -> None:
        """Persist a completion independently from whether it produced a notice."""
        self.migrate()
        now = self._clock() if now is None else float(now)
        fingerprint = result.dedupe_key if result.changed else ""
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE proactive_checks SET last_success_at=?, consecutive_failures=0, "
                "last_result_fingerprint=? WHERE id=?",
                (now, bounded_text(fingerprint, 400), bounded_text(check_id, 80)),
            ).rowcount
            if changed != 1:
                raise KeyError("unknown proactive check")

    def record_check_failure(self, check_id: str, *, now: float | None = None) -> None:
        """Record a failed check without allowing one failure to stop the heartbeat."""
        self.migrate()
        now = self._clock() if now is None else float(now)
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE proactive_checks SET last_failure_at=?, consecutive_failures=consecutive_failures+1 "
                "WHERE id=?",
                (now, bounded_text(check_id, 80)),
            ).rowcount
            if changed != 1:
                raise KeyError("unknown proactive check")

    def upsert_notice(self, result: CheckResult, *, importance: Importance = Importance.INBOX,
                      title: str = "", explanation: str = "") -> ProactiveNotice:
        if not result.changed:
            raise ValueError("only changed check results may create notices")
        self.migrate()
        now = self._clock()
        dedupe_key = result.dedupe_key
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proactive_notices WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            if row is not None:
                current = self._row_to_notice(row)
                conn.execute("UPDATE proactive_notices SET updated_at=?, summary=?, facts_json=?, count=? WHERE id=?",
                             (now, bounded_text(result.summary), json.dumps(safe_facts(result.facts)), current.count + 1, current.id))
                return replace(current, updated_at=now, summary=bounded_text(result.summary), facts=safe_facts(result.facts), count=current.count + 1)
            notice = ProactiveNotice(
                id=uuid.uuid4().hex, created_at=now, updated_at=now, source=result.source, subject=result.subject,
                condition=result.condition, dedupe_key=dedupe_key, importance=importance,
                title=bounded_text(title or result.summary, 160), summary=bounded_text(result.summary), facts=safe_facts(result.facts),
                delivery_state=DeliveryState.NEW, panel_target=result.panel_target,
                explanation=bounded_text(explanation or f"{result.source} changed: {result.condition}", 300),
            )
            conn.execute("INSERT INTO proactive_notices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (notice.id, notice.created_at, notice.updated_at, notice.source, notice.subject, notice.condition,
                          notice.dedupe_key, notice.importance.value, notice.title, notice.summary, json.dumps(notice.facts),
                          notice.delivery_state.value, notice.voice_policy.value, notice.panel_target, notice.explanation,
                          notice.count, 0.0, 0.0, 0.0, notice.expires_at))
        return notice

    def transition_notice(self, notice_id: str, state: DeliveryState) -> ProactiveNotice:
        self.migrate()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proactive_notices WHERE id=?", (str(notice_id),)).fetchone()
            if row is None:
                raise KeyError("unknown proactive notice")
            current = self._row_to_notice(row)
            if state not in _TRANSITIONS[current.delivery_state]:
                raise ValueError("invalid notice transition")
            now = self._clock()
            fields = {"updated_at": now}
            if state is DeliveryState.SURFACED: fields["surfaced_at"] = now
            if state is DeliveryState.SEEN: fields["seen_at"] = now
            if state is DeliveryState.ACKNOWLEDGED: fields["acknowledged_at"] = now
            conn.execute("UPDATE proactive_notices SET delivery_state=?, updated_at=?, surfaced_at=?, seen_at=?, acknowledged_at=? WHERE id=?",
                         (state.value, fields.get("updated_at", current.updated_at), fields.get("surfaced_at", current.surfaced_at),
                          fields.get("seen_at", current.seen_at), fields.get("acknowledged_at", current.acknowledged_at), current.id))
        return replace(current, delivery_state=state, **fields)

    def list_notices(self, *, state: DeliveryState | None = None, limit: int = 50) -> list[ProactiveNotice]:
        self.migrate()
        limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            if state is None:
                rows = conn.execute("SELECT * FROM proactive_notices ORDER BY updated_at DESC LIMIT ?", (limit,))
            else:
                rows = conn.execute("SELECT * FROM proactive_notices WHERE delivery_state=? ORDER BY updated_at DESC LIMIT ?", (state.value, limit))
            return [self._row_to_notice(row) for row in rows]

    def public_notice(self, notice: ProactiveNotice) -> dict[str, Any]:
        return {"id": notice.id, "created_at": notice.created_at, "updated_at": notice.updated_at,
                "source": notice.source, "subject": notice.subject, "condition": notice.condition,
                "importance": notice.importance.value, "title": notice.title, "summary": notice.summary,
                "facts": safe_facts(notice.facts), "state": notice.delivery_state.value,
                "voice_policy": notice.voice_policy.value, "panel_target": notice.panel_target,
                "explanation": notice.explanation, "count": notice.count}

    def diagnostics(self) -> dict[str, Any]:
        checks = self.load_checks()
        return {"checks": len(checks), "enabled_checks": sum(check.enabled for check in checks),
                "held_notices": len(self.list_notices(state=DeliveryState.HELD)),
                "notices": len(self.list_notices(limit=500))}
