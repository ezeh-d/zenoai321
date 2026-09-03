from __future__ import annotations

from pathlib import Path

import pytest

from reyes_agent.proactive_models import (
    CheckResult,
    DeliveryState,
    OverlapPolicy,
    ScheduledCheck,
)
from reyes_agent.proactive_store import ProactiveStore


def _check() -> ScheduledCheck:
    return ScheduledCheck(
        id="calendar",
        description="Calendar due events",
        enabled=True,
        interval_s=300,
        priority=20,
        timeout_s=30,
        overlap_policy=OverlapPolicy.SKIP,
        quiet_hours_policy="hold",
        handler_id="calendar_due",
    )


def _result() -> CheckResult:
    return CheckResult.changed(
        source="battery",
        subject="laptop",
        condition="low",
        summary="Battery at 15 percent",
    )


def test_store_persists_typed_check_and_notice(tmp_path: Path) -> None:
    store = ProactiveStore(tmp_path / "state.db")
    store.migrate()

    stored = store.upsert_check(_check())
    notice = store.upsert_notice(_result())

    assert stored.handler_id == "calendar_due"
    assert store.load_checks() == [stored]
    assert notice.delivery_state is DeliveryState.NEW
    assert notice.dedupe_key == "battery:laptop:low"


def test_notice_dedupe_updates_one_record_and_validates_transitions(tmp_path: Path) -> None:
    store = ProactiveStore(tmp_path / "state.db")
    store.migrate()

    first = store.upsert_notice(_result())
    second = store.upsert_notice(_result())
    held = store.transition_notice(first.id, DeliveryState.HELD)

    assert second.id == first.id
    assert second.count == 2
    assert held.delivery_state is DeliveryState.HELD
    with pytest.raises(ValueError, match="invalid notice transition"):
        store.transition_notice(first.id, DeliveryState.NEW)


def test_claim_due_persists_next_run_and_never_claims_twice(tmp_path: Path) -> None:
    store = ProactiveStore(tmp_path / "state.db")
    store.migrate()
    store.upsert_check(_check())

    first = store.claim_due("calendar", now=1_000.0)
    second = store.claim_due("calendar", now=1_001.0)
    restored = ProactiveStore(tmp_path / "state.db")

    assert first is not None
    assert second is None
    assert restored.load_checks()[0].next_due_at == 1_300.0


def test_snapshot_never_persists_sensitive_facts(tmp_path: Path) -> None:
    store = ProactiveStore(tmp_path / "state.db")
    store.migrate()
    notice = store.upsert_notice(CheckResult.changed(
        source="provider", subject="primary", condition="degraded",
        summary="Provider degraded", facts={"token": "secret", "latency_ms": 120},
    ))

    row = store.public_notice(notice)

    assert row["facts"] == {"latency_ms": 120}
    assert "secret" not in repr(row)
