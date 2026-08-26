"""Bounded session callback memory and a privacy-filtered ZENO adapter."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.charm.models import CharmMode


def _hash_text(value: str) -> str:
    normalized = " ".join(str(value or "").casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class _Session:
    messages: deque[str]
    candidates: deque[tuple[str, str]]
    candidate_text: dict[str, str] = field(default_factory=dict)
    feedback: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=50))
    mode: CharmMode = CharmMode.NATURAL
    intensity: int = 50
    touched_at: float = field(default_factory=time.time)


class CharmSessionStore:
    """Small process-local memory; no transcript is written to durable storage."""

    def __init__(
        self, *, max_sessions: int = 32, max_candidates: int = 50,
        max_messages: int = 20,
    ) -> None:
        self.max_sessions = max(1, min(128, int(max_sessions)))
        self.max_candidates = max(1, min(200, int(max_candidates)))
        self.max_messages = max(1, min(100, int(max_messages)))
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.RLock()

    def _get(self, session_id: str, *, create: bool = True) -> _Session | None:
        key = str(session_id or "default")[:80]
        session = self._sessions.get(key)
        if session is None and create:
            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)
            session = _Session(
                messages=deque(maxlen=self.max_messages),
                candidates=deque(),
            )
            self._sessions[key] = session
        if session is not None:
            session.touched_at = time.time()
            self._sessions.move_to_end(key)
        return session

    def record_conversation(self, session_id: str, messages: list[str] | tuple[str, ...]) -> None:
        with self._lock:
            session = self._get(session_id)
            assert session is not None
            incoming = [str(item)[:1000] for item in messages if str(item).strip()]
            existing = list(session.messages)
            overlap = 0
            for size in range(min(len(existing), len(incoming)), 0, -1):
                if existing[-size:] == incoming[:size]:
                    overlap = size
                    break
            session.messages.extend(incoming[overlap:])

    def recent_conversation(self, session_id: str) -> tuple[str, ...]:
        with self._lock:
            session = self._get(session_id, create=False)
            return tuple(session.messages) if session else ()

    def record_candidates(self, session_id: str, candidates: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        ids: list[str] = []
        with self._lock:
            session = self._get(session_id)
            assert session is not None
            for text in candidates:
                clean = " ".join(str(text or "").split())[:1000]
                if not clean:
                    continue
                digest = _hash_text(clean)
                candidate_id = f"charm_{digest[:16]}"
                existing = next((item for item in session.candidates if item[0] == candidate_id), None)
                if existing is not None:
                    session.candidates.remove(existing)
                while len(session.candidates) >= self.max_candidates:
                    old_id, _old_hash = session.candidates.popleft()
                    session.candidate_text.pop(old_id, None)
                session.candidates.append((candidate_id, digest))
                session.candidate_text[candidate_id] = clean
                ids.append(candidate_id)
        return tuple(ids)

    def recent_hashes(self, session_id: str) -> tuple[str, ...]:
        with self._lock:
            session = self._get(session_id, create=False)
            return tuple(item[1] for item in session.candidates) if session else ()

    def resolve_candidate(self, session_id: str, candidate_id: str) -> str | None:
        with self._lock:
            session = self._get(session_id, create=False)
            return session.candidate_text.get(str(candidate_id)) if session else None

    def record_feedback(self, session_id: str, candidate_id: str, outcome: str) -> bool:
        with self._lock:
            session = self._get(session_id, create=False)
            if session is None or str(candidate_id) not in session.candidate_text:
                return False
            session.feedback.append({
                "candidate_id": str(candidate_id),
                "outcome": self.feedback_label(outcome),
                "at": time.time(),
            })
            return True

    @staticmethod
    def feedback_label(outcome: str) -> str:
        """Reduce arbitrary feedback to a non-sensitive bounded style label."""
        value = " ".join(str(outcome or "").casefold().split())
        labels = (
            ("too_long", ("too long", "shorter", "more concise")),
            ("too_short", ("too short", "longer", "more detail")),
            ("too_formal", ("too formal", "less formal")),
            ("too_flirty", ("too flirty", "less flirty")),
            ("too_dry", ("too dry", "warmer")),
            ("disliked", ("dislike", "bad", "didn't like", "did not like")),
            ("liked", ("liked", "like this", "good", "used it", "natural")),
            ("cringe", ("cringe", "awkward")),
        )
        for label, markers in labels:
            if any(marker in value for marker in markers):
                return label
        return "custom"

    def feedback_hints(self, session_id: str, *, limit: int = 2) -> tuple[str, ...]:
        """Return a tiny session-only voice signal for the next generation."""
        with self._lock:
            session = self._get(session_id, create=False)
            if session is None:
                return ()
            out: list[str] = []
            for item in reversed(session.feedback):
                candidate = session.candidate_text.get(item["candidate_id"], "")
                outcome = " ".join(str(item.get("outcome") or "").split())[:80]
                if not candidate or not outcome:
                    continue
                out.append(f"Session feedback ({outcome}): {candidate[:220]}")
                if len(out) >= max(1, min(3, int(limit))):
                    break
            return tuple(out)

    def set_mode(self, session_id: str, mode: CharmMode | str, intensity: int | None = None) -> None:
        with self._lock:
            session = self._get(session_id)
            assert session is not None
            session.mode = CharmMode.parse(mode)
            if intensity is not None:
                session.intensity = max(0, min(100, int(intensity)))

    def selection(self, session_id: str) -> tuple[CharmMode, int]:
        with self._lock:
            session = self._get(session_id)
            assert session is not None
            return session.mode, session.intensity

    def snapshot(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._get(session_id, create=False)
            if session is None:
                return {"exists": False, "message_count": 0, "candidate_count": 0,
                        "feedback_count": 0}
            return {
                "exists": True,
                "mode": session.mode.value,
                "intensity": session.intensity,
                "message_count": len(session.messages),
                "candidate_count": len(session.candidates),
                "feedback_count": len(session.feedback),
                "session_count": len(self._sessions),
            }


_ALLOWED_MEMORY_CATEGORIES = frozenset({
    "preference", "preferences", "user", "profile", "communication", "style",
})
_SENSITIVE_MEMORY_RE = re.compile(
    r"\b(?:password|passcode|api[ _-]?key|secret|private key|credential|token)\b",
    re.IGNORECASE,
)
_PREFERENCE_MEMORY_RE = re.compile(
    r"\b(?:prefer|preference|likes?|dislikes?|communication|reply|response|tone|"
    r"style|pidgin|language|code-switch|concise|brief|short|formal|informal|"
    r"playful|natural|witty|sweet|funny)\b",
    re.IGNORECASE,
)


class MemoryAdapter:
    """Read-only access to relevant normal ZENO memory; never eMEM."""

    def __init__(self, manager: Any | None = None) -> None:
        self._manager = manager

    def _get_manager(self) -> Any:
        if self._manager is None:
            from reyes_agent.memory.manager import get_memory_manager

            self._manager = get_memory_manager()
        return self._manager

    def preferences(self, query: str, *, limit: int = 6) -> tuple[str, ...]:
        manager = self._get_manager()
        try:
            rows = manager.retrieve(
                f"communication style preference {' '.join(str(query or '').split())}".strip(),
                limit=max(1, min(6, int(limit))),
            )
        except Exception:
            return ()
        out: list[str] = []
        for row in rows:
            category = str(row.get("category") or row.get("source") or "").casefold()
            text = " ".join(str(row.get("memory") or "").split())[:500]
            if category not in _ALLOWED_MEMORY_CATEGORIES or not text:
                continue
            if _SENSITIVE_MEMORY_RE.search(text):
                continue
            if not _PREFERENCE_MEMORY_RE.search(text):
                continue
            if text not in out:
                out.append(text)
            if len(out) >= 6:
                break
        return tuple(out)
