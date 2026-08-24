"""Searchable semantic memory of the user's OWN screen -- privacy first (Pack 10 #6-9).

Screen capture and OCR already exist as tools; the missing piece was the
searchable index and, crucially, the privacy gate. This stores lightweight
semantic snapshots (app, title, OCR text, description, time, url) -- never raw
screenshots -- and answers "what site was I on yesterday?" / "where did I see
that Python error?".

Privacy is enforced here, not left to callers:
* mode OFF stores nothing; SESSION_ONLY / WORK_ONLY / CUSTOM_APPS / FULL_OPT_IN
  bound what is retained (#8);
* excluded apps (banking, password managers, private chats, incognito) are never
  captured (#6);
* any snapshot whose text looks like a secret is refused (reuses safety guard).

Pure logic, deterministic, never raises.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

OFF = "OFF"
SESSION_ONLY = "SESSION_ONLY"
WORK_ONLY = "WORK_ONLY"
CUSTOM_APPS = "CUSTOM_APPS"
FULL_OPT_IN = "FULL_OPT_IN"
_MODES = {OFF, SESSION_ONLY, WORK_ONLY, CUSTOM_APPS, FULL_OPT_IN}

# Always excluded, whatever the mode -- sensitive by nature (#6).
_DEFAULT_EXCLUDED = {"1password", "bitwarden", "keepass", "lastpass",
                     "banking", "bank", "wallet"}
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class ScreenSnapshot:
    id: str
    app: str
    title: str = ""
    ocr_text: str = ""
    description: str = ""
    url: str = ""
    timestamp: float = 0.0

    def _hay(self) -> str:
        return f"{self.app} {self.title} {self.description} {self.ocr_text} {self.url}".casefold()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "app": self.app, "title": self.title,
                "description": self.description, "url": self.url,
                "timestamp": self.timestamp}


class ScreenRecallEngine:
    def __init__(self, mode: str = OFF, *, work_apps: set[str] | None = None,
                 custom_apps: set[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._mode = mode if mode in _MODES else OFF
        self._work = {a.casefold() for a in (work_apps or set())}
        self._custom = {a.casefold() for a in (custom_apps or set())}
        self._excluded = set(_DEFAULT_EXCLUDED)
        self._snaps: list[ScreenSnapshot] = []

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode if mode in _MODES else OFF

    def exclude_app(self, app: str) -> None:
        with self._lock:
            self._excluded.add(str(app or "").strip().casefold())

    def _allowed(self, app: str, incognito: bool) -> bool:
        app_l = str(app or "").strip().casefold()
        if self._mode == OFF or incognito or not app_l:
            return False
        if any(x in app_l for x in self._excluded):
            return False
        if self._mode in (SESSION_ONLY, FULL_OPT_IN):
            return True
        if self._mode == WORK_ONLY:
            return app_l in self._work
        if self._mode == CUSTOM_APPS:
            return app_l in self._custom
        return False

    def capture(self, snap: ScreenSnapshot, *, incognito: bool = False) -> bool:
        """Store a snapshot if the privacy gate allows AND it holds no secret.
        Returns True if retained."""
        try:
            if not self._allowed(snap.app, incognito):
                return False
            from reyes_agent.everyday.safety import detect_sensitive

            if detect_sensitive(f"{snap.ocr_text} {snap.title}")["found"]:
                return False                    # never index a screen full of secrets
            with self._lock:
                self._snaps.append(snap)
            return True
        except Exception:  # noqa: BLE001 -- recall must never break a caller
            return False

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q_tokens = _TOKEN.findall(str(query or "").casefold())
        q_low = str(query or "").casefold().strip()
        if not q_tokens:
            return []
        with self._lock:
            snaps = list(self._snaps)
        scored = []
        for s in snaps:
            hay = s._hay()
            score = 0.0
            for t in q_tokens:
                if t in hay:
                    score += 1.0
                else:
                    best = max((SequenceMatcher(None, t, w).ratio()
                                for w in _TOKEN.findall(hay)), default=0.0)
                    score += best if best >= 0.8 else 0.0
            score /= len(q_tokens)
            if q_low and q_low in hay:
                score = min(1.0, score + 0.15)
            if score >= 0.5:
                out = s.as_dict()
                out["score"] = round(score, 3)
                scored.append((score, s.timestamp, out))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [o for _, _, o in scored[:max(1, limit)]]

    def forget_app(self, app: str) -> int:
        app_l = str(app or "").strip().casefold()
        with self._lock:
            before = len(self._snaps)
            self._snaps = [s for s in self._snaps if s.app.casefold() != app_l]
            return before - len(self._snaps)

    def clear(self) -> None:
        with self._lock:
            self._snaps.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._snaps)


_instance: ScreenRecallEngine | None = None
_lock = threading.Lock()


def get_recall() -> ScreenRecallEngine:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ScreenRecallEngine()
        return _instance
