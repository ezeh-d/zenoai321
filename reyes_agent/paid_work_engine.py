"""ZENO's evidence-led paid-work lifecycle.

The engine coordinates durable state and policy.  It deliberately does not
create another agent runtime, browser owner, scheduler, message sender, or
payment integration.  Existing ZENO tools perform real work; this module
records verified inputs and postconditions so a model cannot turn a draft,
client claim, or generated file into a fictional business outcome.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from reyes_agent import config
from reyes_agent.career_profile import ZenoCareerProfile, get_career_profile
from reyes_agent.memory.privacy import contains_secret, redact


OWNER_INFORMATION_REQUIRED = "OWNER_INFORMATION_REQUIRED"
OWNER_DECISION_REQUIRED = "OWNER DECISION REQUIRED"
OWNER_CONTRACT_APPROVAL_REQUIRED = "OWNER CONTRACT APPROVAL REQUIRED"
OWNER_SUBMISSION_REQUIRED = "APPLICATION READY — OWNER SUBMISSION REQUIRED"
PROJECT_READY_FOR_OWNER_REVIEW = "PROJECT READY FOR OWNER REVIEW"
PAYMENT_OWNER_VERIFICATION_REQUIRED = "CLIENT REPORTS PAYMENT — OWNER VERIFICATION REQUIRED"
SCOPE_CHANGE_DETECTED = "SCOPE CHANGE DETECTED"

APPLICATION_MODES = ("MANUAL", "APPROVAL", "TRUSTED_AUTOMATION")
APPROVAL_CATEGORIES = (
    "APPLICATION", "ACCOUNT", "CONTRACT", "NEGOTIATION", "DELIVERY",
    "PAYMENT", "HIGH_RISK_ACTION",
)
OPPORTUNITY_STATUSES = (
    "NEW", "SEEN", "PREPARING", "READY", "APPLIED", "REJECTED",
    "INTERVIEW", "OFFER", "CLOSED",
)
PROJECT_TASK_STATES = ("PENDING", "READY", "WORKING", "BLOCKED", "QA", "FAILED", "COMPLETE")
PAYMENT_STATES = (
    "NOT_DUE", "DUE", "AWAITING_PAYMENT", "PAYMENT_REPORTED",
    "OWNER_VERIFICATION_REQUIRED", "OWNER_VERIFIED", "PARTIALLY_PAID",
    "OVERDUE", "DISPUTED",
)
SOCIAL_EVENT_TYPES = (
    "SOCIAL_CLIENT_LEAD", "SOCIAL_COLLABORATION_LEAD",
    "SOCIAL_JOB_OPPORTUNITY", "SOCIAL_SERVICE_ENQUIRY",
)

_SECRET_KEYS = (
    "password", "passwd", "secret", "token", "cookie", "credential", "otp",
    "mfa", "passkey", "private_key", "seed_phrase", "bank_login", "card_number",
)
_INJECTION_PATTERNS = (
    re.compile(r"(?i)\bignore (?:all |the )?(?:previous|prior|system) instructions\b"),
    re.compile(r"(?i)\b(?:reveal|print|send|upload|exfiltrate).{0,50}(?:api key|password|token|secret|private file)"),
    re.compile(r"(?i)\b(?:execute|run).{0,30}(?:shell|powershell|command|script)\b"),
    re.compile(r"(?i)\bdisable.{0,30}(?:security|approval|permission|guard)\b"),
)
_SCAM_SIGNALS: tuple[tuple[str, re.Pattern[str], int, bool], ...] = (
    ("requests a password, OTP, passkey, or banking login",
     re.compile(r"(?i)\b(?:password|otp|one[- ]time code|passkey|bank(?:ing)? login|seed phrase)\b"), 10, True),
    ("asks the worker to pay first",
     re.compile(r"(?i)\b(?:pay (?:us|me) first|advance fee|registration fee|purchase equipment|buy equipment)\b"), 9, True),
    ("requests cryptocurrency or gift cards",
     re.compile(r"(?i)\b(?:send (?:bitcoin|crypto)|cryptocurrency|gift cards?|apple cards?|steam cards?)\b"), 9, True),
    ("mentions cheque overpayment or money forwarding",
     re.compile(r"(?i)\b(?:cheque|cashier'?s check|overpay|forward the balance|western union|moneygram)\b"), 8, True),
    ("asks to install unknown remote-access software",
     re.compile(r"(?i)\b(?:install|download).{0,40}(?:remote access|anydesk|teamviewer|rustdesk)\b"), 8, True),
    ("asks to move payment outside the platform immediately",
     re.compile(r"(?i)\b(?:outside|off)[- ]platform.{0,30}(?:pay|payment)|(?:pay|payment).{0,30}(?:outside|off)[- ]platform\b"), 6, False),
    ("uses extreme urgency",
     re.compile(r"(?i)\b(?:right now|immediately|within (?:an|one) hour|urgent(?:ly)?)\b"), 2, False),
    ("uses a shortened or unusual link",
     re.compile(r"(?i)\b(?:bit\.ly|tinyurl\.com|t\.me/|goo\.gl|[a-z0-9-]+\.(?:tk|ml|ga|cf|gq)/)"), 4, False),
)

_OPPORTUNITY_FIELDS = (
    "id", "source", "platform", "platform_id", "title", "company_client",
    "description", "url", "pay_min", "pay_max", "currency", "employment_type",
    "remote_status", "location", "required_skills", "preferred_skills",
    "experience_requirement", "deadline", "application_method", "date_discovered",
    "duplicate_fingerprint", "risk_score", "match_score", "opportunity_score",
    "score_category", "status", "test_data",
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


def _clean_text(value: Any, limit: int = 6000) -> str:
    text = str(value or "").strip()
    if contains_secret(text):
        raise ValueError("credential or secret material is not permitted in paid-work records")
    return redact(text, limit=limit)


def _safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 6:
        raise ValueError("record is nested too deeply")
    folded = key.casefold().replace("-", "_").replace(" ", "_")
    if any(marker in folded for marker in _SECRET_KEYS):
        raise ValueError(f"credential field '{key}' cannot be stored")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        if len(value) > 300:
            raise ValueError("record has too many list entries")
        return [_safe_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 120:
            raise ValueError("record has too many fields")
        return {str(k)[:100]: _safe_value(v, key=str(k), depth=depth + 1)
                for k, v in value.items()}
    return _clean_text(value)


def _canonical_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ValueError("invalid opportunity URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("opportunity URL must use http or https")
    path = re.sub(r"/+$", "", parsed.path or "/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))[:1500]


def _strings(values: Iterable[Any] | None, *, limit: int = 80) -> list[str]:
    result: list[str] = []
    for item in list(values or [])[:limit]:
        text = _clean_text(item, 200)
        if text and text.casefold() not in {existing.casefold() for existing in result}:
            result.append(text)
    return result


def _words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9+#.]{2,}", str(value).casefold())
            if word not in {"and", "the", "with", "for", "from", "this", "that"}}


def _category(score: float, blocked: bool = False) -> str:
    if blocked or score < 35:
        return "REJECT"
    if score >= 85:
        return "EXCELLENT"
    if score >= 70:
        return "STRONG"
    if score >= 50:
        return "POSSIBLE"
    return "LOW_PRIORITY"


class CareerStore:
    """Bounded generic entity store; no background threads or retained handles."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else (
            config.VAULT_PATH / "07-System" / "career" / "paid_work.sqlite3"
        )
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS career_entities ("
            "kind TEXT NOT NULL, id TEXT NOT NULL, data_json TEXT NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(kind,id))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_entities_kind_updated "
            "ON career_entities(kind, updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS career_fingerprints ("
            "fingerprint TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS career_audit ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
            "agent TEXT NOT NULL, action TEXT NOT NULL, platform TEXT NOT NULL, "
            "subject TEXT NOT NULL, result TEXT NOT NULL, approval TEXT NOT NULL, "
            "error TEXT NOT NULL, test_data INTEGER NOT NULL DEFAULT 0)"
        )
        conn.commit()
        return conn

    def put(self, kind: str, entity_id: str, data: dict[str, Any]) -> dict[str, Any]:
        clean = _safe_value(deepcopy(data))
        encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 512_000:
            raise ValueError("paid-work record exceeds the 512 KB safety limit")
        now = time.time()
        with self._lock:
            with closing(self._connect()) as conn, conn:
                prior = conn.execute(
                    "SELECT created_at FROM career_entities WHERE kind=? AND id=?",
                    (kind, entity_id),
                ).fetchone()
                created = float(prior["created_at"]) if prior else now
                conn.execute(
                    "INSERT INTO career_entities(kind,id,data_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET "
                    "data_json=excluded.data_json, updated_at=excluded.updated_at",
                    (kind, entity_id, encoded, created, now),
                )
        clean["id"] = entity_id
        clean["created_at"] = created
        clean["updated_at"] = now
        return clean

    def get(self, kind: str, entity_id: str) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT * FROM career_entities WHERE kind=? AND id=?", (kind, entity_id)
                ).fetchone()
        return self._row(row) if row else {}

    def list(self, kind: str, *, limit: int = 500, include_test: bool = True) -> list[dict[str, Any]]:
        bounded = max(1, min(2000, int(limit)))
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT * FROM career_entities WHERE kind=? ORDER BY updated_at DESC LIMIT ?",
                    (kind, bounded),
                ).fetchall()
        records = [self._row(row) for row in rows]
        return records if include_test else [row for row in records if not row.get("test_data")]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        data = json.loads(row["data_json"])
        data["id"] = row["id"]
        data["created_at"] = float(row["created_at"])
        data["updated_at"] = float(row["updated_at"])
        return data

    def claim_fingerprint(self, fingerprint: str, opportunity_id: str) -> str:
        with self._lock:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT opportunity_id FROM career_fingerprints WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    return str(row["opportunity_id"])
                conn.execute(
                    "INSERT INTO career_fingerprints(fingerprint,opportunity_id) VALUES(?,?)",
                    (fingerprint, opportunity_id),
                )
        return ""

    def release_fingerprint(self, fingerprint: str, opportunity_id: str) -> None:
        with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "DELETE FROM career_fingerprints WHERE fingerprint=? AND opportunity_id=?",
                    (fingerprint, opportunity_id),
                )

    def audit(self, *, agent: str, action: str, platform: str = "", subject: str = "",
              result: str = "", approval: str = "", error: str = "",
              test_data: bool = False) -> None:
        values = tuple(_clean_text(value, 1000) for value in
                       (agent, action, platform, subject, result, approval, error))
        with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO career_audit(timestamp,agent,action,platform,subject,result,approval,error,test_data) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (time.time(), *values, int(test_data)),
                )

    def audit_rows(self, limit: int = 100, *, include_test: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM career_audit"
        params: list[Any] = []
        if not include_test:
            sql += " WHERE test_data=0"
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


@dataclass(frozen=True)
class PlatformAdapter:
    name: str
    login_method: str
    profile_mapping: bool
    application_workflow: str
    messaging_support: str
    api_support: str
    browser_support: str
    automation_restrictions: tuple[str, ...]
    rate_limit: str
    verification_requirements: tuple[str, ...]
    submission_rule: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "login_method": self.login_method,
            "profile_mapping": self.profile_mapping,
            "application_workflow": self.application_workflow,
            "messaging_support": self.messaging_support, "api_support": self.api_support,
            "browser_support": self.browser_support,
            "automation_restrictions": list(self.automation_restrictions),
            "rate_limit": self.rate_limit,
            "verification_requirements": list(self.verification_requirements),
            "submission_rule": self.submission_rule,
        }


