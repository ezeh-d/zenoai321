"""Bounded session language context for English/Nigerian English/Pidgin.

This observer never rewrites the owner's transcript and never selects a
language from one isolated word.  It supplies weak context to diagnostics and
the existing brain while the original speech remains authoritative.
"""

from __future__ import annotations

import re
import threading
from collections import deque

_PIDGIN = {
    "abeg", "wetin", "dey", "wahala", "sabi", "comot", "sha", "jare",
    "shey", "abi", "pikin", "chop", "gist", "vex", "una", "dem", "wey",
}
_lock = threading.RLock()
_recent: deque[str] = deque(maxlen=12)
_candidates: deque[str] = deque(maxlen=3)
_current = "Nigerian English"


def observe(text: str) -> dict:
    global _current
    words = re.findall(r"[a-z']+", str(text or "").casefold())
    hits = sorted(set(words) & _PIDGIN)
    if len(hits) >= 2:
        candidate = "Nigerian Pidgin / mixed English"
        evidence = f"multiple Pidgin context terms: {', '.join(hits[:5])}"
    elif len(hits) == 1:
        candidate = ""
        evidence = "one possible Pidgin term is insufficient to change language context"
    else:
        candidate = "Nigerian English"
        evidence = "no strong language-switch signal"
    with _lock:
        if candidate:
            _candidates.append(candidate)
            if list(_candidates).count(candidate) >= 2:
                _current = candidate
        _recent.append(candidate or "UNCERTAIN")
        result = {
            "current_language": _current,
            "observed_language": candidate or "UNCERTAIN",
            "recent_languages": list(_recent),
            "evidence": evidence,
            "pidgin_terms": hits[:8],
            "transcript_changed": False,
        }
    try:
        from reyes_agent import event_bus

        event_bus.publish("voice.language_context", {
            "current_language": result["current_language"],
            "observed_language": result["observed_language"],
        }, source="language_context")
    except Exception:
        pass
    return result


def status() -> dict:
    try:
        from reyes_agent import user_profiles

        owner = user_profiles.owner() or {}
        preferences = list(owner.get("language_preferences") or [])
    except Exception:
        preferences = []
    with _lock:
        return {
            "state": "READY",
            "current_language": _current,
            "recent_languages": list(_recent),
            "owner_language_preferences": preferences,
            "policy": "requires repeated contextual evidence; one word never switches the whole session",
        }


def reset() -> None:
    global _current
    with _lock:
        _recent.clear()
        _candidates.clear()
        _current = "Nigerian English"
