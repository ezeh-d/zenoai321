"""Career intelligence as brain tools -- analysis over the existing paid_work engine.

Exposes the new scoring/ATS/scam analysis. These COMPLEMENT the existing
paid_work_* and career_profile_* tools (scout, apply, negotiate, track); they add
the "should I bother, and is it safe?" judgement before the owner spends effort.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


def _verified_skills() -> list[str]:
    """Best-effort read of the owner's VERIFIED skills from the career profile."""
    try:
        from reyes_agent import career_profile

        for getter in ("verified_skills", "skills", "get_skills"):
            fn = getattr(career_profile, getter, None)
            if callable(fn):
                val = fn()
                if isinstance(val, list):
                    return [str(s) for s in val]
    except Exception:  # noqa: BLE001
        pass
    return []


@register(
    name="analyze_opportunity",
    description="Analyze a job/freelance opportunity BEFORE applying: an "
                "explainable 0-100 score, ATS skill-match vs the owner's verified "
                "profile, and scam-risk detection. Returns APPLY / CONSIDER / SKIP "
                "/ AVOID with reasons. Use to shortlist quality over spam.",
    input_schema={"type": "object", "properties": {
        "title": {"type": "string"},
        "description": {"type": "string", "description": "The full job/gig description."},
        "pay": {"type": "number", "description": "Pay/rate/budget if known."},
        "remote": {"type": "boolean"},
        "applicants": {"type": "integer", "description": "Applicant count if known."},
        "skills": {"type": "array", "items": {"type": "string"},
                   "description": "Owner's skills; defaults to the verified profile."},
    }, "required": ["description"]},
)
def analyze_opportunity(title: str = "", description: str = "", pay: float | None = None,
                        remote: bool = True, applicants: int | None = None,
                        skills: list | None = None) -> str:
    from reyes_agent.career import opportunity_score

    profile_skills = [str(s) for s in skills] if skills else _verified_skills()
    profile = {"skills": profile_skills, "years": 0, "remote_pref": True}
    opp = {"title": title, "description": description, "remote": bool(remote)}
    if pay is not None:
        opp["pay"] = pay
    if applicants is not None:
        opp["applicants"] = applicants
    result = opportunity_score.score(opp, profile)
    if not profile_skills:
        result["note"] = ("No verified profile skills available, so skill-match is "
                          "based only on the description. Fill the career profile for "
                          "an accurate match.")
    return json.dumps(result, default=str)


@register(
    name="scam_check",
    description="Check whether a job/freelance listing or recruiter message looks "
                "like a scam. Returns a 0-100 risk score with the exact reasons and "
                "a recommendation. Use whenever a listing or offer feels off.",
    input_schema={"type": "object", "properties": {
        "text": {"type": "string", "description": "The listing/message to check."},
    }, "required": ["text"]},
)
def scam_check(text: str = "") -> str:
    from reyes_agent.career import scam_detector

    return json.dumps(scam_detector.assess(text), default=str)
