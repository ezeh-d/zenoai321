"""Informal input -> plain English, without losing what the sentence meant.

DIFFERENT JOB FROM cognition.normalize()
----------------------------------------
`cognition.normalize()` already exists and is deliberately LOSSY: it
lower-cases, strips filler and throws away words, because its only consumer
is signal matching for the router. Feeding its output to the brain would lose
capitalisation, punctuation and negation.

This module produces text a person would recognise as their own sentence,
which is what the reasoning layer needs. It reuses `cognition._PIDGIN` as a
vocabulary seed rather than duplicating it -- the brief is explicit about not
duplicating existing systems.

THE RULE THAT MATTERS MOST
--------------------------
Negation. Every other error degrades quality; inverting a negation turns
"do not delete the file" into a delete command. Pidgin negation is
positional -- "make you no delete am" puts the negator before the verb where
English wants an auxiliary -- so it gets explicit, ordered rules and its own
tests rather than being left to a general substitution pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_PARTICIPLE = {
    "send": "sent", "do": "done", "go": "gone", "run": "run", "make": "made",
    "write": "written", "read": "read", "see": "seen", "take": "taken",
    "give": "given", "get": "got", "put": "put", "set": "set", "cut": "cut",
    "buy": "bought", "bring": "brought", "think": "thought", "catch": "caught",
    "find": "found", "hold": "held", "keep": "kept", "leave": "left",
    "lose": "lost", "pay": "paid", "say": "said", "sell": "sold",
    "tell": "told", "win": "won", "come": "come", "become": "become",
    "begin": "begun", "break": "broken", "choose": "chosen", "eat": "eaten",
    "fall": "fallen", "forget": "forgotten", "hear": "heard", "know": "known",
    "meet": "met", "speak": "spoken", "spend": "spent", "stand": "stood",
    "understand": "understood", "wear": "worn", "build": "built",
}


def past_participle(verb: str) -> str:
    """The completed form. Irregulars by table, the rest by suffix rule."""
    word = verb.lower()
    if word in _PARTICIPLE:
        return _PARTICIPLE[word]
    if word.endswith("e"):
        return word + "d"
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "ied"
    return word + "ed"


# "dey" marks the PROGRESSIVE, not the perfect: "you dey come" is "you are
# coming", not "you are come". Handling it with the participle table produced
# exactly that error.
_NO_DOUBLE = {"open", "check", "listen", "happen", "offer", "visit", "enter",
              "answer", "order", "gather", "deliver", "remember", "consider"}


def gerund(verb: str) -> str:
    word = verb.lower()
    if word.endswith("ie"):
        return word[:-2] + "ying"
    if word.endswith("ee") or word.endswith("ye") or word.endswith("oe"):
        return word + "ing"
    if word.endswith("e") and len(word) > 2:
        return word[:-1] + "ing"
    # Double a final consonant after a single stressed vowel: run -> running.
    # Words stressed on an earlier syllable do not double, hence _NO_DOUBLE.
    if (len(word) >= 3 and word not in _NO_DOUBLE
            and word[-1] not in "aeiouwxy"
            and word[-2] in "aeiou" and word[-3] not in "aeiou"):
        return word + word[-1] + "ing"
    return word + "ing"


def _gerund_sub(prefix: str, suffix: str = ""):
    def replace(match) -> str:
        return f"{prefix}{gerund(match.group(1))}{suffix}"
    return replace


def _participle_sub(prefix: str, suffix: str = ""):
    """Build a replacement callable that conjugates group 1 properly."""
    def replace(match: re.Match) -> str:
        return f"{prefix}{past_participle(match.group(1))}{suffix}"
    return replace


# Ordered. Longest and most structural first: "make you no X" must be seen
# before "make you" alone, or the negation is silently dropped.
_PIDGIN_RULES: tuple[tuple[str, str], ...] = (
    # --- negation, first and explicit -----------------------------------
    (r"\bmake\s+you\s+no\s+", "do not "),
    (r"\bmake\s+we\s+no\s+", "let us not "),
    (r"\bmake\s+i\s+no\s+", "let me not "),
    (r"\bno\s+go\s+", "will not "),
    (r"\bnever\s+finish\b", "has not finished"),
    (r"\be\s+never\s+", "it has not "),
    (r"\bi\s+no\s+wan\s+", "I do not want to "),
    (r"\byou\s+no\s+wan\s+", "you do not want to "),
    (r"\bi\s+no\s+go\s+", "I will not "),
    (r"\bi\s+no\s+sabi\b", "I do not know"),
    (r"\bi\s+no\s+", "I do not "),
    (r"\byou\s+no\s+", "you do not "),
    (r"\bwe\s+no\s+", "we do not "),
    (r"\byou\s+no\s+sabi\b", "you do not know"),
    (r"\bno\s+be\b", "is not"),
    (r"\bno\s+wahala\b", "no problem"),
    (r"\bnothing\s+dey\s+happen\b", "nothing is happening"),
    (r"\bno\s+dey\b", "does not"),

    # --- questions -------------------------------------------------------
    # The completed-aspect forms must precede the general "shey e don" rule:
    # once that fires, "finish" has lost its chance to become "finished" and
    # the sentence reads "Has it finish?".
    (r"\bshey\s+e\s+don\s+(\w+)\b", _participle_sub("has it ")),
    (r"\bshey\s+e\s+don\s+", "has it "),
    (r"\bshey\s+you\s+don\s+(\w+)\s+am\b", _participle_sub("have you ", " it")),
    (r"\bshey\s+you\s+don\s+(\w+)\b", _participle_sub("have you ")),
    (r"\bshey\s+you\s+dey\s+(\w+)\b", _gerund_sub("are you ")),
    (r"\bshey\s+e\s+dey\s+(\w+)\b", _gerund_sub("is it ")),
    (r"\bshey\s+you\s+dey\s+", "are you "),
    (r"\bshey\s+e\s+dey\s+", "is it "),
    (r"\bshey\s+you\s+", "have you "),
    (r"\bshey\b", "is it that"),
    (r"\bwetin\s+dey\s+happen\b", "what is happening"),
    (r"\bwetin\s+dey\b", "what is"),
    (r"\bwetin\b", "what"),
    (r"\bhow\s+far\b", "how are you"),
    (r"\babi\b", "or is it"),

    # --- intent ----------------------------------------------------------
    (r"\bi\s+wan\s+", "I want to "),
    (r"\bi\s+wanna\s+", "I want to "),
    (r"\bmake\s+i\s+", "let me "),
    (r"\bmake\s+we\s+", "let us "),
    (r"\bmake\s+you\s+", "please "),
    (r"\babeg\b", "please"),
    (r"\bbiko\b", "please"),

    # --- aspect ----------------------------------------------------------
    (r"\be\s+don\s+finish\b", "it has finished"),
    (r"\be\s+don\s+", "it has "),
    (r"\bdon\s+finish\b", "has finished"),
    (r"\bi\s+don\s+(\w+)\s+am\b", _participle_sub("I have ", " it")),
    (r"\bi\s+don\s+(\w+)\b", _participle_sub("I have ")),
    (r"\bi\s+don\s+", "I have "),
    (r"\byou\s+don\s+(\w+)\b", _participle_sub("you have ")),
    (r"\bi\s+dey\s+(\w+)\b", _gerund_sub("I am ")),
    (r"\byou\s+dey\s+(\w+)\b", _gerund_sub("you are ")),
    (r"\bwe\s+dey\s+(\w+)\b", _gerund_sub("we are ")),
    (r"\bthey\s+dey\s+(\w+)\b", _gerund_sub("they are ")),
    (r"\be\s+dey\s+(\w+)\b", _gerund_sub("it is ")),
    (r"\bdey\s+go\b", "is going"),
    (r"\bdey\b", "is"),

    # --- objects and pronouns -------------------------------------------
    (r"\bcheck\s+am\b", "check it"),
    (r"\bdo\s+am\b", "do it"),
    (r"\bopen\s+am\b", "open it"),
    (r"\bfix\s+am\b", "fix it"),
    (r"\bdelete\s+am\b", "delete it"),
    (r"\bbring\s+am\b", "bring it"),
    (r"\bcarry\s+am\b", "carry it"),
    (r"\bsend\s+am\b", "send it"),
    (r"\bshow\s+me\s+am\b", "show it to me"),
    (r"\bam\b(?=\s*[.?!,]|$)", "it"),

    # --- vocabulary ------------------------------------------------------
    (r"\bwahala\b", "problem"),
    (r"\bwey\b", "that"),
    (r"\bsabi\b", "know"),
    (r"\bcomot\b", "remove"),
    (r"\bpikin\b", "child"),
    (r"\bchop\b", "eat"),
    (r"\bgist\b", "news"),
    (r"\bvex\b", "angry"),
    (r"\boga\b", "boss"),
    (r"\bcarry\s+go\b", "continue"),
    (r"\bna\s+so\b", "that is right"),

    # --- discourse particles carrying no meaning -------------------------
    (r"\bjare\b", ""),
    (r"\bsha\b", ""),
    (r"\bo{2,}\b", ""),
)

# Texting and internet shorthand. Expansions only -- nothing here changes a
# claim, so it is safe to apply before meaning is established.
_SLANG: tuple[tuple[str, str], ...] = (
    (r"\bfinna\b", "about to"), (r"\bgonna\b", "going to"),
    (r"\bwanna\b", "want to"), (r"\bgotta\b", "have to"),
    (r"\blemme\b", "let me"), (r"\bgimme\b", "give me"),
    (r"\bkinda\b", "kind of"), (r"\bsorta\b", "sort of"),
    (r"\bcuz\b", "because"), (r"\bcos\b", "because"), (r"\bcus\b", "because"),
    (r"\bidk\b", "I do not know"), (r"\bidc\b", "I do not care"),
    (r"\bimo\b", "in my opinion"), (r"\bimho\b", "in my honest opinion"),
    (r"\bngl\b", "not going to lie"), (r"\btbh\b", "to be honest"),
    (r"\bfr\b", "for real"), (r"\brn\b", "right now"),
    (r"\bbrb\b", "be right back"), (r"\bbtw\b", "by the way"),
    (r"\basap\b", "as soon as possible"), (r"\bfyi\b", "for your information"),
    (r"\bthx\b", "thanks"), (r"\bpls\b", "please"), (r"\bplz\b", "please"),
    (r"\bu\b", "you"), (r"\bur\b", "your"), (r"\bpsa\b", "announcement"),
    (r"\bafaik\b", "as far as I know"), (r"\biirc\b", "if I recall correctly"),
    (r"\bdm\b", "direct message"), (r"\bsmth\b", "something"),
    (r"\bsmn\b", "someone"), (r"\bppl\b", "people"), (r"\bmsg\b", "message"),
)

# Frequent misspellings and phonetic spellings. Conservative on purpose --
# a wrong "correction" of a filename or a person's name is worse than leaving
# a typo alone, so `protect.py` masks those before this ever runs.
_TYPOS: tuple[tuple[str, str], ...] = (
    (r"\bspeack\b", "speak"), (r"\blanguge\b", "language"),
    (r"\blanguages?\b", None), (r"\bbuh\b", "but"),
    (r"\beverthing\b", "everything"), (r"\bverfify\b", "verify"),
    (r"\bnegociate\b", "negotiate"), (r"\bcheack\b", "check"),
    (r"\bchek\b", "check"), (r"\bteh\b", "the"), (r"\bthier\b", "their"),
    (r"\brecieve\b", "receive"), (r"\bseperate\b", "separate"),
    (r"\bdefinately\b", "definitely"), (r"\boccured\b", "occurred"),
    (r"\bhowfa\b", "how far"), (r"\bwhatsapp\b", None),
    (r"\bd\b", "the"), (r"\bdis\b", "this"), (r"\bdat\b", "that"),
    (r"\bwit\b", "with"), (r"\bnd\b", "and"),
)

_FILLERS = re.compile(
    r"(?<!\w)(?:um+|uh+|erm+|ehm+|hmm+)(?!\w)[,\s]*", re.IGNORECASE)

_IDIOMS: tuple[tuple[str, str], ...] = (
    (r"\bbreak a leg\b", "good luck"),
    (r"\bspill the beans\b", "reveal the secret"),
    (r"\bpiece of cake\b", "very easy"),
    (r"\bunder the weather\b", "unwell"),
    (r"\bhit the sack\b", "go to sleep"),
    (r"\bcall it a day\b", "stop working for today"),
    (r"\bon the same page\b", "in agreement"),
    (r"\bball is in your court\b", "it is your decision"),
    (r"\bcut to the chase\b", "get to the point"),
    (r"\bbite the bullet\b", "accept the difficult thing"),
)


def _compile(rules) -> tuple[tuple[re.Pattern, str], ...]:
    return tuple((re.compile(pattern, re.IGNORECASE), replacement)
                 for pattern, replacement in rules if replacement is not None)


_PIDGIN_C = _compile(_PIDGIN_RULES)
_SLANG_C = _compile(_SLANG)
_TYPOS_C = _compile(_TYPOS)
_IDIOMS_C = _compile(_IDIOMS)


@dataclass
class Normalisation:
    text: str
    applied: list[str] = field(default_factory=list)
    changed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "applied": self.applied, "changed": self.changed}


def _apply(text: str, rules, label: str, applied: list[str]) -> str:
    out = text
    for pattern, replacement in rules:
        new = pattern.sub(replacement, out)
        if new != out:
            applied.append(f"{label}:{pattern.pattern}")
            out = new
    return out


def _tidy(text: str) -> str:
    """Repair the spacing and capitalisation that substitution disturbs."""
    out = re.sub(r"\s+", " ", text).strip()
    out = re.sub(r"\s+([.,!?;:])", r"\1", out)
    out = re.sub(r"\bi\b", "I", out)
    if out:
        out = out[0].upper() + out[1:]
    # Substitution can leave a doubled auxiliary: "do not do not delete".
    out = re.sub(r"\b(do not|is not|has not)\s+\1\b", r"\1", out, flags=re.IGNORECASE)
    return out


def normalise(text: str, *, pidgin: bool = True, slang: bool = True,
              typos: bool = True, idioms: bool = True,
              fillers: bool = True) -> Normalisation:
    """Rewrite informal English/Pidgin into plain English.

    Runs on text that has already been through `protect.protect()`, so
    filenames, commands, entities and numbers are placeholders by this point
    and cannot be "corrected".
    """
    raw = str(text or "")
    if not raw.strip():
        return Normalisation(raw)

    applied: list[str] = []
    out = raw

    if fillers:
        stripped = _FILLERS.sub(" ", out)
        if stripped != out:
            applied.append("fillers")
            out = stripped

    # Pidgin before slang: "I wan" must become "I want to" before any
    # single-word rule can touch "wan".
    if pidgin:
        out = _apply(out, _PIDGIN_C, "pidgin", applied)
    if slang:
        out = _apply(out, _SLANG_C, "slang", applied)
    if typos:
        out = _apply(out, _TYPOS_C, "typo", applied)
    if idioms:
        out = _apply(out, _IDIOMS_C, "idiom", applied)

    out = _tidy(out)
    return Normalisation(out, applied, changed=out != raw)


def collapse_repeats(text: str) -> str:
    """"open open open Chrome" -> "open Chrome".

    Speech recognition stutters on the leading word. Only immediate
    repetitions of the SAME word are collapsed, and only past two -- "very
    very good" is deliberate emphasis and is left alone.
    """
    return re.sub(r"\b(\w+)(\s+\1\b){2,}", r"\1", str(text or ""), flags=re.IGNORECASE)
