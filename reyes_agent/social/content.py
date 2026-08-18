"""Where ZENO's posts come from.

THE CONSTRAINT THAT MAKES THIS DIFFERENT FROM A CAPTION GENERATOR
------------------------------------------------------------------
The brief says ZENO must not post generic AI quotes, and must not fabricate
performance results. Those two rules together mean an idea cannot be invented
from a topic list -- it has to come from something that actually happened.

So `ContentIdeaEngine` reads the repository: git history, the measurement
reports, the test count. An idea carries the evidence it came from, and
`safety.check_content` BLOCKS any draft that states a number without one.
That is why the evidence field is not decoration.

If there is nothing real to post about, this engine returns nothing. An empty
content queue is a correct answer.

THE SCRIPT STRUCTURE
--------------------
HOOK -> PROBLEM -> ZENO ACTION -> RESULT -> CTA, as specified. It is a
dataclass rather than a prompt so that the RESULT section can be checked
against the evidence that produced it.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.social import store as social_store

# --- content categories (Phase 16) ---------------------------------------
BUILDING_ZENO = "BUILDING_ZENO"
ZENO_IN_ACTION = "ZENO_IN_ACTION"
AI_EDUCATION = "AI_EDUCATION"
CHALLENGES = "CHALLENGES"
BEHIND_THE_SCENES = "BEHIND_THE_SCENES"
BUSINESS_PRODUCTIVITY = "BUSINESS_PRODUCTIVITY"

CATEGORIES: dict[str, str] = {
    BUILDING_ZENO: "development updates, new features, bugs solved, performance "
                   "improvements, voice and agent improvements",
    ZENO_IN_ACTION: "browser automation, Windows control, coding, research, "
                    "website creation, automation, voice interaction",
    AI_EDUCATION: "simple explanations of AI concepts, agent systems, "
                  "automation, coding tips, AI tools",
    CHALLENGES: "can ZENO do X, tests, experiments, comparisons",
    BEHIND_THE_SCENES: "how systems work, architecture, lessons learned, "
                       "the development journey",
    BUSINESS_PRODUCTIVITY: "legitimate ways AI can automate work, business "
                           "automation examples, productivity systems",
}

# Common short-form durations.
DURATIONS = (15, 30, 45, 60)

# Formats an experiment can compare.
SCREEN_RECORDING = "screen_recording"
ORB_ANIMATION = "orb_animation"
CODE_WALKTHROUGH = "code_walkthrough"
TALKING_NARRATION = "talking_narration"
FORMATS = (SCREEN_RECORDING, ORB_ANIMATION, CODE_WALKTHROUGH, TALKING_NARRATION)


@dataclass
class Evidence:
    """One real thing that happened, with where it can be checked."""
    kind: str            # commit | measurement | test | report
    summary: str
    source: str          # commit sha, file path, or report name
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "summary": self.summary,
                "source": self.source, "at": self.at}


@dataclass
class ContentIdea:
    title: str
    hook: str
    platform: str
    format: str
    topic: str
    objective: str
    duration_s: int
    required_media: str
    category: str
    risk: str
    evidence: list[Evidence] = field(default_factory=list)
    status: str = social_store.IDEA

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "hook": self.hook, "platform": self.platform,
            "format": self.format, "topic": self.topic,
            "objective": self.objective, "duration_s": self.duration_s,
            "required_media": self.required_media, "category": self.category,
            "risk": self.risk, "status": self.status,
            "evidence": [e.as_dict() for e in self.evidence],
        }


# --- reading what actually happened --------------------------------------

def _git(*args: str, timeout: float = 10.0) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(config.PROJECT_ROOT), capture_output=True,
            text=True, timeout=timeout, check=False)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def recent_commits(limit: int = 25) -> list[Evidence]:
    """Development that genuinely happened, from git."""
    raw = _git("log", f"-{limit}", "--pretty=format:%H%x1f%s%x1f%at")
    out: list[Evidence] = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, subject, at = parts
        # Merge commits and version bumps are not stories.
        if subject.lower().startswith(("merge ", "bump ", "wip")):
            continue
        try:
            when = float(at)
        except ValueError:
            when = time.time()
        out.append(Evidence(kind="commit", summary=subject.strip(),
                            source=sha[:12], at=when))
    return out


_MEASUREMENT_REPORTS = (
    "ZENO_PERFORMANCE_REPORT.md", "ZENO_SOAK_TEST_REPORT.md",
    "ZENO_BROWSER_STRESS_REPORT.md", "ZENO_ROUTER_REPORT.md",
    "ZENO_TEST_REPORT.md",
)

# A measured figure inside a report: "10.05 s", "21.35 %", "1010 tests".
_FIGURE = re.compile(
    r"\*\*([^*]{2,60}?)\*\*|(\d[\d,]*\.?\d*)\s*(s\b|ms\b|%|×|x\b|tests?\b|"
    r"minutes?\b|MB\b)")


def measured_facts(limit: int = 20) -> list[Evidence]:
    """Numbers ZENO is allowed to quote, because a report recorded them."""
    out: list[Evidence] = []
    for name in _MEASUREMENT_REPORTS:
        path = config.PROJECT_ROOT / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        mtime = path.stat().st_mtime
        for line in text.splitlines():
            stripped = line.strip()
            # Table rows and bolded claims are where the measurements are.
            if not stripped or stripped.startswith("#"):
                continue
            if "**" not in stripped and not stripped.startswith("|"):
                continue
            if not re.search(r"\d", stripped):
                continue
            cleaned = re.sub(r"[|*]", " ", stripped)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            if len(cleaned) < 12 or len(cleaned) > 160:
                continue
            if cleaned.startswith(("---", "===")):
                continue
            out.append(Evidence(kind="measurement", summary=cleaned,
                                source=name, at=mtime))
            if len(out) >= limit:
                return out
    return out


def test_count() -> Evidence | None:
    """How many tests the suite actually has -- countable, not claimed."""
    tests_dir = config.PROJECT_ROOT / "tests"
    if not tests_dir.exists():
        return None
    total = 0
    for path in tests_dir.glob("test_*.py"):
        try:
            total += len(re.findall(r"^\s*def test_", path.read_text(
                encoding="utf-8", errors="ignore"), re.MULTILINE))
        except OSError:
            continue
    if not total:
        return None
    return Evidence(kind="test", summary=f"{total} tests defined in tests/",
                    source="tests/")


# --- turning evidence into ideas -----------------------------------------

# Which commit prefixes suggest which story.
_COMMIT_STORY: tuple[tuple[str, str, str], ...] = (
    ("fix", BUILDING_ZENO, "a bug that was actually solved"),
    ("perf", BUILDING_ZENO, "a measured speed improvement"),
    ("feat", BUILDING_ZENO, "a capability that did not exist before"),
    ("test", BEHIND_THE_SCENES, "how the system is verified"),
    ("refactor", BEHIND_THE_SCENES, "why the architecture changed"),
    ("docs", BEHIND_THE_SCENES, "what was learned"),
    ("security", BEHIND_THE_SCENES, "a safety decision"),
)


def _story_for(subject: str) -> tuple[str, str]:
    low = subject.casefold()
    for prefix, category, angle in _COMMIT_STORY:
        if low.startswith(prefix):
            return category, angle
    return BUILDING_ZENO, "something that changed in the build"


def _clean_subject(subject: str) -> str:
    """`feat(voice): add streaming` -> `add streaming`."""
    return re.sub(r"^\w+(?:\([^)]*\))?:\s*", "", subject).strip()


class ContentIdeaEngine:
    """Generates ideas from what ZENO actually did."""

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()

    def generate(self, *, platform: str = social_store.TIKTOK,
                 limit: int = 5) -> list[ContentIdea]:
        """Ideas grounded in real development. Empty when nothing happened."""
        ideas: list[ContentIdea] = []
        commits = recent_commits(limit=25)
        facts = measured_facts(limit=12)

        # 1. Commits with a measured result attached are the strongest posts:
        #    they have a story AND a number that can be defended.
        for commit in commits[:limit * 2]:
            if len(ideas) >= limit:
                break
            subject = _clean_subject(commit.summary)
            if len(subject) < 12:
                continue
            category, angle = _story_for(commit.summary)
            related = [f for f in facts
                       if _shares_topic(subject, f.summary)][:2]
            evidence = [commit, *related]

            ideas.append(ContentIdea(
                title=subject[:80],
                hook=self._hook_for(subject, category, related),
                platform=platform,
                format=SCREEN_RECORDING if category == ZENO_IN_ACTION else ORB_ANIMATION,
                topic=subject[:120],
                objective=f"show {angle}",
                duration_s=30 if related else 15,
                required_media=("screen recording of the change in use"
                                if category == ZENO_IN_ACTION
                                else "orb animation with text overlay"),
                category=category,
                # A post quoting a number carries more risk than one that
                # does not, because the number has to survive a question.
                risk="medium" if related else "low",
                evidence=evidence,
            ))

        # 2. A standalone measurement is worth a post on its own.
        for fact in facts:
            if len(ideas) >= limit:
                break
            if any(fact in idea.evidence for idea in ideas):
                continue
            ideas.append(ContentIdea(
                title=fact.summary[:80],
                hook=f"Here is a number from ZENO's own build: {fact.summary[:70]}",
                platform=platform,
                format=ORB_ANIMATION,
                topic=fact.summary[:120],
                objective="show a real measurement from the build",
                duration_s=15,
                required_media="text overlay on orb animation",
                category=BEHIND_THE_SCENES,
                risk="medium",
                evidence=[fact],
            ))

        return ideas[:limit]

    @staticmethod
    def _hook_for(subject: str, category: str, related: list[Evidence]) -> str:
        if related:
            return f"Why did {subject.lower()} matter? The measurement says it did."
        if category == ZENO_IN_ACTION:
            return f"Watch ZENO {subject.lower()}."
        if category == BEHIND_THE_SCENES:
            return f"Here is what building {subject.lower()} actually taught me."
        return f"I just taught my AI assistant to {subject.lower()}."

    def save(self, idea: ContentIdea) -> str:
        """Persist an idea and return its content id."""
        content_id = self._store.create_content(
            platform=idea.platform, title=idea.title, hook=idea.hook,
            topic=idea.topic, objective=idea.objective, format=idea.format,
            duration_s=idea.duration_s, required_media=idea.required_media,
            category=idea.category, risk=idea.risk, status=social_store.IDEA,
            evidence=[e.as_dict() for e in idea.evidence],
            dry_run=1)
        self._store.audit("ContentIdeaEngine", "idea_created",
                          platform=idea.platform, target=content_id,
                          result=idea.title[:80])
        return content_id


def _shares_topic(a: str, b: str) -> bool:
    """Cheap overlap test: do these two lines talk about the same thing?"""
    stop = {"the", "and", "for", "with", "that", "this", "from", "was", "are",
            "not", "have", "been", "will", "when", "then", "than", "into"}
    words_a = {w for w in re.findall(r"[a-z]{4,}", a.casefold()) if w not in stop}
    words_b = {w for w in re.findall(r"[a-z]{4,}", b.casefold()) if w not in stop}
    return len(words_a & words_b) >= 2


# --- the script (Phase 21) -----------------------------------------------

@dataclass
class Script:
    hook: str
    problem: str
    action: str
    result: str
    cta: str
    duration_s: int = 30

    def as_text(self) -> str:
        return "\n".join((
            f"[HOOK] {self.hook}",
            f"[PROBLEM] {self.problem}",
            f"[ZENO ACTION] {self.action}",
            f"[RESULT] {self.result}",
            f"[CTA] {self.cta}",
        ))

    def as_dict(self) -> dict[str, Any]:
        return {"hook": self.hook, "problem": self.problem,
                "action": self.action, "result": self.result,
                "cta": self.cta, "duration_s": self.duration_s}


def write_script(item: dict[str, Any]) -> tuple[Script | None, str]:
    """Build a HOOK/PROBLEM/ACTION/RESULT/CTA script from stored evidence.

    Refuses when the RESULT section would need a number that no evidence
    supports, because that is the exact moment a content system starts
    inventing performance claims.
    """
    evidence = item.get("evidence") or []
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except (TypeError, ValueError):
            evidence = []

    title = str(item.get("title") or "").strip()
    hook = str(item.get("hook") or "").strip() or f"ZENO: {title}"
    if not title:
        return None, "no title to write a script about"

    measurements = [e for e in evidence if e.get("kind") == "measurement"]
    commits = [e for e in evidence if e.get("kind") == "commit"]

    if not evidence:
        return None, ("no evidence attached; ZENO does not script content it "
                      "cannot substantiate")

    if measurements:
        result = measurements[0].get("summary", "")
        result_line = f"The measurement: {result}"
    elif commits:
        result_line = (f"It works, and the change is in the repository "
                       f"({commits[0].get('source', '')}).")
    else:
        result_line = "It works."

    problem = _problem_from(title)
    action = (f"I taught ZENO to {_clean_subject(title).lower()}."
              if not title.lower().startswith(("i ", "we ")) else title)

    duration = int(item.get("duration_s") or 30)
    if duration not in DURATIONS:
        duration = min(DURATIONS, key=lambda d: abs(d - duration))

    return Script(hook=hook, problem=problem, action=action,
                  result=result_line, cta="Follow the build.",
                  duration_s=duration), "scripted from attached evidence"


def _problem_from(title: str) -> str:
    low = title.casefold()
    if any(word in low for word in ("slow", "latency", "speed", "fast", "perf")):
        return "It was too slow to be useful."
    if any(word in low for word in ("fix", "bug", "break", "fail", "error")):
        return "It was broken, and the failure was not obvious."
    if any(word in low for word in ("test", "verify", "stress", "soak")):
        return "I could not prove it worked."
    if any(word in low for word in ("voice", "mic", "audio", "speech")):
        return "It could not hear me properly."
    if any(word in low for word in ("secure", "auth", "token", "safety")):
        return "It was not safe to expose."
    return "Here is what was missing."
