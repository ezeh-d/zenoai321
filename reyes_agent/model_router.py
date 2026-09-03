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
    "coding":    ("anthropic", "openai", "xai", "gemini", "ollama"),
    "reasoning": ("anthropic", "openai", "xai", "gemini", "ollama"),
    "research":  ("gemini", "openai", "anthropic", "xai", "ollama"),
    "vision":    ("gemini", "openai", "anthropic", "xai"),
    "offline":   ("ollama",),
    "general":   ("gemini", "openai", "anthropic", "xai", "ollama"),
}


# Circuit breaker. After this many consecutive failures a provider is
# OPEN (skipped entirely) for the cooldown, then HALF_OPEN -- one probe
# call is allowed through. A success closes it; a failure re-opens it with
# a longer cooldown. Without this, "route around a degraded provider" meant
# permanently, and a provider that recovered was never used again.
_BREAKER_THRESHOLD = 3
# Recovery has to be FAST for the primary provider. A transient blip (an
# SSL-proxy connection reset, a burst of rate-limit 429s while ZENO warms) can
# trip three failures and open gemini's breaker even though gemini is actually
# healthy -- a live probe answers in ~700ms right after. With the old 900s max
# backoff, every turn in that window fell through to the slow local model and
# ZENO felt broken for up to 15 minutes after a one-second hiccup. Keep the
# cooldown short so a half-open probe re-tries the real provider within seconds
# and closes the breaker the moment it succeeds; a genuinely down provider just
# gets re-probed a little more often, which is cheap.
_BREAKER_COOLDOWN_S = 15.0
_BREAKER_MAX_COOLDOWN_S = 60.0

# These failures cannot heal while the process keeps using the same loaded
# credential. Treating them like a transient outage caused ZENO to retry a
# known-invalid key every cooldown before falling back to a working provider.
_AUTH_FAILURE_MARKERS = (
    "incorrect api key",
    "invalid api key",
    "api key not valid",
    "invalid_api_key",
    "authentication failed",
    "authentication_error",
    "invalid authentication",
    "unauthorized",
    "status code: 401",
    "error code: 401",
)

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"


@dataclass
class ProviderStats:
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    total_latency: float = 0.0
    last_latency: float = 0.0
    last_used: float = 0.0
    last_error: str = ""
    opened_at: float = 0.0
    cooldown: float = _BREAKER_COOLDOWN_S
    permanent_failure: bool = False

    @property
    def avg_latency(self) -> float:
        return (self.total_latency / self.calls) if self.calls else 0.0

    @property
    def breaker(self) -> str:
        """CLOSED / OPEN / HALF_OPEN, derived from real failures and time."""
        if self.permanent_failure:
            return OPEN
        if self.consecutive_failures < _BREAKER_THRESHOLD:
            return CLOSED
        if time.time() - self.opened_at >= self.cooldown:
            return HALF_OPEN
        return OPEN

    @property
    def healthy(self) -> bool:
        # OPEN is skipped; HALF_OPEN is allowed exactly so recovery can be
        # detected instead of assumed.
        return self.breaker != OPEN


_stats: dict[str, ProviderStats] = {}
_lock = threading.Lock()


