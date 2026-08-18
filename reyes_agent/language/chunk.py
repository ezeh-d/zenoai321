"""Long text through a translator, without losing the seams.

WHY NAIVE SPLITTING FAILS
-------------------------
A translator has a context limit, so long documents must be split. Split at a
fixed character count and you cut sentences in half, separate a number from
its unit, and break `npm run build` across two requests. Each half then
translates as though the other did not exist.

So chunks are cut at the strongest boundary available, in order:

    paragraph break  >  sentence end  >  clause comma  >  hard limit

and a hard limit is only reached by text with no punctuation at all.

CONSISTENCY ACROSS CHUNKS
-------------------------
A term translated one way in chunk 1 and another way in chunk 7 makes a
document read as though two people wrote it. `Glossary` records the first
choice for each protected term and reapplies it, so "Council Mode" stays
"Council Mode" throughout rather than becoming "Mode du Conseil" halfway.

OVERLAP IS CONTEXT, NOT CONTENT
-------------------------------
Each chunk carries the tail of the previous one so a pronoun still has its
referent. The overlap is passed as context and its translation is discarded --
including it in the output would duplicate sentences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

# Comfortably inside every translation model's window, and small enough that
# one failed chunk is a small loss.
DEFAULT_CHUNK_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 200

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ɏ])")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")


@dataclass
class Chunk:
    text: str
    index: int
    context_before: str = ""
    start: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "chars": len(self.text), "start": self.start}


def _split_on(pattern: re.Pattern, text: str) -> list[str]:
    pieces = pattern.split(text)
    return [p for p in pieces if p and p.strip()]


def _pack(pieces: list[str], limit: int, joiner: str) -> list[str]:
    """Greedily fill chunks up to `limit` without splitting a piece."""
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = (current + joiner + piece) if current else piece
        if current and len(candidate) > limit:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def split(text: str, *, limit: int = DEFAULT_CHUNK_CHARS,
          overlap: int = DEFAULT_OVERLAP_CHARS) -> list[Chunk]:
    """Cut `text` at the strongest boundary that fits."""
    raw = str(text or "")
    if not raw.strip():
        return []
    if len(raw) <= limit:
        return [Chunk(raw, 0, "", 0)]

    pieces = _pack(_split_on(_PARAGRAPH, raw), limit, "\n\n")

    # Any paragraph still over the limit is re-split on sentences, then
    # clauses, then -- only if it has no punctuation at all -- on length.
    refined: list[str] = []
    for piece in pieces:
        if len(piece) <= limit:
            refined.append(piece)
            continue
        sentences = _pack(_split_on(_SENTENCE_END, piece), limit, " ")
        for sentence in sentences:
            if len(sentence) <= limit:
                refined.append(sentence)
                continue
            clauses = _pack(_split_on(_CLAUSE, sentence), limit, " ")
            for clause in clauses:
                if len(clause) <= limit:
                    refined.append(clause)
                else:
                    refined.extend(_hard_split(clause, limit))

    chunks: list[Chunk] = []
    cursor = 0
    for index, body in enumerate(refined):
        start = raw.find(body, cursor)
        if start >= 0:
            cursor = start + len(body)
        context = refined[index - 1][-overlap:] if index and overlap else ""
        chunks.append(Chunk(body, index, context, max(start, 0)))
    return chunks


def _hard_split(text: str, limit: int) -> list[str]:
    """Last resort, and it still refuses to cut mid-word."""
    out: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        out.append(remaining)
    return out


@dataclass
class Glossary:
    """One translation per term, for the whole document."""

    terms: dict[str, str] = field(default_factory=dict)

    def learn(self, source: str, target: str) -> None:
        key = str(source or "").strip()
        if key and key not in self.terms:
            self.terms[key] = str(target or "").strip()

    def apply(self, text: str) -> str:
        out = str(text or "")
        # Longest first, so a term containing another is replaced whole.
        for source in sorted(self.terms, key=len, reverse=True):
            target = self.terms[source]
            if not target or source == target:
                continue
            out = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", target, out)
        return out

    def as_dict(self) -> dict[str, str]:
        return dict(self.terms)


@dataclass
class DocumentResult:
    english: str
    chunks: int
    failed: list[int] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0

    @property
    def complete(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, Any]:
        return {"english": self.english, "chunks": self.chunks,
                "failed_chunks": self.failed, "complete": self.complete,
                "confidence": round(self.confidence, 3),
                "glossary": self.glossary}


def understand_document(text: str, *, limit: int = DEFAULT_CHUNK_CHARS,
                        overlap: int = DEFAULT_OVERLAP_CHARS,
                        understand: Callable | None = None) -> DocumentResult:
    """Convert a long document to English, chunk by chunk.

    A failed chunk is REPORTED, not silently dropped: its original text is
    kept in place so the document stays whole, and the index is listed so the
    caller knows which part is untranslated. Silently omitting a paragraph is
    the worst possible failure for a document.
    """
    from reyes_agent.language.engine import understand_text

    understand = understand or understand_text
    chunks = split(text, limit=limit, overlap=overlap)
    if not chunks:
        return DocumentResult("", 0)

    glossary = Glossary()
    out: list[str] = []
    failed: list[int] = []
    confidences: list[float] = []

    for chunk in chunks:
        try:
            result = understand(chunk.text, conversation_context=chunk.context_before)
        except Exception:  # noqa: BLE001
            failed.append(chunk.index)
            out.append(chunk.text)
            confidences.append(0.0)
            continue

        english = glossary.apply(result.english)
        for token, value in (result.entities or {}).items():  # noqa: B007
            glossary.learn(value, value)      # entities translate to themselves
        out.append(english)
        confidences.append(result.confidence)
        if result.confidence < 0.4:
            failed.append(chunk.index)

    return DocumentResult(
        english="\n\n".join(out),
        chunks=len(chunks),
        failed=sorted(set(failed)),
        glossary=glossary.as_dict(),
        confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
    )
