"""What the owner means when they say a particular thing.

WHY THIS IS NOT A GLOBAL DICTIONARY
-----------------------------------
"bring it out" means "give me the full output now" when this owner says it.
It does not mean that in English generally, and hard-coding it globally would
corrupt every other sentence containing those words.

So mappings are:
  * scoped to the owner
  * matched only as a WHOLE utterance, or a clearly delimited phrase
  * confidence-weighted, with owner corrections outranking observations
  * individually removable

A single correction does not become a rule everywhere. It becomes a
higher-confidence entry for one phrase.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent import config

_DB = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "language" / "phrases.sqlite"

# An owner saying "when I say X I mean Y" is authoritative. Something merely
# observed is a hint. The gap has to be big enough that one observation never
# overrides one instruction.
CONFIDENCE_TAUGHT = 0.95
CONFIDENCE_CORRECTED = 0.9
CONFIDENCE_OBSERVED = 0.4


@dataclass(frozen=True)
class Phrase:
    phrase: str
    meaning: str
    language: str
    confidence: float
    source: str
    uses: int = 0
    last_used: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"phrase": self.phrase, "meaning": self.meaning,
                "language": self.language, "confidence": round(self.confidence, 2),
                "source": self.source, "uses": self.uses}


class LanguageMemory:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._count: int | None = None
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS phrases(
                    phrase TEXT PRIMARY KEY,
                    meaning TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.4,
                    source TEXT NOT NULL DEFAULT 'observed',
                    uses INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL,
                    last_used REAL NOT NULL DEFAULT 0,
                    history TEXT NOT NULL DEFAULT '[]');
                """)

    def has_phrases(self) -> bool:
        """Whether ANY phrase is stored, cached.

        `apply()` opened a connection, ran an UPDATE and selected up to 200
        rows on EVERY turn, including plain English ones. Fast-path latency
        climbed 11ms -> 31ms across three consecutive calls because of it.
        An empty store is the normal case and must cost nothing.
        """
        if self._count is None:
            with self._connection() as conn:
                row = conn.execute("SELECT COUNT(*) AS n FROM phrases").fetchone()
            self._count = int(row["n"])
        return self._count > 0

    def teach(self, phrase: str, meaning: str, *, language: str = "",
              source: str = "taught") -> bool:
        """Record what a phrase means. `source` sets how much it is trusted."""
        key = _key(phrase)
        if not key or not str(meaning or "").strip():
            return False
        confidence = {"taught": CONFIDENCE_TAUGHT,
                      "corrected": CONFIDENCE_CORRECTED}.get(source, CONFIDENCE_OBSERVED)
        now = time.time()
        with self._connection() as conn:
            row = conn.execute("SELECT meaning, history FROM phrases WHERE phrase=?",
                               (key,)).fetchone()
            history = json.loads(row["history"]) if row else []
            if row and row["meaning"] != meaning:
                # Keep what it used to mean. A correction that silently
                # overwrites leaves no way to see the mapping drifted.
                history.append({"was": row["meaning"], "at": now})
            conn.execute(
                "INSERT INTO phrases(phrase,meaning,language,confidence,source,"
                "created,last_used,history) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(phrase) DO UPDATE SET meaning=excluded.meaning, "
                "confidence=MAX(confidence, excluded.confidence), "
                "source=excluded.source, history=excluded.history",
                (key, str(meaning).strip(), language, confidence, source,
                 now, now, json.dumps(history[-10:])))
        self._count = None
        return True

    def correct(self, phrase: str, meaning: str, *, language: str = "") -> bool:
        return self.teach(phrase, meaning, language=language, source="corrected")

    def lookup(self, phrase: str) -> Phrase | None:
        key = _key(phrase)
        if not key:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM phrases WHERE phrase=?", (key,)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE phrases SET uses=uses+1, last_used=? WHERE phrase=?",
                         (time.time(), key))
        return Phrase(row["phrase"], row["meaning"], row["language"],
                      row["confidence"], row["source"], row["uses"] + 1,
                      row["last_used"])

    def apply(self, text: str, *, minimum_confidence: float = 0.5) -> tuple[str, list[str]]:
        if not self.has_phrases():
            return str(text or ""), []
        return self._apply(text, minimum_confidence=minimum_confidence)

    def _apply(self, text: str, *, minimum_confidence: float = 0.5) -> tuple[str, list[str]]:
        """Substitute known phrases. Whole utterance first, then phrases.

        Only phrases above `minimum_confidence` are applied, so a merely
        observed guess never rewrites a sentence on its own.
        """
        raw = str(text or "")
        whole = self.lookup(raw)
        if whole and whole.confidence >= minimum_confidence:
            return whole.meaning, [whole.phrase]

        applied: list[str] = []
        out = raw
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT phrase, meaning FROM phrases WHERE confidence >= ? "
                "ORDER BY LENGTH(phrase) DESC LIMIT 200",
                (minimum_confidence,)).fetchall()
        for row in rows:
            pattern = re.compile(rf"(?<!\w){re.escape(row['phrase'])}(?!\w)",
                                 re.IGNORECASE)
            new = pattern.sub(row["meaning"], out)
            if new != out:
                applied.append(row["phrase"])
                out = new
        return out, applied

    def forget(self, phrase: str) -> bool:
        with self._connection() as conn:
            deleted = bool(conn.execute("DELETE FROM phrases WHERE phrase=?",
                                        (_key(phrase),)).rowcount)
        self._count = None
        return deleted

    def clear(self) -> int:
        """"ZENO, clear my learned language preferences." Only these."""
        with self._connection() as conn:
            removed = int(conn.execute("DELETE FROM phrases").rowcount)
        self._count = None
        return removed

    def all(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM phrases ORDER BY confidence DESC, uses DESC LIMIT ?",
                (limit,)).fetchall()
        return [Phrase(r["phrase"], r["meaning"], r["language"], r["confidence"],
                       r["source"], r["uses"], r["last_used"]).as_dict() for r in rows]


_TEACH_RE = re.compile(
    r"\bwhen\s+i\s+say\s+[\"'“]?(?P<phrase>[^\"'”,]{2,60})[\"'”]?\s*[,]?\s*"
    r"i\s+mean\s+[\"'“]?(?P<meaning>.{2,200}?)[\"'”]?\s*[.!]?$",
    re.IGNORECASE)


def parse_teaching(text: str) -> tuple[str, str] | None:
    """Recognise "when I say X, I mean Y" so the owner can state a mapping."""
    match = _TEACH_RE.search(str(text or "").strip())
    if not match:
        return None
    return match.group("phrase").strip(), match.group("meaning").strip()


def _key(phrase: str) -> str:
    return " ".join(str(phrase or "").lower().split())[:120]


_memory: LanguageMemory | None = None
_lock = threading.Lock()


def get_memory() -> LanguageMemory:
    global _memory
    with _lock:
        if _memory is None:
            _memory = LanguageMemory()
        return _memory


def reset_for_tests(db_path: Path | None = None) -> LanguageMemory:
    global _memory
    with _lock:
        _memory = LanguageMemory(db_path)
        return _memory
