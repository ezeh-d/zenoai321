"""Offline regression coverage for the bounded next-intelligence layer."""
from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _temporary_history():
    from reyes_agent import intelligence

    temp = tempfile.TemporaryDirectory()
    original = intelligence._DB_PATH
    intelligence._DB_PATH = Path(temp.name) / "state.db"
    return intelligence, temp, original


def test_interrupt_cancels_managed_work_without_waiting_for_its_deadline() -> None:
    from reyes_agent.worker_pool import ManagedWorkerPool, TaskCancelled
    from reyes_agent.intelligence import get_runtime_control

    pool = ManagedWorkerPool(max_workers=1, max_queue=4, thread_name_prefix="intelligence-test")
    control = get_runtime_control()

    def long_job(context):
        for _ in range(100):
            context.wait(0.05)
        return "should not finish"

    handle = pool.submit(long_job, name="interruptible", with_context=True, timeout=20)
    control.register(handle, label="interruptible", kind="test")
    time.sleep(0.03)
    result = control.interrupt(action="cancel")
    assert "interruptible" in result["cancelled_operations"]
    try:
        handle.result(1)
    except TaskCancelled:
        pass
    else:
        raise AssertionError("Cancelled task completed unexpectedly")
    control.release(handle)
    pool.shutdown()


def test_project_write_history_restores_only_unchanged_file() -> None:
    intelligence, temp, original = _temporary_history()
    try:
        target = Path(temp.name) / "project" / "index.txt"
        target.parent.mkdir()
        target.write_text("before", encoding="utf-8")
        action_id = intelligence.begin_project_write(target)
        assert action_id
        target.write_text("after", encoding="utf-8")
        intelligence.complete_project_write(action_id, target, "Wrote index.txt")
        result = intelligence.undo_last()
        assert result["ok"]
        assert target.read_text(encoding="utf-8") == "before"

        action_id = intelligence.begin_project_write(target)
        target.write_text("zeno update", encoding="utf-8")
        intelligence.complete_project_write(action_id, target, "Wrote index.txt")
        target.write_text("owner changed this", encoding="utf-8")
        refused = intelligence.undo_last()
        assert not refused["ok"]
        assert "refusing" in refused["failures"][0]["reason"].lower()
    finally:
        intelligence._DB_PATH = original
        temp.cleanup()


def test_multiple_undoes_reverse_writes_newest_first() -> None:
    intelligence, temp, original = _temporary_history()
    try:
        target = Path(temp.name) / "project" / "index.txt"
        target.parent.mkdir()
        target.write_text("one", encoding="utf-8")
        first = intelligence.begin_project_write(target)
        target.write_text("two", encoding="utf-8")
        intelligence.complete_project_write(first, target, "Wrote two")
        second = intelligence.begin_project_write(target)
        target.write_text("three", encoding="utf-8")
        intelligence.complete_project_write(second, target, "Wrote three")
        result = intelligence.undo_last(2)
        assert result["ok"]
        assert target.read_text(encoding="utf-8") == "one"
    finally:
        intelligence._DB_PATH = original
        temp.cleanup()


def test_mission_state_and_temporal_resolution_are_explicit() -> None:
    intelligence, temp, original = _temporary_history()
    try:
        saved = intelligence.persist_mission_state(
            9, goal="Build site", plan=["plan", "test"], completed=["plan"], pending=["test"],
            files=["index.html"], agents=["tosin"], verification=["test pending"],
        )
        assert saved["goal"] == "Build site"
        restored = intelligence.load_mission_state(9)
        assert restored and restored["completed"] == ["plan"] and restored["pending"] == ["test"]
        tomorrow = intelligence.resolve_time("tomorrow")
        assert tomorrow["resolved"] and tomorrow["timezone"]
        assert intelligence.resolve_time("some unspecified time")["resolved"] is False
    finally:
        intelligence._DB_PATH = original
        temp.cleanup()


def test_temporal_resolution_handles_common_relative_and_clock_phrases() -> None:
    from reyes_agent import intelligence

    local = datetime(2026, 8, 24, 14, 30, tzinfo=timezone(timedelta(hours=1)))
    assert intelligence.resolve_time("today at 6:15 pm", now=local)["iso"].startswith("2026-08-24T18:15")
    assert intelligence.resolve_time("in 45 minutes", now=local)["iso"].startswith("2026-08-24T15:15")
    assert intelligence.resolve_time("2 hours ago", now=local)["iso"].startswith("2026-08-24T12:30")
    assert intelligence.resolve_time("next Monday", now=local)["iso"].startswith("2026-08-31T00:00")
    assert intelligence.resolve_time("2026-02-30", now=local)["resolved"] is False


def test_context_reference_resolves_only_one_observed_target_and_keeps_risk_gate() -> None:
    from reyes_agent import intelligence

    unique = intelligence.resolve_reference(
        "that app", state={"active_application": "notepad.exe"}, risk="high",
    )
    assert unique["resolved"] is True
    assert unique["target"]["value"] == "notepad.exe"
    assert unique["requires_confirmation"] is True

    ambiguous = intelligence.resolve_reference(
        "it", state={"active_application": "notepad.exe", "current_task": "write report"},
    )
    assert ambiguous["resolved"] is False
    assert len(ambiguous["candidates"]) == 2


def test_relationship_memory_requires_owner_confirmation_at_tool_boundary() -> None:
    from reyes_agent.tools import TOOLS

    assert TOOLS["remember_relationship"].requires_confirmation is True


def test_personal_relationships_support_correction_and_deletion() -> None:
    intelligence, temp, original = _temporary_history()
    try:
        saved = intelligence.add_relationship("Divine", "owns", "ZENO", evidence="owner-confirmed")
        assert intelligence.relationships("divine")[0]["target"] == "ZENO"
        corrected = intelligence.add_relationship("Divine", "owns", "ZENO", evidence="corrected by owner")
        assert corrected["id"] == saved["id"]
        assert intelligence.remove_relationship(saved["id"])
        assert not intelligence.relationships("Divine")
    finally:
        intelligence._DB_PATH = original
        temp.cleanup()


def test_capability_and_simulation_never_claim_execution() -> None:
    from reyes_agent import intelligence

    simulation = intelligence.simulate_plan("Restart a service", ["inspect", "restart"], risk="high", files=["config.py"])
    assert simulation["mode"] == "SIMULATION"
    assert simulation["executed"] is False
    assert simulation["approval_required"] is True
    assert intelligence.capability("undo")["status"] == "AVAILABLE"


def test_agent_worker_observes_owner_cancellation_between_provider_steps() -> None:
    from reyes_agent import agent_runtime

    worker = agent_runtime.AgentWorker("test", "test")
    worker.start()

    def cancellable() -> str:
        for _ in range(100):
            agent_runtime.current_task_cancel_check()
            time.sleep(0.01)
        return "should not finish"

    task = worker.submit_task("long specialist task", cancellable)
    time.sleep(0.04)
    assert worker.cancel_tasks("owner interruption") >= 1
    assert task.done.wait(1)
    assert task.error == "owner interruption"
    worker.stop()


def test_frontend_keeps_barge_in_on_the_existing_single_vad_stream() -> None:
    html = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/intelligence/interrupt" in html
    assert "if (!ambientEnabled || transcriptionActive || vadRecorder) return;" in html
    assert "pendingBargeTranscript" in html


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
    return failed


if __name__ == "__main__":
    raise SystemExit(_run_all())
