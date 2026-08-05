"""
Long-term memory retrieval.

A dependency-free relevance search over text (notes, past conversation). Uses
TF cosine similarity — good enough to surface the right memory without pulling
in an embedding stack. Swap in embeddings later behind the same interface.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "with", "as", "at", "by", "it", "this", "that",
    "i", "you", "he", "she", "they", "we", "my", "your",
}


def _vec(text: str) -> Counter:
    return Counter(
        w for w in _TOKEN.findall(text.lower()) if w not in _STOP and len(w) > 1
    )


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in shared)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    """Index a set of documents and rank them against a query."""

    def __init__(self) -> None:
        self._docs: list[str] = []
        self._vecs: list[Counter] = []

    def add(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._docs.append(text)
            self._vecs.append(_vec(text))

    def add_many(self, texts) -> None:
        for t in texts:
            self.add(t)

    def search(self, query: str, k: int = 3, min_score: float = 0.03):
        qv = _vec(query)
        scored = [
            (round(_cosine(qv, dv), 3), doc)
            for doc, dv in zip(self._docs, self._vecs)
        ]
        scored = [s for s in scored if s[0] >= min_score]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self._docs)


def deep_recall(query: str, notes, history=None, k: int = 3) -> str:
    """Rank notes + optional conversation lines against a query."""
    r = Retriever()
    r.add_many(notes or [])
    r.add_many(history or [])
    hits = r.search(query, k=k)
    if not hits:
        return "Nothing relevant in long-term memory."
    return "\n".join(f"• ({score}) {doc[:200]}" for score, doc in hits)
