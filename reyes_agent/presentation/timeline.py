"""ZENO's development history, built from evidence rather than recollection.

WHAT THE GIT HISTORY CAN AND CANNOT PROVE
-----------------------------------------
This matters more than it sounds, because a supervisor asking "when did you
build that" deserves an answer that is true rather than tidy.

The repository's first commit is dated 2026-08-05 and is already titled
"ZENO AI Operating System". So git CANNOT evidence:

  * the REYES era,
  * the rename from REYES to ZENO,
  * anything built between 1 July, when SIWES started, and 5 August.

That is roughly five weeks of work with no commits behind it, and pretending
otherwise would be the easiest lie in this whole system to tell.

What DOES survive from the REYES era is the package name. Every module still
lives under `reyes_agent/`, imported by all 545 Python files here. A project
does not accidentally carry its old name in every import; that directory is
the fossil record of the rename, and it is the honest thing to point at when
someone asks how the project began.

So this module reports three kinds of thing separately, and never blurs them:

  EVIDENCED   -- a date git can prove, with the commit behind it.
  ATTESTED    -- the owner's account, with the corroboration available.
  UNRECORDED  -- known to have happened, with no artefact to date it.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

EVIDENCED = "EVIDENCED"
ATTESTED = "ATTESTED"
UNRECORDED = "UNRECORDED"

# Supplied by the owner. Stated as attested, never as measured.
SIWES_START = "2026-07-01"
SIWES_END = "2026-09-30"


@dataclass
class Stage:
    name: str
    what: str
    evidence_kind: str = UNRECORDED
    first_seen: str = ""
    commits: int = 0
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "what": self.what,
                "evidence_kind": self.evidence_kind, "first_seen": self.first_seen,
                "commits": self.commits, "evidence": self.evidence}

    def say(self) -> str:
        """How ZENO states this out loud -- hedged exactly as far as the
        evidence requires, and no further."""
        if self.evidence_kind == EVIDENCED:
            return f"{self.what} -- first committed {self.first_seen}."
        if self.evidence_kind == ATTESTED:
            return f"{self.what} -- {self.evidence}"
        return f"{self.what} -- no dated record of that survives."


def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(config.PROJECT_ROOT),
                              capture_output=True, text=True, timeout=25)
        return (done.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _first_commit_for(path: str) -> tuple[str, int]:
    """(first date, commit count) for a path. ('', 0) when git knows nothing."""
    dates = _git("log", "--reverse", "--format=%ad", "--date=short", "--", path)
    if not dates:
        return "", 0
    first = dates.splitlines()[0].strip()
    count = len(_git("log", "--oneline", "--", path).splitlines())
    return first, count


# Subsystem -> (spoken description, path git should be asked about).
_SUBSYSTEMS: list[tuple[str, str, str]] = [
    ("Voice output", "ZENO speaking its replies aloud", "reyes_agent/voice_manager.py"),
    ("Speech input", "listening through a microphone", "reyes_agent/microphone.py"),
    ("Wake word", "waking on the word ZENO", "reyes_agent/voice/wake.py"),
    ("Memory", "remembering context between conversations", "reyes_agent/memory"),
    ("Browser automation", "authorised web actions", "reyes_agent/tools/browser.py"),
    ("Desktop automation", "opening and driving Windows applications",
     "reyes_agent/computer"),
    ("Vision", "reading what is on the screen", "reyes_agent/vision"),
    ("Multi-agent system", "specialist agents working under ZENO",
     "reyes_agent/agent_teams.py"),
    ("Council mode", "several specialists contributing to one answer",
     "reyes_agent/council.py"),
    ("Phone remote microphone", "using the phone as ZENO's microphone",
     "reyes_agent/remote_mic"),
    ("Agent Space", "seeing the agents and who is doing what",
     "reyes_agent/agent_space.py"),
]


def repository() -> dict[str, Any]:
    """What the repository itself can attest to."""
    dates = _git("log", "--format=%ad", "--date=short")
    days = sorted({d.strip() for d in dates.splitlines() if d.strip()})
    total = len(_git("log", "--oneline").splitlines())
    first_subject = _git("log", "--reverse", "--format=%s").splitlines()
    return {
        "first_commit": days[0] if days else "",
        "latest_commit": days[-1] if days else "",
        "active_days": len(days),
        "commits": total,
        "first_commit_subject": first_subject[0] if first_subject else "",
        "python_files": len(_git("ls-files", "*.py").splitlines()),
        "test_files": len(_git("ls-files", "tests/*.py").splitlines()),
    }


def naming() -> Stage:
    """The REYES -> ZENO rename, and what actually supports it."""
    package = config.PROJECT_ROOT / "reyes_agent"
    if package.is_dir():
        return Stage(
            name="REYES became ZENO",
            what="the project began as REYES and was later renamed ZENO",
            evidence_kind=ATTESTED,
            evidence=("the package is still called `reyes_agent`, and every "
                      "module here imports from it. The rename itself predates "
                      "this repository, so git cannot date it -- the directory "
                      "name is what survives of it."),
        )
    return Stage(name="REYES became ZENO",
                 what="the project began as REYES and was later renamed ZENO",
                 evidence_kind=UNRECORDED)


def stages() -> list[Stage]:
    """Every development stage, each carrying its own evidence."""
    found: list[Stage] = [
        Stage(name="SIWES began",
              what=f"Divine's three-month SIWES started {SIWES_START} and runs "
                   f"to {SIWES_END}",
              evidence_kind=ATTESTED,
              evidence="supplied by Divine; this is a placement date, not a "
                       "software artefact."),
        Stage(name="The project started",
              what="Mr BJ and Mr K encouraged Divine and the others to build "
                   "something of their own during the training, and Divine "
                   "chose to build an AI assistant",
              evidence_kind=ATTESTED,
              evidence="Divine's account of how it began; nothing in the code "
                       "records a conversation."),
        naming(),
    ]

    repo = repository()
    if repo.get("first_commit"):
        found.append(Stage(
            name="Version control",
            what="the project came under git",
            evidence_kind=EVIDENCED,
            first_seen=repo["first_commit"],
            commits=repo["commits"],
            evidence=f"{repo['commits']} commits across {repo['active_days']} "
                     f"active days; the first is already titled "
                     f"'{repo['first_commit_subject']}'."))

    for name, what, path in _SUBSYSTEMS:
        first, count = _first_commit_for(path)
        if first:
            found.append(Stage(name=name, what=what, evidence_kind=EVIDENCED,
                               first_seen=first, commits=count,
                               evidence=f"{count} commit(s) touching {path}"))
        elif (config.PROJECT_ROOT / path).exists():
            found.append(Stage(name=name, what=what, evidence_kind=UNRECORDED,
                               evidence=f"{path} exists but git has no history "
                                        "for it"))
    found.sort(key=lambda s: (s.first_seen or "0000-00-00", s.name))
    return found


def gap() -> dict[str, Any]:
    """The stretch of SIWES with no commits behind it. Stated, not hidden."""
    repo = repository()
    first = repo.get("first_commit") or ""
    return {
        "siwes_start": SIWES_START,
        "first_commit": first,
        "unrecorded_before_git": bool(first and first > SIWES_START),
        "say": (f"The repository starts on {first}, but SIWES started "
                f"{SIWES_START}. The work before that -- including the REYES "
                f"version and the rename -- has no commit history behind it. "
                f"What survives of it is the package name, `reyes_agent`, "
                f"which everything here still imports from."
                if first and first > SIWES_START else
                "The repository covers the whole placement."),
    }


def build() -> dict[str, Any]:
    return {
        "generated_for": "SIWES supervision visit",
        "siwes": {"start": SIWES_START, "end": SIWES_END, "months": 3},
        "repository": repository(),
        "gap_before_version_control": gap(),
        "stages": [s.as_dict() for s in stages()],
        "evidence_key": {
            EVIDENCED: "git can prove the date",
            ATTESTED: "the owner's account, with what corroborates it",
            UNRECORDED: "it happened; nothing dates it",
        },
    }


def path() -> Path:
    return config.PROJECT_ROOT / "presentation" / "zeno_timeline.json"


def write() -> Path:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), indent=2), encoding="utf-8")
    return target


def status() -> dict[str, Any]:
    data = build()
    kinds: dict[str, int] = {}
    for stage in data["stages"]:
        kinds[stage["evidence_kind"]] = kinds.get(stage["evidence_kind"], 0) + 1
    return {"state": "ONLINE", "stages": len(data["stages"]), "by_evidence": kinds,
            "repository": data["repository"],
            "rule": "Evidenced, attested and unrecorded are reported as three "
                    "different things and never blurred together."}
