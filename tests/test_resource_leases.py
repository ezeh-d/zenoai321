"""Contracts for exclusive self-expiring resource leases."""

from __future__ import annotations

import pytest

from reyes_agent.resource_leases import LeaseManager, ResourceBusy


class Clock:
    def __init__(self) -> None:
        self.t = 500.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_acquire_grants_when_free():
    m = LeaseManager(clock=Clock())
    lease = m.acquire("browser:tab:1", "kate")
    assert lease is not None and lease.holder == "kate"
    assert m.holder_of("browser:tab:1") == "kate"


def test_second_holder_is_denied():
    m = LeaseManager(clock=Clock())
    assert m.acquire("file:/x", "kate") is not None
    assert m.acquire("file:/x", "stark") is None      # busy
    assert m.holder_of("file:/x") == "kate"


def test_reacquire_by_same_holder_extends():
    clock = Clock()
    m = LeaseManager(clock=clock)
    first = m.acquire("gpu:0", "oracle", ttl_s=10)
    clock.advance(5)
    second = m.acquire("gpu:0", "oracle", ttl_s=10)
    assert second is not None and second.expires_at > first.expires_at


def test_lease_expires_and_frees():
    clock = Clock()
    m = LeaseManager(clock=clock)
    m.acquire("window:Slack", "kate", ttl_s=10)
    clock.advance(11)                                  # TTL passed
    assert m.is_free("window:Slack") is True
    assert m.acquire("window:Slack", "stark") is not None  # now grantable


def test_release_frees_and_is_idempotent():
    m = LeaseManager(clock=Clock())
    m.acquire("file:/y", "kate")
    assert m.release("file:/y", "kate") is True
    assert m.release("file:/y", "kate") is False       # already released
    assert m.is_free("file:/y") is True


def test_release_by_wrong_holder_does_nothing():
    m = LeaseManager(clock=Clock())
    m.acquire("file:/z", "kate")
    assert m.release("file:/z", "stark") is False
    assert m.holder_of("file:/z") == "kate"


def test_hold_context_manager_releases():
    m = LeaseManager(clock=Clock())
    with m.hold("browser:tab:9", "kate") as lease:
        assert lease.holder == "kate"
        assert m.holder_of("browser:tab:9") == "kate"
    assert m.is_free("browser:tab:9") is True


def test_hold_raises_when_busy():
    m = LeaseManager(clock=Clock())
    m.acquire("file:/busy", "kate")
    with pytest.raises(ResourceBusy) as excinfo:
        with m.hold("file:/busy", "stark"):
            pass
    assert excinfo.value.holder == "kate"


def test_blank_inputs_are_safe():
    m = LeaseManager(clock=Clock())
    assert m.acquire("", "kate") is None
    assert m.acquire("r", "") is None
    assert m.is_free("") is True


def test_active_leases_lists_live_only():
    clock = Clock()
    m = LeaseManager(clock=clock)
    m.acquire("a", "kate", ttl_s=10)
    m.acquire("b", "stark", ttl_s=100)
    clock.advance(11)                                  # 'a' expired
    live = {row["resource"] for row in m.active_leases()}
    assert live == {"b"}
