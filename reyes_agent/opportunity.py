"""Evidence-led online opportunity intelligence for ZENO.

The engine scores inputs; it does not invent market demand, clients, income,
or research.  Dated observations retain their epistemic kind and source so a
market estimate can never silently become a fact.  Execution remains in the
existing builder, research, messaging, and permission systems.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from reyes_agent import config
from reyes_agent.memory.privacy import redact


FACT = "FACT"
ESTIMATE = "ESTIMATE"
ASSUMPTION = "ASSUMPTION"
OPINION = "OPINION"
EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
OBSERVATION_KINDS = frozenset({FACT, ESTIMATE, ASSUMPTION, OPINION, EXPERIMENT_RESULT})

FACTOR_NAMES = (
    "skill_fit", "startup_cost", "time_to_first_result", "market_demand",
    "competition", "repeatability", "scalability", "risk", "estimated_effort",
)

# Positive factors use their supplied value; cost/latency/risk/effort and
# competition are inverted.  Weights are transparent and intentionally total 1.
WEIGHTS = {
    "skill_fit": 0.18,
    "startup_cost": 0.08,
    "time_to_first_result": 0.12,
    "market_demand": 0.20,
    "competition": 0.10,
    "repeatability": 0.12,
    "scalability": 0.10,
    "risk": 0.06,
    "estimated_effort": 0.04,
}
INVERTED = frozenset({"startup_cost", "time_to_first_result", "competition", "risk", "estimated_effort"})

CATEGORIES = frozenset({
    "freelancing", "web development", "ai automation services", "graphic design",
    "logo/design services", "data analysis", "digital products", "micro-saas",
    "website creation", "content creation", "seo", "affiliate-content research",
    "social media growth", "video content", "online tutoring", "business automation",
    "legitimate lead generation", "market research", "product research",
    "software development",
})

# These are role adapters over ZENO's existing registered Council.  They do
# not create duplicate agents, schedulers, model clients, or hidden workers.
SPECIALIST_COMPONENTS = {
    "OpportunityScout": "aris",
    "MarketResearchAgent": "aris",
    "CompetitionAgent": "titan",
    "SkillGapAgent": "kate",
    "ContentAgent": "zeal",
    "ProductBuilderAgent": "tosin",
    "FreelanceAgent": "titan",
    "PricingResearchAgent": "titan",
    "SEOAgent": "titan",
    "AnalyticsAgent": "oracle",
}

GUARDRAILS = (
    "No guaranteed-income claims.",
    "No spam, fake testimonials, fake identities, or deceptive outreach.",
    "No copyrighted-work theft or platform-protection bypass.",
    "Money movement and purchases are outside this engine and require the existing approval policy.",
)


def _clean_source(value: str) -> str:
    """Keep citation identity without retaining query tokens or fragments."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:1000]
    except ValueError:
        pass
    return redact(text, limit=1000)


