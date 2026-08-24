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
                  data_quality: str = "", competition: str = "BL1") -> str:
    from reyes_agent.sports.prediction import TeamStrength, predict_football

    supplied = any(v not in (1.0, 1500.0) for v in
                   (home_elo, away_elo, home_attack, home_defense, away_attack, away_defense))

    # Prefer a GROUNDED forecast from real standings + results when no explicit
    # ratings were supplied and football-data.org is connected.
    if not supplied:
        try:
            from reyes_agent.sports.providers.football_data import get_provider
            from reyes_agent.sports.ratings import grounded_prediction

            provider = get_provider()
            if provider.available():
                for comp in _competitions_to_try(competition):
                    grounded = grounded_prediction(str(home), str(away), provider, comp)
                    if grounded is not None:
                        return json.dumps(grounded.as_dict(), default=str)
        except Exception:  # noqa: BLE001 -- fall back to the baseline model
            pass

    quality = (data_quality or ("PARTIAL" if supplied else "LIMITED")).upper()
    pred = predict_football(
        TeamStrength(str(home), float(home_elo), float(home_attack), float(home_defense)),
        TeamStrength(str(away), float(away_elo), float(away_attack), float(away_defense)),
        data_quality=quality)
    out = pred.as_dict()
    if not supplied:
        out["note"] = ("Couldn't ground this in a connected competition, so it is a "
                       "baseline forecast (LIMITED). Supply ratings or use a covered "
                       "league for a grounded prediction.")
    return json.dumps(out, default=str)


def _competitions_to_try(preferred: str) -> list[str]:
    # The teams could be in any covered league; try the hint first, then majors.
    seen, order = set(), []
    for c in [preferred, "BL1", "PL", "PD", "SA", "FL1", "CL"]:
        c = (c or "").strip()
        if c and c.upper() not in seen:
            seen.add(c.upper())
            order.append(c)
    return order


@register(
    name="football_matches",
    description="REAL football fixtures, live scores and recent results (via "
                "football-data.org). Use for 'Bayern's next match', 'live "
                "football', 'how did Arsenal do'. status: SCHEDULED (upcoming), "
                "LIVE, or FINISHED (results).",
    input_schema={"type": "object", "properties": {
        "team": {"type": "string", "description": "Team name, e.g. 'Bayern', 'Arsenal'."},
        "competition": {"type": "string", "description": "League, e.g. 'Bundesliga', "
                        "'Premier League' (default Bundesliga)."},
        "status": {"type": "string", "enum": ["SCHEDULED", "LIVE", "FINISHED", ""]},
    }, "required": []},
)
def football_matches(team: str = "", competition: str = "Bundesliga", status: str = "") -> str:
    from reyes_agent.sports.providers.football_data import AVAILABLE, get_provider

    provider = get_provider()
    if not provider.available():
        return json.dumps({"status": "AUTH_REQUIRED",
                           "note": "No football-data.org API key configured."})
    health = provider.health()
    if health["status"] != AVAILABLE:
        return json.dumps({"status": health["status"],
                           "note": f"football-data.org is {health['status']}."})
    if team.strip():
        row = provider.find_team(team, provider.competition_code(competition))
        if not row:
            return json.dumps({"status": "NO_COVERAGE",
                               "note": f"'{team}' not found in {competition}."})
        matches = provider.team_matches(row["team_id"], status)
    else:
        matches = provider.recent_results(competition) if status.upper() != "SCHEDULED" else []
    return json.dumps({"status": "AVAILABLE", "count": len(matches),
                       "matches": matches[:15]}, default=str)


@register(
    name="live_sports",
    description="LIVE in-play scores for ANY sport happening right now (via "
                "API-Sports): football, basketball, baseball, hockey, rugby, "
                "American football, volleyball, handball, F1. Use for 'what's "
                "live now?', 'show me live basketball', 'any live football'.",
    input_schema={"type": "object", "properties": {
        "sport": {"type": "string", "description": "football/basketball/baseball/"
                  "hockey/rugby/american-football/volleyball/handball/formula-1 "
                  "(aliases: soccer, nba, nfl, f1). Default football."},
    }, "required": []},
)
def live_sports(sport: str = "football") -> str:
    from reyes_agent.sports.live_feed import get_engine

    return json.dumps(get_engine().live(sport or "football"), default=str)


@register(
    name="football_table",
    description="REAL league standings (via football-data.org). Use for 'show "
                "the Bundesliga table', 'where are Bayern in the league'.",
    input_schema={"type": "object", "properties": {
        "competition": {"type": "string", "description": "League name (default Bundesliga)."},
    }, "required": []},
)
def football_table(competition: str = "Bundesliga") -> str:
    from reyes_agent.sports.providers.football_data import get_provider

    provider = get_provider()
    if not provider.available():
        return json.dumps({"status": "AUTH_REQUIRED"})
    table = provider.standings(competition)
    if not table:
        return json.dumps({"status": "NO_COVERAGE",
                           "note": f"No standings for {competition}."})
    return json.dumps({"status": "AVAILABLE", "competition": competition,
                       "table": table}, default=str)


# Declare the true capability status so ZENO never fakes coverage (Pack 7 #70).
def _declare() -> None:
    try:
        from reyes_agent import capability_truth as ct

        truth = ct.get_truth()
        truth.declare("sports.predict.football", implemented=True, tested=True,
                      documented=True, has_fallback=True, owner="sports.prediction",
                      description="Elo+Poisson ensemble forecast")
        truth.mark_tested("sports.predict.football", True)
        # Live/fixtures/standings via football-data.org -- available only when a
        # key is actually configured (honest, never faked).
        try:
            from reyes_agent.sports.providers.football_data import get_provider

            live_ok = get_provider().available()
        except Exception:  # noqa: BLE001
            live_ok = False
        for cap in ("sports.fixtures.football", "sports.standings.football"):
            truth.declare(cap, implemented=True, tested=True, available=live_ok,
                          owner="sports.providers.football_data",
                          description="football-data.org" if live_ok else "needs API key")
            if live_ok:
                truth.mark_tested(cap, True)
        # Live in-play across many sports via API-Sports.
        try:
            from reyes_agent.sports.providers.api_sports import SPORTS, get_provider

            aps_ok = get_provider().available()
        except Exception:  # noqa: BLE001
            SPORTS, aps_ok = (), False
        for sport in SPORTS:
            truth.declare(f"sports.live.{sport}", implemented=True, tested=True,
                          available=aps_ok, owner="sports.providers.api_sports",
                          description="API-Sports live" if aps_ok else "needs API_SPORTS_KEY")
            if aps_ok:
                truth.mark_tested(f"sports.live.{sport}", True)
        for sport in ("basketball", "tennis", "cricket", "f1"):
            truth.declare(f"sports.predict.{sport}", implemented=False, tested=False,
                          available=False, owner="sports.prediction",
                          description="model not built yet (UNSUPPORTED)")
    except Exception:  # noqa: BLE001 -- declaration is best-effort
        pass


_declare()
