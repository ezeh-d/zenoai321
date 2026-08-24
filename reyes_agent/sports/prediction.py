"""Evidence-based football prediction: Elo + Poisson, pre-match and live.

This is ZENO's OWN model, not a provider's probability feed repeated back. It is
pure math (no external API, deterministic, fully testable):

* Elo gives a rating-based win expectation with home advantage.
* A Poisson score model turns attack/defense strengths into a scoreline matrix,
  and from it P(home win)/draw/P(away win) and the likeliest scores.
* An ensemble blends the two; a live model re-runs Poisson over the minutes
  remaining, conditioned on the current score.

Every prediction carries a confidence and a data-quality label, and outputs
PROBABILITIES -- never "team X will win". Missing data lowers confidence; it is
never invented. Other sports (basketball/tennis/cricket) need their own models
and are reported UNSUPPORTED until built, rather than mis-using this one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# --- Elo ---------------------------------------------------------------------
HOME_ADVANTAGE_ELO = 65.0     # rating points added to the home side
DEFAULT_ELO = 1500.0


def elo_expected(rating_home: float, rating_away: float,
                 home_advantage: float = HOME_ADVANTAGE_ELO) -> float:
    """Expected score for the home team in [0,1] (win=1, draw=0.5)."""
    return 1.0 / (1.0 + 10 ** ((rating_away - (rating_home + home_advantage)) / 400.0))


def elo_update(rating: float, expected: float, actual: float, k: float = 20.0) -> float:
    return rating + k * (actual - expected)


class EloBook:
    """Dynamic team ratings, updated from results. Seed from a data source; the
    ratings themselves are only as good as the results fed in."""

    def __init__(self, default: float = DEFAULT_ELO) -> None:
        self._default = float(default)
        self._ratings: dict[str, float] = {}

    def rating(self, team: str) -> float:
        return self._ratings.get(_norm(team), self._default)

    def set_rating(self, team: str, rating: float) -> None:
        self._ratings[_norm(team)] = float(rating)

    def expected(self, home: str, away: str,
                 home_advantage: float = HOME_ADVANTAGE_ELO) -> float:
        return elo_expected(self.rating(home), self.rating(away), home_advantage)

    def record(self, home: str, away: str, home_goals: int, away_goals: int,
               k: float = 20.0, home_advantage: float = HOME_ADVANTAGE_ELO) -> None:
        exp_home = self.expected(home, away, home_advantage)
        actual = 1.0 if home_goals > away_goals else (0.5 if home_goals == away_goals else 0.0)
        rh, ra = self.rating(home), self.rating(away)
        self._ratings[_norm(home)] = elo_update(rh, exp_home, actual, k)
        self._ratings[_norm(away)] = elo_update(ra, 1 - exp_home, 1 - actual, k)


# --- Poisson score model -----------------------------------------------------
def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_goals(home_attack: float, home_defense: float,
                   away_attack: float, away_defense: float,
                   league_home_avg: float = 1.5, league_away_avg: float = 1.1) -> tuple[float, float]:
    """Standard Poisson football strengths: strengths are ratios around 1.0
    (1.2 = 20% above league average). Bounded so a bad input can't explode."""
    exp_home = max(0.05, min(6.0, league_home_avg * max(0.1, home_attack) * max(0.1, away_defense)))
    exp_away = max(0.05, min(6.0, league_away_avg * max(0.1, away_attack) * max(0.1, home_defense)))
    return exp_home, exp_away


