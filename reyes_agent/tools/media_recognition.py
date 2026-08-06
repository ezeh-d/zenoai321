"""Tools for explicit audio and bounded screen/video recognition."""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="recognize_audio",
    description=(
        "Identify a song or currently playing audio from an explicit short microphone or Windows system-audio sample. "
        "Never guesses a title: reports a match only when a configured recognition provider returns one. "
        "System-audio recognition must be enabled in ZENO's Awareness settings first."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["system", "microphone"], "description": "Use system for audio playing on this PC; microphone for sound in the room."},
            "seconds": {"type": "integer", "description": "Capture 4-18 seconds. Default 8."},
        },
    },
)
def recognize_audio(source: str = "system", seconds: int = 8) -> str:
    from reyes_agent import audio_recognition, visual_awareness

    source = str(source or "system").lower()
    current = visual_awareness.settings()
    setting = "system_audio_recognition" if source == "system" else "microphone_recognition"
    if not current.get(setting):
        label = "System Audio Recognition" if source == "system" else "Microphone Recognition"
        return f"{label} is off. Enable it in Awareness settings before ZENO captures audio."
    try:
        result = audio_recognition.recognize_current(source=source, seconds=seconds)
    except audio_recognition.AudioRecognitionError as exc:
        return f"Audio recognition could not run: {exc}"
    if not result.get("matched"):
        return result.get("reason") or "No confident audio match. ZENO did not guess a title."
    details = [f"Recognized: {result.get('artist', '').strip()} — {result.get('title', '').strip()}".strip(" —")]
    if result.get("album"):
        details.append(f"Album: {result['album']}")
    if result.get("release_date"):
        details.append(f"Release: {result['release_date']}")
    details.append(f"Source: {result.get('provider', 'unknown')}" + (" (cached)" if result.get("cached") else ""))
    return "\n".join(details)


@register(
    name="understand_video",
    description=(
        "Understand the currently visible screen/video from one direct sample, or answer what changed in the past N seconds "
        "from ZENO's explicitly enabled in-memory rolling visual buffer. Uses local OCR and at most one vision-model frame; "
        "does not continuously send frames to AI or identify unknown people."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What to inspect, summarise or verify."},
            "lookback_seconds": {"type": "integer", "description": "Use only for past events; requires enabled rolling buffer."},
        },
        "required": ["question"],
    },
)
def understand_video(question: str, lookback_seconds: int = 0) -> str:
    from reyes_agent import video_recognition

    return video_recognition.format_result(video_recognition.analyze(question, lookback_seconds=lookback_seconds))


@register(
    name="awareness_status",
    description="Show ZENO's real observation controls and bounded rolling-buffer state: screen, microphone, system audio and retained metadata.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def awareness_status() -> str:
    from reyes_agent import visual_awareness

    state = visual_awareness.settings()
    return (
        f"Visual Awareness: {'on' if state['visual_awareness'] else 'off'}; "
        f"Microphone Recognition: {'on' if state['microphone_recognition'] else 'off'}; "
        f"System Audio Recognition: {'on' if state['system_audio_recognition'] else 'off'}; "
        f"Rolling Buffer: {'on' if state['rolling_buffer'] else 'off'}; "
        f"frames retained: {state['rolling_frames']}; audio observations retained: {state['rolling_audio_observations']}. "
        f"{state['privacy']}"
    )
