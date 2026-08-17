"""Focused regression tests for Phase 22 validation and lifecycle cleanup."""

from __future__ import annotations

import ast
import sys
import threading
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import agent_runtime, event_bus
from reyes_agent import config, voice_manager
from reyes_agent.provider import ProviderError, run_turn
from reyes_agent.worker_pool import ManagedWorkerPool


def test_agent_restart_never_leaves_a_duplicate_worker() -> None:
    worker = agent_runtime.AgentWorker("phase22-test")
    original = agent_runtime._workers.get(worker.agent_id)
    agent_runtime._workers[worker.agent_id] = worker
    gate = threading.Event()
    entered = threading.Event()
    try:
        worker.start()
        original_thread = worker._thread
        task = agent_runtime.submit(worker.agent_id, "blocking test", lambda: (entered.set(), gate.wait(5), "done")[-1])
        assert task is not None and entered.wait(1)
        message = agent_runtime.restart(worker.agent_id, reason="phase22 test")
        assert "waiting" in message
        assert original_thread is not None and original_thread.is_alive()
        assert len([t for t in threading.enumerate() if t.name == "agent-phase22-test"]) == 1
        gate.set()
        assert task.wait(2) == "done"
        deadline = time.monotonic() + 2
        while original_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not original_thread.is_alive()
        assert "recovered successfully" in agent_runtime.restart(worker.agent_id, reason="phase22 test")
        assert worker.is_alive()
        assert len([t for t in threading.enumerate() if t.name == "agent-phase22-test"]) == 1
    finally:
        gate.set()
        worker.stop()
        if worker._thread is not None:
            worker._thread.join(2)
        if original is None:
            agent_runtime._workers.pop(worker.agent_id, None)
        else:
            agent_runtime._workers[worker.agent_id] = original


def test_failed_agent_task_isolated_from_next_task() -> None:
    worker = agent_runtime.AgentWorker("phase22-failure")
    try:
        worker.start()
        failed = agent_runtime.AgentTask("bad", worker.agent_id, "failure", lambda: (_ for _ in ()).throw(RuntimeError("expected")))
        succeeded = agent_runtime.AgentTask("good", worker.agent_id, "success", lambda: "recovered")
        worker.queue.put(failed)
        worker.queue.put(succeeded)
        assert "Error: RuntimeError: expected" in failed.wait(2)
        assert succeeded.wait(2) == "recovered"
        assert worker.is_alive()
        assert worker.metrics.tasks_failed == 1
    finally:
        worker.stop()
        if worker._thread is not None:
            worker._thread.join(2)


def test_bounded_workers_do_not_grow_for_many_tasks() -> None:
    pool = ManagedWorkerPool(max_workers=2, max_queue=64, thread_name_prefix="phase22-bounded")
    try:
        handles = [pool.submit(lambda: "ok") for _ in range(50)]
        assert all(handle.result(2) == "ok" for handle in handles)
        metrics = pool.metrics()
        assert metrics["workers"] == 2
        assert metrics["workers_alive"] == 2
        assert len([t for t in threading.enumerate() if t.name.startswith("phase22-bounded-")]) == 2
    finally:
        pool.shutdown()
    assert not any(t.name.startswith("phase22-bounded-") for t in threading.enumerate())


def test_successful_worker_history_does_not_retain_task_synchronization_objects() -> None:
    pool = ManagedWorkerPool(max_workers=2, max_queue=64, thread_name_prefix="phase22-history")
    try:
        handles = [pool.submit(lambda: "ok") for _ in range(50)]
        assert all(handle.result(2) == "ok" for handle in handles)
        del handles
        assert pool.metrics()["recent_failures"] == []
        assert not hasattr(pool, "_recent")
        assert len(pool._recent_failures) == 0
    finally:
        pool.shutdown()


def test_event_publisher_stays_fast_with_a_slow_subscriber() -> None:
    subscriber = event_bus.subscribe()
    try:
        started = time.perf_counter()
        for i in range(1_000):
            event_bus.publish("phase22.publisher", {"i": i}, source="phase22")
        assert time.perf_counter() - started < 1.5
        assert subscriber.qsize() <= 500
    finally:
        event_bus.unsubscribe(subscriber)


def test_desktop_starts_server_from_background_loader_not_main() -> None:
    source = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    main = ast.get_source_segment(source, functions["main"]) or ""
    loader = ast.get_source_segment(source, functions["_load_when_ready"]) or ""
    assert "_start_server()" not in main
    assert "_start_server()" in loader
    assert "time.monotonic()" in loader
    assert "_STARTUP_SERVER_DEADLINE_S" in loader
    assert "_show_startup_failure()" in loader
    assert "create_window(" in main


