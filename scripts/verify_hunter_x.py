"""Run the native tool with an isolated paper account; --live-data is read-only."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reyes_agent import config
from reyes_agent.tools import TOOLS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-data", action="store_true")
    args = parser.parse_args()
    evidence = []
    original = config.VAULT_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="hunter-x-verification-") as folder, ExitStack() as cleanup:
            from reyes_agent import event_bus
            cleanup.callback(event_bus.shutdown)
            config.VAULT_PATH = Path(folder)
            call = TOOLS["hunter_x"].func
            def check(action, **options):
                start = time.perf_counter()
                result = json.loads(call(action=action, options=options))
                assert result["ok"], result
                evidence.append({"action": action, "elapsed_ms": (time.perf_counter()-start)*1000,
                                 "result": result})
                return result
            check("status")
            check("training")
            check("paper_status", currency="USD")
            trade = dict(currency="USD", symbol="TEST", market="stocks", side="buy",
                         quantity=2, price=100, stop=95, target=115, order_id="verification-only",
                         simulation_acknowledged=True)
            check("paper_trade", **trade)
            check("paper_trade", **trade)
            assert check("paper_status", currency="USD")["orders"] == 1
            check("paper_trade", **{**trade, "side": "sell", "order_id": "verification-close"})
            check("journal", currency="USD")
            check("stop")
            assert not json.loads(call(action="paper_trade", options={**trade, "order_id": "blocked"}))["ok"]
            if args.live_data:
                for market, symbol in (("stocks", "AAPL"), ("crypto", "BTC-USD"), ("forex", "EURUSD=X")):
                    result = json.loads(call(action="analyze", options={"market": market, "symbol": symbol}))
                    evidence.append({"live_data": symbol, "result": result})
                result = json.loads(call(action="backtest", options={"market": "stocks", "symbol": "AAPL"}))
                # Keep the CLI report compact; full arrays are available in the tool.
                evidence.append({"historical_backtest": {k: v for k, v in result.items() if k not in {"equity", "trades"}}})
    finally:
        config.VAULT_PATH = original
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
