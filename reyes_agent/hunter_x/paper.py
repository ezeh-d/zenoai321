"""Durable simulation ledger. This module has no network or broker calls."""
from contextlib import closing
from decimal import Decimal
import json
import sqlite3
import time
from .data import number


class PaperAccount:
    def __init__(self, path, currency, capital=10000):
        from pathlib import Path
        import re
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Explicit account currency required")
        capital = number(capital)
        self.path, self.currency = Path(path), currency
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS hx_account (id INTEGER PRIMARY KEY, currency TEXT, cash TEXT, initial TEXT, paused INTEGER)")
            conn.execute("CREATE TABLE IF NOT EXISTS hx_positions (instrument TEXT PRIMARY KEY, quantity TEXT, cost TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS hx_orders (id TEXT PRIMARY KEY, request TEXT, result TEXT)")
            conn.execute("INSERT OR IGNORE INTO hx_account VALUES (1,?,?,?,0)", (currency, str(capital), str(capital)))
            if conn.execute("SELECT currency FROM hx_account WHERE id=1").fetchone()[0] != currency:
                raise ValueError("Account currency mismatch")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def pause(self):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE hx_account SET paused=1 WHERE id=1")
        return self.status()

    def status(self):
        with closing(self._connect()) as conn:
            currency, cash, initial, paused = conn.execute("SELECT currency,cash,initial,paused FROM hx_account WHERE id=1").fetchone()
            positions = [{"instrument": s, "quantity": q, "cost": c} for s, q, c in conn.execute("SELECT * FROM hx_positions")]
            orders = conn.execute("SELECT COUNT(*) FROM hx_orders").fetchone()[0]
        return {"mode": "LOCAL_PAPER", "currency": currency, "cash": cash,
                "initial": initial, "paused": bool(paused), "positions": positions,
                "orders": orders, "live_enabled": False,
                "valuation": "cost basis only; unrealized market P&L unavailable"}

    def trade(self, order_id, instrument, side, quantity, price, *, fee_bps=10, slippage_bps=5):
        if not isinstance(order_id, str) or not 1 <= len(order_id) <= 100:
            raise ValueError("Bounded unique order ID required")
        if side not in {"buy", "sell"} or instrument.currency != self.currency:
            raise ValueError("Invalid side or currency mismatch")
        quantity, price = number(quantity), number(price)
        if quantity % instrument.lot:
            raise ValueError("Quantity violates simulation unit step")
        fee_rate, slip_rate = [number(v, positive=False) / 10000 for v in (fee_bps, slippage_bps)]
        if fee_rate >= 1 or slip_rate >= 1:
            raise ValueError("Invalid costs")
        key = instrument.market + ":" + instrument.symbol
        request = json.dumps([key, side, str(quantity), str(price), str(fee_rate), str(slip_rate)])
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute("SELECT request,result FROM hx_orders WHERE id=?", (order_id,)).fetchone()
            if prior:
                if prior[0] != request:
                    raise ValueError("Order ID already used for different request")
                return json.loads(prior[1])
            cash, paused = conn.execute("SELECT cash,paused FROM hx_account WHERE id=1").fetchone()
            if paused:
                raise ValueError("Paper trading paused; no new orders")
            cash = number(cash, positive=False)
            row = conn.execute("SELECT quantity,cost FROM hx_positions WHERE instrument=?", (key,)).fetchone()
            held, cost = map(Decimal, row or ("0", "0"))
            fill = price * (1 + slip_rate if side == "buy" else 1 - slip_rate)
            gross = quantity * fill
            fee = gross * fee_rate
            realized = Decimal(0)
            if side == "buy":
                if gross + fee > cash:
                    raise ValueError("Insufficient paper cash")
                cash -= gross + fee
                held += quantity
                cost += gross + fee
            else:
                if quantity > held:
                    raise ValueError("Cannot sell unowned paper units")
                allocated = cost * quantity / held
                realized = gross - fee - allocated
                cash += gross - fee
                cost -= allocated
                held -= quantity
            if held:
                conn.execute("INSERT OR REPLACE INTO hx_positions VALUES (?,?,?)", (key, str(held), str(cost)))
            else:
                conn.execute("DELETE FROM hx_positions WHERE instrument=?", (key,))
            conn.execute("UPDATE hx_account SET cash=? WHERE id=1", (str(cash),))
            result = {"id": order_id, "mode": "LOCAL_PAPER", "status": "SIMULATED_FILLED",
                      "instrument": key, "side": side, "quantity": str(quantity),
                      "fill": str(fill), "fee": str(fee), "realized_pnl": str(realized),
                      "currency": self.currency, "timestamp": time.time(),
                      "price_source": "explicit simulation input, not a broker quote"}
            conn.execute("INSERT INTO hx_orders VALUES (?,?,?)", (order_id, request, json.dumps(result)))
        return result

    def journal(self, limit=100):
        with closing(self._connect()) as conn:
            return [json.loads(row[0]) for row in conn.execute(
                "SELECT result FROM hx_orders ORDER BY rowid DESC LIMIT ?", (max(1, min(int(limit), 1000)),))]
