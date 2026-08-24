"""Scam / suspicious-listing detection for job & freelance opportunities.

Rule-based, explainable risk scoring (0-100) with the exact reasons -- the brief
lists these signals explicitly. It NEVER auto-accepts or auto-rejects; it flags
risk and recommends, so the owner (and the paid_work approval gate) decides.
Pure logic, deterministic, never raises.
"""

from __future__ import annotations

import re
from typing import Any

# (weight, label, compiled pattern). Weights are capped at 100 in total.
_SIGNALS = [
    (45, "asks for payment/fee before work or employment",
     re.compile(r"(?:pay|send|deposit|transfer|require[sd]?).{0,25}"
                r"(?:registration|training|processing|onboarding|equipment|starter)\s*fee\b|"
                r"\bpay .{0,20}(?:before|upfront|to start|to apply)|"
                r"\bsend .{0,15}(?:money|payment|deposit)\b", re.I)),
    (30, "crypto-only / wire-only payment demand",
     re.compile(r"\b(crypto|bitcoin|btc|usdt|ethereum)\s*(only|payment)|"
                r"pay(?:ment)? (?:only )?(?:via|in) (?:crypto|bitcoin|gift ?cards?)|"
                r"wire transfer only\b", re.I)),
    (25, "requests identity documents / bank details early",
     re.compile(r"\b(send|upload|provide) .{0,20}(passport|national id|ssn|bank "
                r"(?:details|account)|driver.?s licen|bvn)\b", re.I)),
    (20, "off-platform-only contact (Telegram/WhatsApp only)",
     re.compile(r"\b(?:contact|message|reach|apply) .{0,15}(?:only )?(?:on |via |through )"
                r"(telegram|whatsapp|signal)\b|telegram only|whatsapp only", re.I)),
    (20, "remote-access / install-software request",
     re.compile(r"\b(anydesk|teamviewer|remote access|install .{0,15}(?:our )?"
                r"(?:software|app) to)\b", re.I)),
    (18, "unrealistic pay for little/no experience",
     re.compile(r"\$?\d{3,4}\s*(?:/|per )?\s*day\b|\$\d{4,}\s*(?:/|per )?\s*week\b|"
                r"earn \$?\d{3,}.{0,20}(?:daily|per day|from home).{0,20}no experience", re.I)),
    (15, "reshipping / package-forwarding / money-mule",
     re.compile(r"\b(reship|package forwarding|receive .{0,15}packages|"
                r"money transfer agent|process payments? on behalf)\b", re.I)),
    (15, "recruitment via personal email / vague company",
     re.compile(r"@(?:gmail|yahoo|outlook|hotmail)\.com\b.{0,40}(?:hr|recruit|hiring)|"
                r"\b(?:hiring manager|hr).{0,20}@(?:gmail|yahoo)\.com", re.I)),
    (12, "pressure / urgency to act immediately",
     re.compile(r"\b(act now|urgent(?:ly)?|immediately|limited slots|"
                r"apply within \d+ (?:hours|minutes)|start today)\b", re.I)),
    (12, "guaranteed job / no interview needed",
     re.compile(r"\b(guaranteed (?:job|income|hiring)|no interview (?:needed|required)|"
                r"instant hire|hired on the spot)\b", re.I)),
]

# Positive signals that REDUCE risk (legitimate structure).
_TRUST = [
    (-10, "posted on a known platform / company careers page",
     re.compile(r"\b(linkedin|indeed|upwork|greenhouse|lever|workday|"
                r"careers\.\w+|\.jobs\b)\b", re.I)),
    (-8, "structured interview process mentioned",
     re.compile(r"\b(interview process|technical interview|assessment stage|"
                r"reference check)\b", re.I)),
]


def _text_of(listing: Any) -> str:
    if isinstance(listing, dict):
        return " ".join(str(v) for v in listing.values())
    return str(listing or "")


def assess(listing: Any) -> dict[str, Any]:
    """Return {score 0-100, level, reasons, recommendation}. Higher = riskier."""
    text = _text_of(listing)
    score = 0
    reasons: list[str] = []
    for weight, label, pat in _SIGNALS:
        if pat.search(text):
            score += weight
            reasons.append(label)
    trust_notes: list[str] = []
    for weight, label, pat in _TRUST:
        if pat.search(text):
            score += weight               # weight is negative
            trust_notes.append(label)
    score = max(0, min(100, score))
    if score >= 60:
        level, rec = "HIGH", "DO NOT PROCEED"
    elif score >= 30:
        level, rec = "MODERATE", "PROCEED WITH CAUTION — verify the employer first"
    else:
        level, rec = "LOW", "No strong scam signals; still verify normally"
    return {"score": score, "level": level, "reasons": reasons,
            "trust_signals": trust_notes, "recommendation": rec}
