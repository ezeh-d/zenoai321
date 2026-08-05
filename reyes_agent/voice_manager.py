"""Voice Manager -- per-agent ElevenLabs voices, with a registry, an
on-disk cache, and a serialized speech queue.

REGISTRY / PROFILES
-------------------
Each specialist has a profile: a voice id, plus stability/similarity
settings that shape delivery (ULTRON deliberately flatter and steadier
than ZEAL, for instance). Voice IDs come from .env so they're the user's
own voices, e.g.

    ELEVENLABS_VOICE_ARIS=<voice id>
    ELEVENLABS_VOICE_TOSIN=<voice id>

Any agent without its own configured id falls back to the main
ELEVENLABS_VOICE_ID. That is a real fallback, not a stub: with zero extra
config every agent speaks in ZENO's configured voice, and each agent
gains its own the moment an id is added. Nothing here invents voice ids
that don't exist on the account.

CACHE
-----
Identical (text, voice, settings) is synthesized once and reused from
disk. Repeated lines -- "I'm listening.", "Standing by.", tool
acknowledgements -- are the common case for an always-on assistant, and
ElevenLabs bills per character, so this directly cuts API usage. Cache is
bounded by file count.

QUEUE
-----
Synthesis and playback are serialized through one worker thread, so two
agents finishing at once produce sequential speech rather than two
overlapping audio streams.
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from reyes_agent import config

_CACHE_DIR = config.VAULT_PATH / "07-System" / "voice_cache"
_MAX_CACHE_FILES = 400


@dataclass(frozen=True)
class VoiceProfile:
    agent: str
    voice_id: str
    stability: float
    similarity: float
    description: str


# Delivery settings per role. Higher stability = steadier/flatter delivery;
# lower = more expressive variation. These are real ElevenLabs parameters.
_PROFILE_SPEC: dict[str, tuple[float, float, str]] = {
    "zeno":        (0.55, 0.80, "Executive -- calm, confident"),
    "aris":        (0.60, 0.75, "Research -- measured, analytical"),
    "tosin":       (0.50, 0.75, "Engineering -- direct, technical"),
    "stark":       (0.70, 0.80, "Security -- controlled, serious"),
    "titan":       (0.55, 0.80, "Business -- assured, consultative"),
    "kate":        (0.65, 0.75, "Academic -- patient, explanatory"),
    "ultron":      (0.85, 0.85, "Strategic -- flat, deliberate, zero warmth"),
    "zeal":        (0.35, 0.70, "Creative -- expressive, energetic"),
    "hermes_comm": (0.50, 0.75, "Communication -- warm, friendly"),
    "oracle":      (0.65, 0.80, "Analytics -- even, narrating"),
    "nova":        (0.55, 0.75, "Vision -- attentive, descriptive"),
    "helios":      (0.60, 0.70, "Wellbeing -- calm, unhurried"),
    "apex":        (0.30, 0.70, "Gaming -- upbeat, high energy"),
}


def _env_voice(agent: str) -> str:
    """Per-agent override, else the main configured voice."""
    key = f"ELEVENLABS_VOICE_{agent.upper().replace('_COMM', '')}"
    return os.environ.get(key, "").strip() or config.ELEVENLABS_VOICE_ID


def get_profile(agent: str) -> VoiceProfile:
    agent = (agent or "zeno").strip().lower()
    stability, similarity, desc = _PROFILE_SPEC.get(agent, _PROFILE_SPEC["zeno"])
    return VoiceProfile(agent, _env_voice(agent), stability, similarity, desc)


def registry() -> list[dict]:
    """Every profile plus whether it has its own voice or is falling back --
    honest about which agents are actually distinct right now."""
    main = config.ELEVENLABS_VOICE_ID
    out = []
    for agent in _PROFILE_SPEC:
        p = get_profile(agent)
        out.append({
            "agent": agent,
            "voice_id": p.voice_id,
            "own_voice": bool(p.voice_id) and p.voice_id != main or agent == "zeno",
            "using_fallback": bool(p.voice_id) and p.voice_id == main and agent != "zeno",
            "stability": p.stability,
            "similarity": p.similarity,
            "description": p.description,
        })
    return out


def _cache_path(text: str, p: VoiceProfile) -> Path:
    key = f"{p.voice_id}|{p.stability}|{p.similarity}|{text}".encode("utf-8")
    return _CACHE_DIR / (hashlib.sha256(key).hexdigest()[:32] + ".mp3")


def _prune_cache() -> None:
    try:
        files = sorted(_CACHE_DIR.glob("*.mp3"), key=lambda f: f.stat().st_mtime)
        for f in files[:-_MAX_CACHE_FILES]:
            f.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def synthesize(text: str, agent: str = "zeno") -> bytes:
    """MP3 bytes for `text` in `agent`'s voice, cached on disk.

    Raises TTSError (from voice.tts) if ElevenLabs isn't configured or the
    call fails -- callers fall back to the browser voice, same as before.
    """
    from reyes_agent.voice.tts import TTSError

    profile = get_profile(agent)
    if not config.ELEVENLABS_API_KEY:
        raise TTSError("ElevenLabs is not configured.")

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(text, profile)
    if path.exists():
        return path.read_bytes()

    from reyes_agent.voice.tts import _get_elevenlabs_client

    client = _get_elevenlabs_client()
    try:
        audio = client.text_to_speech.convert(
            voice_id=profile.voice_id,
            model_id=config.ELEVENLABS_MODEL,
            text=text,
            output_format="mp3_44100_128",
            voice_settings={
                "stability": profile.stability,
                "similarity_boost": profile.similarity,
            },
        )
        data = b"".join(audio) if not isinstance(audio, (bytes, bytearray)) else bytes(audio)
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"ElevenLabs synthesis failed: {exc}") from exc

    try:
        path.write_bytes(data)
        _prune_cache()
    except Exception:  # noqa: BLE001
        pass  # cache write failure must not break speech
    return data


# --- speech queue -------------------------------------------------------
# One worker, so overlapping requests play in order instead of on top of
# each other. Server-side playback only (CLI/desktop paths); the web panel
# fetches audio over HTTP and plays it in the browser instead.
# Speech is intentionally serialized (two voices must never overlap), but a
# stalled audio backend must not let announcements grow memory without bound.
_speech_q: queue.Queue = queue.Queue(maxsize=100)
_worker: threading.Thread | None = None
_speech_lock = threading.Lock()


def _speak_now(text: str, agent: str) -> None:
    """Server-side playback in the agent's voice.

    Streams PCM straight to sounddevice, mirroring the proven
    voice/tts.py::_speak_elevenlabs path -- the cached MP3 from
    `synthesize()` can't be used here because nothing in this environment
    decodes MP3 to PCM, and sounddevice needs PCM. So: the browser/HTTP
    path gets caching (that's where repeated lines actually happen), and
    this path gets the per-agent voice without it.
    """
    import sounddevice as sd

    from reyes_agent.voice.tts import _EL_SAMPLE_RATE, _get_elevenlabs_client

    profile = get_profile(agent)
    client = _get_elevenlabs_client()
    stream = client.text_to_speech.stream(
        voice_id=profile.voice_id,
        text=text,
        model_id=config.ELEVENLABS_MODEL,
        output_format="pcm_24000",
        voice_settings={"stability": profile.stability, "similarity_boost": profile.similarity},
    )
    out = sd.RawOutputStream(samplerate=_EL_SAMPLE_RATE, channels=1, dtype="int16")
    out.start()
    try:
        for chunk in stream:
            if chunk:
                out.write(chunk)
    finally:
        out.stop()
        out.close()


def _run_queue() -> None:
    while True:
        item = _speech_q.get()
        if item is None:
            _speech_q.task_done()
            break
        text, agent = item
        try:
            _speak_now(text, agent)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _speech_q.task_done()


def speak_queued(text: str, agent: str = "zeno") -> None:
    global _worker
    if not text:
        return
    with _speech_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_queue, daemon=True, name="zeno-speech")
            _worker.start()
        try:
            _speech_q.put_nowait((text, agent))
        except queue.Full:
            # Live announcements are disposable under pressure; the durable notice
            # remains visible in the panel and the UI must stay responsive.
            return


def shutdown() -> None:
    """Stop the owned playback worker and discard only unsaid transient audio."""
    global _worker
    with _speech_lock:
        worker = _worker
        if worker is None or not worker.is_alive():
            _worker = None
            return
        # Queued speech is presentation state, not a durable task.  It must not
        # keep the process alive after the user closes ZENO.
        while True:
            try:
                _speech_q.get_nowait()
                _speech_q.task_done()
            except queue.Empty:
                break
        _speech_q.put_nowait(None)
    if worker is not threading.current_thread():
        worker.join(timeout=2.0)
    with _speech_lock:
        if _worker is worker:
            _worker = None


# --- introductions ------------------------------------------------------
# Each specialist's own words, spoken in its own voice. Kept short on
# purpose: a roll call of 12 agents is already ~40 seconds of audio, and
# task acknowledgements must not slow real work down.
INTRODUCTIONS: dict[str, str] = {
    "aris": "Hello. I am ARIS, the Research and Knowledge Specialist. I handle research, documentation, and current information.",
    "tosin": "Hello. I'm TOSIN, ZENO's Software Engineering Specialist. Programming, debugging, architecture, and AI development.",
    "stark": "Hello. I am STARK, responsible for cybersecurity, permissions, system monitoring, and risk analysis.",
    "titan": "Hello. I am TITAN, your Business and Investment Specialist. Markets, strategy, and finance.",
    "kate": "Hello. I am KATE, your Academic and Education Specialist. Mathematics, science, and study support.",
    "ultron": "I am ULTRON. I oversee strategic planning, critical review, and Serious Mode.",
    "zeal": "Hello. I'm ZEAL, responsible for creativity, design, branding, and user experience.",
    "hermes_comm": "Hello. I am HERMES, your communication and scheduling specialist.",
    "nova": "Hello. I am NOVA. I specialise in computer vision and visual intelligence.",
    "helios": "Hello. I am HELIOS. I focus on health, wellness, and sustainable working.",
    "oracle": "Hello. I am ORACLE. I provide analytics, reporting, and predictive insight.",
    "apex": "Hey! I'm APEX, your gaming and entertainment specialist.",
}

# Terse roll-call lines -- the full introductions are too long for twelve
# agents back to back.
ROLL_CALL_LINE: dict[str, str] = {a: f"I am {a.upper().replace('_COMM', '')}." for a in INTRODUCTIONS}

ACKNOWLEDGEMENTS: dict[str, str] = {
    "aris": "Research task accepted.",
    "tosin": "Task accepted. Beginning development.",
    "stark": "Security review initiated.",
    "titan": "Business analysis starting.",
    "kate": "Happy to explain.",
    "ultron": "Reviewing.",
    "zeal": "On it, creatively.",
    "hermes_comm": "Handling communications.",
    "nova": "Looking now.",
    "helios": "Checking in on that.",
    "oracle": "Running the numbers.",
    "apex": "Let's go!",
}

# Introduced-once-per-session tracking. Process lifetime == session, which
# matches "once per session unless explicitly requested again".
_introduced: set[str] = set()


def introduction_for(agent: str, force: bool = False) -> str | None:
    """The agent's introduction if it hasn't spoken yet this session."""
    a = (agent or "").strip().lower()
    if a not in INTRODUCTIONS:
        return None
    if a in _introduced and not force:
        return None
    _introduced.add(a)
    return INTRODUCTIONS[a]


def mark_introduced(agent: str) -> None:
    _introduced.add((agent or "").strip().lower())


def reset_introductions() -> None:
    _introduced.clear()


def roll_call_sequence(full: bool = False) -> list[dict]:
    """Ordered [{agent, text}] for the browser to play, each in its own
    voice. Returned as data rather than synthesized here because the panel
    may be open on a phone -- server-side audio would play on the wrong
    machine."""
    seq = [{"agent": "zeno", "text": "Initiating agent roll call."}]
    for a in INTRODUCTIONS:
        seq.append({"agent": a, "text": INTRODUCTIONS[a] if full else ROLL_CALL_LINE[a]})
        _introduced.add(a)
    seq.append({"agent": "zeno", "text": "All specialist agents are online and ready for deployment."})
    return seq


def diagnose() -> dict:
    """Voice diagnostics: which agents have their own voice, which are
    falling back, and whether each configured id actually EXISTS on the
    account. A voice id that was mistyped fails silently at synthesis time
    otherwise -- this catches it up front."""
    result: dict = {
        "elevenlabs_configured": bool(config.ELEVENLABS_API_KEY),
        "main_voice": config.ELEVENLABS_VOICE_ID,
        "agents": [],
        "problems": [],
        "account_voices": None,
    }
    if not config.ELEVENLABS_API_KEY:
        result["problems"].append("ELEVENLABS_API_KEY is not set -- all speech falls back to the browser voice.")
        return result

    # Real check against the account rather than assuming ids are valid.
    available: set[str] = set()
    try:
        from reyes_agent.voice.tts import _get_elevenlabs_client

        client = _get_elevenlabs_client()
        voices = client.voices.get_all()
        items = getattr(voices, "voices", voices)
        for v in items:
            vid = getattr(v, "voice_id", None)
            if vid:
                available.add(vid)
        result["account_voices"] = len(available)
    except Exception as exc:  # noqa: BLE001
        # ElevenLabs API keys are scoped. A key can be perfectly valid for
        # text_to_speech and still 401 on voices.get_all() because it lacks
        # the voices_read permission -- which is exactly this install's
        # case (confirmed 2026-08-04). Say that instead of surfacing a raw
        # header dump, and be clear that speech itself is unaffected.
        if "401" in str(exc):
            result["problems"].append(
                "The ElevenLabs key can synthesize speech but lacks the 'voices_read' "
                "permission, so voice ids can't be validated against the account. "
                "Speech still works; only this validation check is unavailable. "
                "Enable voices_read on the key to turn it on."
            )
        else:
            result["problems"].append(f"Could not list account voices: {str(exc)[:160]}")

    if config.ELEVENLABS_VOICE_ID and available and config.ELEVENLABS_VOICE_ID not in available:
        result["problems"].append(
            f"Main ELEVENLABS_VOICE_ID '{config.ELEVENLABS_VOICE_ID}' is not on this account."
        )

    for entry in registry():
        vid = entry["voice_id"]
        status = "ok"
        if not vid:
            status = "missing"
            result["problems"].append(f"{entry['agent']}: no voice id and no main voice to fall back to.")
        elif available and vid not in available:
            status = "invalid"
            result["problems"].append(
                f"{entry['agent']}: voice id '{vid}' is not on this account -- speech will fail."
            )
        elif entry["using_fallback"]:
            status = "fallback"
        entry["status"] = status
        result["agents"].append(entry)

    own = sum(1 for a in result["agents"] if a["status"] == "ok")
    result["summary"] = (
        f"{own} of {len(result['agents'])} agents have their own working voice; "
        f"{sum(1 for a in result['agents'] if a['status'] == 'fallback')} fall back to ZENO's."
    )
    return result


def preview(agent: str) -> bytes:
    """Short spoken sample in an agent's voice, for auditioning it."""
    p = get_profile(agent)
    line = f"This is {agent.upper().replace('_COMM','')}. {p.description}."
    return synthesize(line, agent)


def cache_stats() -> dict:
    try:
        files = list(_CACHE_DIR.glob("*.mp3"))
        return {"cached_clips": len(files), "bytes": sum(f.stat().st_size for f in files)}
    except Exception:  # noqa: BLE001
        return {"cached_clips": 0, "bytes": 0}
