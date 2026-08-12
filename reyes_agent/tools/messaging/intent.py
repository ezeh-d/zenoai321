"""Turning one spoken sentence into a messaging plan.

NAMES ARE NOT AN ENGLISH PROBLEM
--------------------------------
The owner's people are called Ayomide, Eniola, Tosin -- and tomorrow someone
else in a script this file has never seen. So there is NO list of known
names, no spell-check against a roster, and no assumption that a destination
is an English word. A destination is simply whatever the owner named, in
whatever language they named it, and it is passed through untouched for the
app's own search to resolve. Slack knows who is in Slack; this does not have
to.

What IS matched is the small set of VERBS and PREPOSITIONS that frame a
request -- "send", "tell", "message", "to", "in". Those are recognised across
several languages the owner is likely to use, and when none of them match,
the sentence is handed to the brain rather than guessed at. The brain speaks
every language; the point of this file is to be fast when the shape is
obvious, not to replace it.

WHY A PLAN AND NOT A SINGLE CALL
--------------------------------
    "Do not require the owner to issue three separate commands."

"Open Slack, go to General and send good night" is one intention with three
actions. The planner emits them as an ordered plan so the router can execute
them in sequence and name the step that failed.
"""

from __future__ import annotations

import re
from typing import Any

from reyes_agent.tools.messaging import models

# Which app was named. Aliases only -- never a guess from context, because
# sending to the wrong platform is not a recoverable mistake.
PLATFORM_WORDS: dict[str, str] = {
    "slack": models.SLACK,
    "whatsapp": models.WHATSAPP, "whats app": models.WHATSAPP, "wa": models.WHATSAPP,
    "telegram": models.TELEGRAM, "tg": models.TELEGRAM,
    "discord": models.DISCORD,
}

# Verbs that mean "put this message somewhere", in the languages the owner is
# most likely to mix in. Yoruba, Igbo, Hausa, Pidgin, French, Spanish and
# Portuguese are included because Nigerian English borrows freely and a
# request should not fail for being said naturally.
SEND_WORDS = (
    "send", "tell", "message", "msg", "text", "write", "say", "post", "ping",
    "reply", "forward",
    # `type` and `draft` introduce a message too. Whether it is SUBMITTED is a
    # separate question, answered by DRAFT_MARKERS -- not by the verb.
    "type", "draft", "compose",
    "so", "so fun", "ranse", "ránṣẹ́", "fi", "kowe",          # Yoruba
    "gwa", "ziga", "dee",                                      # Igbo
    "aika", "fada", "rubuta",                                  # Hausa
    "envoyer", "envoie", "dis",                                # French
    "enviar", "envia", "dile", "manda",                        # Spanish/Portuguese
)

# Words that introduce a destination.
TO_WORDS = ("to", "in", "on", "at", "into", "the group", "group",
            "fun", "si", "sí",           # Yoruba: to / for
            "nye",                        # Igbo
            "wa", "ga",                   # Hausa
            "a", "au", "dans", "para", "en")

# "type it but don't send" -- the distinction the brief is explicit about.
DRAFT_MARKERS = ("don't send", "dont send", "do not send", "without sending",
                 "but don't send", "draft", "just type", "type only",
                 "leave it unsent", "no ma se", "má fi ránṣẹ́")

# Destination kind, when the owner states it.
KIND_WORDS: dict[str, str] = {
    "channel": models.CHANNEL, "group": models.GROUP, "chat": models.GROUP,
    "dm": models.DM, "direct message": models.DM, "contact": models.CONTACT,
    "thread": models.THREAD,
}

# The default kind per platform, used only when the owner did not say. Slack
# and Discord are channel-shaped; WhatsApp and Telegram are people-shaped.
DEFAULT_KIND = {models.SLACK: models.CHANNEL, models.DISCORD: models.CHANNEL,
                models.WHATSAPP: models.CONTACT, models.TELEGRAM: models.CONTACT}

_QUOTED = re.compile(r"[\"'‘’“”]([^\"'‘’“”]{1,900})"
                     r"[\"'‘’“”]")


