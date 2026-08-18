"""Language, script and code-switch detection.

WHAT THIS IS AND IS NOT
-----------------------
This is a *fast, local, dependency-free* detector. It is deliberately not a
neural language-ID model: it runs on every single turn, so it has to cost
microseconds, and the expensive path is only worth entering when this one is
unsure.

It answers well:
  * which script is this written in            (near-certain, from Unicode)
  * is this confidently plain English          (the fast-path question)
  * does this contain Nigerian Pidgin          (function words are decisive)
  * does this mix languages                    (per-segment scoring)

It answers *approximately* for closely-related Latin-script languages, and it
says so: `confidence` drops and `candidates` carries more than one entry. A
caller that needs certainty escalates to `LanguageDetectorAdapter`, which can
be backed by a real model when one is installed.

WHY NOT JUST TRUST A MODEL
--------------------------
Because "everything Latin-script is English" is the failure the brief calls
out, and it is exactly what a confident-but-wrong model does on short input.
Function words are far more reliable than character n-grams at three words,
and short input is most of what an assistant receives.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

UNKNOWN = "unknown"

# Script ranges checked in order. First hit wins for a character.
_SCRIPT_PREFIX = (
    ("ARABIC", "Arabic"), ("HEBREW", "Hebrew"), ("CYRILLIC", "Cyrillic"),
    ("GREEK", "Greek"), ("DEVANAGARI", "Devanagari"), ("BENGALI", "Bengali"),
    ("TAMIL", "Tamil"), ("TELUGU", "Telugu"), ("THAI", "Thai"),
    ("HANGUL", "Hangul"), ("HIRAGANA", "Hiragana"), ("KATAKANA", "Katakana"),
    ("CJK", "Han"), ("ETHIOPIC", "Ethiopic"), ("ARMENIAN", "Armenian"),
    ("GEORGIAN", "Georgian"), ("LATIN", "Latin"),
)

# One script maps to a small set of plausible languages. This is where a
# non-Latin script buys near-certainty that Latin script never can.
_SCRIPT_LANGUAGES: dict[str, tuple[str, ...]] = {
    "Arabic": ("ar", "fa", "ur"), "Hebrew": ("he",), "Cyrillic": ("ru", "uk", "bg"),
    "Greek": ("el",), "Devanagari": ("hi", "mr", "ne"), "Bengali": ("bn",),
    "Tamil": ("ta",), "Telugu": ("te",), "Thai": ("th",), "Hangul": ("ko",),
    "Hiragana": ("ja",), "Katakana": ("ja",), "Han": ("zh", "ja"),
    "Ethiopic": ("am",), "Armenian": ("hy",), "Georgian": ("ka",),
}

# Function words: short, extremely common, and rarely borrowed. Content words
# are useless here because they cross languages constantly.
_MARKERS: dict[str, tuple[str, ...]] = {
    "en": ("the", "and", "is", "are", "you", "what", "please", "with", "this",
           "that", "have", "will", "can", "for", "not", "from", "there", "was",
           "my", "me", "it", "of", "to", "in", "on", "at", "be", "do", "does",
           "did", "how", "why", "when", "where", "who", "would", "could",
           "should", "about", "again", "now", "then", "just", "also",
           # Imperatives. A command like "Open Chrome" has no function word at
           # all, and without these English scores nothing on its own commands.
           "open", "close", "start", "stop", "run", "check", "send", "show",
           "find", "make", "create", "delete", "remove", "install", "update",
           "write", "read", "move", "copy", "call", "play", "search", "build",
           "deploy", "tell", "give", "take", "put", "set", "get", "add",
           "file", "files", "folder", "email", "message", "something",
           "everything", "anything", "nothing"),
    "pcm": ("abeg", "wetin", "wahala", "dey", "wey", "sabi", "oga", "na so",
            "no be", "make i", "make we", "make you", "how far", "shey",
            "abi", "jare", "sha", "comot", "pikin", "chop", "gist", "biko",
            "wahalla", "i wan", "e don", "e never", "carry go", "no wahala",
            "vex", "howfa", "wetin dey", "na wa",
            # Object-pronoun "am". Only ever as the object of a verb -- bare
            # "am" is English "I am", so the verb has to be part of the
            # marker or every English sentence becomes Pidgin.
            "delete am", "check am", "do am", "open am", "send am", "fix am",
            "bring am", "carry am", "close am", "run am", "show am",
            # Preverbal negation: the construction this engine exists to get
            # right, because dropping it inverts a destructive command.
            "make you no", "make we no", "make i no", "no go", "i no", "e no",
            "you no sabi", "i no sabi"),
    "yo": ("mo", "fẹ", "fe", "lọ", "lo", "ilé", "ile", "ṣe", "se", "níbo",
           "nibo", "bawo", "jọwọ", "jowo", "ẹ", "kí", "ki", "ni", "wà", "wa",
           "pẹlẹ", "pele", "oti", "dara"),
    "ig": ("kedu", "biko", "nna", "ndewo", "gịnị", "gini", "achọrọ", "achoro",
           "ka", "nke", "ọ", "ya", "anyị", "anyi", "maka", "dị", "di"),
    "ha": ("ina", "kwana", "yaya", "sannu", "don", "allah", "na", "ka", "ba",
           "kai", "wannan", "zan", "muna", "gaskiya"),
    "fr": ("le", "la", "les", "je", "tu", "vous", "est", "et", "pour", "avec",
           "ouvre", "ouvrir", "veux", "mon", "ma", "mes", "bonjour", "merci",
           "que", "qui", "une", "des", "dans", "pas", "ne", "s'il"),
    "es": ("el", "la", "los", "que", "por", "para", "con", "una", "abre",
           "abrir", "quiero", "hola", "gracias", "muy", "está", "esta", "pero",
           "como", "todo", "puedes"),
    "pt": ("o", "os", "que", "para", "com", "uma", "abrir", "abre", "quero",
           "olá", "ola", "obrigado", "não", "nao", "você", "voce", "isso"),
    "de": ("der", "die", "das", "und", "ist", "ich", "nicht", "mit", "für",
           "fur", "öffne", "offne", "bitte", "danke", "kann", "haben", "wird"),
    "it": ("il", "lo", "che", "per", "con", "una", "apri", "voglio", "ciao",
           "grazie", "sono", "questo", "molto", "anche"),
    "nl": ("de", "het", "een", "en", "ik", "niet", "met", "voor", "open",
           "alsjeblieft", "dank", "maar", "wat"),
    "sw": ("na", "ya", "wa", "kwa", "ni", "habari", "asante", "tafadhali",
           "nataka", "fungua", "sasa", "hii"),
    "tr": ("ve", "bir", "bu", "için", "icin", "ile", "değil", "degil", "aç",
           "ac", "lütfen", "lutfen", "teşekkür", "tesekkur", "istiyorum"),
    "pl": ("nie", "jest", "się", "sie", "na", "do", "otwórz", "otworz",
           "proszę", "prosze", "dziękuję", "dziekuje", "co", "jak"),
    "id": ("yang", "dan", "di", "ke", "tidak", "buka", "saya", "terima",
           "kasih", "tolong", "ini", "itu"),
}

# Latin-script spellings that betray a non-Latin-script language.
_TRANSLITERATED: dict[str, tuple[str, ...]] = {
    "ar": ("salam", "alaikum", "habibi", "inshallah", "shukran", "yalla",
           "marhaba", "kayf", "halak"),
    "hi": ("namaste", "kaise", "aap", "hai", "kya", "nahi", "accha", "theek",
           "bhai", "yaar", "kar", "raha"),
    "ja": ("konnichiwa", "arigato", "arigatou", "sumimasen", "ohayo",
           "desu", "kudasai", "onegai"),
    "ko": ("annyeong", "haseyo", "kamsahamnida", "juseyo"),
    "ru": ("privet", "spasibo", "pozhaluysta", "kak dela", "khorosho"),
    "el": ("kalimera", "efharisto", "yasou", "parakalo"),
    "fa": ("salaam", "merci", "khoobi", "mamnoon"),
}

# Words that are ordinary English AND function words somewhere else. A marker
# in this set is weak evidence: "open" is Dutch, but an English sentence
# containing "open" is not code-switched, and treating it as such fired on
# almost every desktop command ZENO receives.
_ENGLISH_COMMON = frozenset("""
a an and the this that these those i you he she it we they me him her us them
my your his its our their is am are was were be been being do does did done
have has had can could will would shall should may might must
open close start stop run check send show tell give take make let get put set
go come see look find know think want need use work play read write
in on at to for from with by of off up down out over under about into
no not never none nor but or so if then than as too very just only also
what when where why how which who whom all any some each every both few more
most other such same own here there now new old good bad big small
file files folder page site app time day week month year thing something
""".split())

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


@dataclass(frozen=True)
class Segment:
    """One run of text attributed to one language."""

    text: str
    language: str
    confidence: float
    start: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "language": self.language,
                "confidence": round(self.confidence, 3)}


@dataclass(frozen=True)
class Detection:
    language: str
    confidence: float
    script: str
    candidates: tuple[tuple[str, float], ...] = ()
    segments: tuple[Segment, ...] = ()
    scripts_present: tuple[str, ...] = ()

    evidence: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def code_switched(self) -> bool:
        """Two or more languages with evidence from DIFFERENT words.

        Clause-level winners were the first approach and were wrong in both
        directions. "Open Chrome and check the file" split into two clauses,
        one scoring English and one scoring nothing, and reported a switch.
        Meanwhile "Abeg ouvre Chrome" -- Pidgin and French inside one clause --
        reported none, because a clause has only one winner.

        Word-level evidence handles intra-sentence mixing, which is the case
        that actually matters.
        """
        languages = {lang for lang, words in self.evidence
                     if _counts_as_language(lang, words)}
        languages.discard(UNKNOWN)
        # Pidgin is English-based; "I wan check am" mixing the two is Pidgin,
        # not a code switch, and reporting one would fire on almost every
        # Nigerian sentence.
        if languages == {"en", "pcm"}:
            return False
        return len(languages) > 1

    @property
    def is_english(self) -> bool:
        return self.language == "en"

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "confidence": round(self.confidence, 3),
            "script": self.script,
            "scripts_present": list(self.scripts_present),
            "candidates": [[c, round(s, 3)] for c, s in self.candidates],
            "code_switched": self.code_switched,
            "segments": [s.as_dict() for s in self.segments] if self.code_switched else [],
        }


def _counts_as_language(language: str, words: tuple[str, ...]) -> bool:
    """Whether this evidence is enough to claim a second language is present.

    One marker that is also an ordinary English word proves nothing -- that
    is how "check the file" acquired Dutch. Either the marker is distinctive
    (not English), or there have to be at least two of them.
    """
    if not words:
        return False
    if language == "en":
        return True
    distinctive = [w for w in words if w not in _ENGLISH_COMMON]
    return bool(distinctive) or len(words) >= 2


def _script_char(char: str) -> str:
    try:
        name = unicodedata.name(char)
    except ValueError:
        return ""
    for prefix, script in _SCRIPT_PREFIX:
        if name.startswith(prefix) or (prefix == "CJK" and "CJK" in name):
            return script
    return ""


def scripts_in(text: str) -> dict[str, int]:
    """Character counts per script. The one near-certain signal available."""
    counts: dict[str, int] = {}
    for char in str(text or ""):
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            continue
        for prefix, script in _SCRIPT_PREFIX:
            if name.startswith(prefix) or (prefix == "CJK" and "CJK" in name):
                counts[script] = counts.get(script, 0) + 1
                break
    return counts


def _evidence_words(words: list[str], text: str) -> dict[str, tuple[str, ...]]:
    """Which words betray which language. The basis for code-switch detection."""
    lowered = [w.lower() for w in words]
    joined = " " + " ".join(lowered) + " "
    found: dict[str, list[str]] = {}
    for language, markers in _MARKERS.items():
        for marker in markers:
            if " " in marker:
                if f" {marker} " in joined:
                    found.setdefault(language, []).append(marker)
            elif marker in lowered:
                found.setdefault(language, []).append(marker)
    for language, markers in _TRANSLITERATED.items():
        for marker in markers:
            if marker in lowered:
                found.setdefault(language, []).append(marker)

    # A word claimed by several languages ("na" is Pidgin, Hausa and Polish)
    # is evidence for none of them on its own.
    claims: dict[str, int] = {}
    for hits in found.values():
        for word in hits:
            claims[word] = claims.get(word, 0) + 1
    return {lang: tuple(w for w in hits if claims[w] == 1)
            for lang, hits in found.items()}


def _score_words(words: list[str]) -> dict[str, float]:
    """Fraction of words that are function words of each language."""
    if not words:
        return {}
    lowered = [w.lower() for w in words]
    joined = " " + " ".join(lowered) + " "
    scores: dict[str, float] = {}

    for language, markers in _MARKERS.items():
        hits = 0
        for marker in markers:
            if " " in marker:
                if f" {marker} " in joined:
                    hits += 2          # a multi-word marker is strong evidence
            elif marker in lowered:
                hits += 1
        if hits:
            scores[language] = hits / max(len(lowered), 1)

    for language, markers in _TRANSLITERATED.items():
        hits = sum(1 for m in markers if m in lowered)
        if hits:
            # Transliterated evidence is strong: nobody types "konnichiwa"
            # by accident in an English sentence about something else.
            scores[language] = scores.get(language, 0.0) + (hits / len(lowered)) * 1.6

    return scores


def detect(text: str, *, segment: bool = True) -> Detection:
    """Identify the language(s) of `text`."""
    raw = str(text or "").strip()
    if not raw:
        return Detection(UNKNOWN, 0.0, "", (), ())

    script_counts = scripts_in(raw)
    scripts_present = tuple(sorted(script_counts, key=script_counts.get, reverse=True))
    script = scripts_present[0] if scripts_present else ""

    # A non-Latin script settles the question almost by itself.
    if script and script != "Latin":
        languages = _SCRIPT_LANGUAGES.get(script, ())
        total = sum(script_counts.values()) or 1
        share = script_counts.get(script, 0) / total
        candidates = tuple((lang, round(share, 3)) for lang in languages)
        language = languages[0] if languages else UNKNOWN
        # Han is genuinely ambiguous between Chinese and Japanese without kana.
        confidence = 0.95 * share if len(languages) == 1 else 0.7 * share
        segments = _segment(raw) if (segment and "Latin" in scripts_present) else ()
        latin_words = _WORD_RE.findall("".join(
            c for c in raw if not c.isalpha() or _script_char(c) == "Latin"))
        evidence = tuple(sorted(_evidence_words(latin_words, raw).items()))
        evidence = ((language, (script,)),) + tuple(
            (lang, words) for lang, words in evidence if words)
        return Detection(language, min(confidence, 0.99), script, candidates,
                         segments, scripts_present, evidence)

    words = _WORD_RE.findall(raw)
    scores = _score_words(words)
    evidence = tuple(sorted(_evidence_words(words, raw).items()))
    if not scores:
        # No function word matched. Short input like "Chrome" or "ok" lands
        # here; claiming a language would be invention.
        return Detection(UNKNOWN, 0.0, script or "Latin", (), (),
                         scripts_present, ())

    evidence = tuple(sorted(_evidence_words(words, raw).items()))
    # A language whose only evidence is words that are ordinary English --
    # Dutch "open", Hausa "na" -- must not outrank English. That is how
    # "Open Chrome" was classified as Dutch and then sent to a translation
    # model, costing 4.8 seconds to return the text unchanged.
    evidence_map = dict(evidence)
    for language in list(scores):
        if language == "en":
            continue
        if not _counts_as_language(language, evidence_map.get(language, ())):
            scores[language] *= 0.05

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    # Confidence is about SEPARATION, not raw score. "the and is" scores high
    # for English partly because English markers are common; what matters is
    # how far ahead of the next language it is.
    lead = top_score - runner_up
    confidence = min(0.99, 0.45 + lead * 2.2 + min(len(words), 12) * 0.015)

    # Pidgin outranks English when its markers are present at all: "abeg" and
    # "wetin" do not appear in English, so their presence is decisive even
    # though most of the surrounding words are English.
    if "pcm" in scores and scores["pcm"] > 0 and top == "en":
        top, confidence = "pcm", max(confidence, 0.8)

    segments = _segment(raw) if segment else ()
    candidates = tuple((lang, round(score, 3)) for lang, score in ranked[:4])
    return Detection(top, confidence, script or "Latin", candidates, segments,
                     scripts_present, evidence)


def _segment(text: str) -> tuple[Segment, ...]:
    """Attribute each clause to a language, for code-switch detection.

    Splits on punctuation and conjunctions rather than every word: a word is
    far too little evidence, and single-word attribution produces confident
    nonsense. Clauses are the smallest unit that carries a function word.
    """
    pieces = [p for p in re.split(r"(?<=[.!?,;:])\s+|\s+(?:because|but|and|et|y|und|e)\s+",
                                  text) if p and p.strip()]
    if len(pieces) < 2:
        pieces = [text]

    out: list[Segment] = []
    cursor = 0
    for piece in pieces:
        start = text.find(piece, cursor)
        cursor = start + len(piece) if start >= 0 else cursor
        words = _WORD_RE.findall(piece)
        if not words:
            continue
        scripts = scripts_in(piece)
        non_latin = [s for s in scripts if s != "Latin"]
        if non_latin:
            languages = _SCRIPT_LANGUAGES.get(non_latin[0], ())
            out.append(Segment(piece.strip(), languages[0] if languages else UNKNOWN,
                               0.9, max(start, 0)))
            continue
        scores = _score_words(words)
        if not scores:
            out.append(Segment(piece.strip(), UNKNOWN, 0.0, max(start, 0)))
            continue
        best, score = max(scores.items(), key=lambda kv: kv[1])
        if "pcm" in scores and best == "en":
            best = "pcm"
        out.append(Segment(piece.strip(), best, min(0.95, 0.4 + score * 2),
                           max(start, 0)))
    return tuple(out)


def is_confidently_english(text: str) -> bool:
    """The fast-path question, answered as cheaply as possible.

    Used to skip the whole pipeline. It must be conservative: a false `True`
    means a Yoruba sentence is fed to the brain untranslated, while a false
    `False` costs only a few milliseconds of unnecessary work.
    """
    raw = str(text or "").strip()
    if not raw:
        return True
    counts = scripts_in(raw)
    if any(script != "Latin" for script in counts):
        return False
    detection = detect(raw, segment=False)
    # Any distinctive non-English evidence disqualifies the fast path, even
    # when English still wins the count. "Make you no delete am" scored
    # English on the single word "you", fast-pathed unchanged, and delivered
    # an un-normalised Pidgin NEGATION to the brain -- the exact failure this
    # engine exists to prevent.
    others = {lang for lang, hits in detection.evidence
              if lang != "en" and _counts_as_language(lang, hits)}
    if others:
        return False
    if detection.language == "en" and detection.confidence >= 0.6:
        return True
    # Very short input with no marker at all ("ok", "yes", "Chrome") is
    # treated as English: there is nothing to translate either way.
    return detection.language == UNKNOWN and len(_WORD_RE.findall(raw)) <= 3
