"""Fast, offline regression tests for the Phase 21 runtime safeguards."""

from __future__ import annotations

import threading
import time
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import event_bus, memory_manager, notification_bus, performance_monitor
from reyes_agent.scheduler import BackgroundScheduler
from reyes_agent.browser_runtime import BrowserRuntime
from reyes_agent.worker_pool import (
    PRIORITY_BACKGROUND,
    PRIORITY_VOICE,
    ManagedWorkerPool,
    TaskCancelled,
)


def test_worker_pool_prioritises_live_work_over_queued_background() -> None:
    pool = ManagedWorkerPool(max_workers=1, max_queue=8, thread_name_prefix="phase21-test")
    gate = threading.Event()
    started = threading.Event()
    order: list[str] = []

    def block() -> None:
        started.set()
        gate.wait(2)

    pool.submit(block, name="blocker")
    assert started.wait(1)
    low = pool.submit(lambda: order.append("background"), priority=PRIORITY_BACKGROUND)
    high = pool.submit(lambda: order.append("voice"), priority=PRIORITY_VOICE)
    gate.set()
    high.result(2)
    low.result(2)
    assert order == ["voice", "background"]
    pool.shutdown()


def test_worker_pool_retries_and_cancels_pending_work() -> None:
    pool = ManagedWorkerPool(max_workers=1, max_queue=8, thread_name_prefix="phase21-test")
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("temporary")
        return "recovered"

    recovered = pool.submit(flaky, retries=2, retry_backoff=0.01)
    assert recovered.result(2) == "recovered"
    assert recovered.attempts == 3

    gate = threading.Event()
    started = threading.Event()
    pool.submit(lambda: (started.set(), gate.wait(2)), name="blocker")
    assert started.wait(1)
    cancelled = pool.submit(lambda: "should-not-run", name="cancelled")
    assert cancelled.cancel()
    gate.set()
    try:
        cancelled.result(2)
    except TaskCancelled:
        pass
    else:
        raise AssertionError("Cancelled pending work completed unexpectedly")
    pool.shutdown()


def test_scheduler_prevents_overlapping_periodic_runs() -> None:
    pool = ManagedWorkerPool(max_workers=2, max_queue=8, thread_name_prefix="phase21-scheduler")
    scheduler = BackgroundScheduler()
    active = 0
    maximum_active = 0
    runs = 0
    lock = threading.Lock()

    def slow_tick() -> None:
        nonlocal active, maximum_active, runs
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            runs += 1
        time.sleep(0.05)
        with lock:
            active -= 1

    # Redirect the scheduler module's singleton accessor only for this test.
    import reyes_agent.scheduler as scheduler_module

    original = scheduler_module.get_worker_pool
    scheduler_module.get_worker_pool = lambda: pool
    try:
        scheduler.schedule("slow", slow_tick, interval=0.01)
        time.sleep(0.16)
        scheduler.cancel("slow")
    finally:
        scheduler_module.get_worker_pool = original
        scheduler.shutdown()
        pool.shutdown()
    assert runs >= 2
    assert maximum_active == 1


def test_history_is_bounded_and_archived() -> None:
    original = memory_manager._ARCHIVE_PATH
    with tempfile.TemporaryDirectory() as temp_dir:
        memory_manager._ARCHIVE_PATH = Path(temp_dir) / "history.jsonl"
        try:
            history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(32)]
            removed = memory_manager.trim_history(history, max_messages=20)
            assert removed > 0
            assert len(history) <= 20
            assert history[0]["role"] == "user"
            assert memory_manager._ARCHIVE_PATH.read_text(encoding="utf-8").strip()
        finally:
            memory_manager._ARCHIVE_PATH = original


def test_notification_subscriber_is_bounded() -> None:
    q = notification_bus.subscribe()
    try:
        for i in range(250):
            notification_bus.publish({"type": "test", "n": i})
        assert q.qsize() <= 100
    finally:
        notification_bus.unsubscribe(q)


def test_event_bus_batches_durably_without_blocking_publishers() -> None:
    original = event_bus._DB_PATH
    assert event_bus.flush(5)
    with tempfile.TemporaryDirectory() as temp_dir:
        event_bus._DB_PATH = Path(temp_dir) / "events.db"
        try:
            started = time.perf_counter()
            for index in range(250):
                event_bus.publish("test.batch", {"index": index}, source="phase21-test")
            publish_seconds = time.perf_counter() - started
            assert publish_seconds < 1.0
            assert event_bus.flush(5)
            assert len(event_bus.history(limit=300, event_type="test.batch")) == 250
        finally:
            event_bus._DB_PATH = original