def score_matrix(exp_home: float, exp_away: float, max_goals: int = 8) -> list[list[float]]:
    home = [poisson_pmf(i, exp_home) for i in range(max_goals + 1)]
    away = [poisson_pmf(j, exp_away) for j in range(max_goals + 1)]
    matrix = [[home[i] * away[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    total = sum(sum(row) for row in matrix) or 1.0
    return [[cell / total for cell in row] for row in matrix]   # renormalise the truncation


def outcome_probabilities(matrix: list[list[float]]) -> tuple[float, float, float]:
    home_win = draw = away_win = 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if i > j:
                home_win += p
            elif i == j:
                draw += p
            else:
                away_win += p
    return home_win, draw, away_win


def likeliest_scores(matrix: list[list[float]], n: int = 5) -> list[dict[str, Any]]:
    scores = [{"score": f"{i}-{j}", "home": i, "away": j, "p": round(p, 4)}
              for i, row in enumerate(matrix) for j, p in enumerate(row)]
    scores.sort(key=lambda s: -s["p"])
    return scores[:max(1, n)]


# --- prediction --------------------------------------------------------------
@dataclass
class TeamStrength:
    name: str
    elo: float = DEFAULT_ELO
    attack: float = 1.0        # ratio vs league average goals scored
    defense: float = 1.0       # ratio vs league average goals conceded (lower=better defence -> use as multiplier)


@dataclass
class Prediction:
    home: str
    away: str
    home_win: float
    draw: float
    away_win: float
    exp_home_goals: float
    exp_away_goals: float
    likely_scores: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "MEDIUM"
    data_quality: str = "PARTIAL"
    kind: str = "MODEL_PREDICTION"        # FACT vs ESTIMATE vs PREDICTION vs RUMOR
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "home": self.home, "away": self.away,
            "probabilities": {"home_win": round(self.home_win, 4),
                              "draw": round(self.draw, 4),
                              "away_win": round(self.away_win, 4)},
            "expected_goals": {"home": round(self.exp_home_goals, 2),
                               "away": round(self.exp_away_goals, 2)},
            "most_likely_score": self.likely_scores[0]["score"] if self.likely_scores else None,
            "likely_scores": self.likely_scores,
            "confidence": self.confidence, "data_quality": self.data_quality,
            "kind": self.kind, "reasons": self.reasons,
        }


def predict_football(home: TeamStrength, away: TeamStrength, *,
                     elo_weight: float = 0.4, data_quality: str = "PARTIAL",
                     league_home_avg: float = 1.5, league_away_avg: float = 1.1) -> Prediction:
    """Ensemble of a Poisson score model and an Elo win expectation. Returns
    probabilities with an honest confidence/data-quality label -- never a
    certainty."""
    exp_h, exp_a = expected_goals(home.attack, home.defense, away.attack, away.defense,
                                  league_home_avg, league_away_avg)
    matrix = score_matrix(exp_h, exp_a)
    p_home, p_draw, p_away = outcome_probabilities(matrix)

    # Elo contributes a home/away split; distribute a draw share by closeness.
    e_home = elo_expected(home.elo, away.elo)
    draw_share = p_draw                       # keep Poisson's draw mass
    elo_home = e_home * (1 - draw_share)
    elo_away = (1 - e_home) * (1 - draw_share)

    w = max(0.0, min(1.0, elo_weight))
    home_win = (1 - w) * p_home + w * elo_home
    away_win = (1 - w) * p_away + w * elo_away
    draw = (1 - w) * p_draw + w * draw_share
    total = home_win + draw + away_win or 1.0
    home_win, draw, away_win = home_win / total, draw / total, away_win / total

    reasons = _reasons(home, away, exp_h, exp_a, e_home)
    confidence = _confidence(data_quality, abs(home_win - away_win))
    return Prediction(home.name, away.name, home_win, draw, away_win, exp_h, exp_a,
                      likeliest_scores(matrix), confidence, data_quality, reasons=reasons)


def live_win_probability(exp_home_goals: float, exp_away_goals: float, *,
                         home_goals: int, away_goals: int, minute: int,
                         home_red_cards: int = 0, away_red_cards: int = 0) -> dict[str, Any]:
    """In-play probabilities: final = current score + Poisson over the goals
    still expected in the minutes remaining, dampened by red cards."""
    frac_left = max(0.0, min(1.0, (90 - max(0, min(90, minute))) / 90.0))
    rem_home = exp_home_goals * frac_left * (0.75 ** home_red_cards)
    rem_away = exp_away_goals * frac_left * (0.75 ** away_red_cards)
    matrix = score_matrix(rem_home, rem_away, max_goals=6)
    home_win = draw = away_win = 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            fh, fa = home_goals + i, away_goals + j
            if fh > fa:
                home_win += p
            elif fh == fa:
                draw += p
            else:
                away_win += p
    return {"minute": minute, "score": f"{home_goals}-{away_goals}",
            "home_win": round(home_win, 4), "draw": round(draw, 4),
            "away_win": round(away_win, 4)}


def _reasons(home: TeamStrength, away: TeamStrength, exp_h: float, exp_a: float,
             e_home: float) -> list[str]:
    out: list[str] = []
    if e_home >= 0.6:
        out.append(f"higher Elo rating ({home.elo:.0f} vs {away.elo:.0f})")
    elif e_home <= 0.4:
        out.append(f"lower Elo rating ({home.elo:.0f} vs {away.elo:.0f})")
    if exp_h > exp_a + 0.4:
        out.append("stronger expected attacking output")
    elif exp_a > exp_h + 0.4:
        out.append("weaker expected attacking output than the opponent")
    out.append("home advantage")
    return out


def _confidence(data_quality: str, margin: float) -> str:
    dq = str(data_quality or "").upper()
    if dq in {"LIMITED", "NONE"}:
        return "LOW"
    if margin >= 0.4 and dq in {"FULL", "GOOD"}:
        return "HIGH"
    if margin >= 0.25:
        return "MEDIUM-HIGH"
    return "MEDIUM"


def _norm(team: str) -> str:
    return str(team or "").strip().casefold()
