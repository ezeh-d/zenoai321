"""Turn real football-data results into grounded ratings for the predictor.

Bridges the FootballDataProvider to the Elo+Poisson model: Elo is built from
finished results, and attack/defense strengths from the standings' goals-for /
goals-against per game. Data quality is set honestly from how many games have
actually been played -- early season => LIMITED, not fake precision.
"""

from __future__ import annotations

from typing import Any

from reyes_agent.sports.prediction import (DEFAULT_ELO, EloBook, Prediction,
                                           TeamStrength, predict_football)


def build_elo(matches: list[dict[str, Any]], book: EloBook | None = None) -> EloBook:
    """Feed FINISHED matches (chronological) into an Elo book."""
    book = book or EloBook()
    for m in matches:
        hg, ag = m.get("home_goals"), m.get("away_goals")
        if hg is None or ag is None or not m.get("home") or not m.get("away"):
            continue
        book.record(str(m["home"]), str(m["away"]), int(hg), int(ag))
    return book


def _league_gpg(standings: list[dict[str, Any]]) -> float:
    played = sum(int(r.get("played") or 0) for r in standings)
    gf = sum(int(r.get("goals_for") or 0) for r in standings)
    return (gf / played) if played else 1.4


def _strength(row: dict[str, Any], league_gpg: float, elo: float) -> TeamStrength:
    played = max(1, int(row.get("played") or 0))
    gf_pg = (int(row.get("goals_for") or 0)) / played
    ga_pg = (int(row.get("goals_against") or 0)) / played
    lg = league_gpg or 1.4
    return TeamStrength(name=str(row.get("team", "")), elo=elo,
                        attack=max(0.2, gf_pg / lg), defense=max(0.2, ga_pg / lg))


def _quality(played: int) -> str:
    if played >= 10:
        return "GOOD"
    if played >= 4:
        return "PARTIAL"
    return "LIMITED"


def _from_season(home: str, away: str, provider: Any, competition: str,
                 season: str, min_played: int) -> Prediction | None:
    standings = provider.standings(competition, season)
    if not standings:
        return None
    home_row = provider.find_team(home, competition, season)
    away_row = provider.find_team(away, competition, season)
    if not home_row or not away_row:
        return None
    played = min(int(home_row.get("played") or 0), int(away_row.get("played") or 0))
    if played < min_played:
        return None            # not enough data this season to ground on
    league_gpg = _league_gpg(standings)
    book = build_elo(provider.recent_results(competition, season=season))
    home_str = _strength(home_row, league_gpg, book.rating(home_row["team"]))
    away_str = _strength(away_row, league_gpg, book.rating(away_row["team"]))
    pred = predict_football(home_str, away_str, data_quality=_quality(played))
    basis = f"{competition} standings + results" + (f" ({season} season)" if season else "")
    pred.reasons.insert(0, f"grounded in {basis}")
    return pred


def grounded_prediction(home: str, away: str, provider: Any,
                        competition: str = "BL1") -> Prediction | None:
    """Predict from REAL data. Uses the current season once enough games are
    played; early in a season it grounds on the most recently completed season
    instead of on empty tables. None if the teams can't be found at all."""
    current = _from_season(home, away, provider, competition, season="", min_played=3)
    if current is not None:
        return current
    from datetime import datetime, timezone

    year = datetime.now(timezone.utc).year
    for season in (str(year - 1), str(year - 2)):
        past = _from_season(home, away, provider, competition, season, min_played=10)
        if past is not None:
            past.data_quality = "PARTIAL"     # last-season basis, honestly
            return past
    return None
