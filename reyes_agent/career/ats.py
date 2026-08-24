"""ATS matching: parse a job description, compare to the verified profile.

Extracts the required technical skills, keywords and experience from a listing
and matches them against the owner's VERIFIED skills -- producing an honest match
percentage, the strong matches, and the gaps. It never tells the owner to claim
a skill they don't have (zero-fabrication policy); it says "apply, but don't
claim the missing ones". Pure logic, deterministic.
"""

from __future__ import annotations

import re
from typing import Any

# A pragmatic technical-skill vocabulary (extensible). Multi-word first so
# "power bi" is caught before "bi".
_SKILLS = [
    "power bi", "machine learning", "deep learning", "data analysis", "data science",
    "rest api", "ci/cd", "unit testing", "product management", "ui/ux", "ux design",
    "graphic design", "video editing", "technical writing", "content writing",
    "social media", "virtual assistant", "customer support", "data annotation",
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "php",
    "sql", "postgresql", "mysql", "mongodb", "excel", "tableau", "looker",
    "react", "vue", "angular", "node", "django", "flask", "fastapi", "next.js",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "linux",
    "git", "pandas", "numpy", "pytorch", "tensorflow", "langchain", "llm",
    "automation", "web scraping", "seo", "figma", "photoshop", "premiere",
    "dax", "etl", "powerpoint", "wordpress", "shopify", "salesforce",
]
_SOFT = ["communication", "problem solving", "teamwork", "leadership",
         "time management", "attention to detail", "adaptability"]

_YEARS = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\b", re.I)
_DEGREE = re.compile(r"\b(bachelor|master|phd|degree|bsc|msc|hnd|diploma)\b", re.I)


def _found(vocab: list[str], text: str) -> list[str]:
    low = text.casefold()
    out = []
    for skill in vocab:
        if re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", low):
            out.append(skill)
    return out


def parse_requirements(job_text: str) -> dict[str, Any]:
    text = str(job_text or "")
    years = [int(m) for m in _YEARS.findall(text)]
    return {
        "tech_skills": _found(_SKILLS, text),
        "soft_skills": _found(_SOFT, text),
        "experience_years": max(years) if years else 0,
        "requires_degree": bool(_DEGREE.search(text)),
    }


def match(job_text: str, profile_skills: list[str], *, profile_years: int = 0,
          has_degree: bool = False) -> dict[str, Any]:
    req = parse_requirements(job_text)
    have = {s.strip().casefold() for s in (profile_skills or [])}
    required = req["tech_skills"] + req["soft_skills"]
    if not required:
        required = req["tech_skills"]
    strong = [s for s in required if s in have]
    missing = [s for s in required if s not in have]
    pct = round(100 * len(strong) / len(required)) if required else 0

    exp_gap = max(0, req["experience_years"] - int(profile_years or 0))
    degree_gap = req["requires_degree"] and not has_degree

    if pct >= 70 and exp_gap == 0:
        rec = "Strong match — apply, tailoring to the listed keywords."
    elif pct >= 45:
        rec = "Partial match — apply, but do NOT claim the missing skills; " \
              "address transferable experience honestly."
    else:
        rec = "Weak match — likely not worth a tailored application yet."
    return {
        "match_pct": pct,
        "strong": strong,
        "missing": missing,
        "experience_required": req["experience_years"],
        "experience_gap_years": exp_gap,
        "degree_gap": degree_gap,
        "recommendation": rec,
    }
