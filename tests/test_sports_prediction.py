"""Contracts for ZENO's own football prediction + self-evaluation (Pack 7)."""

from __future__ import annotations

import math

from reyes_agent.sports import evaluation as ev
from reyes_agent.sports import prediction as pr
from reyes_agent.sports.prediction import TeamStrength


# --- Elo --------------------------------------------------------------------
def test_elo_home_advantage_and_symmetry():
    assert pr.elo_expected(1500, 1500, home_advantage=0) == 0.5
    assert pr.elo_expected(1500, 1500) > 0.5           # home edge
    assert pr.elo_expected(1800, 1500) > pr.elo_expected(1500, 1800)


def test_elo_update_moves_toward_result():
    # A team that wins when expected to lose gains rating.
    new = pr.elo_update(1500, expected=0.3, actual=1.0, k=20)
    assert new > 1500
    assert pr.elo_update(1500, expected=0.7, actual=0.0, k=20) < 1500


def test_elobook_records_result():
    book = pr.EloBook()
    book.set_rating("A", 1600)
    book.set_rating("B", 1500)
    before = book.rating("A")
    book.record("A", "B", 3, 0)
    assert book.rating("A") > before and book.rating("B") < 1500


# --- Poisson ----------------------------------------------------------------
def test_poisson_pmf_is_a_distribution():
    total = sum(pr.poisson_pmf(k, 1.4) for k in range(25))
    assert math.isclose(total, 1.0, abs_tol=1e-6)


def test_expected_goals_responds_to_strength_and_is_bounded():
    strong, _ = pr.expected_goals(1.6, 1.0, 1.0, 1.0)
    weak, _ = pr.expected_goals(0.7, 1.0, 1.0, 1.0)
    assert strong > weak
    hi, _ = pr.expected_goals(99, 1, 1, 99)   # absurd input stays bounded
    assert hi <= 6.0


def test_score_matrix_and_outcomes_sum_to_one():
    m = pr.score_matrix(1.8, 1.1)
    assert math.isclose(sum(sum(r) for r in m), 1.0, abs_tol=1e-6)
    h, d, a = pr.outcome_probabilities(m)
    assert math.isclose(h + d + a, 1.0, abs_tol=1e-6)


# --- prediction -------------------------------------------------------------
def test_prediction_probabilities_normalise_and_favour_the_stronger_side():
    home = TeamStrength("Bayern", elo=1850, attack=1.6, defense=0.7)
    away = TeamStrength("Minnows", elo=1450, attack=0.8, defense=1.3)
    pred = pr.predict_football(home, away, data_quality="GOOD")
    d = pred.as_dict()
    probs = d["probabilities"]
    assert math.isclose(sum(probs.values()), 1.0, abs_tol=1e-6)
    # Strong favourite, but never a certainty.
    assert probs["home_win"] > probs["away_win"]
    assert probs["home_win"] < 1.0 and probs["away_win"] > 0.0
    assert d["most_likely_score"] and d["kind"] == "MODEL_PREDICTION"
    assert d["confidence"] in {"HIGH", "MEDIUM-HIGH", "MEDIUM", "LOW"}


def test_prediction_confidence_drops_with_poor_data():
    a = TeamStrength("A", elo=1550, attack=1.1, defense=1.0)
    b = TeamStrength("B", elo=1500, attack=1.0, defense=1.0)
    assert pr.predict_football(a, b, data_quality="LIMITED").confidence == "LOW"


def test_likeliest_scores_sorted():
    pred = pr.predict_football(TeamStrength("A", attack=1.4), TeamStrength("B"))
    ps = pred.likely_scores
    assert ps[0]["p"] >= ps[-1]["p"]


# --- live -------------------------------------------------------------------
def test_live_leading_late_is_strong_but_not_certain():
    live = pr.live_win_probability(1.8, 1.1, home_goals=1, away_goals=0, minute=85)
    assert live["home_win"] > 0.8 and live["home_win"] < 1.0
    assert math.isclose(live["home_win"] + live["draw"] + live["away_win"], 1.0, abs_tol=1e-6)


def test_live_red_card_hurts_that_team():
    base = pr.live_win_probability(1.5, 1.5, home_goals=0, away_goals=0, minute=40)
    reduced = pr.live_win_probability(1.5, 1.5, home_goals=0, away_goals=0, minute=40,
                                      home_red_cards=1)
    assert reduced["home_win"] < base["home_win"]


def test_live_kickoff_matches_prematch_shape():
    live = pr.live_win_probability(1.6, 1.2, home_goals=0, away_goals=0, minute=0)
    assert 0.0 < live["home_win"] < 1.0


# --- evaluation -------------------------------------------------------------
def test_brier_and_logloss_bounds():
    perfect = {"home_win": 1.0, "draw": 0.0, "away_win": 0.0}
    assert ev.brier_score(perfect, "home_win") == 0.0
    assert ev.log_loss(perfect, "home_win") < 1e-6
    worst = {"home_win": 0.0, "draw": 0.0, "away_win": 1.0}
    assert ev.brier_score(worst, "home_win") == 2.0


def test_outcome_of():
    assert ev.outcome_of(2, 1) == "home_win"
    assert ev.outcome_of(1, 1) == "draw"
    assert ev.outcome_of(0, 2) == "away_win"


def test_evaluator_metrics_and_accuracy():
    e = ev.PredictionEvaluator()
    e.record({"home_win": 0.7, "draw": 0.2, "away_win": 0.1}, "home_win")
    e.record({"home_win": 0.2, "draw": 0.3, "away_win": 0.5}, "away_win")
    m = e.metrics()
    assert m["n"] == 2 and m["result_accuracy"] == 1.0
    assert 0.0 <= m["brier"] <= 2.0 and m["log_loss"] >= 0.0


def test_evaluator_calibration_well_calibrated_is_low_error():
    e = ev.PredictionEvaluator()
    # 10 games predicted 70% home: 7 actually home wins -> well calibrated.
    for i in range(10):
        e.record({"home_win": 0.7, "draw": 0.15, "away_win": 0.15},
                 "home_win" if i < 7 else "away_win")
    assert e.metrics()["calibration_error"] < 0.2
    assert e.calibration_table() and all("predicted" in r for r in e.calibration_table())


def test_empty_evaluator_is_honest():
    m = ev.PredictionEvaluator().metrics()
    assert m["n"] == 0 and m["brier"] is None
