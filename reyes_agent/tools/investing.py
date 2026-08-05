"""Investment Policy Engine -- portfolio tracking, a configurable risk
policy, pre-trade validation, and reporting.

Modular by design (the user's requirement): everything lives in its own
tables and its own tools, so disabling this module means dropping this
import from tools/__init__.py and nothing else in ZENO changes.

WHERE THIS STOPS, AND WHY
-------------------------
This engine does everything up to and including producing a fully
validated order ticket -- symbol, side, quantity, limit, and a pass/fail
check against every rule in the policy. It does NOT place the order.
There is no broker/bank/wallet API call anywhere in this file and there
won't be one: a wrong trade is the one failure mode in this whole build
that cannot be undone, retried, or apologised for, and the model driving
these tools demonstrably emits malformed tool calls (empty-input
`delegate` calls, three separate times on 2026-08-03). Placing the order
is a ten-second human action; everything expensive and error-prone around
it -- the tracking, the math, the limit checks, the record-keeping -- is
automated here.

That boundary is enforced in code, not convention: see
config.AUTONOMY_NEVER_AUTO_TOOLS.

NOT ADVICE
----------
These tools report arithmetic on data the user entered (allocation
percentages, P&L, concentration, policy breaches). They do not recommend
what to buy or sell. ZENO is not a licensed adviser and should say so
plainly if asked to pick investments.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

_SIDES = ("buy", "sell")

# Policy keys with their defaults. Stored as one JSON row so the user can
# add fields later without a migration.
_DEFAULT_POLICY: dict = {
    "max_capital": None,            # total currency amount ZENO may consider allocated
    "max_loss_per_trade": None,     # currency
    "daily_loss_limit": None,       # currency
    "max_position_pct": None,       # percent of portfolio in any one holding
    "approved_brokers": [],
    "approved_asset_classes": [],
    "approved_strategies": [],
    "market_hours": "",             # free text, e.g. "09:30-16:00 ET Mon-Fri"
    "emergency_stop": False,
    "currency": "NGN",
}


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS invest_policy (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT, updated TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS invest_holdings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, asset_class TEXT, broker TEXT, "
        "quantity REAL, cost_basis REAL, last_price REAL, updated TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS invest_trades ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, quantity REAL, price REAL, "
        "broker TEXT, strategy TEXT, realized_pl REAL, trade_date TEXT, note TEXT, created TEXT)"
    )
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_policy(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT data FROM invest_policy WHERE id = 1").fetchone()
    policy = dict(_DEFAULT_POLICY)
    if row and row[0]:
        try:
            policy.update(json.loads(row[0]))
        except json.JSONDecodeError:
            pass  # corrupt row -> fall back to defaults rather than breaking every tool
    return policy


def _save_policy(conn: sqlite3.Connection, policy: dict) -> None:
    conn.execute(
        "INSERT INTO invest_policy (id, data, updated) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
        (json.dumps(policy), _now()),
    )


def _portfolio_value(conn: sqlite3.Connection) -> float:
    rows = conn.execute("SELECT quantity, last_price, cost_basis FROM invest_holdings").fetchall()
    total = 0.0
    for qty, last, cost in rows:
        price = last if last else cost
        total += (qty or 0) * (price or 0)
    return total


@register(
    name="set_investment_policy",
    description=(
        "Set or update the investment policy limits ZENO checks every "
        "proposed trade against -- max capital, max loss per trade, daily "
        "loss limit, max position size percent, approved brokers/asset "
        "classes/strategies, market hours, and the emergency stop. Only "
        "the fields you pass are changed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "max_capital": {"type": "number", "description": "Total capital ZENO may treat as investable."},
            "max_loss_per_trade": {"type": "number", "description": "Maximum acceptable loss on a single trade."},
            "daily_loss_limit": {"type": "number", "description": "Stop for the day once realized losses exceed this."},
            "max_position_pct": {"type": "number", "description": "Max percent of the portfolio in any one holding."},
            "approved_brokers": {"type": "array", "items": {"type": "string"}},
            "approved_asset_classes": {"type": "array", "items": {"type": "string"}, "description": "e.g. stocks, etf, bonds, crypto."},
            "approved_strategies": {"type": "array", "items": {"type": "string"}},
            "market_hours": {"type": "string", "description": "Free text, e.g. '09:30-16:00 ET Mon-Fri'."},
            "emergency_stop": {"type": "boolean", "description": "True blocks every proposed trade until cleared."},
            "currency": {"type": "string", "description": "Currency code for all amounts, e.g. NGN or USD."},
        },
    },
    light=True,
)
def set_investment_policy(**fields) -> str:
    provided = {k: v for k, v in fields.items() if v is not None and k in _DEFAULT_POLICY}
    if not provided:
        return "Nothing to change -- pass at least one policy field."
    with _connect() as conn:
        policy = _load_policy(conn)
        policy.update(provided)
        _save_policy(conn, policy)
    changed = ", ".join(f"{k}={v}" for k, v in provided.items())
    return f"Investment policy updated: {changed}."


@register(
    name="get_investment_policy",
    description="Show the current investment policy limits and whether the emergency stop is engaged.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def get_investment_policy() -> str:
    with _connect() as conn:
        policy = _load_policy(conn)
    if policy.get("emergency_stop"):
        header = "EMERGENCY STOP ENGAGED -- every proposed trade is blocked.\n"
    else:
        header = ""
    lines = [f"{k}: {v if v not in (None, [], '') else '(not set)'}" for k, v in policy.items()]
    return header + "Investment policy:\n" + "\n".join(lines)


@register(
    name="record_holding",
    description=(
        "Add or update a portfolio holding the user actually owns. Use "
        "after they tell you what's in their portfolio, or after they "
        "confirm a trade they placed themselves."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ticker or asset name."},
            "quantity": {"type": "number", "description": "Units held. 0 removes the holding."},
            "cost_basis": {"type": "number", "description": "Average price paid per unit."},
            "last_price": {"type": "number", "description": "Latest known price per unit (optional)."},
            "asset_class": {"type": "string", "description": "e.g. stocks, etf, crypto, bonds."},
            "broker": {"type": "string", "description": "Where it's held."},
        },
        "required": ["symbol", "quantity"],
    },
    light=True,
)
def record_holding(symbol: str, quantity: float, cost_basis: float = 0, last_price: float = 0,
                   asset_class: str = "", broker: str = "") -> str:
    sym = symbol.strip().upper()
    with _connect() as conn:
        row = conn.execute("SELECT id FROM invest_holdings WHERE symbol = ?", (sym,)).fetchone()
        if quantity == 0:
            if row:
                conn.execute("DELETE FROM invest_holdings WHERE id = ?", (row[0],))
                return f"Removed {sym} from the portfolio."
            return f"No holding for {sym}."
        if row:
            conn.execute(
                "UPDATE invest_holdings SET quantity = ?, cost_basis = ?, last_price = ?, "
                "asset_class = ?, broker = ?, updated = ? WHERE id = ?",
                (quantity, cost_basis, last_price, asset_class.strip(), broker.strip(), _now(), row[0]),
            )
            return f"Updated {sym}: {quantity} units."
        conn.execute(
            "INSERT INTO invest_holdings (symbol, asset_class, broker, quantity, cost_basis, last_price, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sym, asset_class.strip(), broker.strip(), quantity, cost_basis, last_price, _now()),
        )
    return f"Recorded {sym}: {quantity} units."


@register(
    name="portfolio_report",
    description=(
        "Report the tracked portfolio: every holding, its value, unrealized "
        "P&L, allocation percent, plus concentration and any policy "
        "breaches. Factual arithmetic on recorded data -- not advice on "
        "what to buy or sell."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def portfolio_report() -> str:
    with _connect() as conn:
        policy = _load_policy(conn)
        rows = conn.execute(
            "SELECT symbol, asset_class, broker, quantity, cost_basis, last_price FROM invest_holdings ORDER BY symbol"
        ).fetchall()
        total = _portfolio_value(conn)
    if not rows:
        return "No holdings tracked yet."
    cur = policy.get("currency") or ""
    lines = [f"Portfolio value: {total:,.2f} {cur}"]
    breaches = []
    for sym, klass, broker, qty, cost, last in rows:
        price = last if last else cost
        value = (qty or 0) * (price or 0)
        pct = (value / total * 100) if total else 0
        pl = ((price or 0) - (cost or 0)) * (qty or 0)
        detail = f"  {sym}: {qty:g} @ {price:,.2f} = {value:,.2f} ({pct:.1f}%)"
        if cost:
            detail += f", unrealized {pl:+,.2f}"
        if klass:
            detail += f" [{klass}]"
        lines.append(detail)
        max_pct = policy.get("max_position_pct")
        if max_pct and pct > max_pct:
            breaches.append(f"  {sym} is {pct:.1f}% of the portfolio, over the {max_pct}% position limit.")
        approved = policy.get("approved_asset_classes") or []
        if approved and klass and klass.lower() not in [a.lower() for a in approved]:
            breaches.append(f"  {sym} is asset class '{klass}', which is not in the approved list.")
    max_cap = policy.get("max_capital")
    if max_cap and total > max_cap:
        breaches.append(f"  Portfolio value {total:,.2f} exceeds max capital {max_cap:,.2f}.")
    if breaches:
        lines.append("\nPolicy breaches:")
        lines.extend(breaches)
    else:
        lines.append("\nNo policy breaches.")
    return "\n".join(lines)


@register(
    name="check_trade_against_policy",
    description=(
        "Validate a trade the user is considering against every rule in "
        "the investment policy, and produce a ready-to-place order ticket "
        "with the result. This does NOT place the order -- ZENO has no "
        "broker connection and never places orders; the user places it "
        "themselves. Use whenever a trade is being considered."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": list(_SIDES)},
            "quantity": {"type": "number"},
            "price": {"type": "number", "description": "Intended price per unit."},
            "broker": {"type": "string"},
            "strategy": {"type": "string"},
            "asset_class": {"type": "string"},
            "stop_loss": {"type": "number", "description": "Intended stop price, used to check max loss per trade."},
        },
        "required": ["symbol", "side", "quantity", "price"],
    },
    light=True,
)
def check_trade_against_policy(symbol: str, side: str, quantity: float, price: float,
                               broker: str = "", strategy: str = "", asset_class: str = "",
                               stop_loss: float = 0) -> str:
    side = side.strip().lower()
    if side not in _SIDES:
        return "side must be 'buy' or 'sell'."
    sym = symbol.strip().upper()
    notional = quantity * price

    with _connect() as conn:
        policy = _load_policy(conn)
        total = _portfolio_value(conn)
        today = date.today().isoformat()
        realized_today = conn.execute(
            "SELECT COALESCE(SUM(realized_pl), 0) FROM invest_trades WHERE trade_date = ?", (today,)
        ).fetchone()[0] or 0.0

    cur = policy.get("currency") or ""
    fails: list[str] = []
    warns: list[str] = []

    if policy.get("emergency_stop"):
        fails.append("EMERGENCY STOP is engaged -- no trades until it's cleared.")

    brokers = policy.get("approved_brokers") or []
    if brokers and broker and broker.lower() not in [b.lower() for b in brokers]:
        fails.append(f"Broker '{broker}' is not in the approved list ({', '.join(brokers)}).")
    elif brokers and not broker:
        warns.append("No broker given, so the approved-broker rule couldn't be checked.")

    classes = policy.get("approved_asset_classes") or []
    if classes and asset_class and asset_class.lower() not in [c.lower() for c in classes]:
        fails.append(f"Asset class '{asset_class}' is not approved ({', '.join(classes)}).")

    strategies = policy.get("approved_strategies") or []
    if strategies and strategy and strategy.lower() not in [s.lower() for s in strategies]:
        fails.append(f"Strategy '{strategy}' is not approved ({', '.join(strategies)}).")

    max_cap = policy.get("max_capital")
    if max_cap and side == "buy" and (total + notional) > max_cap:
        fails.append(f"Would put {total + notional:,.2f} at work, over max capital {max_cap:,.2f}.")

    max_pct = policy.get("max_position_pct")
    if max_pct and side == "buy":
        projected_total = total + notional
        projected_pct = (notional / projected_total * 100) if projected_total else 0
        if projected_pct > max_pct:
            fails.append(f"Position would be {projected_pct:.1f}% of the portfolio, over the {max_pct}% limit.")

    max_loss = policy.get("max_loss_per_trade")
    if max_loss:
        if stop_loss and side == "buy":
            risk = (price - stop_loss) * quantity
            if risk > max_loss:
                fails.append(f"Risk to stop is {risk:,.2f}, over the {max_loss:,.2f} per-trade limit.")
        elif not stop_loss:
            warns.append("No stop loss given, so per-trade risk couldn't be checked.")

    daily_limit = policy.get("daily_loss_limit")
    if daily_limit and realized_today < 0 and abs(realized_today) >= daily_limit:
        fails.append(f"Today's realized loss ({realized_today:,.2f}) already hit the {daily_limit:,.2f} daily limit.")

    if policy.get("market_hours"):
        warns.append(f"Policy market hours are '{policy['market_hours']}' -- confirm the market is open.")

    verdict = "BLOCKED BY POLICY" if fails else "PASSES POLICY"
    out = [
        f"ORDER TICKET -- {verdict}",
        f"  {side.upper()} {quantity:g} {sym} @ {price:,.2f} = {notional:,.2f} {cur}",
    ]
    if broker:
        out.append(f"  Broker: {broker}")
    if stop_loss:
        out.append(f"  Stop: {stop_loss:,.2f}")
    if fails:
        out.append("\nBlocking:")
        out.extend(f"  - {f}" for f in fails)
    if warns:
        out.append("\nUnchecked / notes:")
        out.extend(f"  - {w}" for w in warns)
    out.append(
        "\nZENO does not place orders. If this passes and you want it, place it "
        "with your broker yourself, then tell me and I'll record it with record_trade."
    )
    return "\n".join(out)


@register(
    name="record_trade",
    description=(
        "Record a trade the user has already placed themselves, so the "
        "portfolio, daily loss tracking, and reports stay accurate."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": list(_SIDES)},
            "quantity": {"type": "number"},
            "price": {"type": "number"},
            "broker": {"type": "string"},
            "strategy": {"type": "string"},
            "realized_pl": {"type": "number", "description": "Realized profit/loss on a closing trade (negative for a loss)."},
            "note": {"type": "string"},
        },
        "required": ["symbol", "side", "quantity", "price"],
    },
    light=True,
)
def record_trade(symbol: str, side: str, quantity: float, price: float, broker: str = "",
                 strategy: str = "", realized_pl: float = 0, note: str = "") -> str:
    side = side.strip().lower()
    if side not in _SIDES:
        return "side must be 'buy' or 'sell'."
    sym = symbol.strip().upper()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO invest_trades (symbol, side, quantity, price, broker, strategy, realized_pl, "
            "trade_date, note, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sym, side, quantity, price, broker.strip(), strategy.strip(), realized_pl,
             date.today().isoformat(), note.strip(), _now()),
        )
        policy = _load_policy(conn)
        today_pl = conn.execute(
            "SELECT COALESCE(SUM(realized_pl), 0) FROM invest_trades WHERE trade_date = ?",
            (date.today().isoformat(),),
        ).fetchone()[0] or 0.0
    msg = f"Recorded: {side} {quantity:g} {sym} @ {price:,.2f}."
    limit = policy.get("daily_loss_limit")
    if limit and today_pl < 0 and abs(today_pl) >= limit:
        msg += (f" WARNING: today's realized loss is {today_pl:,.2f}, at or past your "
                f"{limit:,.2f} daily limit -- policy says stop trading today.")
    return msg


def _fetch_history(symbol: str, period: str = "1y", min_bars: int = 10) -> list[dict]:
    """Real daily bars from Yahoo's keyless chart endpoint.

    Raises RuntimeError with a plain message on failure -- callers surface
    it rather than silently backtesting against nothing, which would
    produce confident numbers from no data.
    """
    import requests

    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.strip().upper()}"
           f"?range={period}&interval=1d")
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"could not fetch price history: {exc}") from exc
    result = (data.get("chart") or {}).get("result")
    if not result:
        err = ((data.get("chart") or {}).get("error") or {}).get("description", "unknown symbol")
        raise RuntimeError(f"no data for '{symbol}': {err}")
    r = result[0]
    ts = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    bars = []
    for t, c in zip(ts, closes):
        if c is None:
            continue  # holidays/halts come back as null; skip rather than interpolate
        bars.append({"t": t, "date": datetime.fromtimestamp(t).strftime("%Y-%m-%d"), "close": float(c)})
    # min_bars is the BACKTEST requirement; a simple price lookup only
    # needs one bar, so callers pass min_bars=1 for that.
    if len(bars) < min_bars:
        raise RuntimeError(f"only {len(bars)} usable bars for '{symbol}' -- not enough to test")
    return bars


@register(
    name="paper_trade",
    description=(
        "Place a SIMULATED trade in the paper-trading account -- no real "
        "money, no broker, nothing leaves this machine. Use to practise or "
        "test an idea before deciding anything real. Prices are fetched "
        "live."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": list(_SIDES)},
            "quantity": {"type": "number"},
            "price": {"type": "number", "description": "Optional; live price is used if omitted."},
        },
        "required": ["symbol", "side", "quantity"],
    },
    light=True,
)
def paper_trade(symbol: str, side: str, quantity: float, price: float = 0) -> str:
    side = side.strip().lower()
    if side not in _SIDES:
        return "side must be 'buy' or 'sell'."
    sym = symbol.strip().upper()
    if not price:
        try:
            price = _fetch_history(sym, "5d", min_bars=1)[-1]["close"]
        except RuntimeError as exc:
            return f"Couldn't get a price for {sym} -- {exc}. Pass an explicit price to proceed."
    notional = quantity * price

    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS paper_account (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL, currency TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS paper_positions ("
            "symbol TEXT PRIMARY KEY, quantity REAL, avg_cost REAL)"
        )
        row = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()
        if row is None:
            conn.execute("INSERT INTO paper_account (id, cash, currency) VALUES (1, 1000000, 'NGN')")
            cash = 1000000.0
        else:
            cash = row[0]

        pos = conn.execute("SELECT quantity, avg_cost FROM paper_positions WHERE symbol=?", (sym,)).fetchone()
        held, avg = (pos or (0.0, 0.0))

        if side == "buy":
            if notional > cash:
                return (f"Paper account has {cash:,.2f} -- not enough for {quantity:g} {sym} "
                        f"at {price:,.2f} ({notional:,.2f}).")
            new_qty = held + quantity
            avg = ((held * avg) + notional) / new_qty if new_qty else 0
            cash -= notional
            conn.execute("INSERT INTO paper_positions (symbol, quantity, avg_cost) VALUES (?,?,?) "
                         "ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, avg_cost=excluded.avg_cost",
                         (sym, new_qty, avg))
            realized = 0.0
        else:
            if quantity > held:
                return f"Paper account holds only {held:g} {sym}; can't sell {quantity:g}."
            realized = (price - avg) * quantity
            new_qty = held - quantity
            cash += notional
            if new_qty <= 0:
                conn.execute("DELETE FROM paper_positions WHERE symbol=?", (sym,))
            else:
                conn.execute("UPDATE paper_positions SET quantity=? WHERE symbol=?", (new_qty, sym))
        conn.execute("UPDATE paper_account SET cash=? WHERE id=1", (cash,))

    msg = f"PAPER {side.upper()} {quantity:g} {sym} @ {price:,.2f} = {notional:,.2f}. Cash now {cash:,.2f}."
    if side == "sell":
        msg += f" Realized P&L {realized:+,.2f}."
    return msg + " (simulated -- no real money moved)"


@register(
    name="paper_portfolio",
    description="Show the simulated paper-trading account: cash, positions, and live unrealized P&L.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def paper_portfolio() -> str:
    with _connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS paper_account (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL, currency TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS paper_positions (symbol TEXT PRIMARY KEY, quantity REAL, avg_cost REAL)")
        row = conn.execute("SELECT cash FROM paper_account WHERE id=1").fetchone()
        cash = row[0] if row else 1000000.0
        positions = conn.execute("SELECT symbol, quantity, avg_cost FROM paper_positions ORDER BY symbol").fetchall()
    lines = [f"PAPER ACCOUNT (simulated)", f"  Cash: {cash:,.2f}"]
    total = cash
    if not positions:
        lines.append("  No open positions.")
    for sym, qty, avg in positions:
        try:
            last = _fetch_history(sym, "5d", min_bars=1)[-1]["close"]
            value = qty * last
            pl = (last - avg) * qty
            total += value
            lines.append(f"  {sym}: {qty:g} @ avg {avg:,.2f}, now {last:,.2f} = {value:,.2f} ({pl:+,.2f})")
        except RuntimeError:
            total += qty * avg
            lines.append(f"  {sym}: {qty:g} @ avg {avg:,.2f} (live price unavailable)")
    lines.append(f"  Total account value: {total:,.2f}")
    return "\n".join(lines)


@register(
    name="backtest_strategy",
    description=(
        "Backtest a simple strategy against REAL historical daily prices. "
        "Strategies: 'buy_and_hold', 'sma_cross' (fast/slow moving average "
        "crossover). Reports return, max drawdown, trade count, and how it "
        "compared to simply holding."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "e.g. AAPL, MSFT, BTC-USD."},
            "strategy": {"type": "string", "enum": ["buy_and_hold", "sma_cross"]},
            "period": {"type": "string", "description": "1mo, 6mo, 1y, 2y, 5y. Default 1y."},
            "fast": {"type": "integer", "description": "Fast SMA window (sma_cross). Default 20."},
            "slow": {"type": "integer", "description": "Slow SMA window (sma_cross). Default 50."},
        },
        "required": ["symbol", "strategy"],
    },
)
def backtest_strategy(symbol: str, strategy: str, period: str = "1y",
                      fast: int = 20, slow: int = 50) -> str:
    try:
        bars = _fetch_history(symbol, period or "1y")
    except RuntimeError as exc:
        return f"Backtest aborted -- {exc}. No result is better than a made-up one."

    closes = [b["close"] for b in bars]
    start, end = closes[0], closes[-1]
    hold_return = (end / start - 1) * 100

    def drawdown(series: list[float]) -> float:
        peak, worst = series[0], 0.0
        for v in series:
            peak = max(peak, v)
            worst = min(worst, (v / peak - 1) * 100)
        return worst

    strat = strategy.strip().lower()
    if strat == "buy_and_hold":
        equity = [c / start for c in closes]
        trades = 1
        ret = hold_return
    elif strat == "sma_cross":
        fast, slow = max(2, int(fast or 20)), max(3, int(slow or 50))
        if fast >= slow:
            return "fast window must be smaller than slow."
        if len(closes) < slow + 5:
            return f"Only {len(closes)} bars -- need more than {slow} for a {slow}-day average. Use a longer period."
        equity, cash_mult, position, trades, entry = [], 1.0, False, 0, 0.0
        for i, price in enumerate(closes):
            if i >= slow:
                f_avg = sum(closes[i - fast + 1:i + 1]) / fast
                s_avg = sum(closes[i - slow + 1:i + 1]) / slow
                if f_avg > s_avg and not position:
                    position, entry, trades = True, price, trades + 1
                elif f_avg < s_avg and position:
                    cash_mult *= price / entry
                    position = False
            equity.append(cash_mult * (price / entry if position else 1.0))
        if position:
            cash_mult *= closes[-1] / entry
        ret = (cash_mult - 1) * 100
    else:
        return "strategy must be 'buy_and_hold' or 'sma_cross'."

    dd = drawdown(equity)
    out = [
        f"BACKTEST -- {symbol.upper()} / {strat} / {period}",
        f"  Real bars used: {len(bars)}  ({bars[0]['date']} to {bars[-1]['date']})",
        f"  Strategy return: {ret:+.1f}%",
        f"  Buy & hold:      {hold_return:+.1f}%",
        f"  Difference:      {ret - hold_return:+.1f}%",
        f"  Max drawdown:    {dd:.1f}%",
        f"  Trades:          {trades}",
        "",
        "Past performance is not predictive. This tests one strategy on one "
        "symbol over one period with no fees, slippage, or taxes modelled -- "
        "real results would be worse. Not advice.",
    ]
    return "\n".join(out)


@register(
    name="investment_performance_report",
    description="Report realized trading performance over a period -- trade count, realized P&L, best and worst trades.",
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "integer", "description": "How many days back. Default 30."}},
    },
    light=True,
)
def investment_performance_report(days: int = 30) -> str:
    days = max(1, min(3650, int(days or 30)))
    with _connect() as conn:
        policy = _load_policy(conn)
        rows = conn.execute(
            "SELECT symbol, side, quantity, price, realized_pl, trade_date FROM invest_trades "
            "WHERE julianday('now') - julianday(trade_date) <= ? ORDER BY trade_date DESC",
            (days,),
        ).fetchall()
    if not rows:
        return f"No trades recorded in the last {days} days."
    cur = policy.get("currency") or ""
    total_pl = sum((r[4] or 0) for r in rows)
    closed = [r for r in rows if r[4]]
    lines = [
        f"Last {days} days: {len(rows)} trades recorded, realized P&L {total_pl:+,.2f} {cur}",
    ]
    if closed:
        best = max(closed, key=lambda r: r[4])
        worst = min(closed, key=lambda r: r[4])
        lines.append(f"  Best: {best[0]} {best[4]:+,.2f} ({best[5]})")
        lines.append(f"  Worst: {worst[0]} {worst[4]:+,.2f} ({worst[5]})")
    lines.append("\nRecent:")
    for sym, side, qty, price, pl, tdate in rows[:10]:
        line = f"  {tdate} {side} {qty:g} {sym} @ {price:,.2f}"
        if pl:
            line += f" -> {pl:+,.2f}"
        lines.append(line)
    return "\n".join(lines)
