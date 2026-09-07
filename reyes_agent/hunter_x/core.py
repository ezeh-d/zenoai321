"""On-demand HUNTER X operations; no background service or live execution."""
from dataclasses import asdict
from decimal import Decimal
import time
from .data import HistoricalData, Instrument, number
from .risk import assess, Limits

MARKETS = ("stocks", "crypto", "forex")


def execute(action, **options):
    if action not in {"paper_status", "paper_trade", "journal", "stop", "resume_paper"}:
        return _execute(action, **options)
    # All currency-account operations share this cross-process transaction.
    # Once stop commits, no subsequent paper submission can cross the gate.
    from reyes_agent import config
    from contextlib import closing
    import sqlite3
    root = config.VAULT_PATH / "07-System" / "hunter_x"
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "control.db", timeout=5)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS hx_control (id INTEGER PRIMARY KEY, paused INTEGER)")
        conn.execute("INSERT OR IGNORE INTO hx_control VALUES (1,0)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        if action == "resume_paper":
            if options.get("simulation_acknowledged") is not True:
                raise ValueError("Explicit paper-only resume acknowledgment required")
            conn.execute("UPDATE hx_control SET paused=0 WHERE id=1")
            return {"paused": False, "scope": "ALL_PAPER_ACCOUNTS", "live_enabled": False}
        if action == "stop":
            conn.execute("UPDATE hx_control SET paused=1 WHERE id=1")
            return {"paused": True, "scope": "ALL_PAPER_ACCOUNTS", "live_enabled": False}
        paused = bool(conn.execute("SELECT paused FROM hx_control WHERE id=1").fetchone()[0])
        if action == "paper_trade" and paused:
            raise ValueError("HUNTER X globally paused; no new paper orders")
        result = _execute(action, **options)
        if action == "paper_status":
            result["paused"] = result["paused"] or paused
        return result


def _execute(action, **options):
    if action == "status":
        return {"agent": "HUNTER X", "readiness": "UNPROVEN", "live_enabled": False,
                "markets": list(MARKETS), "provider": "Yahoo public daily research data",
                "provider_health": "NOT_CHECKED", "broker": "NOT_CONFIGURED",
                "strategies": ["sma_cross_v1"], "training": "NOT_COMPLETED",
                "scope": "cash-backed long-only research and explicit local simulations"}
    if action in {"analyze", "backtest", "walk_forward"}:
        try:
            instrument, bars, provenance = HistoricalData().fetch(options["symbol"], options["market"], options.get("period", "1y"))
        except Exception as exc:
            from reyes_agent.agent_runtime import current_task_cancel_check
            current_task_cancel_check()
            if action != "analyze" or options["market"] != "forex":
                raise
            from .data import ForexReference
            return {**ForexReference().fetch(options["symbol"]), "symbol": options["symbol"],
                    "market": "forex", "mode": "REFERENCE_RATE_ONLY", "decision": "NO_TRADE",
                    "executable_quote": False, "primary_feed_error": type(exc).__name__,
                    "reason": "Reference-rate fallback; no valid candles or executable broker quote"}
        if action == "analyze":
            closes = [b.close for b in bars]
            if len(closes) < 20:
                raise ValueError("At least 20 completed daily bars required")
            fast, slow = sum(closes[-5:])/5, sum(closes[-20:])/20
            return {"symbol": instrument.symbol, "market": instrument.market,
                    "currency": instrument.currency, "historical_close": closes[-1],
                    "regime": "TRENDING_UP" if fast > slow else "TRENDING_DOWN" if fast < slow else "RANGING",
                    "evidence": {"sma5": fast, "sma20": slow}, "data": provenance,
                    "decision": "NO_TRADE", "reason": "Historical observations only; no executable quote or validated strategy"}
        from .backtest import run, walk_forward, resample
        if action == "walk_forward":
            result = {"windows": walk_forward(bars, train=60, test=30)}
        else:
            result = run(bars)
            result["resampling"] = resample(result["trades"])
            result["stress"] = {"higher_cost_final_equity": run(bars, fee_bps=30, slippage_bps=30)["final_equity"]}
        return {**result, "data": provenance, "symbol": instrument.symbol, "currency": instrument.currency}
    if action == "scan":
        symbols = options.get("symbols", [])
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 6:
            raise ValueError("Scan 1–6 explicitly selected instruments")
        results = []
        for row in symbols:
            from reyes_agent.agent_runtime import current_task_cancel_check
            current_task_cancel_check()
            try:
                results.append(execute("analyze", symbol=row["symbol"], market=row["market"]))
            except Exception as exc:
                results.append({"symbol": row.get("symbol"), "decision": "NO_TRADE", "error": type(exc).__name__})
        return {"results": results, "mode": "HISTORICAL_RESEARCH"}
    if action == "risk":
        i = Instrument(options["symbol"], options["market"], options["currency"], Decimal(str(options.get("lot", 1))))
        return assess(i, options["equity"], options["entry"], options["stop"], options["target"], Limits(),
                      currency=options["currency"], age_seconds=options["age_seconds"])
    if action in {"training", "exam"}:
        from .training import QUESTIONS, grade
        return {"questions": QUESTIONS} if action == "training" else grade(options.get("answers", {}))
    from reyes_agent import config
    root = config.VAULT_PATH / "07-System" / "hunter_x"
    if action in {"research_add", "research_list"}:
        from .research import notes
        return {"notes": notes(root / "research.db", options.get("record") if action == "research_add" else None)}
    if action in {"paper_status", "paper_trade", "journal", "stop"}:
        from .paper import PaperAccount
        currency = options.get("currency", "USD")
        # Validate before constructing a path from a supplied currency.
        import re
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Explicit three-letter account currency required")
        account = PaperAccount(root / (currency + ".db"), currency)
        if action == "paper_status":
            return account.status()
        if action == "stop":
            return account.pause()
        if action == "journal":
            return {"orders": account.journal()}
        if options.get("simulation_acknowledged") is not True:
            raise ValueError("Explicit simulation acknowledgment required")
        i = Instrument(options["symbol"], options["market"], currency, Decimal(str(options.get("lot", 1))))
        state = account.status()
        if options["side"] == "buy":
            if state["orders"] >= 1000:
                raise ValueError("Paper review required after 1000 orders")
            today = int(time.time() // 86400)
            loss = sum(max(Decimal(0), -Decimal(t["realized_pnl"])) for t in account.journal(1000)
                       if int(t["timestamp"] // 86400) == today)
            cost = sum(Decimal(p["cost"]) for p in state["positions"])
            equity = Decimal(state["cash"]) + cost
            drawdown = max(Decimal(0), 1 - equity / Decimal(state["initial"]))
            verdict = assess(i, equity, options["price"], options["stop"], options["target"], Limits(),
                currency=currency, age_seconds=0, daily_loss=loss, drawdown=drawdown,
                open_risk=cost, paused=state["paused"])
            if not verdict["allowed"] or number(options["quantity"]) > Decimal(verdict["quantity"]):
                raise ValueError("Paper risk veto: " + ",".join(verdict["reasons"] or ["POSITION_TOO_LARGE"]))
        return account.trade(options["order_id"], i, options["side"], options["quantity"], options["price"])
    raise ValueError("Unsupported action; live trading is unavailable")
