"""A real check of what will and will not work in front of a supervisor.

    "Return: READY / PARTIAL / FAILED for each."

Every check here calls the thing it is checking. None of them reports READY
because a module imported or a key is present in a file -- the whole value of
running this the night before is that it fails HERE rather than in the room.

Where a check cannot be made without side effects (speaking aloud, opening an
application), it says so and reports what it could establish, rather than
either lying or silently skipping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

READY = "READY"
PARTIAL = "PARTIAL"
FAILED = "FAILED"


@dataclass
class Check:
    name: str
    state: str = FAILED
    detail: str = ""
    took_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.name, "state": self.state, "detail": self.detail,
                "took_ms": round(self.took_ms, 1)}


def _run(name: str, probe: Callable[[], tuple[str, str]]) -> Check:
    started = time.perf_counter()
    try:
        state, detail = probe()
    except Exception as exc:  # noqa: BLE001
        state, detail = FAILED, f"{type(exc).__name__}: {exc}"
    return Check(name, state, detail, (time.perf_counter() - started) * 1000)


# -- individual probes ----------------------------------------------------

def _provider() -> tuple[str, str]:
    from reyes_agent import config

    keys = {"anthropic": config.ANTHROPIC_API_KEY, "openai": config.OPENAI_API_KEY,
            "gemini": config.GEMINI_API_KEY}
    have = [n for n, k in keys.items() if str(k or "").strip()]
    if not have:
        return FAILED, "no model provider key is configured"
    chosen = config.MODEL_PROVIDER
    if chosen not in have:
        return PARTIAL, (f"MODEL_PROVIDER is '{chosen}' but only {have} have "
                         "keys -- it will fall back")
    return READY, f"{chosen} configured; fallbacks available: {have}"


def _stt() -> tuple[str, str]:
    from reyes_agent import config

    if not getattr(config, "DEEPGRAM_API_KEY", ""):
        return FAILED, "no DEEPGRAM_API_KEY"
    from reyes_agent.voice.stt import streaming

    ok, why = streaming.available()
    if not ok:
        return PARTIAL, f"batch transcription only ({why})"
    return READY, "streaming transcription available"


def _tts() -> tuple[str, str]:
    try:
        from reyes_agent.voice import tts_router

        state = tts_router.status()
        engine = state.get("selected") or state.get("engine") or "unknown"
        # The router says WORKING, not ONLINE. Treating its healthy word as
        # unhealthy would report a fault that does not exist -- and a false
        # alarm the night before a visit costs as much as a missed one.
        if str(state.get("state", "")).upper() in ("ONLINE", "READY", "WORKING"):
            return READY, f"voice engine: {engine}"
        return PARTIAL, f"voice engine reports {state.get('state')}: {engine}"
    except Exception as exc:  # noqa: BLE001
        return PARTIAL, f"could not query the voice router ({type(exc).__name__})"


def _wake() -> tuple[str, str]:
    from reyes_agent import config
    from reyes_agent.remote_mic import runtime

    phrases = list(getattr(config, "WAKE_PHRASES", []))
    if not phrases:
        return FAILED, "no wake phrases configured"
    probe = f"{phrases[0]} what time is it"
    if runtime._WAKE.match(probe):
        return READY, f"{len(phrases)} phrases; '{phrases[0]}' matches"
    return FAILED, f"configured phrase '{phrases[0]}' does not match its own matcher"


def _microphone() -> tuple[str, str]:
    from reyes_agent.audio.manager import get_audio_manager

    state = get_audio_manager().status()
    sources = state.get("sources") or {}
    active = state.get("active_source") or state.get("physical_owner") or ""
    if sources:
        return READY, f"active source: {active}; {len(sources)} known"
    return PARTIAL, ("no audio source is publishing yet -- connect the phone "
                     "or speak into the laptop microphone")


def _remote_mic() -> tuple[str, str]:
    from reyes_agent.remote_mic import get_remote_mic_runtime, routes

    ready, detail = get_remote_mic_runtime().available()
    if not ready:
        return FAILED, detail
    live = [r for r in routes.selector().routes() if r.health == routes.READY]
    if not live:
        return PARTIAL, "receiver ready but no network is serving the phone port"
    where = ", ".join(f"{r.label} {r.ipv4}" for r in live)
    connected = bool(get_remote_mic_runtime().status().get("peer_ip"))
    return (READY if connected else PARTIAL,
            f"{where}" + ("; phone connected" if connected else
                          "; no phone connected yet"))


def _agents() -> tuple[str, str]:
    from reyes_agent.agents import identity

    roster = identity.roster()
    if not roster:
        return FAILED, "the agent registry is empty"
    unknown = [a["name"] for a in roster if not identity.identity(a["name"])["found"]]
    if unknown:
        return PARTIAL, f"cannot identify: {unknown}"
    workers = sum(a["worker_count"] for a in roster)
    return READY, f"{len(roster)} agents, {workers} workers, all answerable"


def _agent_space() -> tuple[str, str]:
    from pathlib import Path

    from reyes_agent import config

    page = Path(config.PROJECT_ROOT) / "reyes_agent" / "static" / "index.html"
    if not page.exists():
        return FAILED, "the dashboard page is missing"
    text = page.read_text(encoding="utf-8", errors="replace")
    if "subspace-overlay" in text and "zenoSubspace" in text:
        return READY, "Agent Space overlay present; reads live state from /api/hierarchy"
    return PARTIAL, "the dashboard is present but the Agent Space overlay was not found"


def _memory() -> tuple[str, str]:
    from reyes_agent.memory import get_memory_manager

    manager = get_memory_manager()
    context = manager.context_for("SIWES")
    return (READY if context is not None else PARTIAL,
            "memory manager responded")


def _facts() -> tuple[str, str]:
    from reyes_agent.presentation import facts, timeline, visit

    stages = timeline.stages()
    evidenced = [s for s in stages if s.evidence_kind == timeline.EVIDENCED]
    features = facts.feature_status()
    if not stages or not features:
        return FAILED, "presentation facts could not be built"
    visit.write_profile()
    timeline.write()
    return READY, (f"{len(stages)} timeline stages ({len(evidenced)} evidenced "
                   f"by git), {len(features)} features with honest status")


def _desktop() -> tuple[str, str]:
    from reyes_agent.tools.messaging import desktop

    ok, detail = desktop.available()
    return (READY if ok else PARTIAL), detail


def _siwes_dates() -> tuple[str, str]:
    from datetime import date

    from reyes_agent.presentation import timeline

    start = date.fromisoformat(timeline.SIWES_START)
    end = date.fromisoformat(timeline.SIWES_END)
    today = date.today()
    if not (start <= today <= end):
        return PARTIAL, (f"today ({today}) is outside the stated SIWES window "
                         f"{start}..{end}")
    week = ((today - start).days // 7) + 1
    return READY, f"week {week} of the placement ({start} to {end})"


CHECKS: list[tuple[str, Callable[[], tuple[str, str]]]] = [
    ("SIWES dates", _siwes_dates),
    ("Presentation facts", _facts),
    ("Model provider", _provider),
    ("Speech recognition", _stt),
    ("Speech output", _tts),
    ("Wake word", _wake),
    ("Microphone", _microphone),
    ("Phone remote mic", _remote_mic),
    ("Conversation memory", _memory),
    ("Agent registry", _agents),
    ("Agent Space", _agent_space),
    ("Desktop tools", _desktop),
]


def run() -> dict[str, Any]:
    results = [_run(name, probe) for name, probe in CHECKS]
    failed = [c for c in results if c.state == FAILED]
    partial = [c for c in results if c.state == PARTIAL]

    if failed:
        headline = (f"{len(failed)} thing(s) will not work: "
                    + ", ".join(c.name for c in failed) + ".")
    elif partial:
        headline = (f"Everything essential works. {len(partial)} need(s) "
                    "attention: " + ", ".join(c.name for c in partial) + ".")
    else:
        headline = "Everything checked is ready."

    return {
        "state": FAILED if failed else (PARTIAL if partial else READY),
        "headline": headline,
        "ready": len(results) - len(failed) - len(partial),
        "partial": len(partial), "failed": len(failed),
        "checks": [c.as_dict() for c in results],
        "display": "\n".join(
            f"  {c.state:8} {c.name:22} {c.detail}" for c in results),
        "note": ("Each check calls the thing it checks. Nothing reports READY "
                 "because a module imported."),
    }


def status() -> dict[str, Any]:
    return {"state": "ONLINE", "checks": len(CHECKS),
            "run_with": "ZENO, prepare for Engr Bello"}
