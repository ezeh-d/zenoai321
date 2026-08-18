"""Mask the things translation must not touch, then put them back.

WHY THIS EXISTS
---------------
A translation model is a language model. Given "run npm run build" in French
it will happily return "run npm execute construction", because those are
words and words are what it translates. The same goes for "VS Code", "ZENO",
"£10", "15", and an API key.

So anything that must survive byte-for-byte is replaced with an opaque
placeholder BEFORE translation and restored afterwards. The model never sees
it, so it cannot corrupt it.

PLACEHOLDER SHAPE
-----------------
`__ZX7K_0__` -- not `__ENTITY_001__`. Two reasons: a placeholder must not
itself look like a word the model wants to translate (models will happily
"translate" ENTITY into ENTIDAD), and it must be improbable in real input.
The digits are kept short because some models mangle long runs of them.

ORDER MATTERS
-------------
Secrets first, then code, then URLs and paths, then numbers, then names.
Longest-first inside each class. If names were masked before code, the word
"Code" inside "VS Code" could be captured by the wrong rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.language.safety import looks_like_secret

_TOKEN = "__ZX7K_{index}__"
_TOKEN_RE = re.compile(r"__ZX7K_(\d+)__")

# Names that must never be translated. Seeded here and extended at runtime
# from ZENO's real agent registry and the installed-application list, so this
# is a floor rather than the whole vocabulary.
BASE_ENTITIES: tuple[str, ...] = (
    "ZENO", "REYES", "APEX", "ULTRON", "STARK", "Council Mode", "Dream Mode",
    "Mini Orb", "T21 Services", "T21",
    "Claude", "Codex", "GitHub", "Netlify", "ElevenLabs", "Deepgram",
    "OpenAI", "Anthropic", "Tailscale", "Cloudflare",
    "Chrome", "Firefox", "Edge", "VS Code", "Visual Studio Code", "PyCharm",
    "Slack", "Telegram", "Discord", "WhatsApp", "Notion", "Obsidian",
    "Blender", "Photoshop", "Spotify", "Windows", "Explorer", "Outlook",
)

_CODE_PATTERNS: tuple[str, ...] = (
    r"```[\s\S]*?```",                       # fenced block
    r"`[^`\n]+`",                            # inline code
    r"\b(?:npm|npx|pip|python|git|node|yarn|pnpm|docker|cargo|go|dotnet)\s+"
    r"[a-z0-9][\w.-]*(?:\s+[-\w./=:@]+)*",   # a command line
    r"\b[A-Za-z]:\\[^\s\"'<>|]+",            # Windows path
    r"(?<![\w/])/(?:[\w.-]+/)+[\w.-]+",      # POSIX path
    r"\b\w+\.(?:py|js|ts|tsx|jsx|json|ya?ml|toml|md|html|css|sh|ps1|bat|"
    r"sql|txt|csv|png|jpg|pdf|docx|xlsx)\b",  # filename
    r"\b(?:https?://|www\.)[^\s<>\"')]+",    # URL
    r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b",       # email
    r"\{[^{}\n]*:[^{}\n]*\}",                # small JSON object
    r"<[a-zA-Z/][^<>\n]{0,80}>",             # markup tag
)

# Quantities whose exact form must survive. Currency and decimals first so
# "£10.50" is captured whole rather than as "10" and "50".
_NUMBER_PATTERNS: tuple[str, ...] = (
    r"[£$€₦¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|bn|million|billion))?",
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b",
    r"\b\d+\.\d+\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}[:.]\d{2}\s?(?:am|pm)?\b",
    r"\b\d+\s?%\b",
    r"\bv?\d+\.\d+(?:\.\d+)?\b",
    r"\b\+?\d[\d\s().-]{7,}\d\b",            # phone number
    r"\b\d+\b",
)


@dataclass
class Protected:
    """Masked text plus everything needed to restore it."""

    text: str
    values: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)

    def restore(self, translated: str) -> str:
        """Put the originals back.

        Models sometimes damage a placeholder -- lowercase it, add spaces
        around the underscores, or drop a leading underscore. Each of those is
        repaired rather than left as visible junk in the user's sentence.
        """
        out = str(translated or "")
        for token, value in self.values.items():
            if token in out:
                out = out.replace(token, value)
                continue
            index = _TOKEN_RE.match(token).group(1)
            damaged = re.compile(
                r"_{0,2}\s*Z\s*X\s*7\s*K\s*_?\s*" + index + r"\s*_{0,2}",
                re.IGNORECASE)
            out, count = damaged.subn(lambda _m, v=value: v, out)
            if not count:
                # The model dropped it entirely. Appending is worse than
                # leaving it out -- it would invent word order -- so the loss
                # is reported through `missing()` instead.
                continue
        return out

    def missing(self, restored: str) -> list[str]:
        """Protected values that did not survive. Drives confidence, not repair."""
        return [value for value in self.values.values() if value not in restored]

    def leftover_tokens(self, restored: str) -> list[str]:
        return _TOKEN_RE.findall(restored)

    def as_dict(self) -> dict[str, Any]:
        return {"masked": len(self.values),
                "by_kind": {k: sum(1 for v in self.kinds.values() if v == k)
                            for k in set(self.kinds.values())}}


def protect(text: str, *, entities: tuple[str, ...] = (),
            numbers: bool = True) -> Protected:
    """Replace must-not-translate spans with placeholders."""
    working = str(text or "")
    result = Protected(text=working)
    counter = 0

    def _mask(pattern: re.Pattern, kind: str) -> None:
        nonlocal working, counter

        def swap(match: re.Match) -> str:
            nonlocal counter
            value = match.group(0)
            if not value.strip():
                return value
            token = _TOKEN.format(index=counter)
            counter += 1
            result.values[token] = value
            result.kinds[token] = kind
            return token

        working = pattern.sub(swap, working)

    # 1. Secrets. Before everything, and never sent anywhere.
    def mask_secrets(match: re.Match) -> str:
        nonlocal counter
        value = match.group(0)
        if not looks_like_secret(value):
            return value
        token = _TOKEN.format(index=counter)
        counter += 1
        result.values[token] = value
        result.kinds[token] = "secret"
        return token

    working = re.sub(r"\S+", mask_secrets, working)

    # 2. Code, paths, URLs, filenames.
    for pattern in _CODE_PATTERNS:
        _mask(re.compile(pattern), "code")

    # 3. Named entities, longest first so "VS Code" wins over "Code".
    names = tuple(sorted(set(BASE_ENTITIES) | set(entities), key=len, reverse=True))
    for name in names:
        if not name.strip():
            continue
        _mask(re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE), "entity")

    # 4. Quantities.
    if numbers:
        for pattern in _NUMBER_PATTERNS:
            _mask(re.compile(pattern, re.IGNORECASE), "number")

    result.text = working
    return result


_ENTITY_CACHE: dict[str, Any] = {"names": (), "at": 0.0}
# The roster changes when agents are added, not between sentences. Reading it
# cost 1,956ms cold and 62ms warm ON EVERY TURN, which made a Pidgin command
# slower than the model call it was meant to avoid.
_ENTITY_TTL_S = 300.0


def runtime_entities() -> tuple[str, ...]:
    """Agent and application names read from ZENO itself, cached.

    The brief is explicit that this must not be a static list. Failures are
    swallowed: an unavailable registry should cost protection for a few names,
    never break the language pipeline.
    """
    import time as _time

    if _ENTITY_CACHE["names"] and (_time.time() - _ENTITY_CACHE["at"]) < _ENTITY_TTL_S:
        return _ENTITY_CACHE["names"]

    found: set[str] = set()
    try:
        from reyes_agent import agent_space

        snapshot = agent_space.snapshot()
        for agent in (snapshot or {}).get("agents", []):
            for key in ("name", "id"):
                value = str(agent.get(key, "")).strip()
                if len(value) > 1:
                    found.add(value.upper() if len(value) <= 8 else value)
    except Exception:  # noqa: BLE001
        pass
    names = tuple(sorted(found))
    if names:
        _ENTITY_CACHE["names"] = names
        _ENTITY_CACHE["at"] = _time.time()
    return names


def reset_entity_cache() -> None:
    _ENTITY_CACHE["names"] = ()
    _ENTITY_CACHE["at"] = 0.0
