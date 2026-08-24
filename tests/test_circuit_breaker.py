"""Contracts for per-tool circuit breakers (deterministic, injected clock)."""

from __future__ import annotations

from reyes_agent.circuit_breaker import CircuitBreaker, CLOSED, OPEN, HALF_OPEN


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_starts_closed_and_allows():
    cb = CircuitBreaker()
    assert cb.state("t") == CLOSED and cb.allow("t") is True


def test_trips_open_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=60, clock=Clock())
    for _ in range(2):
        cb.record("t", False)
    assert cb.state("t") == CLOSED and cb.allow("t") is True
    cb.record("t", False)               # third failure trips it
    assert cb.state("t") == OPEN and cb.allow("t") is False


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, clock=Clock())
    cb.record("t", False)
    cb.record("t", False)
    cb.record("t", True)                 # resets
    cb.record("t", False)
    cb.record("t", False)
    assert cb.state("t") == CLOSED       # only 2 consecutive since reset


def test_half_open_after_cooldown_allows_one_probe():
    clock = Clock()
    cb = CircuitBreaker(failure_threshold=2, cooldown_s=30, clock=clock)
    cb.record("t", False)
    cb.record("t", False)
    assert cb.allow("t") is False        # OPEN
    clock.advance(30)
    assert cb.state("t") == HALF_OPEN
    assert cb.allow("t") is True         # first probe allowed
    assert cb.allow("t") is False        # second refused until the probe resolves


def test_probe_success_closes():
    clock = Clock()
    cb = CircuitBreaker(failure_threshold=2, cooldown_s=30, clock=clock)
    cb.record("t", False); cb.record("t", False)
    clock.advance(30)
    assert cb.allow("t") is True
    cb.record("t", True)                 # probe succeeded
    assert cb.state("t") == CLOSED and cb.allow("t") is True


def test_probe_failure_reopens():
    clock = Clock()
    cb = CircuitBreaker(failure_threshold=2, cooldown_s=30, clock=clock)
    cb.record("t", False); cb.record("t", False)
    clock.advance(30)
    assert cb.allow("t") is True
    cb.record("t", False)                # probe failed -> re-open, fresh cooldown
    assert cb.allow("t") is False
    clock.advance(30)
    assert cb.allow("t") is True         # cools down again


def test_independent_per_name():
    cb = CircuitBreaker(failure_threshold=1, clock=Clock())
    cb.record("a", False)
    assert cb.is_open("a") is True and cb.is_open("b") is False


def test_reset():
    cb = CircuitBreaker(failure_threshold=1, clock=Clock())
    cb.record("a", False)
    cb.reset("a")
    assert cb.state("a") == CLOSED
    cb.record("a", False); cb.record("b", False)
    cb.reset()
    assert cb.snapshot() == []


def test_never_raises_on_blank():
    cb = CircuitBreaker()
    cb.record("", False)
    assert cb.allow("") is True and cb.state("") == CLOSED


def test_snapshot_shape():
    cb = CircuitBreaker(failure_threshold=1, clock=Clock())
    cb.record("x", False)
    snap = cb.snapshot()
    assert snap and set(snap[0]) == {"name", "state"} and snap[0]["state"] == OPEN
