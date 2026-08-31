"""ZENO Universal Learning Engine -- Phase 1 (StudyEngine).

Turns a document into STUDYABLE, SOURCE-GROUNDED knowledge: parse (reusing the
Universal Content Engine) -> chunk with real provenance (per PDF page where
possible) -> embed (reusing the same sentence-transformer as spatial memory) ->
a persistent study store SEPARATE from spatial memory (#18) -> grounded
retrieval that always carries a citation (#15) and an honest confidence (#16).

This is NOT a summariser and NOT another AI assistant: it prepares grounded
context and citations; ZENO's existing brain does the explaining/teaching on
top. Later phases (concept graph, courses, quizzes, mastery) build on this
index + store.

HONESTY
-------
* Every retrieved fact carries where it came from (file, page/chunk).
* Retrieval confidence is the real cosine score, bucketed -- never inflated.
* If nothing relevant is found, it says so; it does not invent an answer.
* If embeddings aren't available, it degrades to keyword overlap and says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_ROOT = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "learning"
_DOCS = _ROOT / "documents"
_CATALOG = _ROOT / "catalog.json"
_CHUNK_CHARS = 900
_CHUNK_OVERLAP = 150
_MODEL_NAME = os.environ.get("ZENO_STUDY_EMBED_MODEL", "all-MiniLM-L6-v2")


@dataclass
class Chunk:
    text: str
    idx: int
    page: int | None = None
    section: str = ""


@dataclass
class Citation:
    source: str
    page: int | None
    chunk: int
    score: float
    confidence: str

    def as_dict(self) -> dict[str, Any]:
        loc = f"page {self.page}" if self.page else f"chunk {self.chunk}"
        return {"source": Path(self.source).name, "path": self.source,
                "page": self.page, "chunk": self.chunk, "location": loc,
                "score": round(self.score, 3), "confidence": self.confidence}


def _source_id(path: str) -> str:
    return hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:16]


def _confidence(score: float) -> str:
    # honest buckets over the real cosine similarity
    if score >= 0.60:
        return "high"
    if score >= 0.45:
        return "medium"
    if score >= 0.32:
        return "low"
    return "weak"


def _chunk_text(text: str, *, page: int | None = None,
                start_idx: int = 0) -> list[Chunk]:
    text = str(text or "").strip()
    if not text:
        return []
    out: list[Chunk] = []
    step = max(1, _CHUNK_CHARS - _CHUNK_OVERLAP)
    i = 0
    while i < len(text):
        piece = text[i:i + _CHUNK_CHARS].strip()
        if piece:
            out.append(Chunk(piece, start_idx + len(out), page))
        i += step
    return out


class StudyEngine:
    """One engine per process; the store on disk is the source of truth."""

    def __init__(self, *, embed: Any = None, docs_dir: Path = _DOCS,
                 catalog_path: Path = _CATALOG) -> None:
        self._embed_fn = embed          # injectable for tests
        self._model = None
        self._tried = False
        self._docs_dir = Path(docs_dir)
        self._catalog_path = Path(catalog_path)
        self._lock = threading.RLock()

    # -- embeddings --------------------------------------------------------
    def _encode(self, texts: list[str]):
        import numpy as np
        if self._embed_fn is not None:
            vecs = self._embed_fn(texts)
            return None if vecs is None else np.asarray(vecs, dtype=float)
        if self._model is None:
            if self._tried:
                return None
            self._tried = True
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(_MODEL_NAME)
            except Exception:  # noqa: BLE001 -- degrade to keyword overlap
                self._model = None
                return None
        return np.asarray(self._model.encode(texts, normalize_embeddings=False), dtype=float)

    def _embeddings_available(self) -> bool:
        try:
            probe = self._encode(["probe"])
            return probe is not None and len(probe) > 0
        except Exception:  # noqa: BLE001
            return False

    # -- parsing + chunking ------------------------------------------------
    def _parse_chunks(self, path: Path) -> tuple[list[Chunk], str]:
        """Chunks with provenance. PDFs are chunked per page (real page
        citations); everything else via the content engine's text."""
        try:
            import fitz  # PyMuPDF -- real per-page text
            if path.suffix.lower() == ".pdf":
                chunks: list[Chunk] = []
                with fitz.open(path) as doc:
                    for pno in range(doc.page_count):
                        page_text = doc.load_page(pno).get_text("text")
                        chunks.extend(_chunk_text(page_text, page=pno + 1,
                                                  start_idx=len(chunks)))
                if chunks:
                    return chunks, "pymupdf-per-page"
        except Exception:  # noqa: BLE001 -- fall through to the content engine
            pass
        from reyes_agent.content import get_engine
        result = get_engine().open(str(path), max_chars=400_000)
        if not result.ok or not result.text.strip():
            return [], result.status
        return _chunk_text(result.text), result.source.get("engine", "content-engine")

    # -- studying ----------------------------------------------------------
    def study(self, path: str) -> dict[str, Any]:
        """Ingest, chunk, embed and persist a document for study."""
        try:
            with self._lock:
                p = Path(os.path.abspath(os.path.expanduser(str(path))))
                if not p.exists() or not p.is_file():
                    return {"ok": False, "error": f"'{p}' is not a readable file"}
                chunks, engine = self._parse_chunks(p)
                if not chunks:
                    return {"ok": False, "source": str(p),
                            "error": f"nothing studyable ({engine}); "
                                     "the file may be empty, scanned or unsupported"}
                vecs = self._encode([c.text for c in chunks])
                embedded = vecs is not None
                self._docs_dir.mkdir(parents=True, exist_ok=True)
                record = {
                    "source": str(p), "name": p.name, "engine": engine,
                    "studied_at": self._now(), "chunk_count": len(chunks),
                    "pages": max((c.page or 0 for c in chunks), default=0),
                    "embedded": embedded,
                    "chunks": [{"text": c.text, "idx": c.idx, "page": c.page}
                               for c in chunks],
                }
                (self._docs_dir / f"{_source_id(str(p))}.json").write_text(
                    json.dumps(record, ensure_ascii=False), encoding="utf-8")
                if embedded:
                    import numpy as np
                    np.save(self._docs_dir / f"{_source_id(str(p))}.npy", vecs)
                self._update_catalog(p, record)
                # Best-effort: seed the concept graph so "what concepts did you
                # find?" and prerequisite checks work after studying. Deterministic
                # and guarded -- it never breaks the study itself.
                concepts_found = 0
                try:
                    from reyes_agent.study.concepts import get_concept_graph
                    sample = " ".join(c.text for c in chunks[:60])[:40000]
                    seeded = get_concept_graph().ingest_text(sample, source=str(p))
                    concepts_found = seeded.get("concepts_added", 0)
                except Exception:  # noqa: BLE001
                    pass
                return {"ok": True, "source": str(p), "name": p.name,
                        "concepts_found": concepts_found,
                        "engine": engine, "chunks": len(chunks),
                        "pages": record["pages"], "embedded": embedded,
                        "note": ("indexed with semantic embeddings" if embedded
                                 else "indexed with keyword search (no embedding model)")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    # -- grounded retrieval ------------------------------------------------
    def ask(self, question: str, *, source: str = "", top_k: int = 4) -> dict[str, Any]:
        """Retrieve the passages most relevant to `question`, each with a
        citation and honest confidence. Does NOT answer -- it grounds."""
        try:
            with self._lock:
                records = self._records(source)
                if not records:
                    return {"ok": False, "error": "nothing has been studied yet"
                            if not source else f"'{source}' has not been studied"}
                import numpy as np
                q = self._encode([str(question)])
                hits: list[tuple[float, dict, dict]] = []
                for rec, vecs in records:
                    if vecs is not None and q is not None:
                        qv = q[0]
                        for ci, chunk in enumerate(rec["chunks"]):
                            if ci >= len(vecs):
                                break
                            score = _cosine(qv, vecs[ci])
                            hits.append((score, rec, chunk))
                    else:  # keyword overlap fallback (punctuation-insensitive)
                        words = _tokens(str(question))
                        for chunk in rec["chunks"]:
                            ov = words & _tokens(chunk["text"])
                            if ov:
                                hits.append((len(ov) / (len(words) or 1) * 0.6,
                                             rec, chunk))
                hits.sort(key=lambda h: h[0], reverse=True)
                top = hits[:max(1, min(int(top_k), 10))]
                if not top or top[0][0] < 0.30:
                    return {"ok": True, "grounded": False, "passages": [],
                            "note": "no sufficiently relevant passage was found; "
                                    "ZENO should say it doesn't have that in the "
                                    "studied material rather than guess."}
                passages = []
                for score, rec, chunk in top:
                    cite = Citation(rec["source"], chunk.get("page"),
                                    chunk["idx"], score, _confidence(score))
                    passages.append({"text": chunk["text"], "citation": cite.as_dict()})
                return {"ok": True, "grounded": True, "question": question,
                        "passages": passages,
                        "best_confidence": passages[0]["citation"]["confidence"],
                        "semantic": records[0][1] is not None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    # -- catalog / lifecycle ----------------------------------------------
    def catalog(self) -> dict[str, Any]:
        cat = self._load_catalog()
        return {"ok": True, "studied": list(cat.values()),
                "count": len(cat), "store": str(self._docs_dir)}

    def forget(self, source: str) -> dict[str, Any]:
        with self._lock:
            p = Path(os.path.abspath(os.path.expanduser(str(source))))
            sid = _source_id(str(p))
            removed = False
            for suffix in (".json", ".npy"):
                f = self._docs_dir / f"{sid}{suffix}"
                if f.exists():
                    f.unlink(missing_ok=True)
                    removed = True
            cat = self._load_catalog()
            cat.pop(str(p), None)
            self._save_catalog(cat)
            return {"ok": True, "forgotten": str(p), "found": removed}

    # -- store helpers -----------------------------------------------------
    def _records(self, source: str) -> list[tuple[dict, Any]]:
        import numpy as np
        out: list[tuple[dict, Any]] = []
        if source:
            ids = [_source_id(str(Path(os.path.abspath(os.path.expanduser(source)))))]
        else:
            ids = [f.stem for f in self._docs_dir.glob("*.json")] if self._docs_dir.exists() else []
        for sid in ids:
            jf = self._docs_dir / f"{sid}.json"
            if not jf.exists():
                continue
            try:
                rec = json.loads(jf.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            vf = self._docs_dir / f"{sid}.npy"
            vecs = np.load(vf) if vf.exists() else None
            out.append((rec, vecs))
        return out

    def _update_catalog(self, path: Path, record: dict) -> None:
        cat = self._load_catalog()
        cat[str(path)] = {"source": str(path), "name": path.name,
                          "chunks": record["chunk_count"], "pages": record["pages"],
                          "studied_at": record["studied_at"], "embedded": record["embedded"]}
        self._save_catalog(cat)

    def _load_catalog(self) -> dict[str, Any]:
        if self._catalog_path.exists():
            try:
                return json.loads(self._catalog_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {}

    def _save_catalog(self, cat: dict) -> None:
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._catalog_path.write_text(json.dumps(cat, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    @staticmethod
    def _now() -> float:
        try:
            return time.time()
        except Exception:  # noqa: BLE001
            return 0.0


def _cosine(a, b) -> float:
    import numpy as np
    denom = (float(np.linalg.norm(a)) * float(np.linalg.norm(b))) or 1.0
    return float(np.dot(a, b) / denom)


def _tokens(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


_engine: StudyEngine | None = None
_engine_lock = threading.Lock()


def get_study_engine() -> StudyEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = StudyEngine()
    return _engine
