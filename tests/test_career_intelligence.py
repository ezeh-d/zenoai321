"""Contracts for career intelligence: scam detection, ATS matching, scoring."""

from __future__ import annotations

from reyes_agent.career import ats, opportunity_score, scam_detector


# --- scam detector ----------------------------------------------------------
def test_upfront_fee_is_flagged():
    # A single strong signal is MODERATE ("verify first"); it takes several to
    # reach HIGH (see the multi-signal test below) -- honest, not one-keyword panic.
    r = scam_detector.assess("Great remote job! Pay a $200 registration fee to start.")
    assert r["level"] in ("MODERATE", "HIGH") and r["score"] >= 45
    assert any("payment" in reason for reason in r["reasons"])
    # And a legit mention of "no registration fee" must NOT trip it.
    clean = scam_detector.assess("Real job on LinkedIn. There is no registration fee. "
                                 "Structured interview process.")
    assert clean["level"] == "LOW"


def test_crypto_and_identity_signals():
    r = scam_detector.assess("Payment in crypto only. Send your passport and bank details.")
    assert r["score"] >= 30 and r["level"] in ("MODERATE", "HIGH")


def test_off_platform_only():
    r = scam_detector.assess("Contact us only on Telegram to apply. Start today!")
    assert r["score"] >= 20 and any("Telegram" in x or "off-platform" in x for x in r["reasons"])


def test_legitimate_listing_is_low_risk():
    r = scam_detector.assess("Software Engineer at Acme. Apply on LinkedIn. "
                             "Structured interview process with a technical interview.")
    assert r["level"] == "LOW" and r["trust_signals"]


# --- ATS --------------------------------------------------------------------
def test_parse_requirements():
    req = ats.parse_requirements("We need Python, SQL and Power BI. 3+ years. Bachelor's degree.")
    assert "python" in req["tech_skills"] and "power bi" in req["tech_skills"]
    assert req["experience_years"] == 3 and req["requires_degree"] is True


def test_match_strong_and_missing():
    m = ats.match("Requires Python, SQL, AWS and Kubernetes.",
                  ["Python", "SQL"], profile_years=4)
    assert "python" in m["strong"] and "aws" in m["missing"]
    assert 0 < m["match_pct"] < 100
    assert "do NOT claim" in m["recommendation"].lower() or "apply" in m["recommendation"].lower()


def test_match_experience_gap():
    m = ats.match("Senior role, 8+ years Python.", ["Python"], profile_years=2)
    assert m["experience_gap_years"] == 6


def test_weak_match_flagged():
    m = ats.match("Requires Rust, Go, Kubernetes, Terraform.", ["Excel"], profile_years=1)
    assert m["match_pct"] < 45 and "weak" in m["recommendation"].lower()


# --- opportunity score ------------------------------------------------------
_PROFILE = {"skills": ["Python", "SQL", "data analysis", "communication"],
            "years": 3, "remote_pref": True, "min_rate": 30}


def test_strong_opportunity_recommends_apply():
    opp = {"title": "Python Data Analyst",
           "description": "Remote role using Python, SQL and data analysis. "
                          "Apply on LinkedIn. Interview process included.",
           "pay": 45, "remote": True, "applicants": 8, "employer_reputation": 85}
    r = opportunity_score.score(opp, _PROFILE)
    assert r["recommendation"] == "APPLY" and r["score"] >= 75
    assert set(r["breakdown"]) == {"skill_match", "safety", "pay", "remote",
                                   "competition", "reputation"}


def test_scam_hard_gates_recommendation():
    opp = {"title": "Easy Python job",
           "description": "Python role. Pay a $300 training fee first. Telegram only. "
                          "Crypto payment only.",
           "pay": 999, "remote": True}
    r = opportunity_score.score(opp, _PROFILE)
    assert r["recommendation"] == "AVOID — high scam risk"   # overrides good pay


def test_weak_match_skips():
    opp = {"title": "Senior Rust Engineer",
           "description": "Requires Rust, Go, Kubernetes, Terraform, 10 years.",
           "pay": 20, "remote": False, "applicants": 120}
    r = opportunity_score.score(opp, _PROFILE)
    assert r["recommendation"] == "SKIP" and r["score"] < 55


def test_score_is_explainable():
    opp = {"title": "SQL Analyst", "description": "SQL and Excel, remote.",
           "remote": True}
    r = opportunity_score.score(opp, _PROFILE)
    assert isinstance(r["reasons"], list) and "ats" in r and "scam" in r
