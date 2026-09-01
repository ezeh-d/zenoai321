"""Semantic intent router -- ultra-fast command intent classification (#3).

Adapted from aurelio-labs/semantic-router (a Route is an intent + example
utterances; a query is embedded and matched to the nearest route by cosine
similarity above a threshold). Nothing is copied: this reuses ZENO's already
installed sentence-transformer (the same all-MiniLM the spatial memory uses)
and maps intents onto ZENO's EXISTING capabilities.

WHY, ALONGSIDE THE REGEX CAPABILITY ROUTER
------------------------------------------
routing/capability.py matches deterministic trigger phrases -- exact and fast,
but brittle to paraphrase ("fire up spotify", "get spotify going"). This adds a
semantic layer: it recognises intent by meaning, so a phrasing the triggers miss
still routes. It AUGMENTS, never replaces -- capability.tools_for stays the
authority; this only suggests a capability to include when it is confident.

DEGRADES, NEVER BREAKS
----------------------
If sentence-transformers/numpy aren't importable, or the model can't load,
available() is False and callers fall back to the regex router unchanged. Gated
by ZENO_INTENT_ROUTER (default 'auto' = on when the model is present).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

_MODEL_NAME = os.environ.get("ZENO_INTENT_MODEL", "all-MiniLM-L6-v2")
_DEFAULT_THRESHOLD = 0.42


@dataclass
class Route:
    intent: str
    capability: str            # a key that exists in capability.CAPABILITIES
    utterances: tuple[str, ...]
    threshold: float = _DEFAULT_THRESHOLD


@dataclass
class IntentMatch:
    intent: str
    capability: str
    confidence: float
    method: str = "semantic"

    def as_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "capability": self.capability,
                "confidence": round(self.confidence, 3), "method": self.method}


# Intents mapped onto ZENO's real capabilities. Utterances are paraphrases the
# regex triggers would miss; the point is robustness to phrasing, not coverage.
_DEFAULT_ROUTES: tuple[Route, ...] = (
    Route("open_app", "desktop", (
        "open chrome", "launch spotify", "fire up notepad", "get calculator going",
        "start the browser", "bring up the settings app", "run the terminal")),
    Route("play_media", "media", (
        "play some music", "pause the song", "skip this track", "turn it up",
        "next song please", "resume playback", "put on some afrobeats",
        "what's playing", "turn spotify down", "what song is this")),
    Route("open_content", "files", (
        "look at this file", "open that pdf", "read this document for me",
        "what is this file", "open the spreadsheet", "check this word document",
        "have a look at this image", "what does this file say")),
    Route("study_material", "study", (
        "study this", "teach me this", "quiz me", "test me on this",
        "help me revise for the exam", "learn this course", "make flashcards",
        "explain this chapter", "what am I weak in", "what did you learn")),
    Route("defense_mode", "presentation", (
        "defense mode", "get ready for my presentation", "we're about to present",
        "presentation mode on", "prepare for the demo", "it's defense time")),
    Route("reply_message", "communication", (
        "reply to him", "tell her i'll be there", "send him a message",
        "let them know i'm coming", "respond saying yes", "text her back")),
    Route("system_query", "diagnostics", (
        "why is my laptop slow", "check the memory usage", "what's using the cpu",
        "is my disk full", "how much ram is left", "what's slowing things down")),
    Route("web_search", "web", (
        "search for the news", "look up the weather", "google the score",
        "find information about", "what's happening in the world", "look this up")),
    Route("where_is", "spatial", (
        "where is my laptop", "where did i leave my keys", "where did you last see",
        "which room is my bag in", "find my phone")),
)


def _cosine(a, b) -> float:
    import numpy as np
    denom = (float(np.linalg.norm(a)) * float(np.linalg.norm(b))) or 1.0
    return float(np.dot(a, b) / denom)


class IntentRouter:
    def __init__(self, routes: tuple[Route, ...] = _DEFAULT_ROUTES, *,
                 encoder: Any = None) -> None:
        self._routes = routes
        # encoder(list[str]) -> list[vector]; None loads the shared model lazily.
        # Injectable so the routing logic is tested without loading a model.
        self._encoder = encoder
        self._ready = False
        self._tried = False
        self._err = ""
        self._lock = threading.RLock()
        self._route_vecs: list[tuple[Route, Any]] = []   # embeddings, built once

    # -- lifecycle ---------------------------------------------------------
    def _encode(self, texts: list[str]):
        import numpy as np
        if self._encoder is not None:
            return np.asarray(self._encoder(texts))
        return np.asarray(self._model.encode(texts, normalize_embeddings=False))

    def _ensure(self) -> bool:
        with self._lock:
            if self._ready:
                return True
            if self._tried:
                return False
            self._tried = True
            mode = os.environ.get("ZENO_INTENT_ROUTER", "auto").strip().casefold()
            if mode in ("0", "off", "false", "no"):
                self._err = "disabled (ZENO_INTENT_ROUTER=off)"
                return False
            try:
                import numpy as np  # noqa: F401 -- ensures the dep is present
                if self._encoder is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(_MODEL_NAME)
                for route in self._routes:
                    self._route_vecs.append((route, self._encode(list(route.utterances))))
                self._ready = True
                return True
            except Exception as exc:  # noqa: BLE001 -- optional; degrade to regex
                self._err = f"{type(exc).__name__}: {exc}"[:150]
                self._ready = False
                return False

    def available(self) -> bool:
        return self._ensure()

    # -- classification ----------------------------------------------------
    def classify(self, message: str) -> IntentMatch | None:
        """Best intent for `message`, or None if nothing clears its threshold
        (the caller then uses the regex router unchanged)."""
        text = str(message or "").strip()
        if len(text) < 2 or not self._ensure():
            return None
        try:
            q = self._encode([text])[0]
            best: IntentMatch | None = None
            for route, vecs in self._route_vecs:
                # max similarity to any example utterance of the route
                score = max(_cosine(q, v) for v in vecs)
                if score >= route.threshold and (best is None or score > best.confidence):
                    best = IntentMatch(route.intent, route.capability, score)
            return best
        except Exception:  # noqa: BLE001 -- never break routing on telemetry
            return None

    def suggest_capability(self, message: str) -> str:
        """The capability to fold in when confident, else '' (safe for the hot
        path: an empty string changes nothing)."""
        match = self.classify(message)
        return match.capability if match else ""

    def status(self) -> dict[str, Any]:
        return {"available": self._ready, "model": _MODEL_NAME,
                "routes": len(self._routes), "error": self._err}


_router: IntentRouter | None = None
_router_lock = threading.Lock()


def get_intent_router() -> IntentRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = IntentRouter()
    return _router


def classify(message: str) -> IntentMatch | None:
    return get_intent_router().classify(message)
