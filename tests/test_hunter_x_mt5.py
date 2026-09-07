"""Account identity gate: external SDK responses, real verifier behavior."""
import importlib
import json
from types import SimpleNamespace

import pytest


def verify(account, login=123, server="Deriv-Demo"):
    module = importlib.import_module("reyes_agent.hunter_x.brokers.mt5_demo")
    sdk = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0, account_info=lambda: account)
    return module.verify_demo(sdk, login, server)


def account(**changes):
    fields = dict(login=123, server="Deriv-Demo", trade_mode=0, currency="USD",
                  name="PRIVATE_ACCOUNT_NAME", balance=12345.67)
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_verified_demo_exposes_only_safe_metadata():
    assert verify(account()) == {"ok": True, "mode": "PAPER",
                                 "demo_verified": True, "currency": "USD"}


@pytest.mark.parametrize("mode", [1, 2, None, False, "0"])
def test_rejects_non_demo_or_ambiguous_mode(mode):
    result = verify(account(trade_mode=mode))
    assert result["error"] == "NOT_DEMO"
    assert result["demo_verified"] is False


@pytest.mark.parametrize("changes", [{"login": 999}, {"server": "Deriv-Real"},
                                      {"login": "123"}])
def test_rejects_account_switch(changes):
    assert verify(account(**changes))["error"] == "ACCOUNT_MISMATCH"


def test_missing_account_fails_closed():
    assert verify(None)["error"] == "ACCOUNT_UNAVAILABLE"


@pytest.mark.parametrize("login,server", [(0, "Deriv-Demo"), (True, "Deriv-Demo"),
                                         (123, ""), (123, None)])
def test_invalid_expected_identity_fails_closed(login, server):
    assert verify(account(), login, server)["error"] == "INVALID_CONFIGURATION"


@pytest.mark.parametrize("currency", [None, "", "USD\nPRIVATE", "PRIVATE_ACCOUNT_NAME"])
def test_invalid_metadata_not_exposed(currency):
    result = verify(account(currency=currency))
    assert result["error"] == "INVALID_ACCOUNT_METADATA"
    assert "PRIVATE" not in json.dumps(result)


def test_sdk_exception_is_sanitized():
    module = importlib.import_module("reyes_agent.hunter_x.brokers.mt5_demo")
    def failing():
        raise RuntimeError("PASSWORD_SECRET_SENTINEL")
    result = module.verify_demo(SimpleNamespace(account_info=failing), 123, "Deriv-Demo")
    assert result["error"] == "ACCOUNT_UNAVAILABLE"
    assert "SECRET" not in json.dumps(result)