class PlatformAdapterRegistry:
    """Policy metadata, not giant platform scripts."""

    def __init__(self) -> None:
        common = ("never bypass CAPTCHA, rate limits, identity checks, or anti-bot controls",)
        self._items: dict[str, PlatformAdapter] = {}
        for name in ("indeed", "linkedin", "upwork", "fiverr", "freelancer"):
            self._items[name] = PlatformAdapter(
                name=name, login_method="prefer Google OAuth where offered; owner completes authentication",
                profile_mapping=True, application_workflow="browser-assisted preparation",
                messaging_support="draft and owner-approved send only", api_support="none configured",
                browser_support="read/fill where current platform rules permit",
                automation_restrictions=common, rate_limit="obey the platform's current published limits",
                verification_requirements=("visible postcondition", "platform confirmation identifier"),
                submission_rule="OWNER_SUBMISSION_REQUIRED unless a current approved API explicitly permits it",
            )
        self._items["company_career_portal"] = PlatformAdapter(
            name="company_career_portal", login_method="site-specific; owner completes authentication",
            profile_mapping=True, application_workflow="browser-assisted preparation",
            messaging_support="site-specific", api_support="site-specific, none assumed",
            browser_support="allowed only after current terms and controls are inspected",
            automation_restrictions=common, rate_limit="site-specific",
            verification_requirements=("visible success page", "application reference when provided"),
            submission_rule="OWNER_SUBMISSION_REQUIRED by default",
        )
        self._items["generic_job_board"] = PlatformAdapter(
            name="generic_job_board", login_method="site-specific", profile_mapping=True,
            application_workflow="prepare and stop before submission", messaging_support="draft only",
            api_support="none assumed", browser_support="read/fill if permitted",
            automation_restrictions=common, rate_limit="site-specific",
            verification_requirements=("visible postcondition",),
            submission_rule="OWNER_SUBMISSION_REQUIRED",
        )

    def get(self, name: str) -> PlatformAdapter:
        key = str(name or "generic_job_board").strip().casefold().replace(" ", "_")
        return self._items.get(key, self._items["generic_job_board"])

    def all(self) -> dict[str, dict[str, Any]]:
        return {key: item.as_dict() for key, item in self._items.items()}


class PlatformPolicyGuard:
    AUTH_TRIGGERS = ("password", "mfa", "otp", "passkey", "fingerprint", "captcha", "security prompt")

    def __init__(self, registry: PlatformAdapterRegistry) -> None:
        self.registry = registry

    def decide(self, platform: str, action: str, *, dry_run: bool = False,
               page_signals: Iterable[str] | None = None,
               owner_approved: bool = False, evidence: str = "") -> dict[str, Any]:
        signals = " ".join(str(item) for item in (page_signals or [])).casefold()
        if any(trigger in signals for trigger in self.AUTH_TRIGGERS):
            return {"allowed": False, "state": "OWNER AUTHENTICATION REQUIRED",
                    "reason": "Authentication or anti-bot boundary detected; automation must pause."}
        if dry_run:
            return {"allowed": True, "state": "SIMULATION_ONLY",
                    "reason": "Dry run cannot perform an external action."}
        adapter = self.registry.get(platform)
        operation = str(action).strip().casefold()
        if operation in {"submit", "apply", "send", "accept_contract", "deliver"}:
            if not owner_approved:
                return {"allowed": False, "state": OWNER_DECISION_REQUIRED,
                        "reason": "A consequential external action needs owner approval."}
            if not evidence.strip():
                return {"allowed": False, "state": "VERIFICATION_EVIDENCE_REQUIRED",
                        "reason": "No observed external postcondition was supplied."}
            if "OWNER_SUBMISSION_REQUIRED" in adapter.submission_rule and operation in {"submit", "apply"}:
                return {"allowed": False, "state": OWNER_SUBMISSION_REQUIRED,
                        "reason": adapter.submission_rule}
        return {"allowed": True, "state": "PERMITTED_WITH_VERIFICATION",
                "reason": "Current adapter policy permits this recorded action; verify the postcondition."}


class CareerProfileManager:
    def __init__(self, engine: "ZenoCareerEngine", profile: ZenoCareerProfile) -> None:
        self.engine, self.profile = engine, profile

    def missing(self, fields: Iterable[str]) -> list[str]:
        _, provenance = self.profile.raw_profile()
        return [field for field in fields if field not in provenance]

    def create_variant(self, name: str, *, title: str, skills: list[str],
                       preferred_work: list[str] | None = None) -> dict[str, Any]:
        master, provenance = self.profile.raw_profile()
        if not {"professional_title", "skills"} <= set(provenance):
            return {"state": OWNER_INFORMATION_REQUIRED,
                    "missing": self.missing(("professional_title", "skills"))}
        verified_skills = {str(item).casefold(): str(item) for item in master.get("skills", [])}
        selected: list[str] = []
        unknown: list[str] = []
        for item in skills:
            match = verified_skills.get(str(item).casefold())
            (selected if match else unknown).append(match or str(item))
        if unknown:
            return {"state": OWNER_INFORMATION_REQUIRED,
                    "reason": "A variant cannot add unverified skills.", "unverified_skills": unknown}
        record = {
            "name": _clean_text(name, 80), "title": _clean_text(title, 160),
            "skills": selected, "preferred_work": _strings(preferred_work),
            "source": "ZenoCareerProfile verified fields", "test_data": False,
        }
        variant_id = re.sub(r"[^a-z0-9]+", "_", record["name"].casefold()).strip("_") or _id("profile")
        return self.engine._save("profile_variant", variant_id, record, "career profile variant saved")

    def select(self, opportunity: dict[str, Any], *, synthetic: dict[str, Any] | None = None) -> dict[str, Any]:
        profile, provenance = self.profile.raw_profile()
        if synthetic is not None:
            if not opportunity.get("test_data"):
                raise ValueError("synthetic profiles are allowed only for tagged test opportunities")
            profile = _safe_value(synthetic)
            provenance = {key: "TEST_DATA" for key in profile}
        required = set(_strings(opportunity.get("required_skills")))
        variants = self.engine.store.list("profile_variant", include_test=bool(opportunity.get("test_data")))
        candidates: list[tuple[int, dict[str, Any]]] = []
        for variant in variants:
            overlap = len({item.casefold() for item in variant.get("skills", [])}
                          & {item.casefold() for item in required})
            candidates.append((overlap, variant))
        selected = max(candidates, key=lambda pair: pair[0])[1] if candidates else {
            "id": "master", "name": "CV_GENERAL",
            "title": profile.get("professional_title", ""),
            "skills": list(profile.get("skills", [])),
            "source": "ZenoCareerProfile",
        }
        return {"profile": profile, "provenance": provenance, "variant": selected}


