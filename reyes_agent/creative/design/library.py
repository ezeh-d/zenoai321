"""Design knowledge as data, read by ZENO's own code.

WHERE THIS CAME FROM, AND WHAT DID NOT
--------------------------------------
The CSVs under `data/` are vendored from `nextlevelbuilder/ui-ux-pro-max-skill`
(MIT, licence kept alongside them). 51 files: UI styles, colour palettes,
font pairings, industry conventions, layout and chart guidance.

Only the DATA was taken. None of the upstream Python or JavaScript is in
ZENO, and the loader below is ZENO's own -- because several of the
upstream scripts make network calls (`fetch-background.py` reaches image
APIs), and vendoring a script that phones out is how a design library
becomes an egress path nobody reviewed.

That also means there is no global npm install, nothing on PATH, and
nothing to keep in sync: the data sits in the repo under version control
like any other asset.

WHY CSV AND NOT A DATABASE
--------------------------
It is a few megabytes of rows that change when someone edits them by hand.
A CSV the owner can open in a spreadsheet and correct is worth more here
than an index that is faster than anyone can perceive.
"""

from __future__ import annotations

import csv
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ATTRIBUTION = ("Design data from nextlevelbuilder/ui-ux-pro-max-skill (MIT). "
               "Data only -- no upstream code runs inside ZENO.")

_lock = threading.RLock()
_tables: dict[str, list[dict[str, str]]] | None = None


def _root() -> Path:
    return Path(__file__).resolve().parent / "data"


def _load() -> dict[str, list[dict[str, str]]]:
    global _tables
    with _lock:
        if _tables is not None:
            return _tables
        tables: dict[str, list[dict[str, str]]] = {}
        root = _root()
        if root.is_dir():
            for path in sorted(root.glob("*.csv")):
                try:
                    with path.open(encoding="utf-8-sig", newline="") as handle:
                        rows = [dict(row) for row in csv.DictReader(handle)]
                except (OSError, UnicodeDecodeError, csv.Error):
                    continue          # one bad file never hides the rest
                if rows:
                    tables[path.stem] = rows
        _tables = tables
        return _tables


@dataclass
class Match:
    table: str
    row: dict[str, str]
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {"table": self.table, "score": round(self.score, 3), **self.row}


def tables() -> list[str]:
    return sorted(_load())


def rows(table: str) -> list[dict[str, str]]:
    return list(_load().get(table, []))


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())]


def search(query: str, *, table: str = "", limit: int = 8) -> list[Match]:
    """Find design guidance matching a brief.

    Scored on term COVERAGE first, then frequency -- a row mentioning every
    word in the brief once beats one that repeats a single word, which is
    the failure mode of raw frequency matching over short rows.
    """
    terms = _terms(query)
    if not terms:
        return []

    found: list[Match] = []
    for name, table_rows in _load().items():
        if table and table not in name:
            continue
        for row in table_rows:
            haystack = " ".join(str(v) for v in row.values()).lower()
            hits = {t: haystack.count(t) for t in terms}
            covered = sum(1 for t in terms if hits[t])
            if not covered:
                continue
            coverage = covered / len(terms)
            density = sum(hits.values()) / max(40, len(haystack) / 12)
            found.append(Match(name, row, coverage * 2 + min(density, 1.0)))

    found.sort(key=lambda m: -m.score)
    return found[:max(1, limit)]


def palette_for(brief: str, limit: int = 5) -> list[dict[str, Any]]:
    """Colour guidance for a brief, from the palette tables only."""
    return [m.as_dict() for m in search(brief, table="color", limit=limit)] or \
           [m.as_dict() for m in search(brief, table="palette", limit=limit)]


def style_for(brief: str, limit: int = 5) -> list[dict[str, Any]]:
    return [m.as_dict() for m in search(brief, table="style", limit=limit)]


def typography_for(brief: str, limit: int = 5) -> list[dict[str, Any]]:
    return [m.as_dict() for m in search(brief, table="typograph", limit=limit)] or \
           [m.as_dict() for m in search(brief, table="font", limit=limit)]


def brief_guidance(brief: str) -> dict[str, Any]:
    """Everything the library has to say about one creative brief."""
    return {
        "brief": brief,
        "styles": style_for(brief, 3),
        "palettes": palette_for(brief, 3),
        "typography": typography_for(brief, 3),
        "other": [m.as_dict() for m in search(brief, limit=4)],
        "attribution": ATTRIBUTION,
        "note": ("Guidance, not a decision. These are conventions other designers "
                 "settled on, offered so ZENO is not inventing a palette from "
                 "nothing."),
    }


def reset_cache() -> None:
    global _tables
    with _lock:
        _tables = None


def status() -> dict[str, Any]:
    loaded = _load()
    return {
        "state": "ONLINE" if loaded else "DEGRADED",
        "tables": len(loaded),
        "rows": sum(len(v) for v in loaded.values()),
        "path": str(_root()),
        "source": "nextlevelbuilder/ui-ux-pro-max-skill",
        "license": "MIT (kept at data/LICENSE-ui-ux-pro-max.txt)",
        "vendored": "data only -- no upstream code runs inside ZENO",
        "offline": True,
        "note": ATTRIBUTION,
    }
