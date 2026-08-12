"""Bounded local vocabulary corrections, separate from conversation memory."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from reyes_agent.voice.vocabulary.project_terms import current_terms

_DEFAULT = Path(__file__).with_name("owner_terms.json")
_USER = Path(os.environ.get("LOCALAPPDATA", ".")) / "ZENO" / "Vocabulary" / "owner_terms.json"
_LOCK = threading.RLock()
_MAX_TERMS = 200


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def terms(limit: int = 100) -> list[str]:
    values: list[str] = []
    with _LOCK:
        for source in (_read(_DEFAULT), _read(_USER)):
            values.extend(str(value).strip() for value in source.get("terms", []) if str(value).strip())
            values.extend(str(value).strip() for value in source.get("corrections", {}).values() if str(value).strip())
    values.extend(current_terms())
    return list(dict.fromkeys(values))[: max(1, min(_MAX_TERMS, limit))]


def add_correction(heard: str, intended: str) -> dict:
    heard, intended = str(heard).strip(), str(intended).strip()
    if not heard or not intended or len(heard) > 80 or len(intended) > 80:
        raise ValueError("Vocabulary corrections require two short non-empty terms")
    with _LOCK:
        data = _read(_USER)
        corrections = dict(data.get("corrections") or {})
        corrections[heard] = intended
        if len(corrections) > _MAX_TERMS:
            corrections = dict(list(corrections.items())[-_MAX_TERMS:])
        data = {"terms": list(dict.fromkeys([*(data.get("terms") or []), intended]))[-_MAX_TERMS:],
                "corrections": corrections}
        _USER.parent.mkdir(parents=True, exist_ok=True)
        temporary = _USER.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(_USER)
    return {"heard": heard, "intended": intended, "stored_locally": True}

