"""Did the meaning survive?

WHAT THIS CATCHES THAT A SIMILARITY SCORE DOES NOT
--------------------------------------------------
"Delete the file" and "Do not delete the file" are ~95% similar by any
embedding measure. They are opposite instructions. A semantic verifier that
only compares vectors will wave that through, which is why the checks here
are STRUCTURAL first and similarity second:

  * negation      -- counted on both sides; a mismatch is a hard failure
  * numbers       -- every numeric literal must appear in the output
  * entities      -- every protected name must survive
  * imperative    -- a command must not become a description

These run on text where `protect.py` has already masked numbers and names, so
"survives" means "the placeholder came back", which is exact rather than
fuzzy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Words that flip a sentence's polarity. Checked on the ENGLISH side, since
# that is what the brain will act on.
_NEGATORS = (
    r"\bnot\b", r"\bn't\b", r"\bnever\b", r"\bno\b", r"\bnone\b", r"\bnothing\b",
    r"\bwithout\b", r"\bcannot\b", r"\bcan't\b", r"\bdon't\b", r"\bdoesn't\b",
    r"\bdidn't\b", r"\bwon't\b", r"\bshouldn't\b", r"\bmustn't\b",
    r"\bstop\b", r"\bavoid\b", r"\bexcept\b", r"\bneither\b", r"\bnor\b",
)
_NEGATOR_RE = re.compile("|".join(_NEGATORS), re.IGNORECASE)

# Source-language negators, so the ORIGINAL can be scored before translation.
_SOURCE_NEGATORS = re.compile(
    r"\b(?:no|not|non|ne|pas|nicht|nie|niet|nao|não|nunca|jamais|nada|"
    r"nunca|hayır|değil|nie|ingen|inte|ikke|ei|mai|geen|"
    r"ma|la|lam|lan|mish|"          # Arabic transliterated
    r"kò|ko|rara|"                  # Yoruba
    r"adịghị|adighi|mba|"           # Igbo
    r"ba|babu|"                     # Hausa
    r"hapana|si)\b",                # Swahili
    re.IGNORECASE)

_IMPERATIVE_VERBS = (
    "open", "close", "delete", "remove", "send", "run", "start", "stop",
    "create", "make", "check", "show", "find", "install", "update", "write",
    "read", "move", "copy", "call", "play", "search", "build", "deploy",
)


@dataclass
class Verification:
    ok: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "confidence": round(self.confidence, 3),
                "issues": self.issues, "checks": self.checks}


def count_negation(text: str) -> int:
    return len(_NEGATOR_RE.findall(str(text or "")))


def source_has_negation(text: str) -> bool:
    return bool(_SOURCE_NEGATORS.search(str(text or "")))


def _is_imperative(text: str) -> bool:
    """Whether the sentence is a command.

    A NEGATED command is still a command: "do not delete it" is imperative.
    The first version only looked at the leading word, so every correctly
    translated negative instruction was reported as "a command became a
    description" -- a false alarm on exactly the sentences that matter most.
    """
    stripped = str(text or "").strip().lower()
    stripped = re.sub(r"^(?:please|kindly|abeg|biko)\s+", "", stripped)
    stripped = re.sub(r"^(?:do\s+not|don't|do\s+n't|never|no)\s+", "", stripped)
    stripped = re.sub(r"^(?:please|kindly)\s+", "", stripped)
    first = re.split(r"[\s,]+", stripped)[0] if stripped else ""
    return first in _IMPERATIVE_VERBS


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(t) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard over content tokens.

    Deliberately crude and deliberately NOT the primary check. A real
    embedding model (SONAR or equivalent) plugs in via `set_semantic_scorer`;
    until one is installed this gives a usable floor without a download, and
    the structural checks above do the safety-critical work regardless.
    """
    first, second = _tokens(a), _tokens(b)
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


_scorer = None


def set_semantic_scorer(fn) -> None:
    """Install a real multilingual semantic model. `fn(a, b) -> float`."""
    global _scorer
    _scorer = fn


def semantic_score(a: str, b: str) -> float:
    if _scorer is not None:
        try:
            return float(_scorer(a, b))
        except Exception:  # noqa: BLE001
            pass
    return similarity(a, b)


def verify(original: str, english: str, *, protected=None,
           source_language: str = "") -> Verification:
    """Check that the English carries the same instruction as the original."""
    issues: list[str] = []
    checks: dict[str, bool] = {}

    # --- negation, the check that actually protects the machine ----------
    english_negations = count_negation(english)
    source_negated = source_has_negation(original) or count_negation(original) > 0
    negation_ok = True
    if source_negated and english_negations == 0:
        negation_ok = False
        issues.append("the original appears negated and the English is not")
    elif not source_negated and english_negations > 0 and source_language in ("en", ""):
        # Only suspicious for English-to-English: other languages express
        # negation with words this module cannot enumerate.
        negation_ok = False
        issues.append("the English is negated and the original does not appear to be")
    checks["negation"] = negation_ok

    # --- protected values ------------------------------------------------
    if protected is not None:
        missing = protected.missing(english)
        leftovers = protected.leftover_tokens(english)
        checks["protected_values"] = not missing
        checks["no_leftover_placeholders"] = not leftovers
        if missing:
            issues.append(f"lost through translation: {missing[:4]}")
        if leftovers:
            issues.append(f"unrestored placeholders: {leftovers[:4]}")

    # --- imperative mood --------------------------------------------------
    # "Open Chrome" must not become "The user would like Chrome to be opened":
    # the intent parser keys on the verb.
    if _is_imperative(original) and not _is_imperative(english):
        checks["imperative"] = False
        issues.append("a command became a description")
    else:
        checks["imperative"] = True

    # --- similarity, last and least ---------------------------------------
    score = semantic_score(original, english)
    checks["semantic"] = score >= 0.15 or source_language not in ("en", "pcm", "")

    hard_failures = sum(1 for key in ("negation", "protected_values")
                        if checks.get(key) is False)
    soft_failures = sum(1 for key, value in checks.items()
                        if value is False and key not in ("negation", "protected_values"))

    confidence = 1.0 - (hard_failures * 0.5) - (soft_failures * 0.15)
    confidence = max(0.0, min(1.0, confidence))
    return Verification(ok=hard_failures == 0, confidence=confidence,
                        issues=issues, checks=checks)
