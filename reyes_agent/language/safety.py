"""Unicode and injection safety for untrusted multilingual text.

TRANSLATION DOES NOT LAUNDER INPUT
----------------------------------
A sentence that says "ignore all previous instructions" in Yoruba is still a
prompt injection after it becomes English. Worse, translation can make it
*look* trustworthy: the hostile phrasing arrives in the same clean English as
a legitimate request. So the scan runs on BOTH the original and the
translated text, and a hit is metadata attached to the result -- never a
reason to silently rewrite the user's words.

WHY NFKC IS NOT APPLIED BLINDLY
-------------------------------
NFKC folds a lot of genuinely distinct characters together. It maps "ﬁ" to
"fi", which is usually fine, but it also collapses characters that carry
meaning in other writing systems. Yoruba's ẹ and e are different letters.
So this module uses NFC -- which composes without discarding distinctions --
and treats NFKC as a comparison view only, for spotting homoglyph tricks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Characters with no legitimate place in typed input. Zero-width joiners are
# real in Arabic, Persian and Indic scripts, so ZWJ/ZWNJ are NOT in this set;
# stripping them would corrupt those languages.
_INVISIBLE = {
    "​",  # zero-width space
    "‎", "‏",  # LTR/RTL marks
    "‪", "‫", "‬", "‭", "‮",  # bidi overrides
    "⁦", "⁧", "⁨", "⁩",  # bidi isolates
    "﻿",  # BOM used mid-string
    "­",  # soft hyphen
}

# Kept, because removing them breaks real scripts.
_MEANINGFUL_JOINERS = {"‌", "‍"}

_BIDI_OVERRIDES = {"‪", "‫", "‬", "‭", "‮",
                   "⁦", "⁧", "⁨", "⁩"}

# Latin letters and the confusable characters that render almost identically.
# Used to spot a domain or command that LOOKS familiar and is not.
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "і": "i", "ј": "j", "һ": "h", "ԁ": "d", "ɡ": "g", "ⅼ": "l",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "օ": "o", "ս": "u", "ɑ": "a", "ν": "v", "ԛ": "q", "ѡ": "w",
}

_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("instruction_override",
     r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
     r"(?:previous|prior|earlier|above|preceding|system)\s+"
     r"(?:instruction|instructions|prompt|prompts|rule|rules|message|messages)\b"),
    ("role_hijack",
     r"\b(?:you\s+are\s+now|from\s+now\s+on\s+you|act\s+as|pretend\s+to\s+be|"
     r"developer\s+mode|jailbreak|dan\s+mode)\b"),
    ("authority_claim",
     r"(?:^|\n)\s*(?:system|assistant|developer|admin)\s*:|"
     r"\b(?:the\s+owner\s+(?:said|approved|authorised|authorized)|"
     r"anthropic\s+(?:says|requires))\b"),
    ("secret_extraction",
     r"\b(?:show|reveal|print|send|tell|give)\b[^.\n]{0,30}\b"
     r"(?:api[\s_-]?key|secret|token|password|credential|\.env|private\s+key)\b"),
    ("shell_execution",
     r"\b(?:run|execute|eval)\b[^.\n]{0,20}\b(?:command|shell|bash|powershell|"
     r"cmd|script|subprocess)\b"),
)

_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE))
                  for name, pattern in _INJECTION_PATTERNS)


@dataclass(frozen=True)
class SafetyReport:
    """What was found. Nothing here rewrites the user's meaning."""

    cleaned: str
    removed_invisible: int = 0
    had_bidi_override: bool = False
    homoglyphs: tuple[str, ...] = ()
    injection_markers: tuple[str, ...] = ()
    mixed_script_tokens: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return bool(self.injection_markers or self.homoglyphs
                    or self.had_bidi_override)

    def as_dict(self) -> dict[str, Any]:
        return {
            "removed_invisible": self.removed_invisible,
            "had_bidi_override": self.had_bidi_override,
            "homoglyphs": list(self.homoglyphs),
            "injection_markers": list(self.injection_markers),
            "mixed_script_tokens": list(self.mixed_script_tokens),
            "suspicious": self.suspicious,
        }


