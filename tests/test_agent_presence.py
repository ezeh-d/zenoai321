"""Regression coverage for Task 14's event-driven agent appearances."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_worker_emits_queue_thinking_and_terminal_visual_evidence() -> None:
    from reyes_agent import agent_runtime

    published: list[tuple[str, dict]] = []
    original = agent_runtime._publish
    agent_runtime._publish = lambda kind, payload: published.append((kind, payload))
    try:
        worker = agent_runtime.AgentWorker("stark")
        task = worker.submit_task("check the security", lambda: "clear")
        worker._execute(task)
    finally:
        agent_runtime._publish = original

    by_type = {kind: payload for kind, payload in published}
    assert by_type["agent.task_queued"]["visual_state"] == "waiting"
    assert by_type["agent.task_started"]["visual_state"] == "thinking"
    assert by_type["agent.task_finished"]["visual_state"] == "success"
    assert by_type["agent.task_finished"]["task_id"] == task.id


def test_agent_visuals_are_created_from_real_lifecycle_not_a_permanent_roster() -> None:
    dashboard = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    mini = (ROOT / "reyes_agent" / "static" / "mini.html").read_text(encoding="utf-8")
    presence = (ROOT / "reyes_agent" / "static" / "agent_presence.js").read_text(encoding="utf-8")

    assert "function ensureVisual(id)" in dashboard
    assert "agentRing.lifecycle(update)" in dashboard
    assert "councilVisualStates" in dashboard
    assert "function refreshSituationAgentPresence()" in dashboard
    assert "agentPresence.consume(update)" in mini
    assert "new EventSource('/api/events/stream')" in mini
    assert '"agent.task_finished"' in presence
    assert "destroyFace(agentId)" in presence
    assert "Registered specialist" in presence
    assert "ensureAgentIdentity" in dashboard


def test_faces_support_waiting_and_release_on_dismissal() -> None:
    faces = (ROOT / "reyes_agent" / "static" / "agent_faces.js").read_text(encoding="utf-8")
    assert '"waiting"' in faces
    assert "export function destroyFace(agentId)" in faces
    assert "f.card.remove()" in faces
    assert "export function setEmotion" in faces
    assert "export function setAttention" in faces
    assert "Math.random" not in faces


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


if __name__ == "__main__":
    raise SystemExit(_run_all())