def platform_in(text: str) -> str:
    low = f" {(text or '').lower()} "
    for word, platform in sorted(PLATFORM_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", low):
            return platform
    return ""


def wants_draft(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in DRAFT_MARKERS)


def parse(text: str, *, default_platform: str = "") -> dict[str, Any]:
    """Best-effort decomposition. `confident` says whether to trust it.

    When this is not confident the caller should let the model fill the
    fields instead -- an uncertain guess about WHO receives a message is
    exactly the thing not to act on.
    """
    said = (text or "").strip()
    low = said.lower()
    platform = platform_in(said) or default_platform
    draft = wants_draft(said)

    message, destination = "", ""

    # A quoted span is the message, and it is unambiguous. Preferred over
    # every heuristic below.
    quoted = _QUOTED.search(said)
    if quoted:
        message = quoted.group(1).strip()
        remainder = (said[:quoted.start()] + " " + said[quoted.end():])
        destination = _destination_from(remainder)
    else:
        # Remove the draft instruction FIRST. It contains a send-verb -- "but
        # don't SEND it" -- and leaving it in makes that the verb the message
        # is read from, yielding the message "it".
        destination, message = _split(_without_draft(said))

    kind = ""
    for word, value in KIND_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            kind = value
            break
    if not kind and platform:
        kind = DEFAULT_KIND.get(platform, "")

    destination = destination.strip(" .,:;!?")
    message = message.strip(" .,:;")
    return {"platform": platform, "destination": destination,
            "message": message, "destination_type": kind,
            "send": not draft,
            "confident": _trustworthy(platform, destination, message),
            "why_unsure": _why_unsure(platform, destination, message),
            "said": said}


def _trustworthy(platform: str, destination: str, message: str) -> bool:
    """Would acting on this parse be safe.

    THIS IS THE MOST IMPORTANT FUNCTION IN THE FILE. A regex cannot parse
    every language, and the failure that matters is not "I could not parse it"
    -- that is recoverable. It is a CONFIDENT WRONG destination, which sends
    the owner's words to the wrong person and cannot be taken back.

    So confidence requires a parse that is clean on its own terms: all three
    fields present, and neither the destination nor the message polluted with
    the scaffolding words that mean the split landed in the wrong place. When
    that does not hold, the model is asked instead -- it speaks every language
    this file does not.
    """
    return not _why_unsure(platform, destination, message)


def _why_unsure(platform: str, destination: str, message: str) -> str:
    if not platform:
        return "no messaging app was named"
    if not destination:
        return "no destination was identified"
    if not message:
        return "no message text was identified"

    dest_words = [_clean(w).lower() for w in destination.split()]
    body_words = [_clean(w).lower() for w in message.split()]

    if len(dest_words) > 3:
        return "the destination ran on too long to be a name"
    # Scaffolding inside a field means the sentence was cut in the wrong place.
    for word in dest_words:
        if word in PLATFORM_WORDS:
            return "the destination still contains an app name"
        if word in SEND_WORDS or word in TO_WORDS:
            return "the destination still contains part of the instruction"
    for word in body_words[:2]:
        if word in PLATFORM_WORDS or word in TO_WORDS:
            return "the message still contains part of the instruction"
    return ""


# A destination ENDS at any of these. Without them a name absorbs the rest of
# the sentence -- "to Ayomide on WhatsApp that I am on my way" yielded the
# destination "WhatsApp that I am", which would have opened the wrong chat or
# none at all. Conjunctions and complementisers across the same languages as
# the verbs, because that is where clauses actually break.
STOP_WORDS = frozenset({
    "and", "then", "that", "saying", "says", "said", "with", "about",
    "but", "so", "if", "when", "please", "pls",
    "pe", "ki", "ti", "ni",          # Yoruba
    "na", "ka",                       # Igbo / Hausa
    "que", "qu", "quil", "de", "sur", "dans", "sobre", "por",  # French/Spanish
    *PLATFORM_WORDS.keys(),           # never let an app name become a name
    *SEND_WORDS,
    *TO_WORDS,
})

# Nouns appended for grammar, not identity: "the general group" names
# `general`. Stripped from either end.
FILLER = frozenset({"the", "my", "our", "a", "an",
                    "group", "channel", "chat", "team", "dm", "conversation"})


def _clean(token: str) -> str:
    return token.strip(" .,:;!?#\"'‘’“”")


def _destination_from(fragment: str) -> str:
    """The name after a preposition, in whatever language it was said."""
    words = [w for w in re.split(r"\s+", fragment.strip()) if w]
    lowered = [_clean(w).lower() for w in words]

    for index, word in enumerate(lowered):
        if word not in TO_WORDS or index + 1 >= len(words):
            continue
        tail: list[str] = []
        for offset in range(index + 1, len(words)):
            clean, low = _clean(words[offset]), lowered[offset]
            if not clean:
                break
            if low in FILLER and not tail:
                continue            # skip a leading "the"
            if low in STOP_WORDS or low in FILLER:
                break
            tail.append(clean)
            if len(tail) >= 3:      # real destinations are short
                break
        while tail and _clean(tail[-1]).lower() in FILLER:
            tail.pop()
        if tail:
            return " ".join(tail)
    return ""


def _split(said: str) -> tuple[str, str]:
    """(destination, message) from an unquoted sentence."""
    words = [w for w in said.split() if w]
    lowered = [_clean(w).lower() for w in words]

    # The LAST send-verb: "open slack, go to general and send good night" has
    # "go" earlier, but the message follows "send".
    verb = -1
    for index, word in enumerate(lowered):
        if word in SEND_WORDS:
            verb = index
    if verb < 0:
        return _destination_from(said), ""

    after = words[verb + 1:]
    lowered_after = lowered[verb + 1:]

    # Shape A: "send <message> to <destination>".
    for index, word in enumerate(lowered_after):
        if word not in TO_WORDS:
            continue
        message = _strip_tail(" ".join(after[:index]))
        # A message that STARTS with a preposition means this split landed
        # mid-phrase: "send a message to Ayomide on WhatsApp" would otherwise
        # cut at "on", giving the message "to Ayomide" and the destination
        # "way". Skip and let a later shape handle it.
        if not message or _clean(message.split()[0]).lower() in TO_WORDS:
            continue
        destination = _destination_from(" ".join(after[index:]))
        if destination:
            return destination, message

    # Shape B: "tell <destination> <message>" -- the name sits right after the
    # verb. Only ONE token is taken: a longer name needs a preposition or
    # quotes, because "tell John Mary is here" cannot be resolved by guessing.
    destination = _destination_from(said)
    if destination:
        # Everything AFTER the destination is the message. Stripping the
        # destination tokens off the front of `after` instead left the
        # scaffolding in place -- the message came out as "to Ayomide on
        # WhatsApp that I am on my way".
        return destination, _strip_tail(_after_destination(words, destination))

    if len(after) >= 2:
        index = 1 if lowered_after[0] in FILLER and len(after) >= 3 else 0
        head = _clean(after[index])          # "tell the general good night"
        body = _strip_scaffolding(after[index + 1:])
        return head, _strip_tail(" ".join(body))
    return "", _strip_tail(" ".join(_strip_scaffolding(after)))


def _without_draft(text: str) -> str:
    """The sentence with any trailing draft instruction removed."""
    low = text.lower()
    cut = len(text)
    for marker in DRAFT_MARKERS:
        found = low.find(marker)
        if found > 0:
            cut = min(cut, found)
    return text[:cut].strip().rstrip(",").strip()


def _after_destination(words: list[str], destination: str) -> str:
    """The message body that follows the destination in the sentence."""
    tokens = [_clean(w).lower() for w in destination.split()]
    lowered = [_clean(w).lower() for w in words]
    for start in range(len(lowered) - len(tokens) + 1):
        if lowered[start:start + len(tokens)] != tokens:
            continue
        tail = words[start + len(tokens):]
        # Drop the scaffolding between the name and what was actually said:
        # "on WhatsApp that I am on my way" -> "I am on my way".
        return " ".join(_strip_scaffolding(tail)).strip()
    return ""


def _strip_scaffolding(tail: list[str]) -> list[str]:
    """Drop the words between a name and what was actually said.

    "General AND SEND good night" -> "good night".
    "Ayomide ON WHATSAPP THAT I am on my way" -> "I am on my way".
    """
    lead = {"that", "saying", "say", "pe", "que", "ki", "na",
            "and", "then", "please", "pls", "just"}
    tail = list(tail)
    while tail:
        head = _clean(tail[0]).lower()
        if (head in TO_WORDS or head in PLATFORM_WORDS or head in lead
                or head in SEND_WORDS):
            tail.pop(0)
            continue
        break
    return tail


def _strip_lead(text: str) -> str:
    """Drop a complementiser the owner used to introduce the message.

    "tell Ayomide THAT I am on my way" -- the message is "I am on my way";
    keeping "that" would send a sentence the owner did not say.
    """
    words = text.split()
    while words and _clean(words[0]).lower() in {
            "that", "saying", "say", "pe", "que", "ki", "na"}:
        words.pop(0)
    return " ".join(words)


def _strip_tail(text: str) -> str:
    """Remove a trailing draft instruction from the message body.

    "type good night but don't send it" must put `good night` in the
    composer -- not `good night but don't send it`.
    """
    low = text.lower()
    for marker in DRAFT_MARKERS:
        found = low.find(marker)
        if found > 0:
            text = text[:found]
            low = text.lower()
    return re.sub(r"\s+(but|and|then)\s*$", "", text.strip(), flags=re.IGNORECASE).strip()


def plan(text: str, *, default_platform: str = "") -> dict[str, Any]:
    """The ordered actions one sentence implies.

    Emitted as data rather than executed here, so the caller can show the
    owner what is about to happen and the router can name the failing step.
    """
    parsed = parse(text, default_platform=default_platform)
    platform = parsed["platform"]
    steps: list[dict[str, Any]] = []
    if platform:
        steps.append({"tool": "open_app", "app": platform})
    if parsed["destination"]:
        steps.append({"tool": "messaging.open_destination", "platform": platform,
                      "destination": parsed["destination"],
                      "destination_type": parsed["destination_type"]})
    if parsed["message"]:
        steps.append({"tool": ("messaging.send_message" if parsed["send"]
                               else "messaging.type_message"),
                      "platform": platform, "destination": parsed["destination"],
                      "message": parsed["message"]})
    return {**parsed, "steps": steps}