def available_providers() -> dict[str, bool]:
    """Which providers have real credentials configured right now."""
    return {
        "anthropic": bool(config.ANTHROPIC_API_KEY),
        "openai": bool(config.OPENAI_API_KEY),
        "xai": bool(config.XAI_API_KEY),
        "gemini": bool(config.GEMINI_API_KEY),
        # Ollama needs no key. It remains opt-in so machines without the
        # daemon do not pay a connection timeout on every cloud outage.
        "ollama": config.OLLAMA_ENABLED or config.MODEL_PROVIDER == "ollama",
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


def record(provider: str, latency: float, ok: bool, error: str = "", *,
           validated_runtime: bool = False) -> None:
    """Record one call for routing metrics.

    ``validated_runtime`` is deliberately explicit. Unit tests and synthetic
    breaker exercises use this function too; they must not write a fake
    ONLINE state into the durable provider registry. The actual provider seam
    sets it only after an SDK request really succeeds or fails.
    """
    with _lock:
        st = _stats.setdefault(provider, ProviderStats())
        was = st.breaker
        st.calls += 1
        st.total_latency += latency
        st.last_latency = latency
        st.last_used = time.time()
        if ok:
            st.consecutive_failures = 0
            st.opened_at = 0.0
            st.cooldown = _BREAKER_COOLDOWN_S      # recovery resets the backoff
            st.permanent_failure = False
        else:
            st.failures += 1
            st.consecutive_failures += 1
            st.last_error = error[:200]
            normalized_error = error.casefold()
            if any(marker in normalized_error for marker in _AUTH_FAILURE_MARKERS):
                # The key is read at process start. A timed half-open probe
                # cannot repair it; reset/restart after changing configuration
                # is the explicit recovery path.
                st.permanent_failure = True
                st.consecutive_failures = max(st.consecutive_failures, _BREAKER_THRESHOLD)
                st.opened_at = time.time()
            elif st.consecutive_failures >= _BREAKER_THRESHOLD:
                # A failure while probing means it is still broken: back off
                # further rather than retrying every cooldown forever.
                st.cooldown = (min(st.cooldown * 2, _BREAKER_MAX_COOLDOWN_S)
                               if was == HALF_OPEN else st.cooldown)
                st.opened_at = time.time()
        now = st.breaker
    if was != now:
        try:
            from reyes_agent import event_bus

            event_bus.publish("model.breaker_changed",
                              {"provider": provider, "from": was, "to": now,
                               "consecutive_failures": _stats[provider].consecutive_failures,
                               "error": _stats[provider].last_error},
                              source="model_router")
        except Exception:  # noqa: BLE001 -- telemetry never breaks a turn
            pass
    if validated_runtime:
        try:
            from reyes_agent import provider_manager

            provider_manager.record_runtime_result(
                provider, ok=ok, latency_s=latency, error=error,
            )
        except Exception:  # noqa: BLE001 -- durable health cannot break a turn
            pass


def chain_for(kind: str = "general") -> list[str]:
    """Every provider worth TRYING for this task kind, best first.

    This is what makes fallback real. `route()` returns the single best
    choice; this returns the ordered list the caller walks when one fails,
    so a dead provider costs one attempt instead of the whole turn.

    Ordering is the CONFIGURED preference, filtered to drop only providers
    whose breaker is fully OPEN. An earlier version moved every HALF_OPEN
    provider to the back of the list, reasoning that a "recovering" provider
    should not block a "healthy" one -- but CLOSED only means "hasn't failed
    _BREAKER_THRESHOLD times in a row", not fast or actually healthy. MEASURED:
    a fast, working Gemini (0.3s) sat HALF_OPEN after one transient blip while
    local Ollama -- CLOSED, because it wasn't outright FAILING, just answering
    correctly in 30-40s+ every time -- got promoted ahead of it. run_turn stops
    at the first provider that returns successfully, so Ollama's slow-but-real
    answer meant Gemini was never even attempted, every single turn, for as
    long as Ollama kept eventually succeeding. That is what read as "ZENO got
    slow" even though the actually-fast provider was one probe away the whole
    time. A HALF_OPEN provider gets its one probe in its normal preferred
    position instead -- the honest behavior the breaker is supposed to give it.
    """
    kind = (kind or "general").strip().lower()
    if kind not in TASK_KINDS:
        kind = "general"
    avail = available_providers()
    with _lock:
        snapshot = {p: s.breaker for p, s in _stats.items()}

    ordered = [
        provider for provider in _configured_route(kind)
        if avail.get(provider) and snapshot.get(provider, CLOSED) != OPEN
    ]
    if not ordered:
        # Everything is open. Trying the configured provider anyway beats
        # refusing to answer -- the breaker exists to stop hammering, not to
        # make ZENO mute.
        ordered = [config.MODEL_PROVIDER]
    return ordered


def breaker_state(provider: str) -> str:
    with _lock:
        st = _stats.get(provider)
    return st.breaker if st else CLOSED


def reset(provider: str = "") -> None:
    """Test hook / manual recovery."""
    with _lock:
        if provider:
            _stats.pop(provider, None)
        else:
            _stats.clear()


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
                "breaker": s.breaker,
                "consecutive_failures": s.consecutive_failures,
                "permanent_failure": s.permanent_failure,
                "last_error": s.last_error,
                "seconds_since_use": round(time.time() - s.last_used) if s.last_used else None,
            }
            for p, s in _stats.items()
        }
    try:
        from reyes_agent import provider_manager

        validation = provider_manager.status()
    except Exception as exc:  # noqa: BLE001 -- diagnostics remain available
        validation = {"state": "FAILED", "providers": {},
                      "detail": f"Provider registry unavailable: {type(exc).__name__}"}
    # Operational means a real validation/model call succeeded and the
    # circuit breaker is not open. Credential presence alone is CONFIGURED.
    operational = {
        provider: (
            validation.get("providers", {}).get(provider, {}).get("state") == "ONLINE"
            and stats.get(provider, {}).get("healthy", True)
        )
        for provider in avail
    }
    return {
        "active_provider": config.MODEL_PROVIDER,
        "active_model": {
            "anthropic": config.ANTHROPIC_MODEL,
            "openai": config.OPENAI_MODEL,
            "gemini": config.GEMINI_MODEL,
            "xai": config.XAI_MODEL,
            "ollama": config.OLLAMA_MODEL,
        }.get(config.MODEL_PROVIDER, "unknown"),
        "available": avail,
        "operational": operational,
        "validation": validation,
        "configured_count": sum(1 for v in avail.values() if v),
        "routes": {k: route(k) for k in TASK_KINDS},
        "measured": stats,
        "note": (
            "Configured means a credential exists; ONLINE requires a real validation or model call. "
            "Routing only takes effect for providers with credentials. "
            f"{sum(1 for v in avail.values() if v)} provider(s) configured -- "
            "with one, every route resolves to it and routing is a no-op."
        ),
    }
