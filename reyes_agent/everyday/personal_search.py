"""Find anything, anywhere the user authorized -- one search over many sources.

Pack 10 #10-13: federate ZENO memory, notes, files, downloads, screenshots,
screen-recall, meeting transcripts -- and, when connected, Gmail / browser
history / cloud. Results are ranked by semantic relevance + recency + source
trust + project context, and every result carries provenance (source, location,
time, confidence). Sources are PLUGGABLE: local ones are wired now; OAuth ones
register as not-connected and are reported honestly, never faked.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

_TOKEN = re.compile(r"[a-z0-9]+")
# Ranking weights (sum 1.0).
_W_RELEVANCE = 0.5
_W_RECENCY = 0.25
_W_TRUST = 0.15
_W_PROJECT = 0.10
_HALF_LIFE_DAYS = 7.0

FetchFn = Callable[[str], list]


@dataclass
class Source:
    name: str
    fetch: FetchFn
    trust: float = 0.7
    connected: bool = True


@dataclass
class Result:
    title: str
    snippet: str
    source: str
    location: str
    timestamp: float
    score: float
    confidence: str

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "snippet": self.snippet, "source": self.source,
                "location": self.location, "timestamp": self.timestamp,
                "score": round(self.score, 4), "confidence": self.confidence}


def _relevance(query_tokens: list[str], text: str, query_low: str) -> float:
    toks = _TOKEN.findall(text.casefold())
    if not toks or not query_tokens:
        return 0.0
    tset = set(toks)
    total = 0.0
    for qt in query_tokens:
        if qt in tset:
            total += 1.0
        else:
            best = max((SequenceMatcher(None, qt, w).ratio() for w in toks), default=0.0)
            total += best if best >= 0.8 else 0.0
    score = total / len(query_tokens)
    if query_low and query_low in text.casefold():
        score = min(1.0, score + 0.15)
    return score


def _recency(timestamp: float, now: float) -> float:
    if not timestamp:
        return 0.3
    age_days = max(0.0, (now - timestamp) / 86400.0)
    return 0.5 ** (age_days / _HALF_LIFE_DAYS)


def _confidence(score: float) -> str:
    return "HIGH" if score >= 0.75 else ("MEDIUM" if score >= 0.5 else "LOW")


class UniversalPersonalSearch:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sources: dict[str, Source] = {}

    def register_source(self, name: str, fetch: FetchFn, *, trust: float = 0.7,
                        connected: bool = True) -> None:
        with self._lock:
            self._sources[name] = Source(name, fetch, max(0.0, min(1.0, trust)), connected)

    def sources_status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"name": s.name, "connected": s.connected, "trust": s.trust}
                    for s in sorted(self._sources.values(), key=lambda x: x.name)]

    def search(self, query: str, *, now: float | None = None, project: str = "",
               limit: int = 10) -> list[dict[str, Any]]:
        now = now if now is not None else datetime.now(timezone.utc).timestamp()
        q_tokens = _TOKEN.findall(str(query or "").casefold())
        q_low = str(query or "").casefold().strip()
        proj = str(project or "").casefold().strip()
        if not q_tokens:
            return []
        with self._lock:
            sources = [s for s in self._sources.values() if s.connected]
        results: list[Result] = []
        for src in sources:
            try:
                items = src.fetch(query) or []
            except Exception:  # noqa: BLE001 -- one bad source can't sink the search
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", ""))
                snippet = str(item.get("snippet", ""))
                text = f"{title} {snippet}"
                rel = _relevance(q_tokens, text, q_low)
                if rel <= 0.0:
                    continue
                ts = float(item.get("timestamp", 0.0) or 0.0)
                proj_hit = 1.0 if proj and proj in text.casefold() else 0.0
                score = (_W_RELEVANCE * rel + _W_RECENCY * _recency(ts, now)
                         + _W_TRUST * src.trust + _W_PROJECT * proj_hit)
                results.append(Result(
                    title=title, snippet=snippet[:280], source=src.name,
                    location=str(item.get("location", "")), timestamp=ts,
                    score=score, confidence=_confidence(rel)))
        results.sort(key=lambda r: (-r.score, -r.timestamp))
        return [r.as_dict() for r in results[:max(1, limit)]]


def wire_default_sources(search: UniversalPersonalSearch) -> dict[str, bool]:
    """Best-effort wiring of the LOCAL sources that exist today; OAuth sources
    register as not-connected so ZENO reports them honestly. Returns which
    connected."""
    wired: dict[str, bool] = {}

    # Screen recall (local, already built).
    try:
        from reyes_agent.everyday.screen_recall import get_recall

        def _recall_fetch(q: str) -> list:
            return [{"title": r.get("title") or r.get("app"), "snippet": r.get("description", ""),
                     "location": r.get("url") or r.get("app"), "timestamp": r.get("timestamp", 0.0)}
                    for r in get_recall().search(q, limit=10)]

        search.register_source("screen_recall", _recall_fetch, trust=0.6)
        wired["screen_recall"] = True
    except Exception:  # noqa: BLE001
        wired["screen_recall"] = False

    # ZENO memory (local, already built).
    try:
        from reyes_agent.memory_manager import get_memory  # type: ignore

        def _mem_fetch(q: str) -> list:
            items = get_memory().search(q, limit=10) if hasattr(get_memory(), "search") else []
            out = []
            for m in items or []:
                if isinstance(m, dict):
                    out.append({"title": m.get("title", m.get("text", ""))[:80],
                                "snippet": str(m.get("text", "")), "location": "ZENO memory",
                                "timestamp": float(m.get("timestamp", 0.0) or 0.0)})
            return out

        search.register_source("zeno_memory", _mem_fetch, trust=0.8)
        wired["zeno_memory"] = True
    except Exception:  # noqa: BLE001
        wired["zeno_memory"] = False

    # OAuth-gated sources: registered but NOT connected until credentials exist.
    for name in ("gmail", "browser_history", "cloud_drive"):
        search.register_source(name, lambda q: [], trust=0.7, connected=False)
        wired.setdefault(name, False)
    return wired


_instance: UniversalPersonalSearch | None = None
_lock = threading.Lock()


def get_search() -> UniversalPersonalSearch:
    global _instance
    with _lock:
        if _instance is None:
            _instance = UniversalPersonalSearch()
            wire_default_sources(_instance)
        return _instance
