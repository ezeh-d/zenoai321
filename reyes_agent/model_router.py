"""Model Router -- configurable per-task-kind model selection with REAL
measured latency, health, and fallback.

WHAT IS ACTUALLY TRUE HERE
--------------------------
Routing is only meaningful for providers that are actually configured. On
a machine with one API key, "route coding to Claude and research to GPT"
is a preference that cannot execute, and pretending otherwise would show
a routing table that silently never fires. So:

  * `available_providers()` reports which providers have real credentials
    right now. Nothing is listed as usable unless it is.
  * A route resolves to its preferred provider ONLY if that provider is
    available; otherwise it falls through the chain to one that is, and
    `explain()` says which happened and why.
  * Latency, success and failure counts are MEASURED from real calls via
    `record()`. They start empty and stay empty until calls happen -- no
    seeded or estimated numbers.
  * Health is derived from those measurements: a provider with recent
    consecutive failures is marked degraded, and the router routes around
    it.

Configuration lives in .env so the user owns the policy:

    MODEL_ROUTE_CODING=anthropic
    MODEL_ROUTE_RESEARCH=gemini
    MODEL_ROUTE_VISION=gemini
    MODEL_ROUTE_OFFLINE=ollama
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from reyes_agent import config

# Task kinds the router understands. Deliberately few: a routing table
# with fifty categories nobody sets is decoration.
TASK_KINDS = ("general", "coding", "research", "vision", "reasoning", "offline")

_DEFAULT_ROUTES: dict[str, tuple[str, ...]] = {
    # preference order; first AVAILABLE provider wins
    "coding":    ("anthropic", "xai", "gemini", "ollama"),
    "reasoning": ("anthropic", "xai", "gemini", "ollama"),
    "research":  ("gemini", "anthropic", "xai", "ollama"),
    "vision":    ("gemini", "anthropic", "xai"),
    "offline":   ("ollama",),
    "general":   ("gemini", "anthropic", "xai", "ollama"),
}


@dataclass
class ProviderStats:
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    total_latency: float = 0.0
    last_latency: float = 0.0
    last_used: float = 0.0
    last_error: str = ""

    @property
    def avg_latency(self) -> float:
        return (self.total_latency / self.calls) if self.calls else 0.0

    @property
    def healthy(self) -> bool:
        # Three consecutive failures is a real signal, not a guess.
        return self.consecutive_failures < 3


_stats: dict[str, ProviderStats] = {}
_lock = threading.Lock()


def available_providers() -> dict[str, bool]:
    """Which providers have real credentials configured right now."""
    return {
        "anthropic": bool(config.ANTHROPIC_API_KEY),
        "xai": bool(config.XAI_API_KEY),
        "gemini": bool(config.GEMINI_API_KEY),
        # Ollama needs no key; treated as available only if explicitly the
        # configured provider, since we can't cheaply prove the daemon is up.
        "ollama": config.MODEL_PROVIDER == "ollama",
    }


def _configured_route(kind: str) -> tuple[str, ...]:
    override = os.environ.get(f"MODEL_ROUTE_{kind.upper()}", "").strip().lower()
    if override:
        chain = tuple(p.strip() for p in override.split(",") if p.strip())
        if chain:
            return chain
    return _DEFAULT_ROUTES.get(kind, _DEFAULT_ROUTES["general"])


def route(kind: str = "general") -> dict:
    """Resolve a task kind to a provider that can actually serve it."""
    kind = (kind or "general").strip().lower()
    if kind not in TASK_KINDS:
        kind = "general"
    avail = available_providers()
    chain = _configured_route(kind)

    for provider in chain:
        if not avail.get(provider):
            continue
        with _lock:
            st = _stats.get(provider)
        if st is not None and not st.healthy:
            continue  # degraded: route around it
        reason = "preferred and available"
        if provider != chain[0]:
            reason = f"'{chain[0]}' unavailable or degraded; fell back"
        return {"kind": kind, "provider": provider, "reason": reason,
                "chain": list(chain), "fallback_used": provider != chain[0]}

    # Nothing in the chain is usable -- fall back to whatever is actually
    # configured, and say so rather than failing silently.
    return {"kind": kind, "provider": config.MODEL_PROVIDER,
            "reason": "no provider in the configured chain is available; "
                      "using the globally configured provider",
            "chain": list(chain), "fallback_used": True}


def record(provider: str, latency: float, ok: bool, error: str = "") -> None:
    """Record a REAL call. This is the only thing that produces metrics."""
    with _lock:
        st = _stats.setdefault(provider, ProviderStats())
        st.calls += 1
        st.total_latency += latency
        st.last_latency = latency
        st.last_used = time.time()
        if ok:
            st.consecutive_failures = 0
        else:
            st.failures += 1
            st.consecutive_failures += 1
            st.last_error = error[:200]


def explain() -> dict:
    """Full router state for the GUI/diagnostics."""
    avail = available_providers()
    with _lock:
        stats = {
            p: {
                "calls": s.calls,
                "failures": s.failures,
                "avg_latency_s": round(s.avg_latency, 2),
                "last_latency_s": round(s.last_latency, 2),
                "healthy": s.healthy,
                "last_error": s.last_error,
                "seconds_since_use": round(time.time() - s.last_used) if s.last_used else None,
            }
            for p, s in _stats.items()
        }
    return {
        "active_provider": config.MODEL_PROVIDER,
        "active_model": {
            "anthropic": config.ANTHROPIC_MODEL,
            "gemini": config.GEMINI_MODEL,
            "xai": config.XAI_MODEL,
            "ollama": config.OLLAMA_MODEL,
        }.get(config.MODEL_PROVIDER, "unknown"),
        "available": avail,
        "configured_count": sum(1 for v in avail.values() if v),
        "routes": {k: route(k) for k in TASK_KINDS},
        "measured": stats,
        "note": (
            "Routing only takes effect for providers with real credentials. "
            f"{sum(1 for v in avail.values() if v)} provider(s) configured -- "
            "with one, every route resolves to it and routing is a no-op."
        ),
    }
