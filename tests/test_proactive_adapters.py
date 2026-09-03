from __future__ import annotations

from pathlib import Path


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def schedule(self, name, fn, **kwargs):
        self.jobs[name] = {"fn": fn, **kwargs}
        return self.jobs[name]

    def cancel(self, name):
        return self.jobs.pop(name, None) is not None


class ImmediatePool:
    def submit(self, fn, *args, **kwargs):
        return fn(*args)


def test_proactive_adapters_register_with_the_shared_heartbeat_only(tmp_path: Path) -> None:
    from reyes_agent import heartbeat, proactive

    scheduler = FakeScheduler()
    heartbeat._configure_for_tests(tmp_path / "state.db", scheduler=scheduler, worker_pool=ImmediatePool())
    proactive.start_background()

    assert set(scheduler.jobs) == {"heartbeat"}
    assert heartbeat.get_heartbeat_engine().diagnostics()["registered_checks"] >= 5
