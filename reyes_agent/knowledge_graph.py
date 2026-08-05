"""Knowledge Graph -- real entities and relationships extracted from the
vault, not an invented ontology.

WHERE THE EDGES COME FROM
-------------------------
Every edge is derived from something actually present in the user's
files, so the graph can be trusted and traced back:

  * `[[wikilink]]`   -> a LINK edge (Obsidian's own explicit relation)
  * `#tag`           -> a TAG edge to a tag node
  * folder placement -> a CONTAINS edge from the folder node
  * shared tags      -> a RELATED edge between notes (co-occurrence)

Nothing is inferred by a model. If two notes are connected here, the user
connected them -- which is what makes "show me everything about X" a
factual answer instead of a plausible-sounding one.

Orphans (notes nothing links to) are reported honestly rather than hidden,
because they are usually the interesting part of a real vault.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from reyes_agent import config

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
# Tags: #word, but not inside a code fence or a URL fragment.
_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{1,40})")
_MAX_FILES = 3000


@dataclass
class Node:
    id: str
    kind: str            # note | tag | folder
    label: str
    path: str = ""
    degree: int = 0


@dataclass
class Edge:
    src: str
    dst: str
    kind: str            # link | tag | contains | related


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node_id: str, kind: str, label: str, path: str = "") -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(node_id, kind, label, path)

    def add_edge(self, src: str, dst: str, kind: str) -> None:
        if src == dst:
            return
        self.edges.append(Edge(src, dst, kind))
        if src in self.nodes:
            self.nodes[src].degree += 1
        if dst in self.nodes:
            self.nodes[dst].degree += 1


def _vault_files() -> list[Path]:
    """Same scan rule as rag.py: vault root PLUS the named subfolders,
    because this vault keeps notes loose at the root (Obsidian default)
    and an earlier version missed all of them by only walking subfolders."""
    root = config.VAULT_PATH
    if not root.is_dir():
        return []
    out: list[Path] = []
    for pattern in ("*.md", "*.txt"):
        out.extend(root.glob(pattern))
    for sub in ("00-Inbox", "01-Daily", "02-Projects", "03-Areas", "04-Archive", "05-Resources"):
        d = root / sub
        if d.is_dir():
            for pattern in ("*.md", "*.txt"):
                out.extend(d.rglob(pattern))
    return out[:_MAX_FILES]


def build() -> Graph:
    g = Graph()
    tag_index: dict[str, set[str]] = defaultdict(set)

    files = _vault_files()
    for path in files:
        note_id = f"note:{path.stem.lower()}"
        g.add_node(note_id, "note", path.stem, str(path.relative_to(config.VAULT_PATH)))

        folder = path.parent.name if path.parent != config.VAULT_PATH else "(vault root)"
        folder_id = f"folder:{folder.lower()}"
        g.add_node(folder_id, "folder", folder)
        g.add_edge(folder_id, note_id, "contains")

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for target in _WIKILINK.findall(text):
            t = target.strip().lower()
            if not t:
                continue
            tid = f"note:{t}"
            g.add_node(tid, "note", target.strip())
            g.add_edge(note_id, tid, "link")

        for tag in set(_TAG.findall(text)):
            tid = f"tag:{tag.lower()}"
            g.add_node(tid, "tag", "#" + tag)
            g.add_edge(note_id, tid, "tag")
            tag_index[tid].add(note_id)

    # Living Memory records are first-class graph sources.  They remain in
    # their own canonical ledger; this merely derives relationship edges.
    try:
        from reyes_agent import living_memory

        for record in living_memory.graph_documents():
            memory_id = f"memory:{record['id']}"
            g.add_node(memory_id, "memory", record["title"], f"Living Memory/{record['id']}")
            for tag in set(record.get("tags", [])):
                tid = f"tag:{tag.lower()}"
                g.add_node(tid, "tag", "#" + tag)
                g.add_edge(memory_id, tid, "tag")
                tag_index[tid].add(memory_id)
            for target in _WIKILINK.findall(record["content"]):
                target = target.strip()
                if target:
                    tid = f"note:{target.lower()}"
                    g.add_node(tid, "note", target)
                    g.add_edge(memory_id, tid, "link")
    except Exception:  # graph views must remain available if memory is unavailable
        pass

    # Co-occurrence: notes sharing a tag are related. Capped so one very
    # common tag can't produce a quadratic explosion of meaningless edges.
    for tid, notes in tag_index.items():
        if 2 <= len(notes) <= 25:
            ordered = sorted(notes)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    g.add_edge(a, b, "related")
    return g


def stats() -> dict:
    g = build()
    kinds: dict[str, int] = defaultdict(int)
    for n in g.nodes.values():
        kinds[n.kind] += 1
    edge_kinds: dict[str, int] = defaultdict(int)
    for e in g.edges:
        edge_kinds[e.kind] += 1
    notes = [n for n in g.nodes.values() if n.kind == "note"]
    orphans = [n for n in notes if n.degree <= 1]  # only its folder edge
    hubs = sorted(notes, key=lambda n: n.degree, reverse=True)[:10]
    return {
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "by_kind": dict(kinds),
        "by_edge_kind": dict(edge_kinds),
        "orphan_count": len(orphans),
        "orphans": [n.label for n in orphans[:15]],
        "hubs": [{"label": n.label, "connections": n.degree, "path": n.path} for n in hubs],
    }


def neighbourhood(query: str, depth: int = 1, limit: int = 40) -> dict:
    """Everything connected to a topic, traced through real edges."""
    g = build()
    q = query.strip().lower()
    if not q:
        return {"error": "empty query"}

    seeds = [nid for nid, n in g.nodes.items() if q in n.label.lower() or q in nid.lower()]
    if not seeds:
        return {"query": query, "found": False,
                "message": f"Nothing in the vault matches '{query}'."}

    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in g.edges:
        adjacency[e.src].append((e.dst, e.kind))
        adjacency[e.dst].append((e.src, e.kind))

    seen = set(seeds)
    frontier = list(seeds)
    connections: list[dict] = []
    for _ in range(max(1, min(3, depth))):
        nxt = []
        for nid in frontier:
            for neighbour, kind in adjacency.get(nid, []):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                nxt.append(neighbour)
                node = g.nodes.get(neighbour)
                if node:
                    connections.append({
                        "from": g.nodes[nid].label if nid in g.nodes else nid,
                        "to": node.label, "kind": node.kind, "via": kind, "path": node.path,
                    })
                if len(connections) >= limit:
                    break
            if len(connections) >= limit:
                break
        frontier = nxt
        if not frontier or len(connections) >= limit:
            break

    return {
        "query": query,
        "found": True,
        "seeds": [g.nodes[s].label for s in seeds[:10]],
        "connection_count": len(connections),
        "connections": connections,
    }
