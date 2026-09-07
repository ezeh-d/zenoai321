"""Instrument units and explicit historical-data provenance."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
import time


def number(value, *, positive=True):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid numeric value") from None
    if not value.is_finite() or (value <= 0 if positive else value < 0):
        raise ValueError("Expected a finite positive number" if positive else "Expected finite nonnegative number")
    return value


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str
    currency: str
    lot: Decimal

    def __post_init__(self):
        if self.market not in {"stocks", "crypto", "forex"}:
            raise ValueError("Unsupported market")
        if not re.fullmatch(r"[A-Z0-9.^=\-]{1,24}", self.symbol):
            raise ValueError("Invalid symbol")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Explicit quote currency required")
        object.__setattr__(self, "lot", number(self.lot))


@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def validate_bars(bars):
    if not bars or len(bars) > 100000:
        raise ValueError("Require 1–100000 chronological bars")
    previous = -1
    for bar in bars:
        if not isinstance(bar.timestamp, int) or bar.timestamp <= previous:
            raise ValueError("Duplicate or unordered timestamps")
        previous = bar.timestamp
        for value in (bar.open, bar.high, bar.low, bar.close):
            number(value)
        number(bar.volume, positive=False)
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
            raise ValueError("Impossible OHLC bar")
    return bars


class ForexReference:
    """Independent daily reference-rate research fallback, not OHLC or quotes."""
    def fetch(self, symbol):
        import requests
        from datetime import date
        pair = str(symbol).upper().removesuffix("=X").replace("/", "")
        if len(pair) == 3:
            pair = "USD" + pair
        if not re.fullmatch(r"[A-Z]{6}", pair) or pair[:3] == pair[3:]:
            raise ValueError("Require a valid base/quote currency pair")
        url = "https://api.frankfurter.dev/v1/latest"
        with requests.get(url, params={"base": pair[:3], "symbols": pair[3:]}, timeout=(5, 15)) as response:
            response.raise_for_status()
            result = response.json()
        observed = date.fromisoformat(result["date"])
        age = (date.today() - observed).days
        if not 0 <= age <= 7 or result.get("base") != pair[:3]:
            raise ValueError("Stale or mismatched reference data")
        return {"source": url, "base": pair[:3], "currency": pair[3:],
                "date": observed.isoformat(), "rate": str(number(result["rates"][pair[3:]])),
                "retrieved_at": time.time(), "rate_type": "daily reference rate"}


class HistoricalData:
    """Yahoo public daily research observations, never executable quotes.

    No API key, no price inferred from model text, and no background polling.
    Vendor outages propagate as unavailable data. Availability is not a claim
    of exchange certification, real-time delivery or broker suitability.
    """
    def fetch(self, symbol, market, period="1y"):
        import requests
        symbol = str(symbol).strip().upper()
        if not re.fullmatch(r"[A-Z0-9.^=\-]{1,24}", symbol):
            raise ValueError("Invalid symbol")
        if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y"}:
            raise ValueError("Unsupported history period")
        if market not in {"stocks", "crypto", "forex"}:
            raise ValueError("Unsupported market")
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol
        with requests.get(url, params={"range": period, "interval": "1d"},
                          timeout=(5, 15), headers={"User-Agent": "ZENO-HunterX/1.0"}) as response:
            response.raise_for_status()
            payload = response.json()
        rows = (payload.get("chart") or {}).get("result")
        if not rows:
            raise ValueError("Market data unavailable")
        row = rows[0]
        meta = row["meta"]
        expected = {"stocks": {"EQUITY", "ETF"}, "crypto": {"CRYPTOCURRENCY"}, "forex": {"CURRENCY"}}
        if meta.get("instrumentType") not in expected[market]:
            raise ValueError("Provider instrument type does not match requested market")
        lot = {"stocks": "1", "crypto": "0.00000001", "forex": "1"}[market]
        instrument = Instrument(symbol, market, meta.get("currency", ""), Decimal(lot))
        quote = row["indicators"]["quote"][0]
        bars, omitted = [], 0
        now = time.time()
        for index, timestamp in enumerate(row.get("timestamp", [])):
            values = [quote.get(key, [])[index] for key in ("open", "high", "low", "close", "volume")]
            # Exclude potentially incomplete daily bars conservatively.
            if timestamp + 86400 > now:
                continue
            if any(v is None for v in values[:4]):
                omitted += 1
                continue
            bars.append(Bar(int(timestamp), *values[:4], values[4] or 0))
        validate_bars(bars)
        if omitted:
            raise ValueError(f"Incomplete OHLC data: {omitted} bars missing")
        return instrument, bars, {"source": url, "retrieved_at": now,
            "last_bar": bars[-1].timestamp, "executable_quote": False,
            "mode": "HISTORICAL_RESEARCH", "currency": instrument.currency,
            "lot_semantics": "simulation units; not broker contract specifications",
            "adjustment": "raw OHLC; corporate actions not modeled"}
