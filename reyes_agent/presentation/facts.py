"""What the owner actually built, read from the repository rather than written.

WHY THIS READS GIT INSTEAD OF A SCRIPT
--------------------------------------
A presentation script is a claim. Git history is a record. If ZENO is going
to stand in front of a supervisor and describe someone's industrial training,
every sentence it says should be traceable to something that happened -- a
commit, a file, a test that passes.

So the facts are DERIVED: commit count and date range from `git log`, feature
status from the capability registry and the roadmap's own labels, technology
list from what is genuinely imported and installed. Nothing here is a
sentence somebody wrote to sound impressive.

THE ATTRIBUTION RULE
--------------------
The brief is explicit and it is the right instinct: do not let ZENO imply the
owner wrote Three.js. Every technology carries who provided it, so when a
supervisor asks "did he build all this?", the honest answer is available
rather than improvised -- custom architecture and integration here,
open-source libraries there, AI coding assistants named plainly.

That distinction makes the demonstration MORE credible, not less. A student
who can say precisely which parts are theirs is a student who understands
the system.

WHAT IT REFUSES TO DO
---------------------
It will not describe a planned feature as finished. `feature_status()`
returns WORKING, PARTIAL, EXPERIMENTAL or NOT_IMPLEMENTED from real state,
and the presentation layer is expected to say the label out loud.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WORKING = "WORKING"
PARTIAL = "PARTIAL"
EXPERIMENTAL = "EXPERIMENTAL"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

# Who provided each piece. The answer to "did you build all of this?"
OWNER_BUILT = "owner"
OPEN_SOURCE = "open-source library"
AI_SERVICE = "AI service"
AI_ASSISTED = "built with AI coding assistance"


@dataclass
class Technology:
    name: str
    provenance: str
    what_for: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "provenance": self.provenance,
                "what_for": self.what_for}


@dataclass
class Facts:
    project_name: str = "ZENO"
    owner_name: str = ""
    institution: str = ""
    generated_at: float = field(default_factory=time.time)
    commits: int = 0
    first_commit: str = ""
    last_commit: str = ""
    active_days: int = 0
    modules: int = 0
    tests_passing: int = 0
    features: list[dict[str, str]] = field(default_factory=list)
    technologies: list[Technology] = field(default_factory=list)
    recent_work: list[str] = field(default_factory=list)
    company_tasks: list[str] = field(default_factory=list)
    challenges: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name, "owner_name": self.owner_name,
            "institution": self.institution, "generated_at": self.generated_at,
            "history": {"commits": self.commits, "first": self.first_commit,
                        "last": self.last_commit, "active_days": self.active_days},
            "scale": {"modules": self.modules, "tests_passing": self.tests_passing},
            "features": self.features,
            "technologies": [t.as_dict() for t in self.technologies],
            "recent_work": self.recent_work,
            "company_tasks": self.company_tasks,
            "challenges": self.challenges, "lessons": self.lessons,
            "attribution_note": (
                "Custom architecture, integration and workflows were built by the "
                "owner. Libraries, AI models and coding assistants are named "
                "separately and were not written by him."),
        }


def _git(*args: str, root: Path | None = None) -> str:
    try:
        from reyes_agent import config

        cwd = root or Path(config.PROJECT_ROOT)
    except Exception:  # noqa: BLE001
        cwd = Path.cwd()
    try:
        result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                                text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def history() -> dict[str, Any]:
    """Real commit record. Empty rather than invented if git is unavailable."""
    count = _git("rev-list", "--count", "HEAD")
    last = _git("log", "-1", "--format=%ad", "--date=short")

    # `--max-count` is applied BEFORE `--reverse`, so asking for one reversed
    # commit returns the NEWEST one -- which reported the project as starting
    # and ending on the same day. Take the whole list and read the end of it.
    dates = [d.strip() for d in _git("log", "--format=%ad", "--date=short").splitlines()
             if d.strip()]
    first = dates[-1] if dates else ""
    active = len(set(dates))
    return {"commits": int(count) if count.isdigit() else 0,
            "first": first, "last": last, "active_days": active}


def recent_work(limit: int = 12) -> list[str]:
    """What was actually done lately, in the owner's own commit subjects."""
    raw = _git("log", f"--max-count={limit}", "--format=%s")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def feature_status() -> list[dict[str, str]]:
    """Feature labels from real state, not from a marketing list."""
    found: list[dict[str, str]] = []

    def add(name: str, state: str, detail: str) -> None:
        found.append({"feature": name, "status": state, "detail": detail})

    try:
        from reyes_agent.capabilities import registry

        registry.status()
        checks = (
            ("Voice conversation", "deepgram", "speech recognition"),
            ("Local AI fallback", "ollama", "runs without the internet"),
            ("Desktop automation", "computer_control", "reads and drives applications"),
            ("Browser automation", "playwright", "real selectors, not screen positions"),
            ("Memory", "memory", "remembers across sessions"),
            ("Specialist agents", "agents", "delegates to specialists"),
            ("Web research", "web_research", "fetches and cites real pages"),
            ("Video rendering", "ffmpeg", "renders and verifies real files"),
        )
        for label, capability_name, detail in checks:
            capability = registry.get(capability_name)
            if capability is None:
                add(label, NOT_IMPLEMENTED, detail)
                continue
            state, why = capability.health()
            add(label, WORKING if state in registry.USABLE else PARTIAL,
                detail if state in registry.USABLE else f"{detail} — {why}")
    except Exception:  # noqa: BLE001
        pass

    # The roadmap's own honesty labels, counted rather than paraphrased.
    try:
        from reyes_agent import config

        roadmap = Path(config.PROJECT_ROOT) / "ROADMAP.md"
        if roadmap.exists():
            text = roadmap.read_text(encoding="utf-8", errors="replace")
            partial = len(re.findall(r"—\s*PARTIAL", text))
            not_built = len(re.findall(r"—\s*NOT BUILT", text))
            if partial:
                add("Documented in-progress work", PARTIAL,
                    f"{partial} areas are recorded as partial with their limits named")
            if not_built:
                add("Documented unbuilt work", NOT_IMPLEMENTED,
                    f"{not_built} areas are recorded as not built")
    except Exception:  # noqa: BLE001
        pass

    return found


