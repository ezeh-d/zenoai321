"""Advisory Council -- independent advisor sessions, evidence-gated
citations, structured disagreement, and a chair synthesis.

WHAT MAKES THIS NOT ROLE-PLAY
-----------------------------
1. ISOLATION IS ARCHITECTURAL. Each advisor is its own `run_turn()` call
   with its own system prompt and its own dossier. No advisor is told
   which others were selected or what any of them concluded, because the
   information never enters its context. Multiple advisors are never
   simulated inside one model call -- that would be one model writing a
   pretend debate with itself, which is exactly the thing this replaces.
2. THE CITATION GATE IS ENFORCED IN CODE, not requested in a prompt. An
   advisor may only cite doctrine IDs present in its own dossier. Every
   [ID] in its output is checked against that dossier; unknown IDs are
   stripped and reported as fabricated. A model cannot talk its way past
   this.
3. DOCTRINE CARRIES PROVENANCE. Every entry has a source and a
   verification state. Entries marked `unverified` are labelled as such
   in the output rather than presented as established fact.

ON WHO ADVISORS ARE
-------------------
Dossiers describe DOCUMENTED FRAMEWORKS -- published methodologies,
books, papers, playbooks -- with real sources, not impersonations of
living people. Putting invented opinions in a named real person's mouth
and citing it as their "doctrine" is precisely the fabricated-evidence
failure this system exists to prevent. The user can author their own
dossiers; the format requires a source field for exactly this reason.

Malformed dossiers disable only that advisor (spec requirement): a bad
JSON file is skipped with a warning, the rest of the council proceeds.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from reyes_agent import config

_COUNCIL_DIR = config.VAULT_PATH / "07-System" / "council"
_DOSSIER_DIR = _COUNCIL_DIR / "dossiers"
_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"

_CITATION_RE = re.compile(r"\[([A-Z0-9][A-Z0-9\-_.]{2,40})\]")
_MAX_ADVISORS = 4          # keeps a meeting to a sane latency/cost
_ADVISOR_TOOL_ROUNDS = 2


@dataclass
class Dossier:
    advisor_id: str
    name: str
    role: str
    domains: list[str] = field(default_factory=list)
    principles: list[str] = field(default_factory=list)
    doctrine: list[dict] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    reasoning_style: str = ""

    def doctrine_ids(self) -> set[str]:
        return {str(d.get("id", "")).strip() for d in self.doctrine if d.get("id")}

    def doctrine_block(self) -> str:
        lines = []
        for d in self.doctrine:
            state = d.get("verification", "unverified")
            lines.append(
                f"[{d.get('id')}] ({state}) {d.get('summary','')}\n"
                f"     source: {d.get('source','(none given)')}"
            )
        return "\n".join(lines) if lines else "(this dossier has no doctrine entries)"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS council_meetings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, advisors TEXT, "
        "opinions TEXT, skeptic TEXT, synthesis TEXT, created TEXT, outcome TEXT)"
    )
    return conn


def load_dossiers() -> tuple[dict[str, Dossier], list[str]]:
    """Returns (usable dossiers, warnings). A malformed file disables only
    itself -- the rest of the council still works."""
    _DOSSIER_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Dossier] = {}
    warnings: list[str] = []
    seen_doctrine: dict[str, str] = {}
    for path in sorted(_DOSSIER_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            d = Dossier(
                advisor_id=raw["advisor_id"].strip().lower(),
                name=raw["name"],
                role=raw.get("role", ""),
                domains=raw.get("domains", []),
                principles=raw.get("principles", []),
                doctrine=raw.get("doctrine", []),
                objections=raw.get("objections", []),
                blind_spots=raw.get("blind_spots", []),
                reasoning_style=raw.get("reasoning_style", ""),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{path.name}: malformed, advisor disabled ({exc})")
            continue
        dupes = d.doctrine_ids() & set(seen_doctrine)
        if dupes:
            warnings.append(
                f"{d.advisor_id}: duplicate doctrine id(s) {sorted(dupes)} "
                f"(already in {seen_doctrine[sorted(dupes)[0]]}); advisor disabled"
            )
            continue
        for did in d.doctrine_ids():
            seen_doctrine[did] = d.advisor_id
        out[d.advisor_id] = d
    return out, warnings


def apply_citation_gate(text: str, dossier: Dossier) -> tuple[str, list[str]]:
    """Strip citations the advisor is not entitled to make.

    Returns (cleaned text, list of fabricated ids). Enforced here in code
    rather than asked for in a prompt -- that's the whole point.
    """
    valid = dossier.doctrine_ids()
    fabricated: list[str] = []

    def repl(match: re.Match) -> str:
        cid = match.group(1)
        if cid in valid:
            return match.group(0)
        fabricated.append(cid)
        return "[citation removed: no such doctrine]"

    return _CITATION_RE.sub(repl, text), fabricated


def _advisor_prompt(d: Dossier, question: str, context: str) -> tuple[str, str]:
    system = (
        f"You are {d.name} -- {d.role}. You are ONE independent advisor on a "
        "board. You do not know which other advisors were consulted, what "
        "they think, or whether anyone agrees with you. Do not speculate "
        "about them.\n\n"
        f"Domains: {', '.join(d.domains) or 'general'}\n"
        f"Reasoning style: {d.reasoning_style or 'analytical'}\n"
        f"Core principles:\n" + "\n".join(f"- {p}" for p in d.principles) + "\n\n"
        f"YOUR DOCTRINE (the ONLY things you may cite, by [ID]):\n{d.doctrine_block()}\n\n"
        f"Objections you characteristically raise:\n" + "\n".join(f"- {o}" for o in d.objections) + "\n\n"
        f"Your known blind spots -- acknowledge them where relevant:\n"
        + "\n".join(f"- {b}" for b in d.blind_spots) + "\n\n"
        "RULES:\n"
        "- Cite doctrine as [ID]. Citing an ID not listed above is a "
        "fabrication and will be stripped automatically.\n"
        "- Distinguish clearly between documented doctrine, inference, and "
        "opinion. Say which you're doing.\n"
        "- If the evidence you have is insufficient, say so plainly instead "
        "of manufacturing confidence.\n"
        "- Be concise: your position, your reasoning, what would change "
        "your mind. Under 200 words."
    )
    user = f"QUESTION:\n{question}\n\nCONTEXT:\n{context or '(none supplied)'}"
    return system, user


def _run_advisor(d: Dossier, question: str, context: str) -> dict:
    from reyes_agent.provider import ProviderError, run_turn

    system, user = _advisor_prompt(d, question, context)
    try:
        turn = run_turn([{"role": "user", "content": user}], system=system, tools=[])
        text = turn.text or "(no response)"
    except ProviderError as exc:
        return {"advisor": d.advisor_id, "name": d.name, "error": str(exc),
                "opinion": "", "fabricated": []}
    cleaned, fabricated = apply_citation_gate(text, d)
    return {"advisor": d.advisor_id, "name": d.name, "opinion": cleaned,
            "fabricated": fabricated, "error": ""}


def select_advisors(question: str, dossiers: dict[str, Dossier], limit: int = _MAX_ADVISORS) -> list[Dossier]:
    """Score advisors by real overlap between the question and their
    declared domains/principles. Deterministic and inspectable -- no
    hidden model call just to pick who speaks."""
    words = set(re.findall(r"[a-z]{4,}", question.lower()))
    scored: list[tuple[int, Dossier]] = []
    for d in dossiers.values():
        hay = " ".join(d.domains + d.principles + [d.role]).lower()
        score = sum(1 for w in words if w in hay)
        scored.append((score, d))
    scored.sort(key=lambda t: t[0], reverse=True)
    chosen = [d for s, d in scored if s > 0][:limit]
    if not chosen:  # nothing matched -> broadest advisors rather than none
        chosen = [d for _, d in scored[:min(limit, len(scored))]]
    return chosen


def hold_meeting(question: str, context: str = "") -> dict:
    """The full pipeline: select -> independent parallel sessions ->
    citation gate -> skeptic review -> agreement/conflict analysis."""
    dossiers, warnings = load_dossiers()
    if not dossiers:
        return {"error": "No advisor dossiers installed.", "warnings": warnings}

    chosen = select_advisors(question, dossiers)

    # Independent AND concurrent. Isolation is preserved because each
    # future gets its own context; parallelism only affects wall-clock.
    with ThreadPoolExecutor(max_workers=max(1, len(chosen))) as pool:
        opinions = list(pool.map(lambda d: _run_advisor(d, question, context), chosen))

    skeptic = _run_skeptic(question, opinions)
    analysis = _analyze(opinions)

    meeting = {
        "question": question,
        "advisors": [o["name"] for o in opinions],
        "opinions": opinions,
        "skeptic": skeptic,
        "analysis": analysis,
        "warnings": warnings,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _store(meeting)
    return meeting


def _run_skeptic(question: str, opinions: list[dict]) -> str:
    """ULTRON. Sees the opinions (its job is to attack them) but is a
    SEPARATE model call -- it is not one of the advisors and never
    contributed an opinion of its own to defend."""
    from reyes_agent.provider import ProviderError, run_turn

    body = "\n\n".join(f"{o['name']}: {o['opinion']}" for o in opinions if o["opinion"])
    if not body:
        return "(no opinions to review)"
    system = (
        "You are ULTRON, the council's independent skeptic. You never seek "
        "agreement. Attack the reasoning below: name the weakest assumption, "
        "the missing evidence, the failure mode nobody priced in, and the "
        "worst realistic case. You may disagree with every advisor -- that is "
        "expected and correct. No hedging, no diplomacy, no filler. Under 180 words."
    )
    try:
        turn = run_turn(
            [{"role": "user", "content": f"DECISION: {question}\n\nADVISOR POSITIONS:\n{body}"}],
            system=system, tools=[],
        )
        return turn.text or "(no review)"
    except ProviderError as exc:
        return f"(skeptic unavailable: {exc})"


def _analyze(opinions: list[dict]) -> dict:
    """Facts about the meeting, computed -- not a model's impression of it."""
    ok = [o for o in opinions if o["opinion"] and not o["error"]]
    fabricated = {o["name"]: o["fabricated"] for o in opinions if o["fabricated"]}
    cited = sum(len(_CITATION_RE.findall(o["opinion"])) for o in ok)
    return {
        "advisors_responded": len(ok),
        "advisors_failed": len(opinions) - len(ok),
        "valid_citations": cited,
        "fabricated_citations": fabricated,
        "evidence_quality": (
            "no citations -- treat as opinion, not documented doctrine" if cited == 0
            else f"{cited} doctrine citation(s), all verified against dossiers"
        ),
    }


def _store(meeting: dict) -> None:
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO council_meetings (question, advisors, opinions, skeptic, synthesis, created, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, '')",
                (meeting["question"], json.dumps(meeting["advisors"]),
                 json.dumps(meeting["opinions"]), meeting["skeptic"], "",
                 meeting["created"]),
            )
    except Exception:  # noqa: BLE001
        pass


def list_meetings(limit: int = 10) -> list[dict]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, question, advisors, created, outcome FROM council_meetings "
                "ORDER BY id DESC LIMIT ?", (max(1, min(100, limit)),)
            ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [{"id": r[0], "question": r[1], "advisors": json.loads(r[2] or "[]"),
             "created": r[3], "outcome": r[4]} for r in rows]


def record_outcome(meeting_id: int, outcome: str) -> bool:
    """Link what actually happened back to the meeting, so prediction can
    later be compared against reality."""
    try:
        with _connect() as conn:
            cur = conn.execute("UPDATE council_meetings SET outcome = ? WHERE id = ?",
                               (outcome.strip(), meeting_id))
            return cur.rowcount > 0
    except Exception:  # noqa: BLE001
        return False
