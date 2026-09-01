"""Turn display text into SPEAKABLE text.

ZENO should not read markdown, URLs, code fences or stray symbols aloud. This
keeps the DISPLAYED text untouched and produces a spoken form: headings without
the hashes, links spoken as their label, code fences summarised, common symbols
voiced, bullets flattened. Meaning-preserving and conservative -- when unsure it
leaves text alone rather than mangling it. Deterministic, no model.
"""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```[\w+-]*\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_BARE_URL = re.compile(r"\bhttps?://([^\s)]+)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BOLD_ITALIC = re.compile(r"(\*\*|\*|__|_)(.+?)\1")
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_NUM_BULLET = re.compile(r"^\s*\d+\.\s+", re.M)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]")

# Symbols worth voicing when they stand alone (not inside a word/number run).
_SYMBOLS = [
    (re.compile(r"\s&\s"), " and "),
    (re.compile(r"(\d)\s*%"), r"\1 percent"),
    (re.compile(r"\s/\s"), " or "),
    (re.compile(r"\s*=>\s*"), " leads to "),
    (re.compile(r"\s*->\s*"), " to "),
]
_MD_LEFTOVER = re.compile(r"[#>`*_~]")


def _domain(url: str) -> str:
    host = url.split("/")[0]
    return host[4:] if host.startswith("www.") else host


def prepare_for_speech(text: str) -> str:
    """A speakable version of `text`. Never raises; returns the input on any
    unexpected failure so speech still happens."""
    try:
        s = str(text or "")
        if not s.strip():
            return ""
        # code: a fenced block becomes a short spoken marker; inline keeps content
        s = _CODE_FENCE.sub(lambda m: " (code) " if m.group(1).strip() else " ", s)
        s = _INLINE_CODE.sub(r"\1", s)
        # links: keep the human label; a bare URL becomes its domain, spoken calmly
        s = _MD_LINK.sub(r"\1", s)
        s = _BARE_URL.sub(lambda m: f"the link {_domain(m.group(1))}", s)
        # structure markers
        s = _HEADING.sub("", s)
        s = _BOLD_ITALIC.sub(r"\2", s)
        s = _BULLET.sub("", s)
        s = _NUM_BULLET.sub("", s)
        s = _TABLE_ROW.sub(lambda m: m.group(0).strip().strip("|").replace("|", ", "), s)
        # symbols and emoji
        for pat, repl in _SYMBOLS:
            s = pat.sub(repl, s)
        s = _EMOJI.sub("", s)
        s = _MD_LEFTOVER.sub("", s)
        # whitespace: collapse, but keep sentence structure (single newlines ->
        # a pause-worthy boundary the SentenceStreamer/TTS handles naturally)
        s = _MULTISPACE.sub(" ", s)
        s = _MULTINEWLINE.sub("\n\n", s)
        return s.strip()
    except Exception:  # noqa: BLE001
        return str(text or "")
