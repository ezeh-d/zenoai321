"""Lazy ZENO interface; importing this module starts no trading runtime."""
import json
import time
from reyes_agent.tools import register


@register(name="hunter_x", description=(
    "HUNTER X research specialist for stocks, crypto spot and forex. Actions: status; "
    "analyze/backtest/walk_forward (symbol, market, optional period); scan (symbols list "
    "of {symbol,market}, max 6); risk (symbol,market,currency,equity,entry,stop,target,age_seconds); "
    "paper_status/journal/stop (currency); paper_trade (currency,symbol,market,side,quantity,price,"
    "stop,target,order_id,simulation_acknowledged=true). training returns arithmetic questions; "
    "exam grades answers. Paper uses explicitly supplied scenario "
    "prices, NOT current executable quotes. Stop persistently pauses ALL paper accounts. "
    "resume_paper requires simulation_acknowledged=true and only resumes the global paper gate. "
    "research_add (record with hypothesis,source,classification,source_quality,test_plan); research_list. "
    "No real orders. Yahoo historical research symbols: AAPL, BTC-USD, EURUSD=X. "
    "Never claim a trained/validated or profitable system from these tools alone."),
    input_schema={"type": "object", "properties": {"action": {"type": "string"},
        "options": {"type": "object"}}, "required": ["action"]}, light=True)
def hunter_x(action, options=None):
    from reyes_agent.hunter_x.core import execute
    started = time.perf_counter()
    try:
        from reyes_agent import event_bus
        event_bus.publish("hunter_x.update", {"operation": action, "status": "RUNNING",
                          "mode": "RESEARCH_OR_PAPER", "live_enabled": False}, source="hunter_x")
    except Exception:
        pass
    try:
        result = {"ok": True, **execute(action, **(options or {}))}
    except Exception as exc:
        from reyes_agent.agent_runtime import current_task_cancel_check
        current_task_cancel_check()
        result = {"ok": False, "error": str(exc)[:300], "status": "ERROR", "live_enabled": False}
    result["operation"] = action
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    try:
        from reyes_agent import event_bus
        # The panel needs a compact result, not an entire equity curve or
        # private journal/research records copied to every event subscriber.
        summary = {k: v for k, v in result.items() if k not in {"equity", "trades", "notes", "orders"}}
        if "trades" in result:
            summary["closed_trades"] = len(result["trades"])
        event_bus.publish("hunter_x.update", summary, source="hunter_x")
    except Exception:
        pass
    return json.dumps(result, default=str, allow_nan=False)
