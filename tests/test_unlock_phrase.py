"""The unlock phrase: approve a browser by a spoken/typed secret, safely."""

from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.auth import unlock  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return unlock.reset_for_tests(tmp_path / "unlock.sqlite")


def test_not_configured_until_a_phrase_is_set(store):
    assert store.configured() is False
    ok, _ = store.set_phrase("john unlock")
    assert ok and store.configured() is True


def test_a_too_short_phrase_is_refused(store):
    ok, reason = store.set_phrase("hi")
    assert ok is False and "at least" in reason


def test_the_phrase_is_stored_only_as_a_hash(store, tmp_path):
    store.set_phrase("john unlock")
    blob = (tmp_path / "unlock.sqlite").read_bytes()
    assert b"john unlock" not in blob and b"john" not in blob


@pytest.mark.parametrize("spoken", [
    "john unlock", "John Unlock", "  john   unlock  ",
    "John, unlock.", "JOHN UNLOCK!", "john... unlock?",
])
def test_spoken_and_typed_variants_all_match(store, spoken):
    """Speech-to-text sprinkles case and punctuation; every rendering of the
    phrase must still unlock, or voice would be unusable."""
    store.set_phrase("john unlock")
    assert store.verify(spoken, identity="phone")[0] is True


def test_a_wrong_phrase_is_refused(store):
    store.set_phrase("john unlock")
    assert store.verify("some other words", identity="phone")[0] is False


def test_repeated_wrong_attempts_lock_out(store):
    store.set_phrase("john unlock")
    for _ in range(unlock.MAX_FAILED):
        store.verify("wrong", identity="attacker")
    # Even the correct phrase is refused once locked -- brute force is stopped.
    ok, reason = store.verify("john unlock", identity="attacker")
    assert ok is False and "Wait" in reason


def test_lockout_is_per_identity(store):
    store.set_phrase("john unlock")
    for _ in range(unlock.MAX_FAILED):
        store.verify("wrong", identity="attacker")
    assert store.verify("john unlock", identity="the-owner")[0] is True


def test_clearing_removes_the_phrase(store):
    store.set_phrase("john unlock")
    assert store.clear() is True
    assert store.configured() is False
    assert store.verify("john unlock", identity="p")[0] is False


def test_the_endpoints_are_registered_and_tunnel_reachable():
    os.environ.setdefault("ZENO_ENV", "test")
    from reyes_agent import web
    from reyes_agent.remote_access import boundary

    paths = set(web.app.openapi()["paths"])
    assert "/api/owner/auth/unlock" in paths
    assert "/api/owner/auth/unlock/status" in paths
    # Reachable through the tunnel (owner surface is allow-listed).
    assert boundary.remote_path_allowed("/api/owner/auth/unlock") is True


def test_set_unlock_cli_uses_getpass_never_argv():
    import inspect

    from reyes_agent.auth import set_unlock

    source = inspect.getsource(set_unlock)
    assert "getpass" in source and "sys.argv" not in source
