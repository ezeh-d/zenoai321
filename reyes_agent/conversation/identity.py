"""Who is speaking -- session labels and EXPLICIT names only.

Safety (pack6 #14-20, #291-292): ZENO never infers real-world identity from a
voice or a face. A speaker starts as an anonymous session label ("Speaker 2")
and only gains a name when someone introduces themselves, or the owner says who
they are. Nothing here listens to audio; it stores what it is explicitly told.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Identity confidence, weakest to strongest.
UNKNOWN = "UNKNOWN"
SESSION_LABEL = "SESSION_LABEL"      # "Speaker 2" -- a diarization label, no name
INTRODUCED_NAME = "INTRODUCED_NAME"  # they said "I'm Ayo"
OWNER_CONFIRMED = "OWNER_CONFIRMED"  # the owner said "that's my lecturer, Dr. Bello"
ENROLLED_SPEAKER = "ENROLLED_SPEAKER"  # a consented, enrolled voiceprint (not done here)

_ORDER = {UNKNOWN: 0, SESSION_LABEL: 1, INTRODUCED_NAME: 2,
          OWNER_CONFIRMED: 3, ENROLLED_SPEAKER: 4}


@dataclass
class SpeakerProfile:
    speaker_id: str
    level: str = SESSION_LABEL
    display_name: str = ""
    relationship: str = ""      # explicit only: friend/lecturer/manager/...
    role: str = ""
    title: str = ""             # Dr./Prof./Mr./... when explicitly given
    pronunciation: str = ""

    def label(self, fallback_index: int | None = None) -> str:
        if self.display_name:
            return f"{self.title} {self.display_name}".strip()
        if fallback_index is not None:
            return f"Speaker {fallback_index}"
        return self.speaker_id

    def as_dict(self) -> dict[str, Any]:
        return {"speaker_id": self.speaker_id, "level": self.level,
                "display_name": self.display_name, "relationship": self.relationship,
                "role": self.role, "title": self.title,
                "pronunciation": self.pronunciation}


class SpeakerIdentityManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, SpeakerProfile] = {}
        self._order: list[str] = []     # first-seen order, for stable "Speaker N"

    def observe(self, speaker_id: str) -> SpeakerProfile:
        """Register a session label for a diarized speaker (no name)."""
        sid = str(speaker_id or "").strip()
        with self._lock:
            prof = self._by_id.get(sid)
            if prof is None and sid:
                prof = self._by_id[sid] = SpeakerProfile(sid, level=SESSION_LABEL)
                self._order.append(sid)
            return prof or SpeakerProfile(sid, level=UNKNOWN)

    def introduce(self, speaker_id: str, name: str) -> SpeakerProfile:
        """They introduced themselves -- session name, no enrollment."""
        return self._name(speaker_id, name, INTRODUCED_NAME)

    def owner_identify(self, speaker_id: str, name: str, *, relationship: str = "",
                       role: str = "", title: str = "") -> SpeakerProfile:
        """The owner told ZENO who this is -- the strongest non-biometric level."""
        prof = self._name(speaker_id, name, OWNER_CONFIRMED)
        with self._lock:
            if relationship:
                prof.relationship = str(relationship).strip().casefold()
            if role:
                prof.role = str(role).strip()
            if title:
                prof.title = str(title).strip()
        return prof

    def _name(self, speaker_id: str, name: str, level: str) -> SpeakerProfile:
        sid = str(speaker_id or "").strip()
        nm = str(name or "").strip()
        with self._lock:
            prof = self._by_id.get(sid)
            if prof is None:
                prof = self._by_id[sid] = SpeakerProfile(sid)
                self._order.append(sid)
            if nm:
                prof.display_name = nm
            # Never downgrade a stronger, explicit identity to a weaker one.
            if _ORDER.get(level, 0) >= _ORDER.get(prof.level, 0):
                prof.level = level
            return prof

    def set_relationship(self, speaker_id: str, relationship: str) -> bool:
        with self._lock:
            prof = self._by_id.get(str(speaker_id or "").strip())
            if prof is None:
                return False
            prof.relationship = str(relationship or "").strip().casefold()
            return True

    def label_for(self, speaker_id: str) -> str:
        sid = str(speaker_id or "").strip()
        with self._lock:
            prof = self._by_id.get(sid)
            if prof is None:
                return sid or "Unknown speaker"
            index = self._order.index(sid) + 1 if sid in self._order else None
            return prof.label(index)

    def find_by_name(self, name: str) -> list[SpeakerProfile]:
        nm = str(name or "").strip().casefold()
        with self._lock:
            return [p for p in self._by_id.values()
                    if p.display_name and p.display_name.casefold() == nm]

    def forget(self, speaker_id: str) -> bool:
        """Drop a speaker's session identity (pack6 #125-126)."""
        sid = str(speaker_id or "").strip()
        with self._lock:
            existed = self._by_id.pop(sid, None) is not None
            if sid in self._order:
                self._order.remove(sid)
            return existed

    def roster(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._by_id[s].as_dict() for s in self._order if s in self._by_id]
