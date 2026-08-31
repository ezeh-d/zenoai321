"""Concept graph (#4, #5) -- knowledge as connected concepts, not paragraphs.

Concepts connect through typed relationships (REQUIRES, PART_OF, EXAMPLE_OF,
DERIVED_FROM, ...), so ZENO can decompose a subject and, crucially, detect
MISSING PREREQUISITES before teaching something advanced. The graph store and
its queries are deterministic and tested; a lightweight definition-based
extractor seeds it, and ZENO's brain can enrich it with add_concept/add_relation.

Persistent per course in ZENO's learning store. Never raises.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_ROOT = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "learning" / "concepts"

# relationship vocabulary (from the spec)
REQUIRES = "REQUIRES"
PART_OF = "PART_OF"
EXAMPLE_OF = "EXAMPLE_OF"
CAUSES = "CAUSES"
DERIVED_FROM = "DERIVED_FROM"
SIMILAR_TO = "SIMILAR_TO"
CONTRASTS_WITH = "CONTRASTS_WITH"
USED_FOR = "USED_FOR"
FORMULA_FOR = "FORMULA_FOR"
_RELATIONS = {REQUIRES, PART_OF, EXAMPLE_OF, CAUSES, DERIVED_FROM, SIMILAR_TO,
              CONTRASTS_WITH, USED_FOR, FORMULA_FOR}


def _course_key(course: str) -> str:
    return "".join(c for c in str(course or "general").lower()
                   if c.isalnum() or c in "-_") or "general"


def _norm(name: str) -> str:
    return " ".join(str(name or "").strip().split()).lower()


@dataclass
class Concept:
    name: str
    kind: str = "concept"           # concept | subject | course | module | topic
    sources: list[str] = field(default_factory=list)
    definition: str = ""


@dataclass
class Edge:
    src: str
    rel: str
    dst: str


# --- deterministic extraction -----------------------------------------------
_DEF_PATTERNS = [
    re.compile(r"\b([A-Z][A-Za-z0-9 '\-]{2,50}?)\s+(?:is|are)\s+(?:a|an|the)\b", re.I),
    re.compile(r"\b([A-Z][A-Za-z0-9 '\-]{2,50}?)\s+refers to\b", re.I),
    re.compile(r"\b([A-Z][A-Za-z0-9 '\-]{2,50}?)\s+(?:is|are)\s+defined as\b", re.I),
]
_REQUIRES_PATTERN = re.compile(
    r"\b([A-Za-z0-9 '\-]{2,50}?)\s+requires?\s+([A-Za-z0-9 '\-]{2,50}?)\b", re.I)
_STOP = {"this", "that", "these", "those", "it", "there", "here", "he", "she",
         "they", "we", "you", "the", "a", "an"}


def extract_concepts(text: str) -> list[str]:
    """Concepts named by simple 'X is a ...' / 'X refers to ...' definitions.
    Deterministic and conservative -- better to miss one than invent one."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in _DEF_PATTERNS:
        for m in pat.finditer(str(text or "")):
            name = m.group(1).strip(" '-")
            key = _norm(name)
            if key and key not in seen and key not in _STOP and len(key) > 2:
                seen.add(key)
                found.append(name)
    return found


def extract_requirements(text: str) -> list[tuple[str, str]]:
    """(concept, prerequisite) pairs from 'X requires Y' sentences."""
    out = []
    for m in _REQUIRES_PATTERN.finditer(str(text or "")):
        a, b = m.group(1).strip(), m.group(2).strip()
        if _norm(a) and _norm(b) and _norm(a) != _norm(b):
            out.append((a, b))
    return out


