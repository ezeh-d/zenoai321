"""Everything the visit needs, written to disk so the internet cannot take it.

WHY THIS EXISTS AT ALL
----------------------
Every other presentation module computes its answer live -- from git, from
the filesystem, from a health probe. That is the right default, because live
data cannot go stale. But it means a dropped connection during the visit
takes the language model with it, and a supervisor watching an assistant fail
to describe its own project will remember that and nothing else.

So the pack is a SNAPSHOT, written before the visit and readable with no
network and no model: who the visitor is, the SIWES dates, the timeline, the
feature statuses, the challenges, the learning portfolio. Enough to answer
the questions that matter from a file.

WHAT IT IS NOT
--------------
    "DO NOT MAKE PRESENTATION DATA A SECOND MEMORY SYSTEM."

It is curated, visitor-safe, and disposable. It holds nothing private, it is
regenerated on demand, and deleting it costs nothing but a rebuild. ZENO's
real memory is untouched by any of this.

HONESTY WHEN OFFLINE
--------------------
A cached answer is still a cached answer. Anything served from the pack is
stamped with when it was written, and the offline reply says plainly that
cloud-backed features are unavailable rather than pretending the assistant is
whole.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from reyes_agent import config

FILES = ("visitor_profile.json", "siwes_profile.json", "zeno_timeline.json",
         "current_features.json", "project_evidence.json",
         "learning_portfolio.json", "engineering_challenges.json",
         "likely_questions.json")


def directory() -> Path:
    return config.PROJECT_ROOT / "presentation"


def _write(name: str, payload: Any) -> Path:
    target = directory() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(
        {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "data": payload},
        indent=2, default=str), encoding="utf-8")
    return target


def likely_questions() -> list[dict[str, str]]:
    """What a supervisor actually asks, with where the answer comes from."""
    return [
        {"q": "What exactly is ZENO?", "from": "visitor profile + timeline"},
        {"q": "How did the project begin?", "from": "timeline (attested)"},
        {"q": "What is the difference between REYES and ZENO?",
         "from": "timeline -- the package is still named reyes_agent"},
        {"q": "Did you build all this from scratch?",
         "from": "project evidence + technologies"},
        {"q": "Did you use AI to build it?", "from": "answered plainly: yes"},
        {"q": "What actually works today?", "from": "feature status"},
        {"q": "What problems did you solve?",
         "from": "engineering challenges, each citing a commit"},
        {"q": "What have you learned?", "from": "learning portfolio"},
        {"q": "What work did you do for the company?",
         "from": "visit topics -- company work"},
        {"q": "Is there real code behind this?", "from": "code proof"},
    ]


def build() -> dict[str, Any]:
    """Everything, computed fresh. Slow on purpose -- run it before the visit."""
    from reyes_agent.presentation import (evidence, facts, portfolio, timeline,
                                          visit)

    return {
        "visitor_profile.json": {**visit.VISITOR,
                                 "do_not_invent": list(visit.DO_NOT_INVENT)},
        "siwes_profile.json": {
            "owner": "Divine", "institution": "Redeemer's University",
            "placement": "T21 Services", "location": "Ado-Ekiti",
            "start": timeline.SIWES_START, "end": timeline.SIWES_END,
            "months": 3,
            "main_project": "REYES, later renamed ZENO",
            "company_work": ["NHS job applications",
                             "interview requests and follow-ups",
                             "general computer and operational tasks"],
        },
        "zeno_timeline.json": timeline.build(),
        "current_features.json": facts.feature_status(),
        "project_evidence.json": evidence.project_evidence(),
        "learning_portfolio.json": portfolio.portfolio(),
        "engineering_challenges.json": evidence.challenges(),
        "likely_questions.json": likely_questions(),
    }


def write() -> dict[str, Any]:
    """Write the pack. Returns what was written and anything that failed."""
    written, failed = [], []
    try:
        payload = build()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "written": [], "failed": [f"build: {exc}"],
                "directory": str(directory())}

    for name, data in payload.items():
        try:
            written.append(str(_write(name, data)))
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    return {"ok": not failed, "written": written, "failed": failed,
            "directory": str(directory()),
            "note": ("Curated and visitor-safe. Not a second memory system -- "
                     "regenerate it any time.")}


def read(name: str) -> dict[str, Any]:
    """One pack file, straight off disk. No network, no model."""
    target = directory() / name
    if not target.exists():
        return {"available": False,
                "reason": f"{name} has not been generated yet -- run "
                          "'prepare presentation evidence'"}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{name} is unreadable: {exc}"}
    return {"available": True, "generated_at": raw.get("generated_at", ""),
            "data": raw.get("data"),
            "cached": ("Read from the local pack, written "
                       f"{raw.get('generated_at', 'at an unknown time')}.")}


def verify() -> dict[str, Any]:
    """Is the pack complete and fresh enough to lean on."""
    present, missing, stale = [], [], []
    now = time.time()
    for name in FILES:
        target = directory() / name
        if not target.exists():
            missing.append(name)
            continue
        present.append(name)
        age_h = (now - target.stat().st_mtime) / 3600
        if age_h > 24:
            stale.append(f"{name} ({age_h:.0f}h old)")
    return {
        "state": "READY" if not missing else ("PARTIAL" if present else "MISSING"),
        "present": present, "missing": missing, "stale": stale,
        "directory": str(directory()),
        "say": ("The presentation pack is complete." if not missing else
                f"{len(missing)} pack file(s) missing: {', '.join(missing)}."),
    }


def offline_answer() -> dict[str, Any]:
    """What ZENO can still say with no internet -- and what it cannot."""
    available = {}
    for name in FILES:
        entry = read(name)
        if entry.get("available"):
            available[name.replace(".json", "")] = entry["data"]
    return {
        "offline_capable": bool(available),
        "have": sorted(available),
        "data": available,
        "unavailable_offline": [
            "new answers from the language model",
            "speech recognition (cloud)",
            "web search",
            "anything needing a provider",
        ],
        "say": ("I can still explain the project, the timeline, what works and "
                "what Divine learned -- that is all stored locally. I cannot "
                "reason about anything new while the connection is down, and I "
                "will not pretend otherwise."
                if available else
                "The presentation pack has not been generated, so there is "
                "nothing stored locally to fall back on."),
    }


def status() -> dict[str, Any]:
    return {"state": "ONLINE", **verify()}