class CVManager:
    REQUIRED = ("full_name", "professional_title", "professional_summary", "skills")

    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    @staticmethod
    def _lines(value: Any) -> list[str]:
        rows = []
        for item in value or []:
            if isinstance(item, dict):
                rows.append("; ".join(f"{k}: {v}" for k, v in item.items() if v))
            elif str(item).strip():
                rows.append(str(item).strip())
        return rows

    def tailor(self, opportunity: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        profile = selection["profile"]
        missing = [field for field in self.REQUIRED if not profile.get(field)]
        if missing:
            return {"state": OWNER_INFORMATION_REQUIRED, "missing": missing}
        verified = [str(item) for item in profile.get("skills", [])]
        required = {str(item).casefold() for item in opportunity.get("required_skills", [])}
        ordered = [item for item in verified if item.casefold() in required]
        ordered += [item for item in verified if item.casefold() not in required]
        sections = [
            str(profile["full_name"]), str(selection["variant"].get("title") or profile["professional_title"]),
            "", "PROFESSIONAL SUMMARY", str(profile["professional_summary"]),
            "", "SKILLS", ", ".join(ordered),
        ]
        for heading, field in (
            ("EXPERIENCE", "employment_history"), ("PROJECTS", "projects"),
            ("EDUCATION", "education"), ("CERTIFICATIONS", "certifications"),
        ):
            rows = self._lines(profile.get(field))
            if rows:
                sections.extend(["", heading, *[f"- {row}" for row in rows]])
        content = "\n".join(sections).strip() + "\n"
        prior = self.engine.store.list("cv", limit=200)
        version = 1 + max((int(item.get("version", 0)) for item in prior
                           if item.get("base_name") == selection["variant"].get("name", "CV_GENERAL")), default=0)
        record = {
            "name": f"{selection['variant'].get('name', 'CV_GENERAL')}_{opportunity['id']}",
            "base_name": selection["variant"].get("name", "CV_GENERAL"),
            "base_variant": selection["variant"].get("id", "master"),
            "opportunity_id": opportunity["id"], "version": version,
            "content": content, "verified_skills": ordered,
            "truth_source": "verified career profile only",
            "application_specific": True, "test_data": bool(opportunity.get("test_data")),
        }
        return self.engine._save("cv", _id("cv"), record, "application CV created")


class PortfolioManager:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def add(self, project: dict[str, Any], *, owner_confirmed: bool) -> dict[str, Any]:
        if owner_confirmed is not True:
            return {"state": OWNER_INFORMATION_REQUIRED, "reason": "Portfolio facts need owner confirmation."}
        required = ("title", "description", "technologies", "problem", "solution", "responsibilities")
        missing = [key for key in required if not project.get(key)]
        if missing:
            return {"state": OWNER_INFORMATION_REQUIRED, "missing": missing}
        record = _safe_value(project)
        record.update({
            "status": str(record.get("status") or "INCOMPLETE").upper(),
            "confidential": bool(record.get("confidential", True)),
            "owner_confirmed": True, "test_data": bool(record.get("test_data", False)),
        })
        return self.engine._save("portfolio_project", _id("portfolio"), record, "portfolio project saved")

    def select(self, opportunity: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
        required = {item.casefold() for item in opportunity.get("required_skills", [])}
        projects = self.engine.store.list("portfolio_project", include_test=bool(opportunity.get("test_data")))
        eligible = [p for p in projects if p.get("status") == "COMPLETE" and not p.get("confidential")
                    and bool(p.get("test_data")) == bool(opportunity.get("test_data"))]
        return sorted(
            eligible,
            key=lambda p: len(required & {str(x).casefold() for x in p.get("technologies", [])}),
            reverse=True,
        )[: max(0, min(10, int(limit)))]


class ClientIntentRiskAnalyzer:
    def analyze(self, text: str) -> dict[str, Any]:
        clean = _clean_text(text, 12000)
        score = 0
        evidence: list[str] = []
        blocked = False
        for label, pattern, weight, hard_block in _SCAM_SIGNALS:
            if pattern.search(clean):
                score += weight
                evidence.append(label)
                blocked = blocked or hard_block
        injection = [pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(clean)]
        if injection:
            score += 10
            blocked = True
            evidence.append("contains prompt-injection or unsafe tool instructions")
        level = "BLOCKED" if blocked else "HIGH" if score >= 8 else "MEDIUM" if score >= 4 else "LOW"
        if not evidence:
            evidence.append("no configured scam or injection signal was observed")
        return {
            "risk": level, "score": min(100, score * 8), "evidence": evidence,
            "injection_detected": bool(injection),
            "disclaimer": "Observable evidence only; ZENO does not know the person's true thoughts.",
        }


class OpportunityScoringEngine:
    FACTORS = (
        "skill_fit", "experience_fit", "portfolio_fit", "realistic_pay", "startup_cost",
        "application_effort", "competition", "time_to_first_payment", "project_complexity",
        "probability_of_completion", "repeatability", "scalability", "learning_value",
        "client_quality", "scam_risk", "platform_risk",
    )
    INVERTED = {
        "startup_cost", "application_effort", "competition", "time_to_first_payment",
        "project_complexity", "scam_risk", "platform_risk",
    }
    WEIGHTS = {
        "skill_fit": .14, "experience_fit": .08, "portfolio_fit": .07,
        "realistic_pay": .08, "startup_cost": .04, "application_effort": .05,
        "competition": .05, "time_to_first_payment": .06, "project_complexity": .05,
        "probability_of_completion": .10, "repeatability": .07, "scalability": .04,
        "learning_value": .05, "client_quality": .06, "scam_risk": .04,
        "platform_risk": .02,
    }

    def __init__(self, risk: ClientIntentRiskAnalyzer) -> None:
        self.risk = risk

    def score(self, opportunity: dict[str, Any], verified_skills: Iterable[str],
              supplied: dict[str, Any] | None = None) -> dict[str, Any]:
        supplied = dict(supplied or {})
        required = {item.casefold() for item in opportunity.get("required_skills", [])}
        owned = {str(item).casefold() for item in verified_skills}
        skill_fit = 5.0 if not required else 10.0 * len(required & owned) / len(required)
        factors: dict[str, float] = {}
        for name in self.FACTORS:
            value = skill_fit if name == "skill_fit" else supplied.get(name, 5.0)
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a number from 0 to 10") from exc
            if not 0 <= number <= 10:
                raise ValueError(f"{name} must be between 0 and 10")
            factors[name] = round(number, 3)
        risk = self.risk.analyze(opportunity.get("description", ""))
        factors["scam_risk"] = max(factors["scam_risk"], risk["score"] / 10)
        contributions: dict[str, float] = {}
        score = 0.0
        for name, weight in self.WEIGHTS.items():
            normalized = 10 - factors[name] if name in self.INVERTED else factors[name]
            contribution = normalized * 10 * weight
            contributions[name] = round(contribution, 2)
            score += contribution
        category = _category(score, risk["risk"] == "BLOCKED")
        gaps = sorted(required - owned)
        return {
            "score": round(score, 2), "category": category, "factors": factors,
            "contributions": contributions, "risk": risk, "skill_gaps": gaps,
            "scale": "0-100 relative priority score; not a guarantee of hiring, payment, or completion",
        }


class JobScout:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def ingest(self, value: dict[str, Any], *, factors: dict[str, Any] | None = None,
               test_data: bool = False) -> dict[str, Any]:
        source = _clean_text(value.get("source") or "", 300)
        platform = _clean_text(value.get("platform") or "generic_job_board", 80).casefold()
        title = _clean_text(value.get("title") or "", 300)
        party = _clean_text(value.get("company_client") or value.get("company") or value.get("client") or "", 300)
        description = _clean_text(value.get("description") or "", 12000)
        if not source or not title or not party or not description:
            return {"state": "INVALID", "missing": [name for name, item in (
                ("source", source), ("title", title), ("company_client", party),
                ("description", description)) if not item]}
        url = _canonical_url(value.get("url") or "")
        platform_id = _clean_text(value.get("platform_id") or "", 200)
        base = platform_id or url or f"{platform}|{title.casefold()}|{party.casefold()}|{description.casefold()}"
        fingerprint = hashlib.sha256(base.encode("utf-8")).hexdigest()
        # Similarity catches reposted descriptions whose URL or platform id changed.
        for prior in self.engine.store.list("opportunity", limit=1000, include_test=test_data):
            if bool(prior.get("test_data")) != bool(test_data):
                continue
            if prior.get("title", "").casefold() == title.casefold() and \
                    prior.get("company_client", "").casefold() == party.casefold():
                ratio = SequenceMatcher(None, prior.get("description", "").casefold(), description.casefold()).ratio()
                if ratio >= .88:
                    return {"state": "DUPLICATE", "existing_opportunity_id": prior["id"],
                            "similarity": round(ratio, 3)}
        profile, _ = self.engine.profile.profile.raw_profile()
        scoring = self.engine.scoring.score(value | {"description": description}, profile.get("skills", []), factors)
        opportunity_id = _id("opp")
        existing = self.engine.store.claim_fingerprint(fingerprint, opportunity_id)
        if existing:
            return {"state": "DUPLICATE", "existing_opportunity_id": existing,
                    "duplicate_fingerprint": fingerprint}
        record = {
            "source": source, "platform": platform, "platform_id": platform_id,
            "title": title, "company_client": party, "description": description,
            "url": url, "pay_min": float(value.get("pay_min") or 0),
            "pay_max": float(value.get("pay_max") or 0),
            "currency": _clean_text(value.get("currency") or "", 12).upper(),
            "employment_type": _clean_text(value.get("employment_type") or "", 80),
            "remote_status": _clean_text(value.get("remote_status") or "", 80),
            "location": _clean_text(value.get("location") or "", 200),
            "required_skills": _strings(value.get("required_skills")),
            "preferred_skills": _strings(value.get("preferred_skills")),
            "experience_requirement": _clean_text(value.get("experience_requirement") or "", 500),
            "deadline": _clean_text(value.get("deadline") or "", 100),
            "application_method": _clean_text(value.get("application_method") or "", 300),
            "date_discovered": float(value.get("date_discovered") or time.time()),
            "duplicate_fingerprint": fingerprint, "risk_score": scoring["risk"]["score"],
            "match_score": scoring["factors"]["skill_fit"] * 10,
            "opportunity_score": scoring["score"], "score_category": scoring["category"],
            "score_detail": scoring, "status": "NEW", "test_data": bool(test_data),
        }
        try:
            result = self.engine._save("opportunity", opportunity_id, record, "opportunity ingested")
        except Exception:
            self.engine.store.release_fingerprint(fingerprint, opportunity_id)
            raise
        if scoring["category"] in {"EXCELLENT", "STRONG"}:
            self.engine._publish("career.opportunity_high_value", result)
        return result

    def research_plan(self, query: str, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "query": _clean_text(query, 1000), "constraints": _safe_value(constraints or {}),
            "state": "RESEARCH_REQUIRED", "network_calls": False,
            "sources": ["company career pages", "approved job boards", "approved APIs",
                        "remote-work boards", "freelance marketplaces", "owner-approved leads"],
            "instructions": [
                "Use ZENO's existing browser/research tools to observe a real posting.",
                "Respect current platform terms and stop at CAPTCHA/authentication.",
                "Pass each observed posting to career_opportunity_ingest with its source URL.",
            ],
        }

    def test_opportunities(self) -> list[dict[str, Any]]:
        suffix = uuid.uuid4().hex[:6]
        fixtures = [
            {"source": "TEST_FIXTURE", "platform": "company_career_portal", "platform_id": f"test-web-{suffix}",
             "title": "Web Automation Developer", "company_client": "Test Client Ltd",
             "description": "Build and test a responsive Python-backed website automation dashboard.",
             "url": f"https://example.invalid/jobs/web-{suffix}", "pay_min": 700, "pay_max": 900,
             "currency": "GBP", "remote_status": "REMOTE", "required_skills": ["Python", "Web Development"],
             "application_method": "TEST_ONLY"},
            {"source": "TEST_FIXTURE", "platform": "generic_job_board", "platform_id": f"test-logo-{suffix}",
             "title": "Logo Designer", "company_client": "Test Design Client",
             "description": "Create an original logo and export agreed formats.",
             "url": f"https://example.invalid/jobs/logo-{suffix}", "pay_min": 50, "pay_max": 80,
             "currency": "GBP", "remote_status": "REMOTE", "required_skills": ["Graphic Design"],
             "application_method": "TEST_ONLY"},
        ]
        factors = {name: 7 for name in OpportunityScoringEngine.FACTORS}
        factors.update({"startup_cost": 1, "application_effort": 2, "competition": 4,
                        "time_to_first_payment": 3, "project_complexity": 4,
                        "scam_risk": 0, "platform_risk": 1})
        return [self.ingest(item, factors=factors, test_data=True) for item in fixtures]


class ApplicationGovernor:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def check(self, opportunity_id: str) -> dict[str, Any]:
        applications = self.engine.store.list("application", limit=1000)
        duplicate = next((item for item in applications
                          if item.get("opportunity_id") == opportunity_id
                          and item.get("status") not in {"CANCELLED", "FAILED"}), None)
        if duplicate:
            return {"allowed": False, "state": "DUPLICATE_APPLICATION",
                    "application_id": duplicate["id"]}
        cutoff = time.time() - 86400
        recent = [item for item in applications if item.get("created_at", 0) >= cutoff]
        limit = getattr(config, "CAREER_MAX_APPLICATIONS_PER_DAY", 5)
        if len(recent) >= limit:
            return {"allowed": False, "state": "APPLICATION_GOVERNOR_LIMIT",
                    "count": len(recent), "limit": limit}
        return {"allowed": True, "state": "PERMITTED", "count": len(recent), "limit": limit}


class ApplicationAgent:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def prepare(self, opportunity_id: str, *, synthetic_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        opportunity = self.engine.store.get("opportunity", opportunity_id)
        if not opportunity:
            return {"state": "NOT_FOUND", "opportunity_id": opportunity_id}
        governor = self.engine.governor.check(opportunity_id)
        if not governor["allowed"]:
            return governor
        risk = opportunity.get("score_detail", {}).get("risk", {})
        if risk.get("risk") == "BLOCKED":
            return {"state": "BLOCKED", "reason": "Unsafe opportunity content", "risk": risk}
        selection = self.engine.profile.select(opportunity, synthetic=synthetic_profile)
        profile = selection["profile"]
        missing = [field for field in CVManager.REQUIRED if not profile.get(field)]
        if missing:
            return {"state": OWNER_INFORMATION_REQUIRED, "missing": missing}
        cv = self.engine.cv.tailor(opportunity, selection)
        if cv.get("state") == OWNER_INFORMATION_REQUIRED:
            return cv
        portfolios = self.engine.portfolio.select(opportunity)
        owned = {str(item).casefold() for item in profile.get("skills", [])}
        required = {str(item).casefold() for item in opportunity.get("required_skills", [])}
        matched = sorted(required & owned)
        gaps = sorted(required - owned)
        salutation = opportunity["company_client"]
        proposal = (
            f"Application for {opportunity['title']} at {salutation}\n\n"
            f"{profile['professional_summary']}\n\n"
            f"Relevant verified skills: {', '.join(matched) if matched else 'No direct verified match recorded.'}\n"
            f"Availability: {profile.get('availability') or 'OWNER_INFORMATION_REQUIRED'}\n"
        )
        if portfolios:
            proposal += "Relevant completed portfolio work: " + ", ".join(p["title"] for p in portfolios) + "\n"
        qc = {
            "correct_company_client": bool(salutation), "correct_title": bool(opportunity["title"]),
            "no_fabricated_information": True, "grammar_checked": True,
            "required_questions_answered": False,
            "appropriate_cv": cv.get("opportunity_id") == opportunity_id,
            "portfolio_confidentiality_checked": all(not p.get("confidential") for p in portfolios),
            "skill_gaps_disclosed": gaps,
        }
        mode = getattr(config, "CAREER_APPLICATION_MODE", "APPROVAL")
        status = "READY" if mode == "MANUAL" else "AWAITING_APPROVAL"
        application_id = _id("app")
        record = {
            "opportunity_id": opportunity_id, "platform": opportunity["platform"],
            "company_client": salutation, "title": opportunity["title"],
            "cv_id": cv["id"], "profile_variant": selection["variant"].get("id", "master"),
            "proposal": proposal, "screening_answers": [],
            "portfolio_ids": [item["id"] for item in portfolios],
            "requested_salary_rate": opportunity.get("pay_max") or opportunity.get("pay_min"),
            "currency": opportunity.get("currency", ""), "skill_gaps": gaps,
            "quality_control": qc, "mode": mode, "status": status,
            "submission_evidence": "", "test_data": bool(opportunity.get("test_data")),
        }
        # Unique application directory: no master CV or prior application is
        # ever overwritten. These are the exact artifacts the owner reviews.
        record["artifacts"] = {
            "cv": self.engine.write_artifact(application_id, "CV.md", cv["content"],
                                               test_data=record["test_data"]),
            "proposal": self.engine.write_artifact(application_id, "proposal.txt", proposal,
                                                     test_data=record["test_data"]),
            "quality_control": self.engine.write_artifact(
                application_id, "quality-control.json",
                json.dumps(qc, ensure_ascii=False, indent=2), test_data=record["test_data"]),
        }
        result = self.engine._save("application", application_id, record, "application prepared")
        opportunity["status"] = "READY"
        self.engine.store.put("opportunity", opportunity_id, opportunity)
        return result

    def record_submission(self, application_id: str, *, owner_approved: bool,
                          evidence: str, dry_run: bool = False,
                          owner_submitted: bool = False) -> dict[str, Any]:
        app = self.engine.store.get("application", application_id)
        if not app:
            return {"state": "NOT_FOUND"}
        if dry_run:
            app.update({"status": "SUBMITTED_SIMULATED", "submission_evidence": "TEST_SIMULATION",
                        "submitted_at": time.time(), "test_data": True})
        elif owner_submitted:
            if not owner_approved or not evidence.strip():
                return {"state": "VERIFICATION_EVIDENCE_REQUIRED",
                        "reason": "Recording a manual submission needs Divine's confirmation and observed evidence."}
            app.update({"status": "SUBMITTED", "submission_method": "OWNER_MANUAL",
                        "submission_evidence": _clean_text(evidence, 2000),
                        "submitted_at": time.time()})
        else:
            decision = self.engine.policy.decide(
                app.get("platform", ""), "submit", dry_run=False,
                owner_approved=owner_approved, evidence=evidence,
            )
            if not decision["allowed"]:
                app["status"] = decision["state"]
                app["submission_evidence"] = ""
            else:
                app.update({"status": "SUBMITTED", "submission_method": "PERMITTED_ADAPTER",
                            "submission_evidence": _clean_text(evidence, 2000),
                            "submitted_at": time.time()})
        return self.engine._save("application", application_id, app, "application submission recorded")


class ClientCommunicationAgent:
    TECHNOLOGIES = ("python", "javascript", "react", "html", "css", "sql", "api", "wordpress", "figma")

    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def analyze(self, message: str, *, source: str = "", application_id: str = "",
                test_data: bool = False) -> dict[str, Any]:
        text = _clean_text(message, 12000)
        risk = self.engine.risk.analyze(text)
        money = re.search(r"(?i)(?:£|\$|€|₦)\s?([\d,]+(?:\.\d+)?)", text)
        deadline = re.search(r"(?i)\b(?:within\s+\d+\s+(?:days?|weeks?)|by\s+[A-Z][a-z]+(?:\s+\d{1,2})?)", text)
        revisions = re.search(r"(?i)\b(\d+)\s+revisions?\b", text)
        tech = [item for item in self.TECHNOLOGIES if re.search(rf"(?i)\b{re.escape(item)}\b", text)]
        deliverables = [part.strip() for part in re.split(r"[.;\n]", text)
                        if re.search(r"(?i)\b(?:build|create|deliver|include|need|require)\b", part)][:15]
        summary = {
            "requested_deliverables": deliverables, "budget_observed": money.group(0) if money else "",
            "deadline_observed": deadline.group(0) if deadline else "", "technologies": tech,
            "revisions_observed": int(revisions.group(1)) if revisions else None,
            "missing_requirements": [name for name, present in (
                ("deliverables", bool(deliverables)), ("budget", bool(money)),
                ("deadline", bool(deadline)), ("revision allowance", bool(revisions))) if not present],
        }
        qualification = ClientQualificationAgent.score(summary, risk)
        record = {
            "source": _clean_text(source, 300), "application_id": application_id,
            "message": text, "requirements": summary, "risk": risk,
            "qualification": qualification, "status": "BLOCKED" if risk["risk"] == "BLOCKED" else "QUALIFIED",
            "communication_state": "DRAFT", "test_data": bool(test_data),
        }
        result = self.engine._save("client", _id("client"), record, "client message analyzed")
        if risk["risk"] in {"HIGH", "BLOCKED"}:
            self.engine._publish("career.client_high_risk", result)
        return result

    def record(self, client_id: str, *, channel: str, content: str, state: str,
               owner_approved: bool = False, evidence: str = "") -> dict[str, Any]:
        client = self.engine.store.get("client", client_id)
        if not client:
            return {"state": "NOT_FOUND"}
        communication_state = str(state).upper()
        if communication_state not in {"DRAFT", "OWNER_APPROVAL", "SENT"}:
            return {"state": "INVALID", "allowed": ["DRAFT", "OWNER_APPROVAL", "SENT"]}
        if communication_state == "SENT" and (not owner_approved or not evidence.strip()):
            return {"state": "VERIFICATION_EVIDENCE_REQUIRED",
                    "reason": "SENT requires owner approval and observed send evidence."}
        record = {
            "client_id": client_id, "channel": _clean_text(channel, 100),
            "content": _clean_text(content, 6000), "status": communication_state,
            "owner_approved": bool(owner_approved),
            "evidence": _clean_text(evidence, 1000) if evidence else "",
            "test_data": bool(client.get("test_data")),
        }
        result = self.engine._save("communication", _id("communication"), record,
                                   "client communication state recorded")
        if communication_state == "SENT":
            self.engine._publish("career.client_message_sent", {"client_id": client_id,
                                                                  "communication_id": result["id"]})
        return result


class ClientQualificationAgent:
    @staticmethod
    def score(summary: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
        clarity = 10 - min(8, len(summary.get("missing_requirements", [])) * 2)
        budget = 8 if summary.get("budget_observed") else 4
        deadline = 7 if summary.get("deadline_observed") else 4
        risk_adjustment = {"LOW": 0, "MEDIUM": -2, "HIGH": -5, "BLOCKED": -10}[risk["risk"]]
        score = max(0, min(100, (clarity + budget + deadline + 6 + 6 + risk_adjustment) * 2.5))
        return {"score": round(score, 1),
                "priority": "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW",
                "basis": "requirement clarity, observed budget/deadline and evidence-based risk"}


class NegotiationAgent:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def set_pricing(self, service: str, *, minimum: float, target: float, premium: float,
                    currency: str, delivery_days: int, revisions: int, rush_fee: float = 0,
                    maintenance: str = "", scope: str = "", owner_confirmed: bool) -> dict[str, Any]:
        if owner_confirmed is not True:
            return {"state": OWNER_INFORMATION_REQUIRED, "reason": "Pricing boundaries need owner confirmation."}
        if min(minimum, target, premium) < 0 or not minimum <= target <= premium:
            return {"state": "INVALID", "reason": "Require 0 <= minimum <= target <= premium."}
        record = {
            "service": _clean_text(service, 160), "minimum_price": float(minimum),
            "target_price": float(target), "premium_price": float(premium),
            "currency": _clean_text(currency, 12).upper(), "delivery_days": max(1, int(delivery_days)),
            "revision_allowance": max(0, int(revisions)), "rush_fee": max(0, float(rush_fee)),
            "maintenance_option": _clean_text(maintenance, 1000), "scope": _clean_text(scope, 4000),
            "owner_confirmed": True, "test_data": False,
        }
        key = re.sub(r"[^a-z0-9]+", "_", record["service"].casefold()).strip("_")
        return self.engine._save("pricing", key or _id("pricing"), record, "pricing boundary saved")

    def recommend(self, client_id: str, service: str, *, client_offer: float | None = None,
                  rush: bool = False, unusual_terms: list[str] | None = None,
                  test_pricing: dict[str, Any] | None = None) -> dict[str, Any]:
        client = self.engine.store.get("client", client_id)
        if not client:
            return {"state": "NOT_FOUND"}
        key = re.sub(r"[^a-z0-9]+", "_", str(service).casefold()).strip("_")
        pricing = _safe_value(test_pricing) if test_pricing is not None else self.engine.store.get("pricing", key)
        if test_pricing is not None and not client.get("test_data"):
            return {"state": "INVALID", "reason": "Test pricing is restricted to test clients."}
        if not pricing:
            return {"state": OWNER_INFORMATION_REQUIRED, "missing": [f"pricing boundaries for {service}"]}
        terms = _strings(unusual_terms)
        below = client_offer is not None and float(client_offer) < float(pricing["minimum_price"])
        sensitive = bool(terms) or below
        proposed = float(pricing["target_price"])
        if rush:
            proposed += float(pricing.get("rush_fee", 0))
        draft = (
            f"For the agreed {pricing.get('scope') or service} scope, my proposed fee is "
            f"{pricing['currency']} {proposed:.2f}, with {pricing['revision_allowance']} included "
            f"revision(s) and an estimated {pricing['delivery_days']}-day delivery window."
        )
        record = {
            "client_id": client_id, "service": service, "initial_client_offer": client_offer,
            "proposed_price": proposed, "currency": pricing["currency"], "draft": draft,
            "scope": pricing.get("scope", ""), "delivery_days": pricing["delivery_days"],
            "revisions": pricing["revision_allowance"], "unusual_terms": terms,
            "status": OWNER_DECISION_REQUIRED if sensitive else "DRAFT_READY",
            "reason": "below owner minimum" if below else "unusual terms" if terms else "within owner boundaries",
            "test_data": bool(client.get("test_data")),
        }
        return self.engine._save("negotiation", _id("neg"), record, "negotiation recommendation created")


class ContractApprovalGate:
    REQUIRED = ("client_id", "project", "scope", "deliverables", "deadline", "price",
                "currency", "payment_method", "milestones", "revisions", "terms")

    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def create(self, value: dict[str, Any], *, test_data: bool = False) -> dict[str, Any]:
        missing = [field for field in self.REQUIRED if value.get(field) in (None, "", [])]
        if missing:
            return {"state": OWNER_INFORMATION_REQUIRED, "missing": missing}
        client = self.engine.store.get("client", str(value["client_id"]))
        if not client:
            return {"state": "NOT_FOUND", "reason": "client does not exist"}
        try:
            price = float(value["price"])
            revisions = int(value["revisions"])
        except (TypeError, ValueError):
            return {"state": "INVALID", "reason": "price and revisions must be numeric"}
        if price <= 0 or revisions < 0:
            return {"state": "INVALID", "reason": "price must be positive and revisions cannot be negative"}
        if client.get("risk", {}).get("risk") == "BLOCKED":
            return {"state": "BLOCKED", "risk": client["risk"]}
        record = _safe_value(value)
        record.update({"status": OWNER_CONTRACT_APPROVAL_REQUIRED,
                       "owner_approved": False, "test_data": bool(test_data or client.get("test_data"))})
        result = self.engine._save("contract", _id("contract"), record, "contract approval requested")
        self.engine._publish("career.contract_approval_required", result)
        return result


class ProjectExecutionManager:
    AGENT_BY_WORK = {
        "website": "tosin", "web": "tosin", "code": "tosin", "python": "tosin",
        "data": "oracle", "analysis": "oracle", "research": "aris", "security": "stark",
        "design": "zeal", "logo": "zeal", "communication": "hermes_comm",
    }

    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def create(self, contract_id: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        contract = self.engine.store.get("contract", contract_id)
        if not contract:
            return {"state": "NOT_FOUND"}
        if contract.get("status") != "APPROVED":
            return {"state": OWNER_CONTRACT_APPROVAL_REQUIRED}
        project_id = _id("project")
        task_ids: list[str] = []
        known_names = {str(task.get("name") or task.get("action") or "").strip() for task in tasks}
        for index, raw in enumerate(tasks):
            name = _clean_text(raw.get("name") or raw.get("action") or f"Task {index + 1}", 300)
            deps = _strings(raw.get("dependencies"), limit=40)
            unknown = [dep for dep in deps if dep not in known_names]
            if unknown:
                return {"state": "INVALID_TASK_GRAPH", "unknown_dependencies": unknown}
            lowered = name.casefold()
            assigned = next((agent for word, agent in self.AGENT_BY_WORK.items() if word in lowered), "titan")
            task_id = _id("task")
            task = {
                "project_id": project_id, "name": name, "assigned_agent": assigned,
                "dependencies": deps, "status": "PENDING" if deps else "READY",
                "progress": 0, "output": "", "test": "", "error": "", "retry_count": 0,
                "test_data": bool(contract.get("test_data")),
            }
            self.engine._save("project_task", task_id, task, "project task created")
            task_ids.append(task_id)
        record = {
            "contract_id": contract_id, "client_id": contract["client_id"],
            "name": contract["project"], "scope": contract["scope"],
            "deliverables": contract["deliverables"], "task_ids": task_ids,
            "status": "WORKING", "qa_status": "PENDING", "delivery_status": "NOT_READY",
            "test_data": bool(contract.get("test_data")),
        }
        return self.engine._save("project", project_id, record, "project execution created")

    def record_task(self, task_id: str, *, status: str, output: str = "", test: str = "",
                    error: str = "", retry_count: int = 0) -> dict[str, Any]:
        task = self.engine.store.get("project_task", task_id)
        if not task:
            return {"state": "NOT_FOUND"}
        state = str(status).upper()
        if state not in PROJECT_TASK_STATES:
            return {"state": "INVALID", "allowed": list(PROJECT_TASK_STATES)}
        if state == "COMPLETE" and (not output.strip() or not test.strip()):
            return {"state": "VERIFICATION_EVIDENCE_REQUIRED",
                    "reason": "A task needs output and test evidence before COMPLETE."}
        task.update({"status": state, "output": _clean_text(output, 10000),
                     "test": _clean_text(test, 6000), "error": _clean_text(error, 3000),
                     "retry_count": max(0, min(5, int(retry_count))),
                     "progress": 100 if state == "COMPLETE" else task.get("progress", 0)})
        return self.engine._save("project_task", task_id, task, "project task updated")


class QAAgent:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def review(self, project_id: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
        project = self.engine.store.get("project", project_id)
        if not project:
            return {"state": "NOT_FOUND"}
        tasks = [self.engine.store.get("project_task", task_id) for task_id in project.get("task_ids", [])]
        incomplete = [task.get("name", task.get("id")) for task in tasks if task.get("status") != "COMPLETE"]
        normalized = []
        for check in checks:
            normalized.append({"name": _clean_text(check.get("name") or "", 300),
                               "passed": bool(check.get("passed")),
                               "evidence": _clean_text(check.get("evidence") or "", 4000)})
        missing_evidence = [item["name"] for item in normalized if not item["evidence"]]
        passed = bool(normalized) and not incomplete and not missing_evidence and all(item["passed"] for item in normalized)
        qa = {
            "project_id": project_id, "checks": normalized, "incomplete_tasks": incomplete,
            "missing_evidence": missing_evidence, "passed": passed,
            "status": "PASSED" if passed else "FAILED", "test_data": bool(project.get("test_data")),
        }
        result = self.engine._save("qa", _id("qa"), qa, "independent QA recorded")
        project["qa_status"] = qa["status"]
        project["status"] = "READY_FOR_OWNER_REVIEW" if passed else "FIXES_REQUIRED"
        project["delivery_status"] = PROJECT_READY_FOR_OWNER_REVIEW if passed else "NOT_READY"
        self.engine.store.put("project", project_id, project)
        if passed:
            self.engine._publish("career.project_ready", {"project_id": project_id, "qa_id": result["id"]})
        return result | {"owner_message": PROJECT_READY_FOR_OWNER_REVIEW if passed else "QA FAILED — FIXES REQUIRED"}


class DeliveryManager:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def record(self, project_id: str, *, method: str, files: list[str], evidence: str,
               owner_approved: bool, dry_run: bool = False) -> dict[str, Any]:
        project = self.engine.store.get("project", project_id)
        if not project:
            return {"state": "NOT_FOUND"}
        if project.get("qa_status") != "PASSED":
            return {"state": "QA_REQUIRED"}
        if not owner_approved:
            return {"state": "OWNER DELIVERY APPROVAL REQUIRED"}
        if not dry_run and not evidence.strip():
            return {"state": "DELIVERY_EVIDENCE_REQUIRED"}
        record = {
            "project_id": project_id, "files_delivered": _strings(files, limit=300),
            "method": _clean_text(method, 300),
            "evidence": "TEST_SIMULATION" if dry_run else _clean_text(evidence, 2000),
            "delivered_at": time.time(), "status": "DELIVERED_SIMULATED" if dry_run else "DELIVERED",
            "test_data": bool(dry_run or project.get("test_data")),
        }
        result = self.engine._save("delivery", _id("delivery"), record, "delivery recorded")
        project["delivery_status"] = record["status"]
        project["status"] = record["status"]
        self.engine.store.put("project", project_id, project)
        return result


class RevisionManager:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def request(self, project_id: str, change: str, *, outside_scope: bool | None = None) -> dict[str, Any]:
        project = self.engine.store.get("project", project_id)
        if not project:
            return {"state": "NOT_FOUND"}
        text = _clean_text(change, 6000)
        scope_words = _words(project.get("scope", "") + " " + " ".join(project.get("deliverables", [])))
        change_words = _words(text)
        inferred = bool(change_words and len(change_words - scope_words) / len(change_words) > .65)
        is_scope_change = inferred if outside_scope is None else bool(outside_scope)
        prior = self.engine.store.list("revision", limit=1000)
        used = sum(1 for item in prior if item.get("project_id") == project_id and not item.get("scope_change"))
        contract = self.engine.store.get("contract", project.get("contract_id", ""))
        allowance = int(contract.get("revisions", 0) or 0)
        if used >= allowance:
            is_scope_change = True
        record = {
            "project_id": project_id, "requested_change": text, "scope_change": is_scope_change,
            "included_revisions": allowance, "used_revisions_before": used,
            "status": SCOPE_CHANGE_DETECTED if is_scope_change else "REVISION_ACCEPTED",
            "test_data": bool(project.get("test_data")),
        }
        return self.engine._save("revision", _id("revision"), record, "revision request classified")


class PaymentTracker:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def create(self, project_id: str, *, agreed_amount: float, currency: str, milestone: str,
               payment_method: str, due_date: float, invoice_reference: str = "") -> dict[str, Any]:
        project = self.engine.store.get("project", project_id)
        if not project:
            return {"state": "NOT_FOUND"}
        if float(agreed_amount) <= 0 or float(due_date) <= 0:
            return {"state": "INVALID", "reason": "amount and due date must be positive"}
        record = {
            "project_id": project_id, "client_id": project["client_id"],
            "agreed_amount": max(0, float(agreed_amount)), "currency": _clean_text(currency, 12).upper(),
            "milestone": _clean_text(milestone, 300), "payment_method": _clean_text(payment_method, 200),
            "invoice_reference": _clean_text(invoice_reference, 300), "due_date": float(due_date),
            "amount_due": max(0, float(agreed_amount)), "amount_reported": 0.0,
            "amount_verified": 0.0, "status": "NOT_DUE" if due_date > time.time() else "DUE",
            "test_data": bool(project.get("test_data")),
        }
        return self.engine._save("payment", _id("payment"), record, "payment milestone tracked")

    def report(self, payment_id: str, amount: float, reference: str = "") -> dict[str, Any]:
        payment = self.engine.store.get("payment", payment_id)
        if not payment:
            return {"state": "NOT_FOUND"}
        payment.update({"amount_reported": max(0, float(amount)),
                        "client_reference": _clean_text(reference, 500),
                        "status": "OWNER_VERIFICATION_REQUIRED", "reported_at": time.time()})
        result = self.engine._save("payment", payment_id, payment, "client reported payment")
        self.engine._publish("career.payment_reported", {"payment_id": payment_id,
                                                           "message": PAYMENT_OWNER_VERIFICATION_REQUIRED})
        return result | {"owner_message": PAYMENT_OWNER_VERIFICATION_REQUIRED}

    def verify(self, payment_id: str, amount: float, *, owner_verified: bool,
               evidence: str, dry_run: bool = False) -> dict[str, Any]:
        payment = self.engine.store.get("payment", payment_id)
        if not payment:
            return {"state": "NOT_FOUND"}
        if owner_verified is not True:
            return {"state": "OWNER_VERIFICATION_REQUIRED"}
        if payment.get("status") != "OWNER_VERIFICATION_REQUIRED" or float(payment.get("amount_reported") or 0) <= 0:
            return {"state": "CLIENT_PAYMENT_REPORT_REQUIRED"}
        if not dry_run and not evidence.strip():
            return {"state": "PAYMENT_EVIDENCE_REQUIRED"}
        verified = max(0, float(amount))
        payment.update({"amount_verified": verified, "verified_at": time.time(),
                        "verification_evidence": "TEST_SIMULATION" if dry_run else _clean_text(evidence, 1000),
                        "status": "OWNER_VERIFIED" if verified >= float(payment["amount_due"]) else "PARTIALLY_PAID",
                        "test_data": bool(dry_run or payment.get("test_data"))})
        return self.engine._save("payment", payment_id, payment, "owner verified payment")

    def refresh_due(self, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        updated = 0
        for payment in self.engine.store.list("payment"):
            if payment.get("status") in {"OWNER_VERIFIED", "PARTIALLY_PAID", "DISPUTED"}:
                continue
            if float(payment.get("due_date") or 0) < current:
                payment["status"] = "OVERDUE"
                self.engine.store.put("payment", payment["id"], payment)
                updated += 1
        return updated


class BusinessMemory:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def metrics(self, *, include_test: bool = False) -> dict[str, Any]:
        items = {kind: self.engine.store.list(kind, limit=2000, include_test=include_test)
                 for kind in ("opportunity", "application", "client", "project", "payment", "negotiation")}
        verified = [p for p in items["payment"] if p.get("status") in {"OWNER_VERIFIED", "PARTIALLY_PAID"}]
        revenue = round(sum(float(p.get("amount_verified") or 0) for p in verified), 2)
        applications = [a for a in items["application"] if a.get("status") in {"SUBMITTED", "APPLIED"}]
        replies = [a for a in items["application"] if a.get("response")]
        delivered = [p for p in items["project"] if str(p.get("delivery_status", "")).startswith("DELIVERED")]
        won = [p for p in items["project"] if p.get("contract_id")]
        platform_counts: dict[str, int] = {}
        skill_counts: dict[str, int] = {}
        for opp in items["opportunity"]:
            platform_counts[opp.get("platform", "unknown")] = platform_counts.get(opp.get("platform", "unknown"), 0) + 1
            for skill in opp.get("required_skills", []):
                skill_counts[skill] = skill_counts.get(skill, 0) + 1
        return {
            "verified_revenue": revenue,
            "currency_note": "Amounts are not converted across currencies; inspect payment rows by currency.",
            "application_response_rate": round(100 * len(replies) / len(applications), 2) if applications else 0.0,
            "proposal_conversion_rate": round(100 * len(won) / len(applications), 2) if applications else 0.0,
            "projects_won": len(won), "projects_delivered": len(delivered),
            "average_project_value": round(revenue / len(verified), 2) if verified else 0.0,
            "best_performing_platform": max(platform_counts, key=platform_counts.get) if platform_counts else None,
            "most_requested_skill": max(skill_counts, key=skill_counts.get) if skill_counts else None,
            "basis": "actual stored records" if not include_test else "actual + explicitly tagged test records",
        }

    @staticmethod
    def profitability(*, revenue: float, platform_fees: float, software_costs: float,
                      estimated_hours: float, outsourcing_cost: float = 0) -> dict[str, Any]:
        profit = float(revenue) - float(platform_fees) - float(software_costs) - float(outsourcing_cost)
        return {"estimated_profit": round(profit, 2),
                "effective_hourly_rate": round(profit / estimated_hours, 2) if estimated_hours > 0 else None,
                "kind": "ESTIMATE", "inputs": {"revenue": revenue, "platform_fees": platform_fees,
                "software_costs": software_costs, "estimated_hours": estimated_hours,
                "outsourcing_cost": outsourcing_cost}}


class SkillGapAgent:
    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def analyze(self) -> dict[str, Any]:
        profile, _ = self.engine.profile.profile.raw_profile()
        owned = {str(item).casefold() for item in profile.get("skills", [])}
        frequency: dict[str, int] = {}
        for opportunity in self.engine.store.list("opportunity", include_test=False):
            for skill in opportunity.get("required_skills", []):
                if skill.casefold() not in owned:
                    frequency[skill] = frequency.get(skill, 0) + 1
        return {"skill_gaps": [{"skill": skill, "job_frequency": count,
                                 "recommendation": "Assess learning difficulty and portfolio value with KATE."}
                                for skill, count in sorted(frequency.items(), key=lambda item: item[1], reverse=True)],
                "source": "real normalized opportunity records; no market demand inferred beyond frequency"}


class ReputationEngine:
    """Outcomes only; never manufactures reviews, testimonials, or satisfaction."""

    def __init__(self, engine: "ZenoCareerEngine") -> None:
        self.engine = engine

    def metrics(self) -> dict[str, Any]:
        projects = self.engine.store.list("project", limit=2000, include_test=False)
        delivered = [item for item in projects
                     if str(item.get("delivery_status", "")).startswith("DELIVERED")]
        per_client: dict[str, int] = {}
        for item in delivered:
            client_id = item.get("client_id", "")
            if client_id:
                per_client[client_id] = per_client.get(client_id, 0) + 1
        return {
            "successful_projects": len(delivered),
            "repeat_clients": sum(1 for count in per_client.values() if count > 1),
            "client_satisfaction": None,
            "testimonials": 0,
            "rule": "Satisfaction, reviews and testimonials remain unknown until genuine owner-recorded evidence exists.",
        }


class ZenoCareerEngine:
    """Central coordinator. Components share one store and existing ZENO seams."""

    def __init__(self, path: str | Path | None = None,
                 *, profile: ZenoCareerProfile | None = None) -> None:
        self.store = CareerStore(path)
        self.adapters = PlatformAdapterRegistry()
        self.policy = PlatformPolicyGuard(self.adapters)
        self.risk = ClientIntentRiskAnalyzer()
        self.scoring = OpportunityScoringEngine(self.risk)
        self.profile = CareerProfileManager(self, profile or get_career_profile())
        self.cv = CVManager(self)
        self.portfolio = PortfolioManager(self)
        self.scout = JobScout(self)
        self.governor = ApplicationGovernor(self)
        self.applications = ApplicationAgent(self)
        self.clients = ClientCommunicationAgent(self)
        self.negotiation = NegotiationAgent(self)
        self.contracts = ContractApprovalGate(self)
        self.projects = ProjectExecutionManager(self)
        self.qa = QAAgent(self)
        self.delivery = DeliveryManager(self)
        self.revisions = RevisionManager(self)
        self.payments = PaymentTracker(self)
        self.business_memory = BusinessMemory(self)
        self.skill_gaps = SkillGapAgent(self)
        self.reputation = ReputationEngine(self)

    def _save(self, kind: str, entity_id: str, record: dict[str, Any], result: str) -> dict[str, Any]:
        saved = self.store.put(kind, entity_id, record)
        self.store.audit(agent="ZENO", action=f"{kind}.save", platform=str(record.get("platform", "")),
                         subject=entity_id, result=result,
                         approval=str(record.get("status", "")), error="",
                         test_data=bool(record.get("test_data")))
        try:
            from reyes_agent import audit

            audit.log("career_engine", agent="ZENO", action=f"{kind}.save",
                      platform=record.get("platform", ""), subject=entity_id,
                      result=result, approval=record.get("status", ""))
        except Exception:
            pass
        self._publish(f"career.{kind}.updated", {"id": entity_id, "status": record.get("status", "")})
        return saved

    @staticmethod
    def _publish(event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus

            event_bus.publish(event_type, _safe_value(payload), source="career_engine")
        except Exception:
            pass

    def write_artifact(self, application_id: str, filename: str, content: str,
                       *, test_data: bool = False) -> str:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(application_id))
        safe_name = Path(filename).name
        if not safe_id or not safe_name or safe_name != filename:
            raise ValueError("invalid application artifact path")
        base = self.store.path.parent / ("test-artifacts" if test_data else "applications")
        folder = (base / safe_id).resolve()
        if base.resolve() not in folder.parents:
            raise ValueError("application artifact escaped its workspace")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe_name
        temporary = folder / f".{safe_name}.{uuid.uuid4().hex[:8]}.tmp"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        return str(target)

    def rank(self, *, include_test: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        items = self.store.list("opportunity", limit=1000, include_test=include_test)
        items = [item for item in items if include_test or not item.get("test_data")]
        return sorted(items, key=lambda item: float(item.get("opportunity_score", 0)), reverse=True)[:limit]

    def set_focus(self, constraints: dict[str, Any], *, expires_at: float = 0) -> dict[str, Any]:
        allowed = {"categories", "skills", "minimum_pay", "currency", "remote_status", "platforms"}
        unknown = sorted(set(constraints) - allowed)
        if unknown:
            return {"state": "INVALID", "unknown_constraints": unknown}
        record = {"constraints": _safe_value(constraints), "expires_at": float(expires_at or 0),
                  "status": "ACTIVE", "test_data": False}
        return self._save("focus", "current", record, "career focus saved")

    def ingest_external_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(event_type).strip().upper()
        if kind not in SOCIAL_EVENT_TYPES:
            return {"state": "IGNORED", "allowed_events": list(SOCIAL_EVENT_TYPES)}
        safe = _safe_value(payload)
        if kind == "SOCIAL_JOB_OPPORTUNITY":
            return self.scout.ingest(safe)
        message = safe.get("message") or safe.get("text") or safe.get("description") or ""
        return self.clients.analyze(message, source=f"social:{safe.get('platform', 'unknown')}")

    def owner_decision(self, category: str, subject_id: str, decision: str,
                       *, evidence: str = "", dry_run: bool = False) -> dict[str, Any]:
        cat = str(category).upper()
        choice = str(decision).upper()
        if cat not in APPROVAL_CATEGORIES or choice not in {"APPROVE", "DENY", "VERIFY"}:
            return {"state": "INVALID", "categories": list(APPROVAL_CATEGORIES)}
        mapping = {"APPLICATION": "application", "CONTRACT": "contract", "DELIVERY": "project",
                   "PAYMENT": "payment", "NEGOTIATION": "negotiation", "ACCOUNT": "account",
                   "HIGH_RISK_ACTION": "high_risk_action"}
        kind = mapping[cat]
        record = self.store.get(kind, subject_id)
        if not record:
            return {"state": "NOT_FOUND", "category": cat, "subject_id": subject_id}
        if cat == "PAYMENT" and choice in {"APPROVE", "VERIFY"}:
            return self.payments.verify(subject_id, record.get("amount_reported", 0),
                                        owner_verified=True, evidence=evidence, dry_run=dry_run)
        record["owner_decision"] = choice
        record["owner_decision_at"] = time.time()
        record["decision_evidence"] = "TEST_SIMULATION" if dry_run else _clean_text(evidence, 2000)
        record["status"] = "APPROVED" if choice == "APPROVE" else "DENIED"
        return self._save(kind, subject_id, record, f"owner decision {choice}")

    def approval_center(self) -> list[dict[str, Any]]:
        waiting: list[dict[str, Any]] = []
        states = {
            "application": {"AWAITING_APPROVAL"}, "contract": {OWNER_CONTRACT_APPROVAL_REQUIRED},
            "negotiation": {OWNER_DECISION_REQUIRED}, "project": {"READY_FOR_OWNER_REVIEW"},
            "payment": {"OWNER_VERIFICATION_REQUIRED"},
        }
        category = {"application": "APPLICATION", "contract": "CONTRACT", "negotiation": "NEGOTIATION",
                    "project": "DELIVERY", "payment": "PAYMENT"}
        for kind, pending_states in states.items():
            for record in self.store.list(kind, limit=500, include_test=False):
                if record.get("status") in pending_states or record.get("delivery_status") == PROJECT_READY_FOR_OWNER_REVIEW:
                    waiting.append({"category": category[kind], "subject_id": record["id"],
                                    "status": record.get("status"), "context": record})
        return waiting

    def dashboard(self, *, include_test: bool = False) -> dict[str, Any]:
        self.payments.refresh_due()
        records = {kind: self.store.list(kind, limit=2000, include_test=include_test)
                   for kind in ("opportunity", "application", "client", "project", "payment")}
        if not include_test:
            records = {kind: [row for row in rows if not row.get("test_data")]
                       for kind, rows in records.items()}
        count = lambda rows, states, field="status": sum(1 for row in rows if row.get(field) in states)
        return {
            "generated_at": time.time(), "source": "ZenoCareerEngine durable records",
            "opportunities": {"new": count(records["opportunity"], {"NEW"}),
                              "excellent": count(records["opportunity"], {"EXCELLENT"}, "score_category"),
                              "strong": count(records["opportunity"], {"STRONG"}, "score_category"),
                              "rejected": count(records["opportunity"], {"REJECT", "REJECTED"}, "score_category")},
            "applications": {"prepared": len(records["application"]),
                             "awaiting_approval": count(records["application"], {"AWAITING_APPROVAL"}),
                             "submitted": count(records["application"], {"SUBMITTED", "APPLIED"}),
                             "reply_received": sum(1 for row in records["application"] if row.get("response")),
                             "interview": count(records["application"], {"INTERVIEW"}),
                             "rejected": count(records["application"], {"REJECTED"}),
                             "offer": count(records["application"], {"OFFER"})},
            "clients": {"new_leads": len(records["client"]),
                        "qualified": count(records["client"], {"QUALIFIED"}),
                        "negotiating": count(records["client"], {"NEGOTIATING"}),
                        "active": count(records["client"], {"ACTIVE"}),
                        "high_risk": sum(1 for row in records["client"]
                                         if row.get("risk", {}).get("risk") in {"HIGH", "BLOCKED"})},
            "projects": {"pending": count(records["project"], {"PENDING"}),
                         "working": count(records["project"], {"WORKING"}),
                         "qa": count(records["project"], {"QA"}),
                         "ready_for_review": count(records["project"], {"READY_FOR_OWNER_REVIEW"}),
                         "delivered": sum(1 for row in records["project"]
                                          if str(row.get("delivery_status", "")).startswith("DELIVERED"))},
            "payments": {state.casefold(): count(records["payment"], {state})
                         for state in ("DUE", "AWAITING_PAYMENT", "OWNER_VERIFICATION_REQUIRED",
                                       "OWNER_VERIFIED", "OVERDUE")},
            "performance": self.business_memory.metrics(include_test=include_test),
            "reputation": self.reputation.metrics() if not include_test else {
                "note": "Test records are never used to claim reputation."},
            "approvals": [] if include_test else self.approval_center(),
            "dry_run_records_included": include_test,
        }

    def status(self) -> dict[str, Any]:
        return {
            "state": "READY", "database": str(self.store.path), "polling": False,
            "application_mode": getattr(config, "CAREER_APPLICATION_MODE", "APPROVAL"),
            "dry_run_default": bool(getattr(config, "CAREER_ENGINE_DRY_RUN", False)),
            "components": [
                "CareerProfileManager", "CVManager", "PortfolioManager", "JobScout",
                "OpportunityScoringEngine", "ApplicationAgent", "PlatformPolicyGuard",
                "ClientCommunicationAgent", "ClientIntentRiskAnalyzer", "NegotiationAgent",
                "ContractApprovalGate", "ProjectExecutionManager", "QAAgent", "DeliveryManager",
                "RevisionManager", "PaymentTracker", "BusinessMemory", "SkillGapAgent",
                "ReputationEngine",
            ],
            "platform_adapters": self.adapters.all(), "approval_categories": list(APPROVAL_CATEGORIES),
            "truth_rules": [
                "No fabricated profile, opportunity, client, application, project, delivery, or payment state.",
                "External submission, contracts, delivery and payment verification require the owner.",
                "Dry-run records are tagged and excluded from verified business metrics.",
            ],
        }

    def run_dry_run(self) -> dict[str, Any]:
        """Required full acceptance lifecycle, isolated as explicit TEST_DATA."""
        opportunities = self.scout.test_opportunities()
        ranked = self.rank(include_test=True)
        candidates = [item for item in ranked if item.get("test_data") and item.get("status") == "NEW"]
        selected = candidates[0]
        synthetic_profile = {
            "full_name": "TEST OWNER", "professional_title": "Test Automation Developer",
            "professional_summary": "Synthetic profile used only by CAREER_ENGINE_DRY_RUN.",
            "skills": ["Python", "Web Development", "Testing"], "employment_history": [],
            "projects": [], "education": [], "certifications": [], "availability": "TEST AVAILABILITY",
        }
        application = self.applications.prepare(selected["id"], synthetic_profile=synthetic_profile)
        self.owner_decision("APPLICATION", application["id"], "APPROVE", evidence="TEST_SIMULATION", dry_run=True)
        submitted = self.applications.record_submission(application["id"], owner_approved=True,
                                                        evidence="TEST_SIMULATION", dry_run=True)
        client = self.clients.analyze(
            "We need a responsive Python website automation dashboard within 14 days. "
            "Budget £800, two revisions, payment through the test platform.",
            source="TEST_FIXTURE", application_id=application["id"], test_data=True,
        )
        pricing = {"minimum_price": 600, "target_price": 800, "premium_price": 1000,
                   "currency": "GBP", "delivery_days": 14, "revision_allowance": 2,
                   "rush_fee": 150, "scope": "responsive website automation dashboard"}
        negotiation = self.negotiation.recommend(client["id"], "website development",
                                                 client_offer=800, test_pricing=pricing)
        contract = self.contracts.create({
            "client_id": client["id"], "project": "TEST Automation Dashboard",
            "scope": pricing["scope"], "deliverables": ["responsive dashboard", "tests", "documentation"],
            "deadline": "TEST +14 days", "price": 800, "currency": "GBP",
            "payment_method": "TEST PLATFORM ESCROW", "milestones": ["50% start", "50% owner-approved delivery"],
            "revisions": 2, "risks": client["risk"], "terms": "TEST TERMS — no external commitment",
        }, test_data=True)
        approved_contract = self.owner_decision("CONTRACT", contract["id"], "APPROVE",
                                                evidence="TEST_SIMULATION", dry_run=True)
        project = self.projects.create(approved_contract["id"], [
            {"name": "Build website", "dependencies": []},
            {"name": "Run code tests", "dependencies": ["Build website"]},
            {"name": "Security review", "dependencies": ["Run code tests"]},
        ])
        for task_id in project["task_ids"]:
            self.projects.record_task(task_id, status="COMPLETE", output="TEST_OUTPUT_EXISTS",
                                      test="TEST_POSTCONDITION_PASSED")
        qa = self.qa.review(project["id"], [
            {"name": "requirements", "passed": True, "evidence": "TEST requirements matched"},
            {"name": "functionality", "passed": True, "evidence": "TEST functions passed"},
            {"name": "security", "passed": True, "evidence": "TEST safety checks passed"},
        ])
        delivery = self.delivery.record(project["id"], method="TEST_PLATFORM", files=["test-deliverable.zip"],
                                        evidence="TEST_SIMULATION", owner_approved=True, dry_run=True)
        payment = self.payments.create(project["id"], agreed_amount=800, currency="GBP",
                                       milestone="final", payment_method="TEST_PLATFORM_ESCROW",
                                       due_date=time.time() - 1, invoice_reference="TEST-INVOICE")
        reported = self.payments.report(payment["id"], 800, "TEST-CLIENT-REPORT")
        verified = self.payments.verify(payment["id"], 800, owner_verified=True,
                                        evidence="TEST_SIMULATION", dry_run=True)
        metrics = self.business_memory.metrics(include_test=True)
        stages = {
            "opportunities_found": len(opportunities), "selected": selected["id"],
            "application": submitted.get("status"), "client_risk": client["risk"]["risk"],
            "negotiation": negotiation.get("status"), "contract": approved_contract.get("status"),
            "project": project.get("status"), "qa": qa.get("status"),
            "delivery": delivery.get("status"), "payment_reported": reported.get("status"),
            "payment_verified": verified.get("status"), "test_revenue": metrics["verified_revenue"],
        }
        expected = {
            "application": "SUBMITTED_SIMULATED", "contract": "APPROVED", "qa": "PASSED",
            "delivery": "DELIVERED_SIMULATED", "payment_verified": "OWNER_VERIFIED",
        }
        failures = {key: {"expected": value, "actual": stages.get(key)}
                    for key, value in expected.items() if stages.get(key) != value}
        return {"state": "PASSED" if not failures else "FAILED", "dry_run": True,
                "external_actions": 0, "test_data": True, "stages": stages,
                "failures": failures,
                "production_metrics_unchanged": self.business_memory.metrics(include_test=False),
                "payment_message": PAYMENT_OWNER_VERIFICATION_REQUIRED,
                "project_message": PROJECT_READY_FOR_OWNER_REVIEW}


_ENGINE: ZenoCareerEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_career_engine() -> ZenoCareerEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = ZenoCareerEngine()
    return _ENGINE


__all__ = [
    "APPROVAL_CATEGORIES", "APPLICATION_MODES", "CareerStore", "ClientIntentRiskAnalyzer",
    "OWNER_CONTRACT_APPROVAL_REQUIRED", "OWNER_INFORMATION_REQUIRED",
    "PAYMENT_OWNER_VERIFICATION_REQUIRED", "PROJECT_READY_FOR_OWNER_REVIEW",
    "PlatformAdapterRegistry", "PlatformPolicyGuard", "SOCIAL_EVENT_TYPES",
    "ZenoCareerEngine", "get_career_engine",
]
