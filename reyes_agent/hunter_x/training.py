"""Foundational arithmetic exam; passing does not confer trading readiness."""
from .data import number

QUESTIONS = {
    "risk_budget": "What is 1% of an equity balance of 10,000?",
    "position_units": "Ignoring costs, risk budget 100 and stop distance 5 allow how many units?",
    "net_pnl": "Gross profit 100 minus total fees and slippage of 10 gives what net P&L?",
    "drawdown_percent": "Equity falls from a peak of 10,000 to 9,000. What is drawdown in percent?",
}


def grade(answers):
    expected = {"risk_budget": 100, "position_units": 20, "net_pnl": 90, "drawdown_percent": 10}
    results = {}
    for key, correct in expected.items():
        try:
            results[key] = number(answers.get(key), positive=False) == correct
        except ValueError:
            results[key] = False
    return {"exam": "foundational_arithmetic_v1", "results": results,
            "correct": sum(results.values()), "total": len(results),
            "passed": all(results.values()), "readiness": "UNPROVEN",
            "scope": "arithmetic only; market mechanics, execution and statistical competency not assessed"}
