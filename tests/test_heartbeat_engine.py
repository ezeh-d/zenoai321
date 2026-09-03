from __future__ import annotations

from pathlib import Path

from reyes_agent.proactive_models import CheckResult, OverlapPolicy, ScheduledCheck
from reyes_agent.proactive_store import ProactiveStore


class ImmediatePool:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, fn, *args, name=None, **kwargs):
        self.submissions.append(name or "")
        fn(*args)


class DeferredPool:
    def __init__(self) -> None:
        self.submissions: list[tuple] = []

    def submit(self, fn, *args, name=None, **kwargs):
        self.submissions.append((fn, args, name))

    def run_next(self) -> None:
        fn, args, _name = self.submissions.pop(0)
        fn(*args)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.cancelled: list[str] = []

    def schedule(self, name, fn, **kwargs):
        self.jobs[name] = {"fn": fn, **kwargs}
        return self.jobs[name]

    def cancel(self, name):
        self.cancelled.append(name)
        return self.jobs.pop(name, None) is not None


def check(*, check_id: str = "calendar-summary", next_due_at: float = 0.0,
          event_types: tuple[str, ...] = ()) -> ScheduledCheck:
    return ScheduledCheck(
        id=check_id,
        description="Summarise the next calendar item",
        enabled=True,
        interval_s=10,
        priority=50,
        timeout_s=15,
        overlap_policy=OverlapPolicy.SKIP,
        quiet_hours_policy="hold",
        handler_id="calendar.summary",
        event_types=event_types,
        next_due_at=next_due_at,
    )


def test_engine_claims_due_check_runs_handler_and_persists_success(tmp_path: Path) -> None:
    from reyes_agent.heartbeat_engine import HeartbeatEngine

    store = ProactiveStore(tmp_path / "heartbeat.db")
    pool = ImmediatePool()
    engine = HeartbeatEngine(store, worker_pool=pool, clock=lambda: 100.0)
    engine.register(check(next_due_at=100.0), lambda _context: CheckResult.no_change("calendar"))

    assert engine.tick(now=100.0) == ["calendar-summary"]
    persisted = next(item for item in store.load_checks() if item.id == "calendar-summary")
    assert pool.submissions == ["heartbeat:calendar-summary"]
    assert persisted.last_success_at == 100.0
    assert persisted.consecutive_failures == 0


def test_engine_skips_active_check_without_claiming_another_run(tmp_path: Path) -> None:
    from reyes_agent.heartbeat_engine import HeartbeatEngine

    store = ProactiveStore(tmp_path / "heartbeat.db")
    pool = DeferredPool()
    engine = HeartbeatEngine(store, worker_pool=pool, clock=lambda: 100.0)
    engine.register(check(next_due_at=100.0), lambda _context: CheckResult.no_change("calendar"))

    assert engine.tick(now=100.0) == ["calendar-summary"]
    assert engine.tick(now=110.0) == []
    assert engine.diagnostics()["skipped_overlap"] == 1
    assert len(pool.submissions) == 1

    pool.run_next()
    assert engine.tick(now=110.0) == ["calendar-summary"]


def test_engine_uses_the_existing_scheduler_and_can_pause(tmp_path: Path) -> None:
    from reyes_agent.heartbeat_engine import HeartbeatEngine

    scheduler = FakeScheduler()
    engine = HeartbeatEngine(
        ProactiveStore(tmp_path / "heartbeat.db"),
        worker_pool=ImmediatePool(),
        scheduler=scheduler,
        clock=lambda: 100.0,
        tick_interval_s=30,
    )
    engine.start()
    engine.start()
    assert set(scheduler.jobs) == {"heartbeat"}
    assert scheduler.jobs["heartbeat"]["interval"] == 30

    engine.pause("focus")
    assert engine.tick(now=100.0) == []
    assert engine.diagnostics()["paused"] is True
    engine.resume()
    engine.stop()
    assert scheduler.cancelled == ["heartbeat"]


def test_engine_isolates_handler_failures_and_runs_event_checks(tmp_path: Path) -> None:
    from reyes_agent.heartbeat_engine import HeartbeatEngine

    store = ProactiveStore(tmp_path / "heartbeat.db")
    engine = HeartbeatEngine(store, worker_pool=ImmediatePool(), clock=lambda: 100.0)
    engine.register(
        check(check_id="broken", next_due_at=100.0),
        lambda _context: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    engine.register(
        check(check_id="event-check", next_due_at=200.0, event_types=("calendar.changed",)),
        lambda context: CheckResult.changed(
            "calendar", "agenda", "changed", f"event={context.event_type}"
        ),
    )

    assert engine.tick(now=100.0) == ["broken"]
    broken = next(item for item in store.load_checks() if item.id == "broken")
    assert broken.consecutive_failures == 1
    assert engine.trigger_event("calendar.changed", now=100.0) == ["event-check"]
    assert store.list_notices()[0].summary == "event=calendar.changed"
