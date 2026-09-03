"""Fast local device-command router -- no model call for an unambiguous command.

An LLM round-trip is real latency (hundreds of ms to seconds) that "mute",
"volume 30" or "open spotify" never needed: these already execute with no
confirmation prompt via the normal tool-calling path (registered `light=True`
in reyes_agent/tools -- the same tier ZENO's existing fast-chat path already
trusts, see tools/__init__.py's `[t for t in tools if t.light]`). This module
recognizes the SAME exact phrasing a person actually says for one of them and
calls the SAME underlying tool function directly, skipping only the model's
decision that the command was obvious -- never a new trust decision.

SAFETY, DELIBERATELY NARROW:
  - Every pattern is matched with re.fullmatch against the WHOLE normalized
    message (never a substring search), so a longer sentence that merely
    contains "open" or "mute" is left to the real agent, which can bring
    context and judgement a keyword match cannot.
  - Only tools already marked `light=True` (no confirmation required) are
    reachable here. A destructive or ambiguous action (close_app requires
    confirmation) is deliberately NOT included -- see tools/system.py.
  - Disabled entirely by one flag (FAST_LOCAL_COMMANDS_ENABLED) if this ever
    needs to be turned off without a redeploy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from reyes_agent import config


@dataclass(frozen=True)
class FastCommand:
    text: str
    intent: str
    tool: str


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", str(text).casefold())).strip()


# action -> every exact phrasing that means it. Values are media_control's own
# action vocabulary (tools/system.py), so a hit is a direct pass-through.
_MEDIA_PHRASES: dict[str, str] = {
    "play_pause": "play_pause", "pause": "play_pause", "pause music": "play_pause",
    "resume": "play_pause", "resume music": "play_pause", "play music": "play_pause",
    "unpause": "play_pause", "unpause music": "play_pause",
    "next": "next", "next song": "next", "next track": "next", "skip": "next",
    "skip song": "next", "skip track": "next", "play next": "next",
    "previous": "previous", "previous song": "previous", "previous track": "previous",
    "last song": "previous", "go back a song": "previous", "play previous": "previous",
    "mute": "mute", "unmute": "mute", "mute music": "mute", "mute volume": "mute",
    "volume up": "volume_up", "turn volume up": "volume_up", "louder": "volume_up",
    "turn it up": "volume_up", "increase volume": "volume_up",
    "volume down": "volume_down", "turn volume down": "volume_down", "quieter": "volume_down",
    "turn it down": "volume_down", "decrease volume": "volume_down", "lower volume": "volume_down",
}

_VOLUME_NUMBER = re.compile(r"^(?:set )?volume(?: to| at)? (\d{1,3})(?: percent)?$")
_OPEN_APP = re.compile(r"^open(?: the)? ([a-z0-9][a-z0-9 ]{0,22})$")
# Words that mean "open" was not really an app-launch request; a short
# generic-looking match on one of these is left to the real agent instead.
_OPEN_APP_EXCLUDE = frozenset({
    "my", "the", "a", "an", "up", "door", "window", "windows", "email", "mail",
    "file", "files", "folder", "document", "documents", "link", "url",
})


def route(message: str) -> FastCommand | None:
    """Match one unambiguous device command and EXECUTE it. Returns the spoken
    confirmation, or None to fall through to the real agent (including on any
    execution error -- a failed fast path must never look like a fast path
    that quietly did nothing)."""
    if not getattr(config, "FAST_LOCAL_COMMANDS_ENABLED", True):
        return None
    normalised = _normalise(message)
    if not normalised:
        return None

    action = _MEDIA_PHRASES.get(normalised)
    if action is not None:
        from reyes_agent.tools.system import media_control

        try:
            media_control(action)
        except Exception:  # noqa: BLE001 -- fall through to the real agent
            return None
        spoken = {
            "play_pause": "Toggled playback.", "next": "Skipped.",
            "previous": "Previous track.", "mute": "Toggled mute.",
            "volume_up": "Volume up.", "volume_down": "Volume down.",
        }[action]
        return FastCommand(spoken, f"media_{action}", "media_control")

    volume_match = _VOLUME_NUMBER.match(normalised)
    if volume_match:
        from reyes_agent.tools.utility import set_volume

        level = max(0, min(100, int(volume_match.group(1))))
        try:
            set_volume(level)
        except Exception:  # noqa: BLE001
            return None
        return FastCommand(f"Volume set to {level}.", "set_volume", "set_volume")

    open_match = _OPEN_APP.match(normalised)
    if open_match:
        name = open_match.group(1).strip()
        if len(name) < 2 or _OPEN_APP_EXCLUDE.intersection(name.split()):
            return None
        from reyes_agent.tools.system import open_app

        try:
            result = open_app(name)
        except Exception:  # noqa: BLE001
            return None
        # open_app returns a human sentence on both success and a clean miss
        # (e.g. "No app matching ... found") -- speak that real outcome
        # rather than inventing a generic "Opening X" that could be a lie.
        return FastCommand(str(result), "open_app", "open_app")

    return None
