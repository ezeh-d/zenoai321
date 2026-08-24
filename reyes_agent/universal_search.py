"""Universal search -- one query surface over ZENO's knowledge.

WHY / HOW
---------
Pack #7 wants a fast, typo-tolerant search across memory, files, notes, T21
knowledge, commands, etc. Meilisearch is the eventual engine, but it is an
external service and the pack forbids forcing heavy installs (#255). So this
follows the pack's own *adapter → health check → fallback* rule (#7, #218):

* a **local** backend that is genuinely useful today -- token overlap + fuzzy
  (typo-tolerant) ranking, dependency-free, in-process; and
* an optional **Meilisearch** backend, used ONLY when the ``enable_meilisearch``
  feature flag is on AND a reachable server is configured.

Backend is chosen once, by a health check, at construction; if Meilisearch is
enabled but unreachable, search degrades to local rather than failing. Every
public method is defensive and never raises into a caller.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")
_DEFAULT_THRESHOLD = 0.5


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(str(text or "").casefold())


@dataclass
class SearchHit:
    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "score": round(self.score, 4),
                "text": self.text, "metadata": self.metadata}


# --- local backend ----------------------------------------------------------
@dataclass
class _Doc:
    id: str
    text: str
    tokens: list[str]
    text_low: str
    metadata: dict[str, Any]


class LocalIndex:
    """In-process typo-tolerant ranked search. Good to thousands of docs."""

    name = "local"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._docs: dict[str, _Doc] = {}

    def index(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        doc_id = str(doc_id or "").strip()
        if not doc_id:
            return
        with self._lock:
            self._docs[doc_id] = _Doc(
                doc_id, str(text or ""), _tokens(text),
                str(text or "").casefold(), dict(metadata or {}))

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._docs.pop(str(doc_id or "").strip(), None)

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._docs)

    def search(self, query: str, limit: int = 10,
               threshold: float = _DEFAULT_THRESHOLD) -> list[SearchHit]:
        q_tokens = _tokens(query)
        q_low = str(query or "").casefold().strip()
        if not q_tokens:
            return []
        with self._lock:
            docs = list(self._docs.values())
        hits: list[SearchHit] = []
        for doc in docs:
            score = _score(q_tokens, doc.tokens, doc.text_low, q_low)
            if score >= threshold:
                hits.append(SearchHit(doc.id, score, doc.text, doc.metadata))
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:max(1, int(limit))]

    def health(self) -> dict[str, Any]:
        return {"backend": self.name, "ok": True, "documents": len(self)}


def _score(q_tokens: list[str], d_tokens: list[str], d_low: str, q_low: str) -> float:
    """Mean best-match of each query token against the doc, with a phrase bonus.
    Exact = 1.0, prefix = 0.9, otherwise a fuzzy ratio (typo tolerance)."""
    if not q_tokens or not d_tokens:
        return 0.0
    d_set = set(d_tokens)
    total = 0.0
    for qt in q_tokens:
        if qt in d_set:
            total += 1.0
            continue
        best = 0.0
        for dt in d_tokens:
            if dt.startswith(qt) or qt.startswith(dt):
                best = max(best, 0.9)
            elif abs(len(dt) - len(qt)) <= 3:
                ratio = SequenceMatcher(None, qt, dt).ratio()
                if ratio > best:
                    best = ratio
        total += best
    score = total / len(q_tokens)
    if q_low and q_low in d_low:            # exact phrase present -> boost
        score = min(1.0, score + 0.15)
    return score


# --- optional meilisearch backend -------------------------------------------
class MeilisearchBackend:
    name = "meilisearch"

    def __init__(self, url: str, api_key: str, index_name: str) -> None:
        import meilisearch  # raises if the client is not installed

        self._client = meilisearch.Client(url, api_key or None)
        self._client.health()                # raises if the server is unreachable
        self._index = self._client.index(index_name)
        try:
            self._client.create_index(index_name, {"primaryKey": "id"})
        except Exception:  # noqa: BLE001 -- already exists is fine
            pass

    @staticmethod
    def configure(index_name: str) -> "MeilisearchBackend | None":
        import os

        url = (os.environ.get("MEILISEARCH_URL") or os.environ.get("MEILI_URL") or "").strip()
        if not url:
            return None
        key = (os.environ.get("MEILISEARCH_KEY") or os.environ.get("MEILI_MASTER_KEY") or "").strip()
        try:
            return MeilisearchBackend(url, key, index_name)
        except Exception:  # noqa: BLE001 -- unavailable -> caller falls back
            return None

    def index(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        self._index.add_documents([{"id": str(doc_id), "text": str(text or ""),
                                    **(metadata or {})}])

    def search(self, query: str, limit: int = 10,
               threshold: float = _DEFAULT_THRESHOLD) -> list[SearchHit]:
        res = self._index.search(query, {"limit": max(1, int(limit))})
        hits = []
        for i, row in enumerate(res.get("hits", [])):
            rid = str(row.get("id", ""))
            text = str(row.get("text", ""))
            meta = {k: v for k, v in row.items() if k not in {"id", "text"}}
            # Meilisearch returns already-ranked hits; synthesise a descending score.
            hits.append(SearchHit(rid, 1.0 - i * 0.01, text, meta))
        return hits

    def health(self) -> dict[str, Any]:
        try:
            self._client.health()
            return {"backend": self.name, "ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"backend": self.name, "ok": False, "error": type(exc).__name__}


# --- service ----------------------------------------------------------------
class UniversalSearchService:
    def __init__(self, index_name: str = "zeno") -> None:
        self._local = LocalIndex()
        self._remote: MeilisearchBackend | None = None
        try:
            from reyes_agent import feature_flags

            if feature_flags.is_enabled("enable_meilisearch"):
                self._remote = MeilisearchBackend.configure(index_name)
        except Exception:  # noqa: BLE001 -- flag/backend issues degrade to local
            self._remote = None

    @property
    def backend_name(self) -> str:
        return (self._remote or self._local).name

    def index(self, doc_id: str, text: str, **metadata: Any) -> None:
        # Always keep the local mirror so a later Meilisearch outage still
        # returns results, and so tests/offline use work with no server.
        self._local.index(doc_id, text, metadata)
        if self._remote is not None:
            try:
                self._remote.index(doc_id, text, metadata)
            except Exception:  # noqa: BLE001 -- local mirror is authoritative
                pass

    def index_many(self, docs: list[dict[str, Any]]) -> int:
        count = 0
        for doc in docs or []:
            doc_id = str(doc.get("id", "")).strip()
            if not doc_id:
                continue
            meta = {k: v for k, v in doc.items() if k not in {"id", "text"}}
            self.index(doc_id, str(doc.get("text", "")), **meta)
            count += 1
        return count

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        if self._remote is not None:
            try:
                hits = self._remote.search(query, limit)
                if hits:
                    return hits
            except Exception:  # noqa: BLE001 -- degrade to local
                pass
        return self._local.search(query, limit)

    def health(self) -> dict[str, Any]:
        out = {"active_backend": self.backend_name, "local": self._local.health()}
        if self._remote is not None:
            out["remote"] = self._remote.health()
        return out


_instance: UniversalSearchService | None = None
_instance_lock = threading.Lock()


def get_search() -> UniversalSearchService:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = UniversalSearchService()
        return _instance
