"""Phase 4 — durable missions. TEST B.

The claim under test is "a mission survives ZENO restarting". A test that
only calls functions in one process does not test that at all, so the
restart test below launches a REAL child python process, lets it die
mid-mission, and then checks what a fresh process finds on disk.

Run: `.venv/Scripts/python.exe tests/test_phase4_missions.py`
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _clean(key: str) -> None:
    from reyes_agent.missions import manager, store

    row = store.by_key(key)
    if row:
        store.delete(row["mission_id"])


# --- identity and idempotency -------------------------------------------

def test_the_same_request_never_creates_two_missions() -> None:
    from reyes_agent import missions

    title = "test: research three companies"
    steps = [{"action": "search"}, {"action": "read"}, {"action": "report"}]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        first, created_first = missions.ensure(title, steps)
        second, created_second = missions.ensure(title, steps)

        assert created_first is True, "the first call must create the mission"
        assert created_second is False, "the second call must NOT create a duplicate"
        assert first.mission_id == second.mission_id
        assert len(missions.store.list_missions()) >= 1
    finally:
        _clean(key)


def test_the_key_is_derived_from_the_request_not_the_clock() -> None:
    """After a restart ZENO must reach the same key from the same request."""
    from reyes_agent.missions import manager

    steps = [{"action": "search"}, {"action": "report"}]
    first = manager.key_for("Weekly report", steps)
    time.sleep(0.05)
    second = manager.key_for("weekly report", steps)      # case-insensitive
    assert first == second, "the identity must not depend on time or casing"
    assert manager.key_for("Something else", steps) != first


# --- checkpointing -------------------------------------------------------

def test_every_step_is_committed_before_the_next_one_starts() -> None:
    from reyes_agent import missions

    title = "test: checkpoint each step"
    steps = [{"action": f"step{i}"} for i in range(4)]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        mission, _ = missions.ensure(title, steps)
        seen_on_disk = []

        def runner(step, index):
            # Read the mission back from the DATABASE mid-run, not from memory.
            row = missions.store.by_id(mission.mission_id)
            seen_on_disk.append(row["cursor"])
            return True, f"did {step['action']}"

        done = missions.advance(mission, runner)
        assert done.state == missions.COMPLETED
        assert seen_on_disk == [0, 1, 2, 3], f"cursor was not persisted per step: {seen_on_disk}"

        marks = missions.history(mission.mission_id)
        assert any(m["state"] == "COMPLETED" for m in marks)
        assert len([m for m in marks if m["state"] == "RUNNING"]) == 4
    finally:
        _clean(key)


def test_a_failing_step_stops_after_bounded_retries() -> None:
    """Never an endless loop -- the brief is explicit."""
    from reyes_agent import missions

    title = "test: always fails"
    steps = [{"action": "impossible"}]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        mission, _ = missions.ensure(title, steps)
        attempts = {"n": 0}

        def runner(step, index):
            attempts["n"] += 1
            return False, "nope"

        done = missions.advance(mission, runner)
        assert done.state == missions.FAILED
        assert attempts["n"] == missions.manager.MAX_ATTEMPTS_PER_STEP, attempts
    finally:
        _clean(key)


def test_an_exception_in_a_step_fails_the_mission_not_the_process() -> None:
    from reyes_agent import missions

    title = "test: step raises"
    steps = [{"action": "explode"}]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        mission, _ = missions.ensure(title, steps)

        def runner(step, index):
            raise RuntimeError("boom")

        done = missions.advance(mission, runner)
        assert done.state == missions.FAILED
        assert "RuntimeError" in done.error and "boom" in done.error
    finally:
        _clean(key)


def test_a_finished_mission_is_never_restarted() -> None:
    from reyes_agent import missions

    title = "test: already done"
    steps = [{"action": "one"}]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        mission, _ = missions.ensure(title, steps)
        missions.advance(mission, lambda s, i: (True, "ok"))
        assert mission.state == missions.COMPLETED

        calls = {"n": 0}

        def runner(step, index):
            calls["n"] += 1
            return True, "ran again"

        missions.advance(mission, runner)
        assert calls["n"] == 0, "a COMPLETED mission must not run another step"

        for resumed in missions.resume_all():
            assert resumed.mission_id != mission.mission_id
    finally:
        _clean(key)


# --- TEST B: the actual restart -----------------------------------------

_CHILD = r'''
import sys, os
sys.path.insert(0, r"{root}")
from reyes_agent import missions

title = "test: survives a real restart"
steps = [{{"action": "a"}}, {{"action": "b"}}, {{"action": "c"}}, {{"action": "d"}}]
mission, created = missions.ensure(title, steps)
print("CREATED" if created else "RESUMED", mission.mission_id, mission.cursor, flush=True)

def runner(step, index):
    if index == 2 and os.environ.get("ZENO_TEST_DIE") == "1":
        print("DYING", flush=True)
        os._exit(9)          # a real kill: no cleanup, no finally, no mercy
    return True, "ok"

mission = missions.advance(mission, runner)
print("FINAL", mission.state, mission.cursor, flush=True)
'''


def test_a_mission_survives_the_process_being_killed() -> None:
    """TEST B. Kill a real process mid-mission; a fresh one must continue it."""
    from reyes_agent import missions

    source = _CHILD.format(root=str(ROOT))
    script = ROOT / "tests" / "_mission_child.py"
    script.write_text(source, encoding="utf-8")

    title = "test: survives a real restart"
    steps = [{"action": a} for a in ("a", "b", "c", "d")]
    key = missions.manager.key_for(title, steps)
    _clean(key)

    try:
        environment = {**dict(__import__("os").environ), "ZENO_TEST_DIE": "1",
                       "PYTHONIOENCODING": "utf-8"}
        first = subprocess.run([sys.executable, str(script)], capture_output=True,
                               text=True, timeout=120, env=environment)
        assert "CREATED" in first.stdout, first.stdout + first.stderr
        assert "DYING" in first.stdout, "the child was supposed to die mid-mission"
        assert first.returncode == 9, f"expected a hard kill, got {first.returncode}"
        assert "FINAL" not in first.stdout, "the child finished; it was meant to die"

        # What a completely fresh process finds on disk.
        row = missions.store.by_key(key)
        assert row is not None, "the mission did not survive the kill"
        assert row["cursor"] == 2, f"expected 2 committed steps, found {row['cursor']}"
        assert row["state"] not in ("COMPLETED", "FAILED")

        environment["ZENO_TEST_DIE"] = "0"
        second = subprocess.run([sys.executable, str(script)], capture_output=True,
                                text=True, timeout=120, env=environment)
        assert "RESUMED" in second.stdout, (
            "the restarted process created a NEW mission instead of resuming: "
            + second.stdout)
        assert "RESUMED" in second.stdout and " 2" in second.stdout, second.stdout
        assert "FINAL COMPLETED 4" in second.stdout, second.stdout

        assert len([m for m in missions.store.list_missions()
                    if m["key"] == key]) == 1, "a duplicate mission was created"
    finally:
        _clean(key)
        script.unlink(missing_ok=True)


def test_resume_all_picks_up_what_the_crash_interrupted() -> None:
    from reyes_agent import missions

    title = "test: interrupted"
    steps = [{"action": "x"}, {"action": "y"}]
    key = missions.manager.key_for(title, steps)
    _clean(key)
    try:
        mission, _ = missions.ensure(title, steps)
        missions.store.update(mission.mission_id, state=missions.RUNNING, cursor=1)

        resumed = missions.resume_all()
        ids = [m.mission_id for m in resumed]
        assert mission.mission_id in ids, "an interrupted mission must be picked up"
        assert missions.get(mission.mission_id).state == missions.QUEUED
    finally:
        _clean(key)


def test_status_is_honest_about_the_backend() -> None:
    from reyes_agent import missions

    state = missions.status()
    assert state["state"] == "ONLINE"
    assert len(state["states"]) == 10
    assert "SQLite" in state["backend"]
    assert missions.temporal_backend.status()["classification"] == "ARCHITECTURAL_REFERENCE"
    assert missions.temporal_backend.status()["installed"] is False


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
