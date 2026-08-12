"""The two gaps left open on Subspace: cancellation depth, and the payload
the overlay nests on.

The ROADMAP recorded both as "still not live-verified". A live provider is
not what makes either of them true, though -- a real model call proves the
model answered, not that a stop reaches the worker. What proves that is
where the cancel check is CALLED, and that is testable deterministically and
repeatably, which a paid call is not.
"""

from __future__ import annotations

import json
import pytest

from reyes_agent import agent_teams
from reyes_agent.worker_pool import TaskCancelled


class _Stop:
    """A cancel check that fires after a set number of calls.

    Modelling the owner saying "stop" partway through, rather than before
    anything started -- cancelling a task that never began proves nothing.
    """

    def __init__(self, after: int = 1) -> None:
        self.calls = 0
        self.after = after

    def __call__(self) -> None:
        self.calls += 1
        if self.calls > self.after:
            raise TaskCancelled("owner asked me to stop")


@pytest.fixture
def worker(monkeypatch):
    """A real registered worker, with the provider stubbed out."""
    parent = "apex"
    team = agent_teams.workers_for(parent)
    assert team, "apex must have registered workers"
    return parent, team[0].name


class TestCancellationReachesTheWorker:
    def test_a_stop_before_the_first_round_never_calls_the_provider(
            self, monkeypatch, worker):
        """ZENO -> primary -> worker: the worker inherits the parent's stop."""
        parent, name = worker
        called = []
        monkeypatch.setattr(agent_teams, "_publish", lambda *a, **k: None)
        monkeypatch.setattr("reyes_agent.provider.run_turn",
                            lambda *a, **k: called.append(1))
        monkeypatch.setattr("reyes_agent.agent_runtime.current_task_cancel_check",
                            _Stop(after=0))

        answer = agent_teams.run_worker(parent, name, "do something long")
        assert "cancelled" in answer.lower()
        assert called == [], "the provider was called after a stop"

    def test_cancellation_is_reported_as_cancelled_not_as_failure(
            self, monkeypatch, worker):
        """A stop is not an error.

        Reporting it as failure is how a deliberate interruption turns into a
        bug report -- and worse, into a retry.
        """
        parent, name = worker
        published = []
        monkeypatch.setattr(agent_teams, "_publish",
                            lambda event, payload=None, **k: published.append(
                                (event, payload or {})))
        monkeypatch.setattr("reyes_agent.agent_runtime.current_task_cancel_check",
                            _Stop(after=0))

        agent_teams.run_worker(parent, name, "task")
        terminal = [p for _e, p in published
                    if p.get("outcome") or p.get("state") or p.get("visual_state")]
        assert terminal, "no terminal event was published"
        blob = json.dumps(terminal).lower()
        assert "cancelled" in blob
        assert "success" not in blob

    def test_a_stop_between_tool_rounds_halts_before_the_next_tool(
            self, monkeypatch, worker):
        """The check sits inside the tool loop, so a long worker stops mid-run."""
        parent, name = worker
        ran = []

        class _Turn:
            wants_tool = True
            text = ""

            class _Call:
                id, name, input, extra = "1", "system_health", {}, None

            tool_calls = [_Call()]

        monkeypatch.setattr(agent_teams, "_publish", lambda *a, **k: None)
        monkeypatch.setattr("reyes_agent.provider.run_turn", lambda *a, **k: _Turn())
        monkeypatch.setattr("reyes_agent.tools.run_tool",
                            lambda n, i: ran.append(n) or "ok")
        # Survive the round check and the provider call, then stop at the
        # per-tool check -- so no tool must run.
        monkeypatch.setattr("reyes_agent.agent_runtime.current_task_cancel_check",
                            _Stop(after=1))

        answer = agent_teams.run_worker(parent, name, "task")
        assert "cancelled" in answer.lower()
        assert ran == [], f"a tool ran after the stop: {ran}"


class TestSubspacePayload:
    """The overlay nests on `parent`. If that field moves, the tree collapses."""

    def test_every_worker_declares_its_parent(self):
        for primary, workers in agent_teams.teams().items():
            for worker in workers:
                assert getattr(worker, "parent", "") == primary

    def test_depth_is_bounded_at_zeno_primary_worker(self):
        """No worker is itself a primary -- that would make a third level."""
        primaries = set(agent_teams.teams())
        for workers in agent_teams.teams().values():
            for worker in workers:
                assert worker.name not in primaries

    def test_the_roster_matches_the_canonical_registry(self):
        """The ROADMAP recorded 13 primaries / 74 workers; both grew.

        A hierarchy that disagrees with the registry means the overlay draws
        a team ZENO does not think it has.
        """
        from reyes_agent.agents import identity

        roster = identity.roster()
        assert len(roster) == len(agent_teams.teams())
        assert (sum(a["worker_count"] for a in roster)
                == sum(len(w) for w in agent_teams.teams().values()))
