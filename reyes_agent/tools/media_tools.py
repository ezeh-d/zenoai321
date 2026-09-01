"""Brain tools for the Universal Media Intelligence engine.

These let ZENO KNOW and CONTROL media the way a person means it: "what's
playing?", "pause it", "skip this", "turn spotify down", "play <song>". They
sit on top of reyes_agent/media (GSMTC session reader + adapters + manager),
which targets the SPECIFIC session the user means rather than firing blind
media keys.

Owner-direct and non-destructive (same class as pressing a media key), so they
do not ask for repeated approval. Everything degrades cleanly: no media session
-> a plain "nothing is playing"; no Spotify link -> the Windows session path.
"""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


@register(
    name="media_now_playing",
    description=(
        "What is playing right now, read from Windows' own media sessions "
        "(Spotify, a YouTube/Chrome tab, VLC, ...). Returns title, artist, "
        "album, play state and position for each source. Use for 'what's "
        "playing', 'what song is this', 'who sings this'."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def media_now_playing() -> str:
    from reyes_agent.media import get_media_manager
    mgr = get_media_manager()
    st = mgr.state(with_art=True)
    return _json({"ok": True, "summary": mgr.describe(),
                  "sessions": st.sessions, "active": st.active,
                  "count": len(st.sessions)})


@register(
    name="media_command",
    description=(
        "Control media playback for the session the owner means. action is one "
        "of: play, pause, toggle, next, previous, stop, seek, status. Give "
        "'reference' to name the target in the owner's words -- 'it', 'this "
        "song', 'the music', or a player name like 'spotify'/'youtube'; ZENO "
        "resolves it to the right session. For seek, pass position_s (seconds). "
        "Targets the exact session via Windows controls and falls back to media "
        "keys. Use for 'pause it', 'skip this', 'resume', 'go back'."
    ),
    input_schema={"type": "object", "properties": {
        "action": {"type": "string",
                    "enum": ["play", "pause", "toggle", "next", "previous",
                             "stop", "seek", "status"],
                    "description": "The playback action."},
        "reference": {"type": "string",
                      "description": "What to target: 'it', 'spotify', 'the music', etc."},
        "position_s": {"type": "number",
                       "description": "For seek: absolute position in seconds."},
    }, "required": ["action"]},
    light=True,
)
def media_command(action: str, reference: str = "", position_s: float = 0.0) -> str:
    from reyes_agent.media import get_media_manager
    res = get_media_manager().command(action, reference=reference or None,
                                      position_s=position_s)
    return _json(res)


@register(
    name="media_set_app_volume",
    description=(
        "Set the volume of ONE application without touching the system master "
        "-- e.g. 'turn Spotify down to 30', 'make the browser quieter'. app is "
        "the player/app name ('Spotify', 'chrome'); level is 0-100. The app "
        "must be actively playing audio on the current output device. To set "
        "the whole system volume instead, use set_volume."
    ),
    input_schema={"type": "object", "properties": {
        "app": {"type": "string", "description": "Application name, e.g. 'Spotify'."},
        "level": {"type": "integer", "description": "Volume 0 (mute) to 100 (max)."},
    }, "required": ["app", "level"]},
    light=True,
)
def media_set_app_volume(app: str, level: int) -> str:
    from reyes_agent.media.adapters import SystemAudioAdapter
    lvl = max(0, min(100, int(level))) / 100.0
    res = SystemAudioAdapter().set_app_volume(app, lvl)
    return _json(res)


@register(
    name="media_play_song",
    description=(
        "Play a specific song/artist by name. When the owner has linked their "
        "Spotify account this searches and starts that exact track; otherwise "
        "it resumes the current player (naming a specific song needs Spotify "
        "connected). Use for 'play <song> by <artist>', 'put on <song>'."
    ),
    input_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "Song and/or artist to play."},
    }, "required": ["query"]},
    light=True,
)
def media_play_song(query: str) -> str:
    from reyes_agent.media import get_media_manager
    res = get_media_manager().command("play_query", query=query)
    return _json(res)


@register(
    name="media_panel",
    description=(
        "The live media panel state for the UI: the active session's art, "
        "title, artist, play state and progress, plus every known source. "
        "Returns the compact 'mini_card' for the always-on widget too. Use to "
        "render or refresh the media panel."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def media_panel() -> str:
    from reyes_agent.media import get_media_manager
    st = get_media_manager().state(with_art=True)
    return _json({"ok": True, **st.to_dict()})