class ConceptGraph:
    def __init__(self, root: Path = _ROOT) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    # -- storage -----------------------------------------------------------
    def _path(self, course: str) -> Path:
        return self._root / f"{_course_key(course)}.json"

    def _load(self, course: str) -> dict[str, Any]:
        p = self._path(course)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {"concepts": {}, "edges": []}

    def _save(self, course: str, graph: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        p = self._path(course)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    # -- mutation ----------------------------------------------------------
    def add_concept(self, name: str, *, course: str = "", kind: str = "concept",
                    source: str = "", definition: str = "") -> dict[str, Any]:
        with self._lock:
            key = _norm(name)
            if not key:
                return {"ok": False, "error": "empty concept"}
            g = self._load(course)
            c = g["concepts"].get(key) or {"name": str(name).strip(), "kind": kind,
                                           "sources": [], "definition": ""}
            if source and source not in c["sources"]:
                c["sources"].append(source)
            if definition and not c["definition"]:
                c["definition"] = str(definition)[:400]
            if kind != "concept":
                c["kind"] = kind
            g["concepts"][key] = c
            self._save(course, g)
            return {"ok": True, "concept": c["name"], "kind": c["kind"]}

    def add_relation(self, src: str, rel: str, dst: str, *,
                     course: str = "") -> dict[str, Any]:
        rel = str(rel or "").upper()
        if rel not in _RELATIONS:
            return {"ok": False, "error": f"unknown relation '{rel}'"}
        with self._lock:
            a, b = _norm(src), _norm(dst)
            if not a or not b or a == b:
                return {"ok": False, "error": "need two distinct concepts"}
            g = self._load(course)
            for name in (src, dst):
                if _norm(name) not in g["concepts"]:
                    g["concepts"][_norm(name)] = {"name": str(name).strip(),
                                                  "kind": "concept", "sources": [],
                                                  "definition": ""}
            edge = {"src": a, "rel": rel, "dst": b}
            if edge not in g["edges"]:
                g["edges"].append(edge)
            self._save(course, g)
            return {"ok": True, "edge": f"{src} -{rel}-> {dst}"}

    def ingest_text(self, text: str, *, course: str = "", source: str = "") -> dict[str, Any]:
        """Seed the graph from a passage: definitions -> concepts, 'X requires Y'
        -> REQUIRES edges. Deterministic."""
        added = 0
        for name in extract_concepts(text):
            if self.add_concept(name, course=course, source=source)["ok"]:
                added += 1
        edges = 0
        for a, b in extract_requirements(text):
            if self.add_relation(a, REQUIRES, b, course=course)["ok"]:
                edges += 1
        return {"ok": True, "concepts_added": added, "requires_edges": edges}

    # -- queries -----------------------------------------------------------
    def relations_of(self, concept: str, *, course: str = "") -> dict[str, Any]:
        g = self._load(course)
        key = _norm(concept)
        if key not in g["concepts"]:
            return {"ok": False, "error": f"unknown concept '{concept}'"}
        out = [{"rel": e["rel"], "to": g["concepts"].get(e["dst"], {}).get("name", e["dst"])}
               for e in g["edges"] if e["src"] == key]
        into = [{"rel": e["rel"], "from": g["concepts"].get(e["src"], {}).get("name", e["src"])}
                for e in g["edges"] if e["dst"] == key]
        return {"ok": True, "concept": g["concepts"][key]["name"],
                "outgoing": out, "incoming": into}

    def prerequisites(self, concept: str, *, course: str = "") -> list[str]:
        """The transitive REQUIRES chain, deepest-first (teach these before it)."""
        g = self._load(course)
        edges = [(e["src"], e["dst"]) for e in g["edges"] if e["rel"] == REQUIRES]
        order: list[str] = []
        seen: set[str] = set()

        def walk(node: str) -> None:
            for src, dst in edges:
                if src == node and dst not in seen:
                    seen.add(dst)
                    walk(dst)               # deeper prerequisites first
                    order.append(g["concepts"].get(dst, {}).get("name", dst))
        walk(_norm(concept))
        return order

    def missing_prerequisites(self, concept: str, known: list[str], *,
                              course: str = "") -> list[str]:
        known_norm = {_norm(k) for k in (known or [])}
        return [p for p in self.prerequisites(concept, course=course)
                if _norm(p) not in known_norm]

    def summary(self, *, course: str = "") -> dict[str, Any]:
        g = self._load(course)
        return {"ok": True, "course": course or "general",
                "concepts": len(g["concepts"]), "edges": len(g["edges"]),
                "names": [c["name"] for c in g["concepts"].values()][:100]}

    def reset(self, *, course: str = "") -> dict[str, Any]:
        with self._lock:
            p = self._path(course)
            existed = p.exists()
            p.unlink(missing_ok=True)
            return {"ok": True, "cleared": existed}


_graph: ConceptGraph | None = None
_graph_lock = threading.Lock()


def get_concept_graph() -> ConceptGraph:
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = ConceptGraph()
    return _graph
