"""Regression coverage for on-demand specialist activation and recovery."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import agent_runtime


def _reset_runtime() -> None:
    agent_runtime.shutdown()
    with agent_runtime._lock:
        agent_runtime._workers.clear()
    agent_runtime._booted_at = 0.0


def test_boot_registers_agents_without_starting_idle_threads() -> None:
    _reset_runtime()
    try:
        log = agent_runtime.boot()
        assert any("registered" in item for item in log)
        assert agent_runtime.health()["agents_active"] == 0
        assert not any(thread.name.startswith("agent-") and thread.name != "agent-supervisor"
                       for thread in threading.enumerate())
    finally:
        _reset_runtime()


def test_only_the_delegated_specialist_is_created_and_failure_is_isolated() -> None:
    _reset_runtime()
    try:
        agent_runtime.boot()
        failed = agent_runtime.submit("aris", "controlled failure", lambda: (_ for _ in ()).throw(RuntimeError("expected")))
        assert failed is not None and "RuntimeError: expected" in failed.wait(2)
        recovered = agent_runtime.submit("aris", "next task", lambda: "recovered")
        assert recovered is not None and recovered.wait(2) == "recovered"
        health = agent_runtime.health()
        assert health["agents_active"] == 1
        assert health["working_now"] == []
        assert health["agents"][0]["agent"] == "aris"
    finally:
        _reset_runtime()


def test_duplicate_specialist_submission_reuses_one_inflight_task() -> None:
    _reset_runtime()
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    try:
        agent_runtime.boot()

        def work() -> str:
            calls.append("run")
            started.set()
            release.wait(2)
            return "one result"

        first = agent_runtime.submit("tosin", "Review the deployment plan", work)
        assert first is not None and started.wait(1)
        duplicate = agent_runtime.submit("tosin", "  review the DEPLOYMENT plan ", lambda: "must not run")
        assert duplicate is first
        release.set()
        assert first.wait(2) == "one result"
        time.sleep(0.05)
        assert calls == ["run"]
        assert len([t for t in threading.enumerate() if t.name == "agent-tosin"]) == 1
    finally:
        release.set()
        _reset_runtime()


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


def test_specialist_queue_rejects_overflow_without_growing() -> None:
    original_capacity = agent_runtime.config.AGENT_QUEUE_CAPACITY
    agent_runtime.config.AGENT_QUEUE_CAPACITY = 1
    try:
        worker = agent_runtime.AgentWorker("bounded-test", "test")
        accepted = worker.submit_task("first", lambda: "first")
        rejected = worker.submit_task("second", lambda: "second")

        assert worker.queue.qsize() == 1
        assert not accepted.done.is_set()
        assert rejected.done.is_set()
        assert "queue is full" in rejected.wait(0)
        snapshot = worker.snapshot()
        assert snapshot["tasks_rejected"] == 1
        assert snapshot["queue_capacity"] == 1
    finally:
        agent_runtime.config.AGENT_QUEUE_CAPACITY = original_capacity


if __name__ == "__main__":
    raise SystemExit(_run_all())
