from __future__ import annotations

from pathlib import Path
import json


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


def test_legacy_notice_api_uses_the_proactive_inbox_and_lifecycle(tmp_path: Path) -> None:
    from reyes_agent import heartbeat

    heartbeat._configure_for_tests(tmp_path / "state.db", scheduler=FakeScheduler(), worker_pool=ImmediatePool())
    heartbeat._add_notice("calendar", "Reminder: call Ada")

    notices = heartbeat.list_notices()
    assert len(notices) == 1
    assert notices[0]["source"] == "calendar"
    assert notices[0]["state"] == "SURFACED"
    assert heartbeat.dismiss_notice(notices[0]["id"]) is True
    assert heartbeat.list_notices() == []


def test_legacy_heartbeat_start_registers_only_the_shared_engine_job(tmp_path: Path) -> None:
    from reyes_agent import heartbeat

    scheduler = FakeScheduler()
    heartbeat._configure_for_tests(tmp_path / "state.db", scheduler=scheduler, worker_pool=ImmediatePool())
    heartbeat.start_background()

    assert set(scheduler.jobs) == {"heartbeat"}
    assert scheduler.jobs["heartbeat"]["interval"] == 30
    assert heartbeat.get_heartbeat_engine().diagnostics()["registered_checks"] >= 1
    assert heartbeat.proactive_status()["engine"]["running"] is True


def test_focus_mode_persists_and_pauses_the_heartbeat_without_disabling_inbox(tmp_path: Path) -> None:
    from reyes_agent import heartbeat

    heartbeat._configure_for_tests(tmp_path / "state.db", scheduler=FakeScheduler(), worker_pool=ImmediatePool())
    heartbeat.set_focus_mode(True)
    assert heartbeat.proactive_status()["focus_mode"] is True
    assert heartbeat.get_heartbeat_engine().diagnostics()["paused_reason"] == "focus mode"

    heartbeat.set_focus_mode(False)
    assert heartbeat.proactive_status()["focus_mode"] is False
    assert heartbeat.get_heartbeat_engine().diagnostics()["paused"] is False


def test_proactive_control_uses_the_same_focus_and_catch_up_paths(tmp_path: Path) -> None:
    from reyes_agent import heartbeat

    heartbeat._configure_for_tests(tmp_path / "state.db", scheduler=FakeScheduler(), worker_pool=ImmediatePool())
    assert json.loads(heartbeat.proactive_control("focus_on"))["focus_mode"] is True
    assert json.loads(heartbeat.proactive_control("focus_off"))["focus_mode"] is False
    assert json.loads(heartbeat.proactive_control("catch_up"))["summary"] == "No held updates."
