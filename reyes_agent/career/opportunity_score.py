"""Explainable 0-100 opportunity score -- the funnel's ranking signal.

Composes the ATS skill match and the scam detector with pay/remote/competition
heuristics into one score WITH reasons, so ZENO shortlists high-quality
opportunities instead of spamming applications. A high scam risk hard-gates the
recommendation to AVOID no matter how good the pay looks. Pure logic; every
factor is explained.
"""

from __future__ import annotations

from typing import Any

from reyes_agent.career import ats, scam_detector

# Composite weights (sum 1.0).
_WEIGHTS = {"skill_match": 0.35, "safety": 0.20, "pay": 0.15,
            "remote": 0.10, "competition": 0.10, "reputation": 0.10}


def _pay_score(opp: dict[str, Any], profile: dict[str, Any]) -> float:
    pay = opp.get("pay") or opp.get("budget") or opp.get("rate")
    want = profile.get("min_rate") or 0
    try:
        pay = float(pay)
    except (TypeError, ValueError):
        return 55.0                       # unknown pay -> neutral
    if not want:
        return 70.0
    ratio = pay / float(want)
    return max(10.0, min(100.0, 50.0 + 40.0 * (ratio - 1)))


def _competition_score(opp: dict[str, Any]) -> float:
    n = opp.get("applicants")
    if not isinstance(n, (int, float)):
        return 60.0                       # unknown -> neutral
    if n <= 5:
        return 95.0
    if n <= 20:
        return 75.0
    if n <= 50:
        return 55.0
    return 30.0


def score(opportunity: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    opp = opportunity or {}
    profile = profile or {}
    desc = f"{opp.get('title', '')} {opp.get('description', '')}"

    ats_result = ats.match(desc, profile.get("skills", []),
                           profile_years=int(profile.get("years", 0) or 0),
                           has_degree=bool(profile.get("has_degree", False)))
    scam = scam_detector.assess(opp.get("description", desc))

    breakdown = {
        "skill_match": float(ats_result["match_pct"]),
        "safety": float(100 - scam["score"]),
        "pay": _pay_score(opp, profile),
        "remote": 100.0 if (opp.get("remote") and profile.get("remote_pref", True))
        else (70.0 if opp.get("remote") else 40.0),
        "competition": _competition_score(opp),
        "reputation": float(opp.get("employer_reputation", 60)),
    }
    total = round(sum(_WEIGHTS[k] * v for k, v in breakdown.items()))

    reasons = []
    if breakdown["skill_match"] >= 70:
        reasons.append(f"strong skill match ({breakdown['skill_match']:.0f}%)")
    elif breakdown["skill_match"] < 45:
        reasons.append(f"weak skill match ({breakdown['skill_match']:.0f}%)")
    if scam["level"] != "LOW":
        reasons.append(f"scam risk {scam['level']} ({', '.join(scam['reasons'][:2])})")
    if ats_result["missing"]:
        reasons.append("missing: " + ", ".join(ats_result["missing"][:3]))

    # Hard safety gate: a high scam risk overrides a good-looking score.
    if scam["level"] == "HIGH":
        rec = "AVOID — high scam risk"
    elif total >= 75:
        rec = "APPLY"
    elif total >= 55:
        rec = "CONSIDER"
    else:
        rec = "SKIP"

    return {
        "score": total,
        "breakdown": {k: round(v) for k, v in breakdown.items()},
        "recommendation": rec,
        "reasons": reasons,
        "ats": ats_result,
        "scam": scam,
    }
