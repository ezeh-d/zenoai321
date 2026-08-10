"""Phase 4 — the watchdog. TEST J.

The point of these tests is the STOPPING, not the restarting. Anything can
restart a process; the requirement is "never continuously restart a crashing
process forever", and that is what most of this file checks.

Run: `.venv/Scripts/python.exe tests/test_phase4_health.py`
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh():
    from reyes_agent.health import watchdog

    watchdog.clear_registry()
    watchdog.MIN_RESTART_GAP_S = 0.0        # tests must not wait out the throttle
    return watchdog


# --- TEST J: detect, recover, verify -------------------------------------

def test_a_stopped_worker_is_detected_and_brought_back() -> None:
    """TEST J. The happy path -- and the verification that it really worked."""
    watchdog = _fresh()
    running = {"up": True}

    watchdog.register("voice worker",
                      check=lambda: running["up"],
                      restart=lambda: running.__setitem__("up", True))

    assert watchdog.inspect("voice worker")[0].status == watchdog.HEALTHY

    running["up"] = False                    # the worker dies
    outcomes = watchdog.heal("voice worker")

    assert len(outcomes) == 1
    assert outcomes[0]["action"] == "restarted"
    assert outcomes[0]["result"] == watchdog.HEALTHY
    assert running["up"] is True


def test_a_restart_that_did_not_work_is_not_reported_as_recovery() -> None:
    """The step that makes it honest: verify, do not assume."""
    watchdog = _fresh()
    watchdog.register("stuck worker",
                      check=lambda: False,               # never recovers
                      restart=lambda: True)              # restart "succeeds"

    outcomes = watchdog.heal("stuck worker")
    assert outcomes[0]["result"] != watchdog.HEALTHY, (
        "a restart that returned cleanly must not count as a recovery when the "
        "subsystem is still failing")


def test_it_stops_restarting_rather_than_looping_forever() -> None:
    """The requirement, stated plainly in the brief."""
    watchdog = _fresh()
    attempts = {"n": 0}

    def restart():
        attempts["n"] += 1
        return True

    watchdog.register("crash loop", check=lambda: False, restart=restart)

    for _ in range(12):
        watchdog.heal("crash loop")

    assert attempts["n"] <= watchdog.MAX_RESTARTS, (
        f"restarted {attempts['n']} times -- this is the loop the brief forbids")

    subsystem = watchdog.inspect("crash loop")[0]
    assert subsystem.breaker == watchdog.OPEN
    assert subsystem.status == watchdog.DEGRADED

    last = watchdog.heal("crash loop")[0]
    assert last["action"] in ("gave_up", "refused")
    assert "will not try again" in last["detail"] or "stopped restarting" in last["detail"]


def test_an_open_breaker_only_clears_when_the_owner_says_so() -> None:
    watchdog = _fresh()
    watchdog.register("bad worker", check=lambda: False, restart=lambda: True)
    for _ in range(6):
        watchdog.heal("bad worker")
    assert watchdog.inspect("bad worker")[0].breaker == watchdog.OPEN

    watchdog.reset("bad worker")
    subsystem = watchdog.inspect("bad worker")[0]
    assert subsystem.breaker == watchdog.CLOSED and subsystem.restarts == 0


def test_a_subsystem_with_no_restart_is_degraded_not_retried() -> None:
    watchdog = _fresh()
    watchdog.register("external service", check=lambda: False)

    outcome = watchdog.heal("external service")[0]
    assert outcome["action"] == "none"
    assert outcome["result"] == watchdog.DEGRADED
    assert "no restart is defined" in outcome["detail"]


def test_a_check_that_raises_is_a_failure_not_a_crash() -> None:
    watchdog = _fresh()

    def explode():
        raise RuntimeError("the check itself is broken")

    watchdog.register("broken check", check=explode)
    subsystem = watchdog.inspect("broken check")[0]
    assert subsystem.status == watchdog.FAILED
    assert "RuntimeError" in subsystem.last_error
    watchdog.heal()                                  # must not raise


def test_a_restart_that_raises_does_not_take_zeno_down() -> None:
    watchdog = _fresh()

    def explode():
        raise OSError("cannot spawn")

    watchdog.register("unspawnable", check=lambda: False, restart=explode)
    outcome = watchdog.heal("unspawnable")[0]
    assert outcome["result"] in (watchdog.FAILED, watchdog.DEGRADED)
    assert "OSError" in outcome["detail"]


def test_a_critical_failure_shows_in_the_overall_verdict() -> None:
    watchdog = _fresh()
    watchdog.register("memory", check=lambda: True)
    watchdog.register("core", check=lambda: False, critical=True)

    state = watchdog.status()
    assert state["overall"] == watchdog.FAILED
    assert "core" in state["degraded"]


def test_event_history_is_bounded() -> None:
    """A watchdog that leaks memory is a liability, not a safeguard."""
    watchdog = _fresh()
    subsystem = watchdog.register("noisy", check=lambda: True)
    for i in range(200):
        subsystem.note("tick", str(i))
    assert len(subsystem.events) <= 20


# --- real process metrics ------------------------------------------------

def test_process_metrics_are_measured_not_invented() -> None:
    from reyes_agent.health import processes

    if not processes.available():
        return                                   # psutil absent: nothing to assert
    metrics = processes.self_metrics()
    assert metrics["available"] is True
    assert metrics["pid"] > 0
    assert metrics["memory_mb"] > 0, "a running process uses memory"
    assert metrics["threads"] >= 1
    assert processes.alive(metrics["pid"]) is True
    assert processes.alive(99999999) is False


def test_it_only_looks_at_zenos_own_processes() -> None:
    """Reporting on the owner's other applications would be surveillance."""
    from reyes_agent.health import processes

    state = processes.status()
    assert "own process tree only" in state["scope"]
    for twin in state["duplicate_zeno_processes"]:
        assert "reyes_agent" in twin["cmdline"], "only ZENO processes may be listed"


def test_status_never_raises() -> None:
    from reyes_agent import health

    _fresh()
    state = health.status()
    assert state["state"] == "ONLINE"
    assert "processes" in state and "watchdog" in state


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