def test_provider_failure_isolated_and_does_not_kill_worker() -> None:
    import reyes_agent.provider as provider

    # Updated 2026-08-07: run_turn now walks model_router's fallback chain
    # instead of failing on the single configured provider, so stubbing only
    # MODEL_PROVIDER let the turn reach a REAL second provider over the
    # network and blow the 2s budget. Every runner is stubbed so this test
    # keeps asserting what it is actually about -- that a provider failure
    # is isolated and the worker survives -- against the new contract.
    original_runners = dict(provider._RUNNERS)
    original_retries = provider._MAX_RETRY_ATTEMPTS
    pool = ManagedWorkerPool(max_workers=1, max_queue=4, thread_name_prefix="phase22-provider")

    def timed_out(*_args):
        raise ProviderError("controlled provider timeout", retryable=False)

    for _name in provider._RUNNERS:
        provider._RUNNERS[_name] = timed_out
    provider._MAX_RETRY_ATTEMPTS = 1
    try:
        handle = pool.submit(lambda: run_turn([{"role": "user", "content": "test"}]), timeout=2)
        try:
            handle.result(2)
        except ProviderError as exc:
            assert "controlled provider timeout" in str(exc)
        else:
            raise AssertionError("Provider timeout unexpectedly succeeded")
        assert pool.metrics()["workers_alive"] == 1
    finally:
        provider._RUNNERS.clear()
        provider._RUNNERS.update(original_runners)
        provider._MAX_RETRY_ATTEMPTS = original_retries
        pool.shutdown()


def test_elevenlabs_failure_isolated_and_cache_does_not_grow() -> None:
    from reyes_agent.voice import tts

    old_key = config.ELEVENLABS_API_KEY
    old_cache = voice_manager._CACHE_DIR
    old_client = tts._get_elevenlabs_client

    class FailingClient:
        class text_to_speech:  # noqa: N801 -- mirrors SDK attribute
            @staticmethod
            def convert(**_kwargs):
                raise TimeoutError("controlled ElevenLabs timeout")

    with tempfile.TemporaryDirectory() as temp_dir:
        config.ELEVENLABS_API_KEY = "test-key"
        voice_manager._CACHE_DIR = Path(temp_dir)
        tts._get_elevenlabs_client = lambda: FailingClient()
        try:
            try:
                voice_manager.synthesize("phase22 controlled timeout", "zeno")
            except tts.TTSError as exc:
                assert "controlled ElevenLabs timeout" in str(exc)
            else:
                raise AssertionError("ElevenLabs timeout unexpectedly succeeded")
            assert not list(Path(temp_dir).glob("*.mp3"))
        finally:
            config.ELEVENLABS_API_KEY = old_key
            voice_manager._CACHE_DIR = old_cache
            tts._get_elevenlabs_client = old_client


def test_owned_desktop_shutdown_uses_loopback_snapshot_handshake() -> None:
    desktop = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert "/api/internal/prepare-shutdown" in desktop
    assert "Loopback only." in web
    assert "get_kernel().shutdown(event_flush_timeout=2.0)" in web
    kernel = (ROOT / "reyes_agent" / "kernel.py").read_text(encoding="utf-8")
    assert "notification_listener.shutdown_background()" in kernel


def test_closing_mini_releases_lazy_dashboard_before_webview_exit() -> None:
    desktop = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    shutdown = desktop.split("    def shutdown(self) -> None:", 1)[1].split(
        "\n\n\ndef main()", 1)[0]
    assert "dashboard.destroy()" in shutdown
    assert "self._dashboard_window = None" in shutdown


def test_desktop_log_rotation_is_bounded() -> None:
    from reyes_agent.desktop_app import _MAX_LOG_BYTES, _rotate_log_if_needed

    with tempfile.TemporaryDirectory() as temp_dir:
        log = Path(temp_dir) / "zeno_server.log"
        log.write_bytes(b"x" * _MAX_LOG_BYTES)
        _rotate_log_if_needed(log)
        assert not log.exists()
        assert log.with_suffix(".log.1").exists()


def test_windows_health_avoids_unsafe_open_file_handle_walk() -> None:
    source = (ROOT / "reyes_agent" / "health" / "processes.py").read_text(encoding="utf-8")
    assert "process.open_files()" not in source
    assert "process.num_handles" in source


def test_idle_validation_is_bounded_and_reports_resource_cleanup() -> None:
    source = (ROOT / "scripts" / "validate_phase22_idle.py").read_text(encoding="utf-8")
    for metric in ("rss_mb", "cpu_percent", "threads", "handles", "worker_queue_depth",
                   "event_queue_depth", "freeze_count"):
        assert metric in source
    assert "process_iter([\"pid\", \"cmdline\"])" in source
    assert 'parser.add_argument("--warmup"' in source
    assert '"cold_process": cold' in source


def test_frontend_audit_reads_scoped_animation_metrics_through_public_apis() -> None:
    source = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    audit = source.split("if (performanceAuditEnabled) {", 1)[1]
    assert "orbitTimer !== null" not in audit
    assert "window.agentRing?.auditMetrics" in audit
    assert "agentSpace.state" in audit


def test_build_job_deadlines_are_monotonic_and_test_clock_is_isolated() -> None:
    jobs = (ROOT / "reyes_agent" / "executors" / "jobs.py").read_text(encoding="utf-8")
    continuity_test = (ROOT / "tests" / "test_conversation_continuity.py").read_text(encoding="utf-8")
    assert "time.monotonic() - job._started_monotonic" in jobs
    assert "deadline = time.monotonic()" in jobs
    assert "continuity.time.time =" not in continuity_test


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
