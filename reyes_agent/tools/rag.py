"""Retrieval-augmented generation over the vault: real semantic search,
not just filename/keyword matching. The next increment named in
ZENO_ARCHITECTURE.md's honest gap table -- "embeddings + a local vector
store -> real RAG over the vault/documents."

Design, deliberately simple and dependency-light (no vector DB service,
no ML framework):
- Embeddings: Gemini's native `embedContent` (gemini-embedding-001,
  3072-dim), always used regardless of MODEL_PROVIDER -- same rule as
  vision.py, since embeddings need a specific capability the active text
  provider might not have.
- Chunking: split notes into ~180-word chunks with overlap, so a chunk is
  small enough to be a focused semantic unit but large enough to carry
  context.
- Storage: chunks + vectors as one .npz (numpy's own compressed format)
  in the vault -- no separate vector DB process. Fine at personal-vault
  scale (hundreds to low thousands of chunks); would need a real vector
  DB (e.g. sqlite-vec, Chroma) past that, which is an honest future
  upgrade, not pretended to already exist.
- Retrieval: cosine similarity via plain numpy -- O(n) over the index,
  which is instant at this scale.

Reindexing is incremental: a file's mtime is tracked, only changed/new
files get re-chunked and re-embedded.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from reyes_agent import config
from reyes_agent.tools import register

_INDEX_DIR = config.VAULT_PATH / "07-System" / "rag"
_VECTORS_PATH = _INDEX_DIR / "vectors.npz"
_META_PATH = _INDEX_DIR / "meta.json"
_MEMORY_VECTORS_PATH = _INDEX_DIR / "living_memory_vectors.npz"
_MEMORY_META_PATH = _INDEX_DIR / "living_memory_meta.json"
_memory_lock = threading.RLock()

_EMBED_MODEL = "gemini-embedding-001"
_CHUNK_WORDS = 180
_CHUNK_OVERLAP = 40
_TOP_K_DEFAULT = 5

# Folders/files worth indexing -- notes, projects, daily -- not logs,
# captures, or the rag index's own state.
_INCLUDE_DIRS = ["00-Inbox", "01-Knowledge", "02-Projects", "03-Daily", "04-Reyes-Outputs", "05-Resources"]
_INCLUDE_EXT = {".md", ".txt"}


class RagError(Exception):
    pass


def _embed(text: str) -> np.ndarray:
    if not config.GEMINI_API_KEY:
        raise RagError("No GEMINI_API_KEY set -- embeddings need it regardless of MODEL_PROVIDER.")
    import requests

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{_EMBED_MODEL}:embedContent"
        f"?key={config.GEMINI_API_KEY}"
    )
    resp = requests.post(url, json={"content": {"parts": [{"text": text[:8000]}]}}, timeout=30)
    if resp.status_code != 200:
        raise RagError(f"Embedding request failed ({resp.status_code}): {resp.text[:200]}")
    return np.array(resp.json()["embedding"]["values"], dtype=np.float32)


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = _CHUNK_WORDS - _CHUNK_OVERLAP
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + _CHUNK_WORDS])
        if chunk.strip():
            chunks.append(chunk)
        if i + _CHUNK_WORDS >= len(words):
            break
    return chunks


def _iter_vault_files():
    # Notes often live loose in the vault root (Obsidian default), not
    # just in the organized subfolders -- checked the real vault, that's
    # exactly where most of this one's content actually is.
    for p in config.VAULT_PATH.glob("*"):
        if p.is_file() and p.suffix.lower() in _INCLUDE_EXT:
            yield p
    for d in _INCLUDE_DIRS:
        base = config.VAULT_PATH / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in _INCLUDE_EXT:
                yield p


def _load_index() -> tuple[np.ndarray, list[dict]]:
    if not _VECTORS_PATH.exists() or not _META_PATH.exists():
        return np.zeros((0, 3072), dtype=np.float32), []
    vectors = np.load(_VECTORS_PATH)["vectors"]
    meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
    return vectors, meta


def _save_index(vectors: np.ndarray, meta: list[dict]) -> None:
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(_VECTORS_PATH, vectors=vectors)
    _META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _load_memory_index() -> tuple[np.ndarray, list[dict]]:
    if not _MEMORY_VECTORS_PATH.exists() or not _MEMORY_META_PATH.exists():
        return np.zeros((0, 0), dtype=np.float32), []
    return np.load(_MEMORY_VECTORS_PATH)["vectors"], json.loads(_MEMORY_META_PATH.read_text(encoding="utf-8"))


def _save_memory_index(vectors: np.ndarray, meta: list[dict]) -> None:
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    temp = _MEMORY_VECTORS_PATH.with_suffix(".tmp.npz")
    np.savez_compressed(temp, vectors=vectors)
    temp.replace(_MEMORY_VECTORS_PATH)
    meta_temp = _MEMORY_META_PATH.with_suffix(".tmp")
    meta_temp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    meta_temp.replace(_MEMORY_META_PATH)


def refresh_memory_embedding(memory_id: str, content: str, status: str) -> str:
    """Incrementally update the derived, non-authoritative memory index."""
    with _memory_lock:
        vectors, meta = _load_memory_index()
        kept = [i for i, item in enumerate(meta) if item.get("memory_id") != memory_id]
        kept_vectors = vectors[kept] if kept and len(vectors) else np.zeros((0, 0), dtype=np.float32)
        kept_meta = [meta[i] for i in kept]
        if status == "deleted_pending_purge":
            _save_memory_index(kept_vectors, kept_meta)
            return "removed"
        vec = _embed(content)
        if kept_vectors.size and kept_vectors.shape[1] != len(vec):
            # A changed embedding model cannot safely share an index; rebuild
            # this derived cache from subsequent memory writes.
            kept_vectors, kept_meta = np.zeros((0, len(vec)), dtype=np.float32), []
        all_vectors = np.vstack([kept_vectors, vec.reshape(1, -1)]) if kept_vectors.size else vec.reshape(1, -1)
        kept_meta.append({"memory_id": memory_id, "text": content, "status": status, "updated_at": time.time()})
        _save_memory_index(all_vectors, kept_meta)
        return "updated"


def search_memory_semantic(query: str, top_k: int = _TOP_K_DEFAULT, *, include_archived: bool = False) -> list[dict]:
    with _memory_lock:
        vectors, meta = _load_memory_index()
    eligible = [i for i, item in enumerate(meta) if include_archived or item.get("status") == "active"]
    if not eligible:
        return []
    qvec = _embed(query)
    subset = vectors[eligible]
    norms = np.linalg.norm(subset, axis=1) * np.linalg.norm(qvec)
    norms[norms == 0] = 1e-9
    scores = (subset @ qvec) / norms
    limit = max(1, min(20, int(top_k)))
    return [{"memory_id": meta[eligible[int(i)]]["memory_id"], "score": float(scores[int(i)]),
             "text": meta[eligible[int(i)]]["text"], "status": meta[eligible[int(i)]]["status"]}
            for i in np.argsort(-scores)[:limit]]


@register(
    name="reindex_vault",
    description=(
        "Rebuild/update the semantic search index over the vault (notes, "
        "projects, daily, resources) -- run this after adding a lot of new "
        "notes, or when the user asks to refresh/reindex search. "
        "Incremental: only new/changed files are re-embedded."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def reindex_vault() -> str:
    vectors, meta = _load_index()
    known_mtimes = {m["path"]: m["mtime"] for m in meta}
    # keep chunks belonging to files that still exist and are unchanged
    kept_meta = []
    kept_vec_idx = []
    seen_paths = set()

    files = list(_iter_vault_files())
    changed_files = []
    for f in files:
        rel = str(f.relative_to(config.VAULT_PATH))
        seen_paths.add(rel)
        mtime = f.stat().st_mtime
        if known_mtimes.get(rel) == mtime:
            continue  # unchanged -- its existing chunks get kept below
        changed_files.append((f, rel, mtime))

    for i, m in enumerate(meta):
        if m["path"] in seen_paths and m["path"] not in {r for _f, r, _mt in changed_files}:
            kept_meta.append(m)
            kept_vec_idx.append(i)

    new_vectors = []
    new_meta = []
    errors = []
    for f, rel, mtime in changed_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        for ci, chunk in enumerate(_chunk_text(text)):
            try:
                vec = _embed(chunk)
            except RagError as exc:
                errors.append(f"{rel} chunk {ci}: {exc}")
                continue
            new_vectors.append(vec)
            new_meta.append({"path": rel, "chunk": ci, "text": chunk, "mtime": mtime})

    kept_vectors = vectors[kept_vec_idx] if kept_vec_idx else np.zeros((0, 3072), dtype=np.float32)
    all_vectors = np.vstack([kept_vectors, np.array(new_vectors, dtype=np.float32)]) if new_vectors else kept_vectors
    all_meta = kept_meta + new_meta
    _save_index(all_vectors, all_meta)

    summary = f"Indexed {len(changed_files)} changed file(s) -> {len(new_meta)} new chunk(s). Total: {len(all_meta)} chunks across {len(seen_paths)} files."
    if errors:
        summary += f"\n{len(errors)} error(s), e.g.: {errors[0]}"
    return summary


@register(
    name="search_vault_semantic",
    description=(
        "Search the vault by MEANING, not just keyword matching -- finds "
        "relevant notes/projects even if they don't contain the exact "
        "words. Use for open-ended questions about what's in the vault "
        "('what have I written about X', 'find notes related to Y') where "
        "search_notes' plain-text match might miss the right note."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for, in natural language."},
            "top_k": {"type": "integer", "description": f"How many results. Default {_TOP_K_DEFAULT}."},
        },
        "required": ["query"],
    },
    light=True,
)
def search_vault_semantic(query: str, top_k: int = _TOP_K_DEFAULT) -> str:
    vectors, meta = _load_index()
    if len(meta) == 0:
        return "The semantic index is empty -- run reindex_vault first."
    try:
        top_k = max(1, min(20, int(top_k)))
    except (TypeError, ValueError):
        top_k = _TOP_K_DEFAULT

    try:
        qvec = _embed(query)
    except RagError as exc:
        return str(exc)

    # cosine similarity, vectorized
    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(qvec)
    norms[norms == 0] = 1e-9
    sims = (vectors @ qvec) / norms
    order = np.argsort(-sims)[:top_k]

    lines = []
    for idx in order:
        m = meta[idx]
        score = float(sims[idx])
        snippet = m["text"][:220].replace("\n", " ")
        lines.append(f"[{score:.2f}] {m['path']} (chunk {m['chunk']}): {snippet}...")
    return "\n".join(lines) if lines else "No results."
