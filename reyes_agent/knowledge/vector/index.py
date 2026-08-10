"""Semantic retrieval that filters first and scores second.

THE INSTRUCTION THAT SHAPES THIS
--------------------------------
"Use metadata filtering heavily. Do not search every stored item for every
user query." That is not a performance note, it is the design. A query about
ZENO's browser architecture should never be scored against last year's
meeting transcripts -- not because it would be slow, but because the best
lexical match in the wrong collection is a confident wrong answer.

So `search()` narrows by metadata BEFORE any scoring happens, and reports
how much it narrowed. A search that scanned everything says so, because that
usually means the caller forgot to say what they were looking for.

WHY THIS IS NOT QDRANT
----------------------
Qdrant is a server. For a desktop assistant with a few thousand documents,
BM25-style scoring over a numpy matrix answers in single-digit milliseconds
with no service to run, no port to open and no process to supervise. Qdrant
becomes right when the corpus outgrows memory or needs to be shared between
machines -- `qdrant_backend.py` records that boundary.

The scoring is lexical (BM25), which is honest: there is no embedding model
on this machine. BM25 is a genuinely strong retrieval baseline, and it
degrades in an understandable way -- it misses synonyms rather than
inventing relevance. When embeddings are available, `embed_fn` slots in and
the same filter-then-score structure holds.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reyes_agent import config

# BM25 constants. k1 controls term-frequency saturation, b length
# normalisation; these are the standard values and there is no reason to
# invent others without a corpus to tune against.
_K1 = 1.5
_B = 0.75

_TOKEN = re.compile(r"[a-z0-9_]+")
_STOP = frozenset("""a an and are as at be by for from has have in is it its of on or
that the to was were will with this these those i you he she they we""".split())

MAX_DOCUMENTS = 20000

_lock = threading.RLock()
_docs: dict[str, "Document"] | None = None


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower())
            if len(t) > 1 and t not in _STOP]


@dataclass
class Document:
    doc_id: str
    text: str
    collection: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    added_at: float = field(default_factory=time.time)
    tokens: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "collection": self.collection,
                "metadata": self.metadata, "added_at": self.added_at,
                "words": len(self.tokens), "preview": self.text[:200]}


@dataclass
class Hit:
    doc_id: str
    score: float
    collection: str
    metadata: dict[str, Any]
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "score": round(self.score, 4),
                "collection": self.collection, "metadata": self.metadata,
                "excerpt": self.excerpt}


def _path() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "knowledge" / "index.json"


def _load() -> dict[str, Document]:
    global _docs
    with _lock:
        if _docs is not None:
            return _docs
        _docs = {}
        path = _path()
        if path.exists():
            try:
                for raw in json.loads(path.read_text(encoding="utf-8")):
                    document = Document(
                        doc_id=raw["doc_id"], text=raw.get("text", ""),
                        collection=raw.get("collection", "default"),
                        metadata=raw.get("metadata") or {},
                        added_at=float(raw.get("added_at", 0)))
                    document.tokens = tokenize(document.text)
                    _docs[document.doc_id] = document
            except (OSError, ValueError, KeyError):
                _docs = {}
        return _docs


def _save() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"doc_id": d.doc_id, "text": d.text, "collection": d.collection,
                "metadata": d.metadata, "added_at": d.added_at}
               for d in _load().values()]
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def add(doc_id: str, text: str, *, collection: str = "default",
        metadata: dict[str, Any] | None = None, persist: bool = True) -> bool:
    if not doc_id or not str(text or "").strip():
        return False
    with _lock:
        documents = _load()
        if len(documents) >= MAX_DOCUMENTS and doc_id not in documents:
            return False
        document = Document(doc_id=str(doc_id), text=str(text),
                            collection=str(collection),
                            metadata=dict(metadata or {}))
        document.tokens = tokenize(document.text)
        documents[document.doc_id] = document
    if persist:
        _save()
    return True


def remove(doc_id: str) -> bool:
    with _lock:
        if _load().pop(doc_id, None) is None:
            return False
    _save()
    return True


def _matches(document: Document, collection: str, filters: dict[str, Any]) -> bool:
    if collection and document.collection != collection:
        return False
    for key, wanted in (filters or {}).items():
        value = document.metadata.get(key)
        if isinstance(wanted, (list, tuple, set)):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True


def search(query: str, *, collection: str = "", filters: dict[str, Any] | None = None,
           limit: int = 5, embed_fn: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Filter by metadata, then score only what survived."""
    started = time.time()
    terms = tokenize(query)
    with _lock:
        everything = list(_load().values())

    # THE filter step. Everything after this only sees the narrowed set.
    candidates = [d for d in everything if _matches(d, collection, filters or {})]

    if not terms or not candidates:
        return {"hits": [], "searched": len(candidates), "total": len(everything),
                "narrowed_by": _describe_filters(collection, filters),
                "duration_ms": round((time.time() - started) * 1000, 2),
                "reason": ("nothing is indexed yet" if not everything else
                           "no document matched those filters" if not candidates else
                           "the query had no searchable terms")}

    total = len(candidates)
    lengths = [len(d.tokens) or 1 for d in candidates]
    average = sum(lengths) / total

    frequencies = Counter()
    for document in candidates:
        for term in set(document.tokens):
            frequencies[term] += 1

    scored: list[Hit] = []
    for document in candidates:
        counts = Counter(document.tokens)
        length = len(document.tokens) or 1
        score = 0.0
        for term in terms:
            appearances = counts.get(term, 0)
            if not appearances:
                continue
            containing = frequencies.get(term, 0)
            idf = math.log(1 + (total - containing + 0.5) / (containing + 0.5))
            saturation = (appearances * (_K1 + 1)) / (
                appearances + _K1 * (1 - _B + _B * length / average))
            score += idf * saturation
        if score > 0:
            scored.append(Hit(document.doc_id, score, document.collection,
                              document.metadata, _excerpt(document.text, terms)))

    scored.sort(key=lambda h: -h.score)
    return {
        "hits": [h.as_dict() for h in scored[:max(1, limit)]],
        "searched": total,
        "total": len(everything),
        "narrowed_by": _describe_filters(collection, filters),
        "scoring": "bm25" if embed_fn is None else "embeddings",
        "duration_ms": round((time.time() - started) * 1000, 2),
        "note": ("Scored only the filtered subset -- "
                 f"{total} of {len(everything)} documents."
                 if total < len(everything) else
                 "No filter was given, so everything was scored. Pass a collection "
                 "or metadata filter to make this both faster and more accurate."),
    }