def test_freeze_record_captures_and_rotates_to_configured_log() -> None:
    original = performance_monitor._LOG_PATH
    with tempfile.TemporaryDirectory() as temp_dir:
        performance_monitor._LOG_PATH = Path(temp_dir) / "freezes.jsonl"
        try:
            record = performance_monitor.record_freeze(
                0.25, subsystem="test", source=f"pytest-{time.monotonic()}"
            )
            assert record is not None
            assert record["thread_stacks"] == {}
            assert record["duration_ms"] >= 200
            assert record["call_stack"] == []
            assert performance_monitor._LOG_PATH.exists()
        finally:
            performance_monitor._LOG_PATH = original


def test_desktop_heartbeat_captures_stacks_only_for_a_real_delay() -> None:
    original = performance_monitor._LOG_PATH
    with tempfile.TemporaryDirectory() as temp_dir:
        performance_monitor._LOG_PATH = Path(temp_dir) / "host-freezes.jsonl"
        try:
            before = len(performance_monitor._freezes)
            delay = performance_monitor.record_host_heartbeat(time.time() - 0.6, active_callback="move_window")
            assert delay >= 0.5
            record = list(performance_monitor._freezes)[-1]
            assert len(performance_monitor._freezes) >= before
            assert record["subsystem"] == "desktop_webview_bridge"
            assert record["thread_stacks"]
            assert record["details"]["active_callback"] == "move_window"
        finally:
            performance_monitor._LOG_PATH = original


def test_mini_drag_coalesces_webview_bridge_calls() -> None:
    source = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    assert "moveInFlight" in source
    assert "queuedMove" in source
    assert "requestAnimationFrame(flushMove)" in source
    assert "host_heartbeat" in source


def test_browser_runtime_keeps_all_actions_on_one_owner_thread() -> None:
    runtime = BrowserRuntime()
    owner: dict[str, int] = {}

    def open_context() -> int:
        owner["thread"] = threading.get_ident()
        return owner["thread"]

    def use_context() -> int:
        assert threading.get_ident() == owner["thread"]
        return threading.get_ident()

    try:
        assert runtime.run("open", open_context, timeout=2) == runtime.run("use", use_context, timeout=2)
        metrics = runtime.metrics()
        assert metrics["workers"] == 1
        assert metrics["queue_capacity"] == 16
    finally:
        runtime.shutdown()


def test_browser_runtime_returns_at_its_deadline_without_blocking_caller() -> None:
    """A bad browser action must not hold a web/UI-facing caller forever."""
    runtime = BrowserRuntime()
    finished = threading.Event()

    def stalled_action() -> None:
        time.sleep(0.15)
        finished.set()

    started = time.monotonic()
    try:
        try:
            runtime.run("stalled", stalled_action, timeout=0.04)
        except TimeoutError:
            pass
        else:
            raise AssertionError("A stalled browser action did not time out")
        assert time.monotonic() - started < 0.12
        assert finished.wait(1.0)
        # The same dedicated owner worker remains usable after the timed-out
        # caller returns; this mirrors a Playwright operation completing just
        # after its requested deadline.
        assert runtime.run("recovered", lambda: "ok", timeout=1) == "ok"
    finally:
        runtime.shutdown()


def test_browser_launch_and_navigation_defaults_are_bounded() -> None:
    source = (ROOT / "reyes_agent" / "browser_controller.py").read_text(encoding="utf-8")
    assert "launch_persistent_context(" in source
    assert "timeout=_DEFAULT_TIMEOUT_MS" in source
    assert "set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)" in source


def test_browser_runtime_closes_thread_affine_context_before_worker_shutdown() -> None:
    import reyes_agent.browser_controller as controller

    runtime = BrowserRuntime()
    closed_on: list[int] = []
    original_is_open, original_close = controller.is_open, controller.close_browser
    controller.is_open = lambda: True
    controller.close_browser = lambda: closed_on.append(threading.get_ident())
    try:
        owner = runtime.run("establish-owner", threading.get_ident, timeout=1)
        runtime.shutdown()
        assert closed_on == [owner]
    finally:
        controller.is_open, controller.close_browser = original_is_open, original_close


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 -- standalone test report
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
