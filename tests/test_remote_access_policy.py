"""Independent contract tests for the optional Remote Access security boundary.

These cover the policy modules without mounting a network route, so they are
safe to run while the integration layer is under active development.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent import config
from reyes_agent.remote_access import domains, policy


@contextmanager
def _remote_settings(**values: object):
    previous = {name: getattr(config, name) for name in values}
    try:
        for name, value in values.items():
            setattr(config, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(config, name, value)


def test_unconfigured_remote_access_has_no_allowed_origins() -> None:
    with _remote_settings(ZENO_PUBLIC_DOMAIN="", ZENO_APP_ORIGIN="", REMOTE_DEV_MODE=False):
        assert domains.allowed_origins() == []
        assert not domains.is_allowed_origin("https://attacker.example")
        assert not domains.is_allowed_origin("")


def test_origin_allow_list_rejects_lookalikes_and_localhost_in_production() -> None:
    with _remote_settings(ZENO_PUBLIC_DOMAIN="zenoassitant.com", ZENO_APP_ORIGIN="", REMOTE_DEV_MODE=False):
        assert domains.is_allowed_origin("https://app.zenoassitant.com")
        assert domains.is_allowed_origin("HTTPS://APP.ZENOASSITANT.COM/")
        assert not domains.is_allowed_origin("https://app.zenoassitant.com.attacker.example")
        assert not domains.is_allowed_origin("http://localhost:5173")
        assert "*" not in domains.allowed_origins()


def test_localhost_is_limited_to_explicit_development_mode() -> None:
    with _remote_settings(ZENO_PUBLIC_DOMAIN="", ZENO_APP_ORIGIN="", REMOTE_DEV_MODE=True):
        assert domains.is_allowed_origin("http://localhost:5173")
        assert domains.is_allowed_origin("http://127.0.0.1:3000")


def test_remote_policy_refuses_financial_and_sensitive_commands_even_with_scopes() -> None:
    all_scopes = {"status", "talk"}
    assert not policy.evaluate("Please transfer money to my bank", scopes=all_scopes).allowed
    assert not policy.evaluate("disable defender", scopes=all_scopes).allowed
    assert policy.evaluate("what is my current task?", scopes=all_scopes).allowed


def test_control_requires_scope_and_preserves_local_confirmation() -> None:
    denied = policy.evaluate("open Chrome", scopes={"status"})
    assert not denied.allowed
    allowed = policy.evaluate("open Chrome", scopes={"talk"})
    assert allowed.allowed
    assert allowed.needs_local_approval


def test_rate_limiter_has_a_real_boundary_and_isolated_identities() -> None:
    policy.reset_rates()
    limit, _window = policy.LIMITS["pair"]
    for _ in range(limit):
        assert policy.check_rate("pair", "same-client").allowed
    rejected = policy.check_rate("pair", "same-client")
    assert not rejected.allowed
    assert rejected.retry_after > 0
    assert policy.check_rate("pair", "another-client").allowed


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone project convention
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