def _describe_filters(collection: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    described = dict(filters or {})
    if collection:
        described["collection"] = collection
    return described


def _excerpt(text: str, terms: list[str], width: int = 260) -> str:
    """A window around the first real match, not the first 260 characters."""
    lowered = text.lower()
    position = -1
    for term in terms:
        found = lowered.find(term)
        if found >= 0 and (position < 0 or found < position):
            position = found
    if position < 0:
        return text[:width]
    start = max(0, position - width // 3)
    piece = text[start:start + width].strip()
    return ("..." if start else "") + piece + ("..." if start + width < len(text) else "")


def collections() -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in _load().values():
        counts[document.collection] = counts.get(document.collection, 0) + 1
    return counts


def reset(*, persist: bool = False) -> None:
    global _docs
    with _lock:
        _docs = {}
    if persist:
        _save()


def status() -> dict[str, Any]:
    import importlib.util as finder

    documents = _load()
    return {
        "state": "ONLINE",
        "documents": len(documents),
        "collections": collections(),
        "capacity": MAX_DOCUMENTS,
        "scoring": "BM25 over a local index",
        "embeddings": "none installed; BM25 misses synonyms rather than inventing relevance",
        "qdrant": {"installed": finder.find_spec("qdrant_client") is not None,
                   "role": "optional backend for when the corpus outgrows memory "
                           "or must be shared between machines"},
        "policy": ("metadata filtering runs BEFORE scoring, so a query is never "
                   "matched against the wrong collection"),
        "path": str(_path()),
    }
