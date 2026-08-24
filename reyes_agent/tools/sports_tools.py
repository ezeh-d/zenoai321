"""Sports prediction as a brain tool -- ZENO's OWN evidence-based forecast.

Exposes the Elo+Poisson ensemble (reyes_agent.sports.prediction). The MATH is
real and works from supplied team strengths; automatic strength/ratings ingestion
needs a licensed data provider (football-data.org / Sportradar / StatsBomb) that
is not connected, so without supplied ratings the forecast is labelled LIMITED
data quality rather than pretending to certainty. Football only; other sports
report UNSUPPORTED until their own models exist.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(
    name="predict_match",
    description="ZENO's OWN evidence-based football forecast (Elo + Poisson "
                "ensemble) for a fixture: win/draw/loss probabilities, expected "
                "goals, likeliest scores, confidence and data quality. This is a "
                "MODEL PREDICTION, never a certainty. Supply team ratings for a "
                "grounded forecast; without them it is clearly labelled LIMITED. "
                "Football only for now.",
    input_schema={"type": "object", "properties": {
        "home": {"type": "string", "description": "Home team name."},
        "away": {"type": "string", "description": "Away team name."},
        "home_elo": {"type": "number", "description": "Home Elo rating (default 1500)."},
        "away_elo": {"type": "number", "description": "Away Elo rating (default 1500)."},
        "home_attack": {"type": "number", "description": "Home attack strength ratio (1.0=avg)."},
        "home_defense": {"type": "number", "description": "Home defense multiplier (1.0=avg)."},
        "away_attack": {"type": "number"},
        "away_defense": {"type": "number"},
        "data_quality": {"type": "string", "enum": ["FULL", "GOOD", "PARTIAL", "LIMITED"]},
    }, "required": ["home", "away"]},
)
def predict_match(home: str, away: str, home_elo: float = 1500.0, away_elo: float = 1500.0,
                  home_attack: float = 1.0, home_defense: float = 1.0,
                  away_attack: float = 1.0, away_defense: float = 1.0,
                  data_quality: str = "") -> str:
    from reyes_agent.sports.prediction import TeamStrength, predict_football

    # If the caller supplied no distinguishing ratings, be honest: this is a
    # thin forecast, not a grounded one.
    supplied = any(v not in (1.0, 1500.0) for v in
                   (home_elo, away_elo, home_attack, home_defense, away_attack, away_defense))
    quality = (data_quality or ("PARTIAL" if supplied else "LIMITED")).upper()

    pred = predict_football(
        TeamStrength(str(home), float(home_elo), float(home_attack), float(home_defense)),
        TeamStrength(str(away), float(away_elo), float(away_attack), float(away_defense)),
        data_quality=quality)
    out = pred.as_dict()
    if not supplied:
        out["note"] = ("No team ratings supplied and no live sports-data provider is "
                       "connected, so this is a baseline forecast (LIMITED). Connect "
                       "football-data.org or Sportradar for grounded ratings.")
    return json.dumps(out, default=str)


# Declare the true capability status so ZENO never fakes coverage (Pack 7 #70).
def _declare() -> None:
    try:
        from reyes_agent import capability_truth as ct

        truth = ct.get_truth()
        truth.declare("sports.predict.football", implemented=True, tested=True,
                      documented=True, has_fallback=True, owner="sports.prediction",
                      description="Elo+Poisson ensemble forecast")
        truth.mark_tested("sports.predict.football", True)
        for sport in ("basketball", "tennis", "cricket", "f1"):
            truth.declare(f"sports.predict.{sport}", implemented=False, tested=False,
                          available=False, owner="sports.prediction",
                          description="model not built yet (UNSUPPORTED)")
    except Exception:  # noqa: BLE001 -- declaration is best-effort
        pass


_declare()