def technologies() -> list[Technology]:
    """What is genuinely in use, with who provided it."""
    from reyes_agent.capabilities import inventory

    found = [
        Technology("Python", OPEN_SOURCE, "the language the system is written in"),
        Technology("ZENO architecture", OWNER_BUILT,
                   "the assistant's own design, workflows and integration"),
    ]
    optional = (
        ("FastAPI", "fastapi", OPEN_SOURCE, "the local web API and dashboard"),
        ("Playwright", "playwright", OPEN_SOURCE, "browser automation"),
        ("OpenCV", "cv2", OPEN_SOURCE, "image and camera processing"),
        ("NumPy", "numpy", OPEN_SOURCE, "audio and numeric processing"),
        ("psutil", "psutil", OPEN_SOURCE, "process and resource monitoring"),
        ("comtypes / UI Automation", "comtypes", OPEN_SOURCE,
         "reading Windows application controls"),
    )
    for label, package, provenance, purpose in optional:
        if inventory.has_package(package):
            found.append(Technology(label, provenance, purpose))

    for label, binary, purpose in (("ffmpeg", "ffmpeg", "video and audio processing"),
                                   ("Blender", "blender", "3D rendering"),
                                   ("Node.js", "node", "web tooling")):
        if inventory.find_application(binary):
            found.append(Technology(label, OPEN_SOURCE, purpose))

    try:
        from reyes_agent import config

        if getattr(config, "GEMINI_API_KEY", ""):
            found.append(Technology("Google Gemini", AI_SERVICE, "language model"))
        if getattr(config, "DEEPGRAM_API_KEY", ""):
            found.append(Technology("Deepgram", AI_SERVICE, "speech recognition"))
    except Exception:  # noqa: BLE001
        pass

    found.append(Technology("Claude and Codex", AI_ASSISTED,
                            "coding assistance during development"))
    return found


def scale() -> dict[str, int]:
    try:
        from reyes_agent import config

        root = Path(config.PROJECT_ROOT) / "reyes_agent"
        modules = len([p for p in root.rglob("*.py") if "__pycache__" not in str(p)])
    except Exception:  # noqa: BLE001
        modules = 0
    return {"modules": modules}


def build(*, owner_name: str = "", institution: str = "",
          company_tasks: tuple[str, ...] = (), tests_passing: int = 0) -> Facts:
    """Assemble the fact cache from real records.

    `company_tasks` is passed in by the owner rather than guessed. ZENO has
    no record of NHS applications or office work, and inventing plausible
    ones would be exactly the failure this module exists to prevent.
    """
    log = history()
    facts = Facts(owner_name=owner_name, institution=institution,
                  commits=log["commits"], first_commit=log["first"],
                  last_commit=log["last"], active_days=log["active_days"],
                  tests_passing=tests_passing)
    facts.modules = scale()["modules"]
    facts.features = feature_status()
    facts.technologies = technologies()
    facts.recent_work = recent_work()
    facts.company_tasks = [t for t in company_tasks if str(t).strip()]
    facts.challenges = [
        "Response latency — making a spoken reply feel like conversation rather "
        "than a wait.",
        "Microphone and audio reliability across devices.",
        "Automation that verifies what it did instead of assuming it worked.",
        "Keeping the system honest about what is finished and what is not.",
    ]
    facts.lessons = [
        "How to integrate separate systems — speech, models, automation — into one.",
        "Debugging problems that only appear when the pieces run together.",
        "Why verifying an action matters more than performing it.",
        "Working with APIs, version control and testing in a real project.",
    ]
    return facts


def cache_path() -> Path:
    from reyes_agent import config

    return Path(config.PROJECT_ROOT) / "presentation" / "current_facts.json"


def refresh(**kwargs: Any) -> dict[str, Any]:
    """Rebuild and store the fact cache. Run before a presentation."""
    facts = build(**kwargs)
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = facts.as_dict()
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return payload


def load() -> dict[str, Any] | None:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status() -> dict[str, Any]:
    log = history()
    return {
        "state": "ONLINE" if log["commits"] else "DEGRADED",
        "source": "git history, capability registry, roadmap labels, installed tools",
        "commits": log["commits"],
        "cache": str(cache_path()),
        "cached": cache_path().exists(),
        "refuses": ["describing a planned feature as finished",
                    "implying third-party libraries were written by the owner",
                    "inventing company work ZENO has no record of"],
    }
