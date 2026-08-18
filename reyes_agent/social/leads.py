"""Comment classification, lead detection, and honest risk analysis.

THE THING THIS MODULE REFUSES TO DO
-----------------------------------
The brief is unusually direct: ZENO must not pretend it can read minds. So
there is no `is_genuine()` and no "intent: hiring (94%)". What exists is
`IntentRiskAnalysis`, which lists the EVIDENCE it found and the risk that
evidence supports, with every reason written out. A human reads the reasons
and decides.

The difference matters in practice. "HIGH RISK" alone is a number to argue
with. "HIGH RISK: asked to move to WhatsApp, offered payment before scope,
account has no posts" is three checkable facts.

WHY COMMENTS ARE CLASSIFIED BUT NEVER OBEYED
--------------------------------------------
Every comment is scanned by `safety.scan_untrusted` first. A flagged comment
is stored with `injection_flag` set and NEVER produces an automatic reply --
it goes to the owner. Text from a stranger has no path to a tool in this
module, and `draft_reply` returns a string that a human sends.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.social import control, safety, store as social_store

# --- comment categories (Phase 36) ---------------------------------------
GENERAL = "GENERAL"
QUESTION = "QUESTION"
COMPLIMENT = "COMPLIMENT"
CRITICISM = "CRITICISM"
TECHNICAL_QUESTION = "TECHNICAL_QUESTION"
CLIENT_LEAD = "CLIENT_LEAD"
COLLABORATION = "COLLABORATION"
SPAM = "SPAM"
SCAM = "SCAM"
ABUSE = "ABUSE"

CATEGORIES = (GENERAL, QUESTION, COMPLIMENT, CRITICISM, TECHNICAL_QUESTION,
              CLIENT_LEAD, COLLABORATION, SPAM, SCAM, ABUSE)

# Categories a machine must never answer on its own, whatever the mode.
NEVER_AUTO_REPLY = {CLIENT_LEAD, COLLABORATION, SCAM, ABUSE, CRITICISM}

# Ordered: the first match wins, so SCAM beats QUESTION when a message is both.
_CLASSIFIERS: tuple[tuple[str, str], ...] = (
    (SCAM, r"\b(?:crypto|forex|bitcoin|investment\s+opportunity|"
           r"guaranteed\s+returns?|double\s+your|dm\s+me\s+for\s+(?:money|profit)|"
           r"send\s+(?:me\s+)?(?:your\s+)?(?:seed\s+phrase|wallet|password|otp)|"
           r"telegram\s*:\s*@|whatsapp\s+me\s+on\s+\+?\d)"),
    (ABUSE, r"\b(?:idiot|stupid|trash|garbage|kill\s+yourself|worthless|"
            r"scam(?:mer)?\s+account|fraud)\b"),
    (SPAM, r"\b(?:follow\s*(?:4|for)\s*follow|f4f|check\s+my\s+(?:page|profile|bio)|"
           r"buy\s+followers|cheap\s+followers|link\s+in\s+bio\s+for\s+free|"
           r"promo(?:tion)?\s+dm)\b"),
    (CLIENT_LEAD, r"\b(?:can\s+you\s+build\s+(?:this|it|one)\s+for\s+me|"
                  r"how\s+much\s+(?:would|does|for)|what(?:'s|\s+is)\s+(?:your|the)\s+"
                  r"(?:price|rate|cost|pricing)|can\s+i\s+hire|are\s+you\s+for\s+hire|"
                  r"i\s+need\s+an?\s+(?:ai|assistant|bot|automation|developer)|"
                  r"do\s+you\s+(?:take|accept)\s+(?:clients|projects|work)|"
                  r"quote\s+for|available\s+for\s+(?:work|hire|freelance))"),
    (COLLABORATION, r"\b(?:collab(?:orate|oration)?|partner(?:ship)?|work\s+together|"
                    r"guest\s+(?:post|video)|sponsor(?:ship)?|cross[- ]promot)"),
    (TECHNICAL_QUESTION, r"\b(?:which\s+(?:model|framework|library|api|stack)|"
                         r"what\s+(?:language|framework|model|database|stack)|"
                         r"how\s+did\s+you\s+(?:build|implement|handle|solve)|"
                         r"is\s+(?:this|it)\s+(?:open\s+source|python|local)|"
                         r"does\s+it\s+(?:run|work)\s+(?:locally|offline)|"
                         r"github|repo\b|source\s+code)"),
    (CRITICISM, r"\b(?:doesn'?t\s+work|not\s+impressed|overrated|useless|"
                r"this\s+is\s+(?:fake|staged)|nothing\s+new|already\s+exists|"
                r"why\s+would\s+anyone)\b"),
    (COMPLIMENT, r"\b(?:amazing|incredible|awesome|love\s+this|so\s+cool|"
                 r"impressive|well\s+done|great\s+work|fire\b|goat\b|insane\b)"),
    (QUESTION, r"\?|^\s*(?:what|how|why|when|where|who|can|does|is|are|will)\b"),
)

_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE))
                  for name, pattern in _CLASSIFIERS)


@dataclass
class Classification:
    category: str
    confidence: float
    matched: str = ""
    injection: safety.InjectionVerdict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "confidence": self.confidence,
                "matched": self.matched,
                "injection": self.injection.as_dict() if self.injection else None}


def classify(text: str) -> Classification:
    """Category plus the pattern that decided it, so it can be checked."""
    verdict = safety.scan_untrusted(text)
    for name, pattern in _COMPILED:
        match = pattern.search(text or "")
        if match:
            # Confidence reflects how specific the pattern is, not a guess at
            # what the person meant. QUESTION is the loosest, so it scores low.
            confidence = 0.5 if name == QUESTION else 0.8
            return Classification(category=name, confidence=confidence,
                                  matched=match.group(0)[:60], injection=verdict)
    return Classification(category=GENERAL, confidence=0.3, injection=verdict)


# --- intent risk analysis (Phase 40) -------------------------------------

LOW_RISK = "LOW RISK"
MEDIUM_RISK = "MEDIUM RISK"
HIGH_RISK = "HIGH RISK"

# Each signal is a checkable fact, with the weight it contributes.
_RISK_SIGNALS: tuple[tuple[str, str, int], ...] = (
    ("asks to move off-platform",
     r"\b(?:whatsapp|telegram|signal|dm\s+me\s+on|message\s+me\s+on|"
     r"add\s+me\s+on|text\s+me\s+at)\b", 2),
    ("asks for credentials or access",
     # A word may sit between "your" and the credential: "your BANK login",
     # "your ADMIN password". Adjacency missed real scam messages.
     r"\b(?:your\s+(?:\w+\s+){0,2}(?:password|login|credential|api\s*key|token|seed\s+phrase)|"
     r"give\s+me\s+access|share\s+your\s+account)\b", 3),
    ("offers payment before scope is discussed",
     r"\b(?:i(?:'ll| will)\s+pay\s+(?:you\s+)?\$?\d|"
     r"budget\s+is\s+\$?\d+.{0,20}(?:right\s+now|today|immediately))\b", 2),
    ("unrealistic urgency",
     r"\b(?:urgent(?:ly)?|asap|right\s+now|today\s+only|within\s+(?:the\s+)?hour|"
     r"immediately)\b", 1),
    ("suspicious link",
     r"(?:bit\.ly|tinyurl|t\.me/|goo\.gl|shorturl|[a-z0-9-]+\.(?:tk|ml|ga|cf|gq))", 2),
    ("mentions cheque, wire or overpayment",
     r"\b(?:cashier'?s?\s+check|wire\s+transfer|overpay|western\s+union|"
     r"money\s?gram|gift\s+card|"
     # "I will wire you $5000" is the same offer as "wire transfer",
     # phrased as a verb. Only the noun form matched before.
     r"wire\s+(?:you|u|it|the\s+money)|"
     r"(?:send|transfer)\s+(?:you|u)\s+\$?\d)\b", 3),
    ("no scope, only price",
     r"^\s*(?:how\s+much|price|cost|rate)\s*\??\s*$", 1),
    ("asks for free work first",
     r"\b(?:do\s+(?:it|one)\s+for\s+free|sample\s+first|test\s+project\s+unpaid|"
     r"exposure\s+instead\s+of\s+pay)\b", 1),
)

_COMPILED_RISK = tuple((label, re.compile(pattern, re.IGNORECASE), weight)
                       for label, pattern, weight in _RISK_SIGNALS)

# Signals that a request is thought through -- they reduce risk.
_POSITIVE_SIGNALS: tuple[tuple[str, str], ...] = (
    ("describes a concrete deliverable",
     r"\b(?:i\s+need\s+(?:a|an)\s+\w+\s+(?:that|which|to)|"
     r"looking\s+for\s+(?:someone|a\s+developer)\s+to\s+\w+|"
     r"we(?:'re|\s+are)\s+building)\b"),
    ("states a timeframe",
     r"\b(?:by\s+(?:next|the)\s+\w+|within\s+\d+\s+(?:weeks?|months?)|"
     r"deadline\s+is)\b"),
    ("names a real budget range",
     r"\$\s?\d[\d,]*\s*(?:-|to)\s*\$?\s?\d"),
    ("asks about process",
     r"\b(?:how\s+do\s+you\s+(?:work|usually|handle)|what\s+(?:do\s+you\s+need|"
     r"information\s+do\s+you)|next\s+steps?)\b"),
)

_COMPILED_POSITIVE = tuple((label, re.compile(pattern, re.IGNORECASE))
                           for label, pattern in _POSITIVE_SIGNALS)


@dataclass
class IntentRiskAnalysis:
    """Evidence and the risk it supports. Never a claim about intention."""
    risk: str
    score: int
    reasons: list[str] = field(default_factory=list)
    reassuring: list[str] = field(default_factory=list)
    disclaimer: str = (
        "This is an analysis of observable signals in the message, not a "
        "judgement of what the person intends. ZENO cannot know that.")

    def as_dict(self) -> dict[str, Any]:
        return {"risk": self.risk, "score": self.score, "reasons": self.reasons,
                "reassuring": self.reassuring, "disclaimer": self.disclaimer}


def analyse_risk(message: str, *, account_age_days: float | None = None,
                 account_posts: int | None = None) -> IntentRiskAnalysis:
    """Score the evidence in a message. Every point is traceable to a reason."""
    text = message or ""
    score = 0
    reasons: list[str] = []
    reassuring: list[str] = []

    for label, pattern, weight in _COMPILED_RISK:
        if pattern.search(text):
            score += weight
            reasons.append(label)

    for label, pattern in _COMPILED_POSITIVE:
        if pattern.search(text):
            score -= 1
            reassuring.append(label)

    # Account behaviour, when the platform gives it to us.
    if account_age_days is not None and account_age_days < 7:
        score += 2
        reasons.append(f"account is {account_age_days:.0f} days old")
    if account_posts is not None and account_posts == 0:
        score += 1
        reasons.append("account has no posts")

    # An injected instruction inside a business enquiry is not a business
    # enquiry.
    injection = safety.scan_untrusted(text)
    if injection.flagged:
        score += 4
        reasons.append(f"message contains injection patterns "
                       f"({', '.join(injection.patterns)})")

    score = max(0, score)
    if score >= 4:
        risk = HIGH_RISK
    elif score >= 2:
        risk = MEDIUM_RISK
    else:
        risk = LOW_RISK

    if not reasons:
        reasons.append("no risk signals found in the message")
    return IntentRiskAnalysis(risk=risk, score=score, reasons=reasons,
                              reassuring=reassuring)


# --- extracting what was asked for ---------------------------------------

_SERVICE_HINTS: tuple[tuple[str, str], ...] = (
    ("AI assistant", r"\b(?:ai\s+assistant|personal\s+assistant|chatbot|voice\s+assistant)\b"),
    ("automation", r"\b(?:automat\w+|workflow|bot\s+to|script\s+to|integration)\b"),
    ("website", r"\b(?:website|web\s*app|landing\s+page|portfolio\s+site)\b"),
    ("mobile app", r"\b(?:mobile\s+app|android|ios\s+app)\b"),
    ("data / scraping", r"\b(?:scrap\w+|data\s+(?:extraction|pipeline)|crawler)\b"),
    ("agent system", r"\b(?:agent\s+system|multi[- ]agent|ai\s+agents?)\b"),
)
_COMPILED_SERVICE = tuple((label, re.compile(pattern, re.IGNORECASE))
                          for label, pattern in _SERVICE_HINTS)

_BUDGET = re.compile(r"(?:[$₦£€]\s?\d[\d,]*(?:\.\d+)?\s*(?:k|m)?)"
                     r"(?:\s*(?:-|to)\s*[$₦£€]?\s?\d[\d,]*\s*(?:k|m)?)?",
                     re.IGNORECASE)
_DEADLINE = re.compile(
    r"\b(?:by\s+(?:next\s+)?\w+day|by\s+(?:the\s+)?end\s+of\s+\w+|"
    r"within\s+\d+\s+(?:days?|weeks?|months?)|before\s+\w+\s+\d{1,2}|"
    r"deadline\s+(?:is\s+)?[\w\s\d]{3,20})", re.IGNORECASE)


def extract_request(message: str) -> dict[str, str]:
    text = message or ""
    service = next((label for label, pattern in _COMPILED_SERVICE
                    if pattern.search(text)), "")
    budget = _BUDGET.search(text)
    deadline = _DEADLINE.search(text)
    return {
        "requested_service": service,
        "possible_budget": budget.group(0).strip() if budget else "",
        "deadline": deadline.group(0).strip() if deadline else "",
    }


# --- the agents -----------------------------------------------------------

class CommentAgent:
    """Classifies comments and drafts replies a human sends."""

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()

    def ingest(self, *, platform: str, comment_id: str, author: str,
               text: str, content_id: str = "") -> dict[str, Any]:
        result = classify(text)
        flagged = bool(result.injection and result.injection.flagged)

        draft = "" if flagged else self.draft_reply(result.category, text)
        # Everything starts as a draft. Nothing is ever sent from here.
        state = "OWNER_REVIEW" if (flagged or result.category in NEVER_AUTO_REPLY
                                   or control.comment_mode() == control.APPROVAL) \
            else ("DRAFTED" if draft else "NONE")

        self._store.upsert_comment(
            comment_id, platform=platform, content_id=content_id, author=author,
            text=safety.quarantine(text, limit=1000) if flagged else text[:2000],
            classification=result.category, confidence=result.confidence,
            draft_reply=draft, reply_state=state, injection_flag=int(flagged),
            received_at=time.time())

        self._store.audit("CommentAgent", "comment_classified", platform=platform,
                          target=comment_id, result=result.category,
                          error="injection patterns detected" if flagged else "")

        return {"comment_id": comment_id, "classification": result.as_dict(),
                "reply_state": state, "draft_reply": draft,
                "quarantined": flagged}

    def draft_reply(self, category: str, text: str = "") -> str:
        """A suggestion for a human. Checked so it cannot commit the owner."""
        drafts = {
            COMPLIMENT: "Thank you — glad it's useful. More of the build coming.",
            QUESTION: "Good question. I'll cover this in an upcoming post.",
            TECHNICAL_QUESTION: ("It's a Python backend with a Windows desktop "
                                 "client. Happy to go deeper in a future post."),
            GENERAL: "Thanks for watching.",
        }
        draft = drafts.get(category, "")
        if not draft:
            return ""
        safe, problems = safety.check_reply(draft)
        return draft if safe else ""

    def pending(self, limit: int = 25) -> list[dict[str, Any]]:
        return self._store.comments(reply_state="OWNER_REVIEW", limit=limit)


class LeadDetectionAgent:
    """Turns a qualifying comment into a lead record and an opportunity."""

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()

    def detect(self, *, platform: str, username: str, message: str,
               comment_id: str = "", account_age_days: float | None = None,
               account_posts: int | None = None) -> dict[str, Any] | None:
        if not control.lead_detection_enabled():
            return None

        result = classify(message)
        if result.category not in (CLIENT_LEAD, COLLABORATION):
            return None

        analysis = analyse_risk(message, account_age_days=account_age_days,
                                account_posts=account_posts)
        request = extract_request(message)

        # A scam-shaped message is recorded as one, not routed to the owner
        # as a business opportunity.
        status = (social_store.LEAD_SCAM if analysis.risk == HIGH_RISK
                  and any("credential" in r or "cheque" in r or "wire" in r
                          for r in analysis.reasons)
                  else social_store.LEAD_NEW)

        lead_id = self._store.create_lead(
            platform=platform, username=username[:80],
            message=message[:1500], comment_id=comment_id,
            risk=analysis.risk, risk_reasons=analysis.reasons,
            status=status, **request)

        self._store.audit("LeadDetectionAgent", "lead_detected", platform=platform,
                          target=lead_id, result=f"{result.category} / {analysis.risk}")

        return {"lead_id": lead_id, "category": result.category,
                "risk": analysis.as_dict(), "request": request, "status": status}

    def to_opportunity(self, lead_id: str) -> tuple[bool, str]:
        """Hand a qualified lead to the existing OpportunityEngine."""
        leads = [lead for lead in self._store.leads(limit=200)
                 if lead["lead_id"] == lead_id]
        if not leads:
            return False, f"no lead {lead_id}"
        lead = leads[0]
        if lead["status"] == social_store.LEAD_SCAM:
            return False, "this lead is recorded as a scam; it is not an opportunity"

        try:
            from reyes_agent.opportunity import get_opportunity_engine
            engine = get_opportunity_engine()
            record = engine.assess(
                name=f"{lead['platform']} lead: {lead['username']}"[:80],
                category="client_lead",
                summary=(lead.get("requested_service") or "unspecified request")[:200],
                factors={},
                observations=[{
                    "source": f"{lead['platform']} comment",
                    "detail": lead["message"][:400],
                }],
            )
            opportunity_id = str(record.get("opportunity_id") or record.get("id") or "")
        except Exception as exc:  # noqa: BLE001
            return False, f"opportunity engine refused: {type(exc).__name__}: {exc}"

        self._store.update_lead(lead_id, opportunity_id=opportunity_id,
                                status=social_store.LEAD_OWNER_REVIEW)
        self._store.audit("LeadDetectionAgent", "lead_to_opportunity",
                          platform=lead["platform"], target=lead_id,
                          result=opportunity_id)
        return True, (f"lead {lead_id} sent to the OpportunityEngine as "
                      f"{opportunity_id}; status is OWNER_REVIEW")
