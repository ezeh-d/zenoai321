"""Notification triage: categorize, de-duplicate, digest, respect quiet states.

Cuts the noise the way Pack 10 #20-25 asks: one engine that classifies each
notification, collapses duplicate alerts (the same story from email + news + an
app is ONE item), produces a digest, and stays quiet in meetings/class/focus/
sleep -- where only CRITICAL gets through. Pure logic, deterministic, never
raises. Preferences change ranking/timing, never truth.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

# Priority categories, most to least urgent.
CRITICAL = "CRITICAL"
IMPORTANT = "IMPORTANT"
ACTION_REQUIRED = "ACTION_REQUIRED"
INFORMATIONAL = "INFORMATIONAL"
LOW_PRIORITY = "LOW_PRIORITY"
MUTED = "MUTED"
_ORDER = {CRITICAL: 0, ACTION_REQUIRED: 1, IMPORTANT: 2,
          INFORMATIONAL: 3, LOW_PRIORITY: 4, MUTED: 5}

# Quiet states -- when set, only CRITICAL passes through.
NORMAL = "NORMAL"
_QUIET = {"MEETING", "CLASS", "FOCUS", "SLEEP", "PRESENTATION", "CALL"}

_CRITICAL_RE = re.compile(r"\b(urgent|critical|emergency|security alert|"
                          r"fraud|unauthorized|breach|otp|verification code|"
                          r"account locked|payment failed)\b", re.I)
_ACTION_RE = re.compile(r"\b(action required|please (?:reply|respond|approve|confirm)|"
                        r"awaiting your|reply needed|sign|review and|approve|rsvp)\b", re.I)
_IMPORTANT_RE = re.compile(r"\b(meeting|deadline|invoice|due|boss|manager|"
                           r"interview|flight|delivery|goal|red card|final)\b", re.I)
_LOW_RE = re.compile(r"\b(sale|promo|newsletter|digest|suggested|trending|"
                     r"like[sd]?|followed you|recommended)\b", re.I)


@dataclass
class Notification:
    id: str
    source: str
    title: str = ""
    body: str = ""
    timestamp: float = 0.0
    category: str = ""            # filled by classify() if empty

    def _text(self) -> str:
        return f"{self.title} {self.body}".strip()


def classify(note: Notification, muted_sources: set[str] | None = None) -> str:
    if muted_sources and note.source.strip().casefold() in muted_sources:
        return MUTED
    text = note._text()
    if _CRITICAL_RE.search(text):
        return CRITICAL
    if _ACTION_RE.search(text):
        return ACTION_REQUIRED
    if _IMPORTANT_RE.search(text):
        return IMPORTANT
    if _LOW_RE.search(text):
        return LOW_PRIORITY
    return INFORMATIONAL


class NotificationIntelligenceEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._notes: list[Notification] = []
        self._muted: set[str] = set()
        self._quiet: str = NORMAL

    def mute_source(self, source: str) -> None:
        with self._lock:
            self._muted.add(str(source or "").strip().casefold())

    def set_quiet(self, state: str) -> None:
        state = str(state or "").strip().upper() or NORMAL
        with self._lock:
            self._quiet = state if state in _QUIET or state == NORMAL else NORMAL

    def ingest(self, note: Notification) -> str:
        """Add one notification, classified and de-duplicated. Returns its
        category, or "" if suppressed as a duplicate."""
        with self._lock:
            note.category = note.category or classify(note, self._muted)
            for existing in self._notes:
                if self._same(existing, note):
                    return ""              # duplicate collapsed
            self._notes.append(note)
            return note.category

    def _same(self, a: Notification, b: Notification) -> bool:
        if a.source == b.source and a.title.strip().casefold() == b.title.strip().casefold():
            return True
        return SequenceMatcher(None, a._text().casefold(), b._text().casefold()).ratio() >= 0.85

    def visible(self) -> list[Notification]:
        """Notifications that should surface right now, honouring quiet state."""
        with self._lock:
            quiet = self._quiet
            notes = list(self._notes)
        if quiet in _QUIET:
            notes = [n for n in notes if n.category == CRITICAL]
        else:
            notes = [n for n in notes if n.category != MUTED]
        notes.sort(key=lambda n: (_ORDER.get(n.category, 9), -n.timestamp))
        return notes

    def important_only(self) -> list[Notification]:
        return [n for n in self.visible()
                if n.category in (CRITICAL, ACTION_REQUIRED, IMPORTANT)]

    def digest(self) -> dict[str, Any]:
        with self._lock:
            notes = list(self._notes)
        counts: dict[str, int] = {}
        for n in notes:
            counts[n.category] = counts.get(n.category, 0) + 1
        top = self.important_only()[:5]
        return {
            "total": len(notes),
            "by_category": counts,
            "needs_attention": len([n for n in notes
                                    if n.category in (CRITICAL, ACTION_REQUIRED)]),
            "quiet_state": self._quiet,
            "top": [{"source": n.source, "title": n.title, "category": n.category}
                    for n in top],
        }

    def clear(self) -> None:
        with self._lock:
            self._notes.clear()
