"""Deterministic research risk veto and cash-backed spot sizing."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from .data import number


@dataclass(frozen=True)
class Limits:
    risk_fraction: float = .01
    daily_fraction: float = .02
    portfolio_fraction: float = .05
    drawdown_fraction: float = .1
    max_position_fraction: float = .2
    minimum_rr: float = 2
    fee_bps: float = 10
    slippage_bps: float = 5
    maximum_age_seconds: float = 60

    def __post_init__(self):
        for name in ("risk_fraction", "daily_fraction", "portfolio_fraction", "drawdown_fraction", "max_position_fraction"):
            if number(getattr(self, name)) > 1:
                raise ValueError("Risk fractions must be in (0,1]")
        number(self.minimum_rr)
        number(self.maximum_age_seconds)
        for value in (self.fee_bps, self.slippage_bps):
            if number(value, positive=False) >= 10000:
                raise ValueError("Invalid cost rate")


def assess(instrument, equity, entry, stop, target, limits, *, currency,
           age_seconds, daily_loss=0, drawdown=0, open_risk=0, paused=False):
    equity, entry, stop, target = map(number, (equity, entry, stop, target))
    age, daily, dd, used = [number(v, positive=False) for v in (age_seconds, daily_loss, drawdown, open_risk)]
    reasons = []
    if paused:
        reasons.append("KILL_SWITCH")
    if currency != instrument.currency:
        reasons.append("CURRENCY_MISMATCH")
    if age > number(limits.maximum_age_seconds):
        reasons.append("STALE_DATA")
    if not stop < entry < target:
        reasons.append("INVALID_LONG_STOP_OR_TARGET")
    if daily >= equity * number(limits.daily_fraction):
        reasons.append("DAILY_LOSS_LIMIT")
    if dd >= number(limits.drawdown_fraction):
        reasons.append("DRAWDOWN_LIMIT")
    costs = number(limits.fee_bps + limits.slippage_bps, positive=False) / 10000
    loss = entry - stop + (entry + stop) * costs
    reward = target - entry - (entry + target) * costs
    if loss <= 0 or reward / loss < number(limits.minimum_rr):
        reasons.append("INSUFFICIENT_COST_ADJUSTED_RR")
    budget = min(equity * number(limits.risk_fraction), equity * number(limits.portfolio_fraction) - used)
    if budget <= 0:
        reasons.append("PORTFOLIO_RISK_LIMIT")
    quantity = Decimal(0)
    if not reasons:
        quantity = min(budget / loss, equity * number(limits.max_position_fraction) / (entry * (1 + costs)))
        quantity = (quantity / instrument.lot).to_integral_value(rounding=ROUND_FLOOR) * instrument.lot
        if quantity <= 0:
            reasons.append("BELOW_MINIMUM_SIMULATION_UNIT")
    return {"allowed": not reasons, "reasons": reasons, "quantity": str(quantity),
            "risk": str(quantity * max(Decimal(0), loss)), "currency": currency,
            "risk_reward": str(reward / loss) if loss > 0 else None,
            "scope": "long-only research estimate; not a live order approval"}
