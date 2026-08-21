"""Contracts for the shared failure taxonomy and its recovery semantics."""

from __future__ import annotations

import pytest

from reyes_agent import failures as f


# --- message + status-code classification (existing behaviour) --------------
@pytest.mark.parametrize("message,status,expected", [
    ("Rate limit exceeded", 0, f.PROVIDER_RATE_LIMIT),
    ("", 429, f.PROVIDER_RATE_LIMIT),
    ("Too many requests, slow down", 0, f.PROVIDER_RATE_LIMIT),
    ("Invalid API key", 0, f.AUTH_EXPIRED),
    ("", 401, f.AUTH_EXPIRED),
    ("", 403, f.AUTH_EXPIRED),
    ("session expired", 0, f.AUTH_EXPIRED),
    ("Permission denied by policy", 0, f.PERMISSION_DENIED),
    ("The request timed out", 0, f.TOOL_TIMEOUT),
    ("deadline exceeded", 0, f.TOOL_TIMEOUT),
    ("DNS name resolution failed", 0, f.NETWORK_OFFLINE),
    ("connection refused", 0, f.PERMISSION_DENIED),  # 'refused' -> permission first
    ("host unreachable", 0, f.NETWORK_OFFLINE),
    ("element not found on page", 0, f.ELEMENT_NOT_FOUND),
    ("no device attached", 0, f.DEVICE_DISCONNECTED),
    ("", 500, f.SERVICE_CRASHED),
    ("", 503, f.SERVICE_CRASHED),
    ("process exited unexpectedly", 0, f.SERVICE_CRASHED),
    ("model unavailable right now", 0, f.MODEL_UNAVAILABLE),
    ("required field missing", 0, f.INVALID_REQUEST),
    ("something odd happened", 0, f.UNKNOWN_FAILURE),
])
def test_classify_message(message, status, expected):
    assert f.classify(message, status_code=status) == expected


def test_classify_is_total_and_in_taxonomy():
    for probe in ["", "x", "weird", "429", None]:
        assert f.classify(probe) in f.ALL


# --- exception-type classification (new) ------------------------------------
def test_classify_exception_uses_type_first():
    assert f.classify_exception(TimeoutError("whatever")) == f.TOOL_TIMEOUT
    assert f.classify_exception(PermissionError("nope")) == f.PERMISSION_DENIED
    assert f.classify_exception(ConnectionError("reset")) == f.NETWORK_OFFLINE


def test_classify_exception_message_promotes_generic_type():
    # A ValueError whose message names a known cause is classified by the cause.
    assert f.classify_exception(ValueError("rate limit hit")) == f.PROVIDER_RATE_LIMIT
    # A ValueError with no cause markers is an invalid request.
    assert f.classify_exception(ValueError("bogus")) == f.INVALID_REQUEST
    assert f.classify_exception(KeyError("recipient")) == f.INVALID_REQUEST


def test_classify_exception_retryable_flag_fallback():
    class Blip(Exception):
        retryable = True

    assert f.classify_exception(Blip("nondescript")) == f.SERVICE_CRASHED


def test_classify_exception_none_defers_to_message():
    assert f.classify_exception(None, status_code=429) == f.PROVIDER_RATE_LIMIT
    assert f.classify_exception(None) == f.UNKNOWN_FAILURE


# --- recovery semantics -----------------------------------------------------
def test_retryable_sets_are_consistent():
    assert f.RETRYABLE <= f.ALL
    assert f.RETRYABLE <= f.TRANSIENT
    # A bad request or a missing element must never be blind-retried.
    assert not f.is_retryable(f.INVALID_REQUEST)
    assert not f.is_retryable(f.ELEMENT_NOT_FOUND)
    assert not f.is_retryable(f.PERMISSION_DENIED)
    assert f.is_retryable(f.PROVIDER_RATE_LIMIT)
    assert f.is_retryable(f.TOOL_TIMEOUT)


def test_every_class_has_a_recovery_hint():
    for category in f.ALL:
        assert f.RECOVERY.get(category)


def test_describe_shape_and_unknown_fallback():
    d = f.describe(f.NETWORK_OFFLINE)
    assert d == {"category": f.NETWORK_OFFLINE, "retryable": True,
                 "transient": True, "recovery": f.RECOVERY[f.NETWORK_OFFLINE]}
    # An unrecognised label degrades to UNKNOWN rather than raising.
    assert f.describe("NONSENSE")["category"] == f.UNKNOWN_FAILURE


def test_explain_from_exception_and_message():
    from_exc = f.explain(exc=TimeoutError("slow"))
    assert from_exc["category"] == f.TOOL_TIMEOUT and from_exc["retryable"] is True

    from_msg = f.explain("invalid api key", status_code=401)
    assert from_msg["category"] == f.AUTH_EXPIRED
    assert from_msg["retryable"] is False and from_msg["transient"] is True


def test_explain_never_raises():
    class Nasty:
        def __str__(self):  # noqa: D401 - a message that blows up when read
            raise RuntimeError("boom")

    # exc path: __str__ raising inside classify must be swallowed.
    assert f.explain(exc=ValueError(Nasty()))["category"] in f.ALL
    # message path with a hostile object.
    assert f.explain(Nasty())["category"] in f.ALL