def sanitise(text: str) -> SafetyReport:
    """Remove invisible control characters; report everything else."""
    raw = str(text or "")

    removed = 0
    kept: list[str] = []
    had_bidi = False
    for char in raw:
        if char in _MEANINGFUL_JOINERS:
            kept.append(char)
            continue
        if char in _INVISIBLE:
            removed += 1
            if char in _BIDI_OVERRIDES:
                had_bidi = True
            continue
        # Other format/control characters, except the whitespace we rely on.
        if unicodedata.category(char) in {"Cf", "Cc"} and char not in "\t\n\r":
            removed += 1
            continue
        kept.append(char)

    # NFC composes accents without collapsing distinct letters. NFKC would
    # damage scripts where the "compatibility" form is a different letter.
    cleaned = unicodedata.normalize("NFC", "".join(kept))

    return SafetyReport(
        cleaned=cleaned,
        removed_invisible=removed,
        had_bidi_override=had_bidi,
        homoglyphs=_homoglyphs(cleaned),
        injection_markers=scan_injection(cleaned),
        mixed_script_tokens=_mixed_script_tokens(cleaned),
    )


def scan_injection(text: str) -> tuple[str, ...]:
    """Named injection families present in `text`. Runs on translated text too."""
    found = [name for name, pattern in _COMPILED if pattern.search(str(text or ""))]
    return tuple(dict.fromkeys(found))


def _homoglyphs(text: str) -> tuple[str, ...]:
    """Confusable characters found inside otherwise-Latin words.

    A Cyrillic 'а' in the middle of "paypal" is the whole attack. A Cyrillic
    word in a Russian sentence is not -- so only tokens that MIX scripts are
    reported.
    """
    hits: list[str] = []
    for token in re.findall(r"\S+", text):
        confusable = [c for c in token if c in _CONFUSABLES]
        if not confusable:
            continue
        if any("a" <= c.lower() <= "z" for c in token):
            hits.append(token)
    return tuple(dict.fromkeys(hits))[:10]


def _script_of(char: str) -> str:
    """Coarse script name from the Unicode character name."""
    if not char.isalpha():
        return ""
    try:
        name = unicodedata.name(char)
    except ValueError:
        return ""
    for script in ("LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "HAN",
                   "HIRAGANA", "KATAKANA", "HANGUL", "DEVANAGARI", "THAI",
                   "ETHIOPIC", "ARMENIAN", "GEORGIAN", "BENGALI", "TAMIL"):
        if name.startswith(script):
            return script
    return "OTHER"


def _mixed_script_tokens(text: str) -> tuple[str, ...]:
    """Single words built from more than one script.

    Legitimate in a few places, so this is reported rather than blocked.
    """
    mixed: list[str] = []
    for token in re.findall(r"\S+", text):
        scripts = {s for s in (_script_of(c) for c in token) if s}
        if len(scripts) > 1:
            mixed.append(token)
    return tuple(dict.fromkeys(mixed))[:10]


def looks_like_secret(token: str) -> bool:
    """Whether a token should never be sent to a translation service.

    Deliberately broad: a false positive costs one untranslated token, a false
    negative sends an API key to a third party.
    """
    value = str(token or "")
    if len(value) < 16:
        return False
    if re.match(r"^(?:sk|pk|rk)[-_][A-Za-z0-9_-]{12,}$", value):
        return True
    if re.match(r"^(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}$", value):
        return True
    if re.match(r"^xox[baprs]-[A-Za-z0-9-]{10,}$", value):
        return True
    if re.match(r"^AKIA[0-9A-Z]{16}$", value):
        return True
    if re.match(r"^ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", value):  # JWT
        return True
    # High-entropy mixed-case-and-digit blobs with no vowel run: not language.
    if len(value) >= 24 and re.match(r"^[A-Za-z0-9+/_=-]+$", value):
        has_digit = any(c.isdigit() for c in value)
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        if has_digit and has_upper and has_lower:
            return True
    return False