@dataclass(frozen=True)
class Observation:
    kind: str
    summary: str
    source: str = ""
    observed_at: float = 0.0
    expires_at: float = 0.0

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> "Observation":
        kind = str(value.get("kind") or ASSUMPTION).strip().upper()
        if kind not in OBSERVATION_KINDS:
            raise ValueError(f"observation kind must be one of: {', '.join(sorted(OBSERVATION_KINDS))}")
        summary = redact(str(value.get("summary") or "").strip(), limit=2000)
        if not summary:
            raise ValueError("each observation needs a non-empty summary")
        source = _clean_source(str(value.get("source") or ""))
        if kind in {FACT, EXPERIMENT_RESULT} and not source:
            raise ValueError(f"{kind} observations require a source or local evidence reference")
        observed_at = float(value.get("observed_at") or time.time())
        expires_at = float(value.get("expires_at") or 0.0)
        if expires_at and expires_at < observed_at:
            raise ValueError("observation expiry cannot precede its observation time")
        return cls(kind, summary, source, observed_at, expires_at)

    def as_dict(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        return {
            "kind": self.kind,
            "summary": self.summary,
            "source": self.source,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at or None,
            "expired": bool(self.expires_at and self.expires_at <= current),
        }


def validate_factors(value: dict[str, Any]) -> dict[str, float]:
    missing = [name for name in FACTOR_NAMES if name not in value]
    if missing:
        raise ValueError("missing opportunity factors: " + ", ".join(missing))
    clean: dict[str, float] = {}
    for name in FACTOR_NAMES:
        try:
            number = float(value[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number from 0 to 10") from exc
        if not 0.0 <= number <= 10.0:
            raise ValueError(f"{name} must be between 0 and 10")
        clean[name] = round(number, 3)
    return clean


def score_factors(value: dict[str, Any]) -> dict[str, Any]:
    factors = validate_factors(value)
    contributions: dict[str, float] = {}
    total = 0.0
    for name, weight in WEIGHTS.items():
        normalized = (10.0 - factors[name]) if name in INVERTED else factors[name]
        contribution = normalized * 10.0 * weight
        contributions[name] = round(contribution, 2)
        total += contribution
    return {
        "score": round(total, 2),
        "scale": "0-100 relative opportunity score; not income probability",
        "factors": factors,
        "weights": dict(WEIGHTS),
        "inverted_factors": sorted(INVERTED),
        "contributions": contributions,
    }


def evidence_state(observations: list[Observation], *, now: float | None = None) -> str:
    current = time.time() if now is None else float(now)
    current_sourced = [item for item in observations
                       if item.source and not (item.expires_at and item.expires_at <= current)]
    factual = [item for item in current_sourced if item.kind in {FACT, EXPERIMENT_RESULT}]
    if len(factual) >= 3:
        return "EVIDENCE_BACKED"
    if current_sourced:
        return "LIMITED_EVIDENCE"
    return "ASSUMPTION_ONLY"


class OpportunityEngine:
    """Local persistence and deterministic scoring; no background poller."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.VAULT_PATH / "07-System" / "opportunities" / "opportunities.sqlite3")
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS opportunities ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, "
            "summary TEXT NOT NULL, score REAL NOT NULL, evidence_state TEXT NOT NULL, "
            "factors_json TEXT NOT NULL, observations_json TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
        return conn

    def assess(self, *, name: str, category: str, summary: str,
               factors: dict[str, Any], observations: list[dict[str, Any]] | None = None,
               opportunity_id: str = "") -> dict[str, Any]:
        title = redact(str(name or "").strip(), limit=160)
        if not title:
            raise ValueError("opportunity name is required")
        normalized_category = " ".join(str(category or "").strip().casefold().split())
        if normalized_category not in CATEGORIES:
            raise ValueError("unsupported category; use one of: " + ", ".join(sorted(CATEGORIES)))
        clean_summary = redact(str(summary or "").strip(), limit=3000)
        if not clean_summary:
            raise ValueError("opportunity summary is required")
        scored = score_factors(factors)
        evidence = [Observation.from_value(item) for item in (observations or [])]
        state = evidence_state(evidence)
        record_id = str(opportunity_id or uuid.uuid4().hex[:12]).strip()
        if not record_id.replace("-", "").isalnum() or len(record_id) > 64:
            raise ValueError("opportunity_id must be an alphanumeric identifier")
        now = time.time()
        with self._lock, self._connect() as conn:
            prior = conn.execute("SELECT created_at FROM opportunities WHERE id = ?", (record_id,)).fetchone()
            created_at = float(prior["created_at"]) if prior else now
            conn.execute(
                "INSERT OR REPLACE INTO opportunities "
                "(id,name,category,summary,score,evidence_state,factors_json,observations_json,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (record_id, title, normalized_category, clean_summary, scored["score"], state,
                 json.dumps(scored["factors"], sort_keys=True),
                 json.dumps([item.as_dict(now=now) for item in evidence], ensure_ascii=False),
                 "ASSESSED", created_at, now),
            )
        result = self.get(record_id)
        self._publish("opportunity.assessed", result)
        return result

    def get(self, opportunity_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (str(opportunity_id),)).fetchone()
        return self._row(row) if row else {}

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(100, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunities ORDER BY updated_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._row(row) for row in rows]

    def delete(self, opportunity_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM opportunities WHERE id = ?", (str(opportunity_id),))
        removed = cursor.rowcount > 0
        if removed:
            self._publish("opportunity.deleted", {"id": str(opportunity_id)})
        return removed

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        factors = json.loads(row["factors_json"])
        observations = json.loads(row["observations_json"])
        # Recompute expiry at read time; stored market evidence cannot remain
        # current merely because the record was not opened for a while.
        now = time.time()
        for item in observations:
            item["expired"] = bool(item.get("expires_at") and float(item["expires_at"]) <= now)
        current = [item for item in observations if not item["expired"]]
        current_sourced = [item for item in current if item.get("source")]
        current_factual = [item for item in current_sourced
                           if item.get("kind") in {FACT, EXPERIMENT_RESULT}]
        current_state = ("EVIDENCE_BACKED" if len(current_factual) >= 3
                         else "LIMITED_EVIDENCE" if current_sourced
                         else "ASSUMPTION_ONLY")
        return {
            "id": row["id"], "name": row["name"], "category": row["category"],
            "summary": row["summary"], "score": row["score"],
            "score_scale": "0-100 relative opportunity score; not income probability",
            "evidence_state": current_state, "factors": factors,
            "observations": observations, "current_observations": len(current),
            "expired_observations": len(observations) - len(current),
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "guardrails": list(GUARDRAILS),
        }

    @staticmethod
    def _publish(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus

            event_bus.publish(event_type, payload, source="opportunity")
        except Exception:
            pass

    @staticmethod
    def status() -> dict[str, Any]:
        return {
            "state": "READY", "polling": False, "network_calls": False,
            "specialist_components": dict(SPECIALIST_COMPONENTS),
            "categories": sorted(CATEGORIES), "guardrails": list(GUARDRAILS),
            "note": "Scores owner/research-supplied evidence; never invents demand or guarantees income.",
        }


def research_plan(goal: str, skills: list[str] | None = None,
                  constraints: list[str] | None = None) -> dict[str, Any]:
    """Return observable research tasks, not a fabricated market answer."""
    clean_goal = redact(str(goal or "").strip(), limit=1000)
    if not clean_goal:
        raise ValueError("goal is required")
    skill_list = [redact(str(item), limit=100) for item in (skills or []) if str(item).strip()][:20]
    constraint_list = [redact(str(item), limit=200) for item in (constraints or []) if str(item).strip()][:20]
    steps = [
        {"component": "OpportunityScout", "agent": "aris", "task": "Find concrete paid problems and source each observation."},
        {"component": "MarketResearchAgent", "agent": "aris", "task": "Measure current demand with dated primary or reputable sources."},
        {"component": "CompetitionAgent", "agent": "titan", "task": "Compare real competitors, positioning, prices, and constraints."},
        {"component": "SkillGapAgent", "agent": "kate", "task": "Compare required skills with the owner's stated evidence."},
        {"component": "PricingResearchAgent", "agent": "titan", "task": "Collect cited market prices; do not promise revenue."},
        {"component": "AnalyticsAgent", "agent": "oracle", "task": "Score only after all nine factors have evidence or explicit assumptions."},
    ]
    return {
        "goal": clean_goal, "skills": skill_list, "constraints": constraint_list,
        "steps": steps, "score_after_research": True,
        "required_factor_scale": "Each of nine factors is owner/research supplied on 0-10.",
        "guardrails": list(GUARDRAILS),
    }


_engine: OpportunityEngine | None = None
_engine_lock = threading.Lock()


def get_opportunity_engine() -> OpportunityEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OpportunityEngine()
    return _engine
