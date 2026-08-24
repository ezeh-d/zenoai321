"""The remote executor consults the breaker before dispatch and labels
outcome confidence on every result."""

from __future__ import annotations

from reyes_agent.circuit_breaker import CircuitBreaker


def test_run_tool_refuses_when_breaker_open(monkeypatch):
    from reyes_agent.remote_access import desktop_agent as da

    cb = CircuitBreaker(failure_threshold=1)
    cb.record("system_health", False)            # one failure -> OPEN
    monkeypatch.setattr("reyes_agent.circuit_breaker.get_breaker", lambda: cb)
    called = []
    monkeypatch.setattr("reyes_agent.tools.run_tool",
                        lambda name, args: called.append(name) or "ok")

    ok, result = da._run_tool("status", {})
    assert ok is False and result.get("quarantined") is True
    assert called == []                          # dispatch was skipped, not burned


def test_run_tool_high_confidence_on_clean_return(monkeypatch):
    from reyes_agent.remote_access import desktop_agent as da

    monkeypatch.setattr("reyes_agent.circuit_breaker.get_breaker",
                        lambda: CircuitBreaker())    # CLOSED
    monkeypatch.setattr("reyes_agent.tools.run_tool",
                        lambda name, args: "All systems nominal.")

    ok, result = da._run_tool("status", {})
    assert ok is True
    assert result.get("outcome_confidence") == "HIGH_CONFIDENCE"


def test_run_tool_failed_confidence_on_error(monkeypatch):
    from reyes_agent.remote_access import desktop_agent as da

    monkeypatch.setattr("reyes_agent.circuit_breaker.get_breaker",
                        lambda: CircuitBreaker())
    monkeypatch.setattr("reyes_agent.tools.run_tool",
                        lambda name, args: "Error: could not read health")

    ok, result = da._run_tool("status", {})
    assert ok is False
    assert result.get("outcome_confidence") == "FAILED"


def test_breaker_allows_probe_after_recovery(monkeypatch):
    # A closed breaker lets the call through and dispatch happens normally.
    from reyes_agent.remote_access import desktop_agent as da

    monkeypatch.setattr("reyes_agent.circuit_breaker.get_breaker",
                        lambda: CircuitBreaker())
    seen = []
    monkeypatch.setattr("reyes_agent.tools.run_tool",
                        lambda name, args: seen.append(name) or "All systems nominal.")
    ok, _ = da._run_tool("status", {})
    assert ok is True and seen == ["system_health"]
