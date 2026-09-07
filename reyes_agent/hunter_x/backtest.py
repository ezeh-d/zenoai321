"""Chronological fixed-rule research, with next-bar fills and explicit costs."""
import hashlib
import json
import random
from .data import validate_bars, number


def run(bars, *, fast=5, slow=20, fee_bps=10, slippage_bps=5, capital=10000):
    validate_bars(bars)
    if not 1 <= int(fast) < int(slow) < len(bars):
        raise ValueError("Require 1 <= fast < slow < bar count")
    fast, slow = int(fast), int(slow)
    capital = float(number(capital))
    fee, slip = [float(number(v, positive=False)) / 10000 for v in (fee_bps, slippage_bps)]
    if max(fee, slip) >= 1:
        raise ValueError("Invalid costs")
    cash, quantity, pending, entry, equity, trades = capital, 0., None, None, [], []
    closes = []
    for bar in bars:
        # Only the previous completed bar can authorize a fill here.
        if pending and pending[0] == "buy" and not quantity:
            fill = bar.open * (1 + slip)
            quantity = cash / (fill * (1 + fee))
            entry = {"signal_time": pending[1], "entry_time": bar.timestamp,
                     "entry": fill, "capital": cash, "quantity": quantity}
            cash = 0.
        elif pending and pending[0] == "sell" and quantity:
            fill = bar.open * (1 - slip)
            cash = quantity * fill * (1 - fee)
            trades.append({**entry, "exit_time": bar.timestamp, "exit": fill,
                           "pnl": cash - entry["capital"]})
            quantity, entry = 0., None
        pending = None
        equity.append(cash + quantity * bar.close)
        closes.append(bar.close)
        if len(closes) >= slow:
            a, b = sum(closes[-fast:]) / fast, sum(closes[-slow:]) / slow
            if a > b and not quantity:
                pending = ("buy", bar.timestamp)
            elif a < b and quantity:
                pending = ("sell", bar.timestamp)
    # Explicit final liquidation convention; not an extra strategy signal.
    if quantity:
        fill = bars[-1].close * (1 - slip)
        cash = quantity * fill * (1 - fee)
        trades.append({**entry, "exit_time": bars[-1].timestamp, "exit": fill,
                       "pnl": cash - entry["capital"], "forced_end_liquidation": True})
        equity[-1] = cash
    peak, dd = capital, 0.
    for value in equity:
        peak = max(peak, value)
        dd = max(dd, 1 - value / peak)
    wins = sum(max(0., t["pnl"]) for t in trades)
    losses = -sum(min(0., t["pnl"]) for t in trades)
    benchmark = capital / (bars[0].open * (1 + slip) * (1 + fee)) * bars[-1].close * (1 - slip) * (1 - fee)
    return {"mode": "HISTORICAL_SIMULATION", "strategy": "sma_cross_v1", "fast": fast, "slow": slow,
            "bars": len(bars), "final_equity": cash, "net_return": cash / capital - 1,
            "maximum_drawdown": dd, "profit_factor": wins / losses if losses else None,
            "expectancy": (wins - losses) / len(trades) if trades else None,
            "benchmark_final_equity": benchmark, "trades": trades, "equity": equity,
            "data_hash": hashlib.sha256(json.dumps([b.__dict__ for b in bars], sort_keys=True).encode()).hexdigest(),
            "costs": {"fee_bps": fee_bps, "slippage_bps": slippage_bps},
            "limitations": ["long-only fractional-unit research baseline", "no volume/partial-fill model",
                             "no protective stops in this baseline", "raw prices; corporate actions excluded",
                             "not proof of future profit or live readiness"]}


def walk_forward(bars, *, train=60, test=20, fast=5, slow=20):
    validate_bars(bars)
    if train <= slow or test <= slow or train + test > len(bars):
        raise ValueError("Insufficient walk-forward windows")
    rows = []
    for start in range(train, len(bars) - test + 1, test):
        segment = bars[start:start + test]
        result = run(segment, fast=fast, slow=slow)
        rows.append({"train_start": bars[start-train].timestamp, "train_end": bars[start-1].timestamp,
                     "test_start": segment[0].timestamp, "test_end": segment[-1].timestamp,
                     "net_return": result["net_return"], "data_hash": result["data_hash"],
                     "method": "fixed parameters, separate test windows; no optimizer"})
    return rows


def resample(trades, *, iterations=200, seed=0):
    if not trades:
        return {"status": "INSUFFICIENT_TRADES"}
    iterations = max(1, min(int(iterations), 2000))
    returns = [t["pnl"] / t["capital"] for t in trades]
    rng, outcomes = random.Random(seed), []
    for _ in range(iterations):
        value, peak, dd = 1., 1., 0.
        for _ in returns:
            value *= 1 + rng.choice(returns)
            peak = max(peak, value)
            dd = max(dd, 1 - value / peak)
        outcomes.append(dd)
    outcomes.sort()
    return {"iterations": iterations, "seed": seed, "drawdown_p95": outcomes[int(.95 * (iterations-1))],
            "assumption": "IID resampling; serial dependence and unseen tail events not modeled"}
