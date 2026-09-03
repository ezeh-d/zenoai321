from pathlib import Path

from reyes_agent.proactive_models import CheckResult, OverlapPolicy, ScheduledCheck
from reyes_agent.proactive_store import ProactiveStore


class ImmediatePool:
    def __init__(self) -> None:
        self.count = 0

    def submit(self, fn, *args, **kwargs):
        self.count += 1
        return fn(*args)


def test_heartbeat_stress_runs_one_thousand_deterministic_checks_without_overlap(tmp_path: Path) -> None:
    from reyes_agent.heartbeat_engine import HeartbeatEngine

    store = ProactiveStore(tmp_path / "stress.db")
    pool = ImmediatePool()
    engine = HeartbeatEngine(store, worker_pool=pool, clock=lambda: 100.0)
    for index in range(25):
        check = ScheduledCheck(
            id=f"stress-{index}", description="stress", enabled=True,
            interval_s=10, priority=50, timeout_s=5,
            overlap_policy=OverlapPolicy.SKIP, quiet_hours_policy="hold", handler_id="stress",
            next_due_at=100.0,
        )
        engine.register(check, lambda _context: CheckResult.no_change("stress"))

    for tick in range(40):
        engine.tick(now=100.0 + tick * 10)

    assert pool.count == 1_000
    assert engine.diagnostics()["active_checks"] == []
    assert engine.diagnostics()["recent_failures"] == []
