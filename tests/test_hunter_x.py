from dataclasses import replace
from decimal import Decimal
import math
import pytest

from reyes_agent.hunter_x.data import Bar, Instrument, validate_bars
from reyes_agent.hunter_x.risk import Limits, assess
from reyes_agent.hunter_x.paper import PaperAccount
from reyes_agent.hunter_x.backtest import run, walk_forward


def instrument(market="stocks"):
    return Instrument("TEST", market, "USD", Decimal("1"))


def bars():
    return [Bar(i * 86400, p, p + 1, p - 1, p, 1000)
            for i, p in enumerate([10, 10, 11, 12, 13, 12, 11, 10, 12, 14, 15, 14], 1)]


@pytest.mark.parametrize("market", ["stocks", "forex", "crypto"])
def test_market_metadata_and_valid_data(market):
    assert instrument(market).market == market
    assert validate_bars(bars()) == bars()


@pytest.mark.parametrize("value", [math.nan, math.inf, -1, 0])
def test_invalid_price_rejected(value):
    with pytest.raises(ValueError):
        validate_bars([Bar(1, value, value, value, value, 1)])


def test_duplicate_timestamps_rejected():
    with pytest.raises(ValueError):
        validate_bars([bars()[0], bars()[0]])


def test_risk_sizing_includes_costs_and_rounds_down():
    decision = assess(instrument(), 10000, 100, 95, 115, Limits(),
                      currency="USD", age_seconds=0)
    assert decision["allowed"]
    assert Decimal(decision["quantity"]) < 20
    assert Decimal(decision["risk"]) <= 100


@pytest.mark.parametrize("kwargs", [dict(age_seconds=999999), dict(currency="NGN"),
    dict(daily_loss=300), dict(drawdown=.3), dict(open_risk=1000), dict(paused=True)])
def test_risk_veto(kwargs):
    params = dict(currency="USD", age_seconds=0)
    params.update(kwargs)
    assert not assess(instrument(), 10000, 100, 95, 115, Limits(), **params)["allowed"]


def test_paper_order_idempotency_and_restart(tmp_path):
    path = tmp_path / "paper.db"
    account = PaperAccount(path, "USD", 10000)
    one = account.trade("one", instrument(), "buy", 2, 100)
    assert account.trade("one", instrument(), "buy", 2, 100) == one
    assert PaperAccount(path, "USD", 10000).status()["orders"] == 1
    with pytest.raises(ValueError):
        account.trade("one", instrument(), "buy", 3, 100)
    account.trade("two", instrument(), "sell", 2, 100)
    assert Decimal(account.status()["cash"]) < 10000
    assert account.status()["positions"] == []


def test_paper_pause_and_invalid_numbers(tmp_path):
    account = PaperAccount(tmp_path / "paper.db", "USD", 10000)
    with pytest.raises(ValueError):
        account.trade("bad", instrument(), "buy", -1, 100)
    account.pause()
    with pytest.raises(ValueError):
        account.trade("paused", instrument(), "buy", 1, 100)
    assert PaperAccount(tmp_path / "paper.db", "USD", 10000).status()["paused"]


def test_backtest_signal_precedes_fill_and_costs_reduce_return():
    result = run(bars(), fast=2, slow=3, fee_bps=10, slippage_bps=5)
    assert result["trades"]
    assert all(t["signal_time"] < t["entry_time"] for t in result["trades"])
    assert result["final_equity"] < run(bars(), fast=2, slow=3, fee_bps=0, slippage_bps=0)["final_equity"]


def test_future_prices_cannot_change_past_decisions():
    sample = bars()
    original = run(sample, fast=2, slow=3)
    altered = run(sample[:-2] + [replace(b, open=100, high=101, low=99, close=100)
                                for b in sample[-2:]], fast=2, slow=3)
    assert original["equity"][:-2] == altered["equity"][:-2]


def test_walk_forward_windows_are_disjoint():
    result = walk_forward(bars(), train=6, test=3, fast=1, slow=2)
    assert result
    assert all(r["train_end"] < r["test_start"] for r in result)


def test_zeno_integration_and_live_rejection():
    from reyes_agent.tools import TOOLS
    from reyes_agent.agent_runtime import AGENT_ROLES
    from reyes_agent.tools.subagents import _SPECIALISTS
    from reyes_agent.routing.capability import CAPABILITIES
    assert "hunter_x" in TOOLS
    assert "hunter_x" in AGENT_ROLES
    assert "hunter_x" in _SPECIALISTS
    assert "hunter_x" in CAPABILITIES["hunter_x"]
    import json
    result = json.loads(TOOLS["hunter_x"].func(action="live"))
    assert result["ok"] is False


def test_status_does_not_fetch_market_data(monkeypatch):
    from reyes_agent.hunter_x.core import execute
    from reyes_agent.hunter_x.data import HistoricalData
    def forbidden(*args, **kwargs):
        raise AssertionError("Status triggered data request")
    monkeypatch.setattr(HistoricalData, "fetch", forbidden)
    assert execute("status")["readiness"] == "UNPROVEN"


def test_simultaneous_duplicate_orders_execute_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    account = PaperAccount(tmp_path / "paper.db", "USD", 10000)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: account.trade("same", instrument(), "buy", 2, 100), range(2)))
    assert results[0] == results[1]
    assert account.status()["orders"] == 1


def test_paper_currency_mismatch_leaves_cash_unchanged(tmp_path):
    account = PaperAccount(tmp_path / "paper.db", "NGN", 5000)
    with pytest.raises(ValueError):
        account.trade("bad", instrument(), "buy", 1, 100)
    assert account.status()["cash"] == "5000"


def test_stop_all_paper_accounts_persists(tmp_path, monkeypatch):
    from reyes_agent import config
    from reyes_agent.hunter_x.core import execute
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    execute("paper_status", currency="USD")
    execute("paper_status", currency="NGN")
    execute("stop")
    assert execute("paper_status", currency="USD")["paused"]
    assert execute("paper_status", currency="NGN")["paused"]
    with pytest.raises(ValueError):
        execute("resume_paper")
    execute("resume_paper", simulation_acknowledged=True)
    assert not execute("paper_status", currency="USD")["paused"]


def test_training_requires_actual_answers_and_never_promotes(tmp_path):
    from reyes_agent.hunter_x.training import grade
    assert not grade({})["passed"]
    result = grade({"risk_budget": 100, "position_units": 20, "net_pnl": 90, "drawdown_percent": 10})
    assert result["passed"]
    assert result["readiness"] == "UNPROVEN"


def test_forex_reference_fallback_is_never_an_executable_quote(monkeypatch):
    from reyes_agent.hunter_x import core, data
    monkeypatch.setattr(data.HistoricalData, "fetch", lambda *a, **k: (_ for _ in ()).throw(ValueError("Bad candles")))
    monkeypatch.setattr(data.ForexReference, "fetch", lambda *a: {"source": "fixture", "rate": 1.1})
    result = core.execute("analyze", symbol="EURUSD=X", market="forex")
    assert result["decision"] == "NO_TRADE"
    assert result["executable_quote"] is False
    assert result["mode"] == "REFERENCE_RATE_ONLY"
