"""Independent security regression coverage for the Phone Companion core.

This file intentionally tests the public/persistence boundary without
modifying the remote implementation owned by the integration engineer.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import phone_security
from reyes_agent.phone_security import PENDING_APPROVAL, PhoneSecurity, TRUSTED, _b64, _hash


def _security() -> tuple[tempfile.TemporaryDirectory[str], PhoneSecurity]:
    temp = tempfile.TemporaryDirectory()
    return temp, PhoneSecurity(Path(temp.name) / "devices.sqlite")


def test_new_pairing_invalidates_older_unconsumed_pairing() -> None:
    temp, security = _security()
    try:
        earlier = security.create_pair()
        latest = security.create_pair()
        assert not security._valid_pair(earlier["token"])
        assert security._valid_pair(latest["token"])
    finally:
        temp.cleanup()


def test_challenge_cannot_be_taken_twice_serially() -> None:
    temp, security = _security()
    try:
        challenge = _b64(b"x" * 32)
        security._save_challenge(b"x" * 32, "registration", "subject")
        first = security._take_challenge(challenge, "registration")
        assert first["used"] == 0
        try:
            security._take_challenge(challenge, "registration")
        except PermissionError:
            pass
        else:
            raise AssertionError("a consumed challenge was accepted again")
    finally:
        temp.cleanup()


def test_registration_persists_a_pending_device() -> None:
    """A verified WebAuthn registration must match the durable table schema."""
    temp, security = _security()
    original_verifier = phone_security.verify_registration_response

    class VerifiedCredential:
        credential_id = b"credential-id"
        credential_public_key = b"public-key"
        sign_count = 7

    try:
        pair = security.create_pair()
        options = security.registration_options(pair["token"], "Divine phone", "zeno.example.test")
        phone_security.verify_registration_response = lambda **_kwargs: VerifiedCredential()  # type: ignore[assignment]
        device_id = security.finish_registration(
            {}, options["challenge"], "https://zeno.example.test", "zeno.example.test"
        )
        device = security._device(device_id)
        assert device["state"] == PENDING_APPROVAL
        assert device["sign_count"] == 7
        assert not security._valid_pair(pair["token"])
    finally:
        phone_security.verify_registration_response = original_verifier
        temp.cleanup()


def test_locking_a_device_invalidates_its_existing_session() -> None:
    temp, security = _security()
    try:
        token, csrf = "session-token", "csrf-token"
        now = time.time()
        with security._connection() as conn:
            conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                "device-1", "Audit phone", "credential-1", b"public", 0, TRUSTED,
                '["talk"]', now, now, now, None,
            ))
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (
                _hash(token), "device-1", _hash(csrf), now + 60, now,
            ))
        assert security.session(token, csrf, require_csrf=True)["device_id"] == "device-1"
        security.set_device("device-1", state="LOCKED")
        try:
            security.session(token)
        except PermissionError:
            pass
        else:
            raise AssertionError("a locked device retained a valid session")
    finally:
        temp.cleanup()


def test_command_replay_protection_is_per_device_and_nonce() -> None:
    temp, security = _security()
    try:
        assert security.claim_command("one", "command", "nonce")
        assert not security.claim_command("one", "command", "other-nonce")
        assert not security.claim_command("one", "different-command", "nonce")
        assert security.claim_command("two", "command", "nonce")
    finally:
        temp.cleanup()


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test(); print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone project convention
            failures += 1; print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
