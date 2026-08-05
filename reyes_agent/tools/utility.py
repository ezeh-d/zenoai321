"""Small, high-frequency quality-of-life tools -- the things a real
day-to-day assistant is expected to just do: know the time, handle the
clipboard, set the volume to a number, lock the screen, and honestly
describe its own capabilities.

All ungated (light=True) -- none of these are destructive or send
anything anywhere. Volume/lock affect only the local machine and are
trivially reversible.
"""

from __future__ import annotations

from datetime import datetime

from reyes_agent.tools import register


@register(
    name="get_datetime",
    description=(
        "Get the exact current date, time, and day of week on this "
        "machine. Use whenever the answer depends on 'now' -- what day it "
        "is, the time, how long until something, scheduling."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def get_datetime() -> str:
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y, %I:%M %p")


@register(
    name="read_clipboard",
    description="Read the current text contents of the Windows clipboard.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def read_clipboard() -> str:
    import pyperclip

    try:
        text = pyperclip.paste()
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't read the clipboard: {exc}"
    return text if text else "(clipboard is empty)"


@register(
    name="write_clipboard",
    description="Copy the given text onto the Windows clipboard so the user can paste it.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to place on the clipboard."},
        },
        "required": ["text"],
    },
    light=True,
)
def write_clipboard(text: str) -> str:
    import pyperclip

    try:
        pyperclip.copy(text)
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't write to the clipboard: {exc}"
    return "Copied to the clipboard."


@register(
    name="set_volume",
    description=(
        "Set the system master volume to a specific level from 0 to 100. "
        "For simple up/down/mute nudges, media_control is lighter; use "
        "this when the user names a level ('set volume to 30')."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume level, 0 (mute) to 100 (max)."},
        },
        "required": ["level"],
    },
    light=True,
)
def set_volume(level: int) -> str:
    try:
        level = max(0, min(100, int(level)))
    except (TypeError, ValueError):
        return "Give a whole number from 0 to 100."
    try:
        from pycaw.pycaw import AudioUtilities

        vol = AudioUtilities.GetSpeakers().EndpointVolume
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't set the volume: {exc}"
    return f"Volume set to {level}%."


@register(
    name="set_mic_level",
    description=(
        "Set the microphone INPUT level (0-100) -- raising it lets REYES "
        "hear the user from farther away and pick up quieter/whispered "
        "speech. Use when the user says REYES can't hear them well or wants "
        "to be heard from across the room."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Mic input level, 0 to 100."},
        },
        "required": ["level"],
    },
    light=True,
)
def set_mic_level(level: int) -> str:
    try:
        level = max(0, min(100, int(level)))
    except (TypeError, ValueError):
        return "Give a whole number from 0 to 100."
    try:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        mic = AudioUtilities.GetMicrophone()
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't set the mic level: {exc}"
    return f"Microphone input level set to {level}%."


@register(
    name="lock_screen",
    description="Lock the Windows screen (same as Win+L). The user's password unlocks it again.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def lock_screen() -> str:
    import ctypes

    try:
        ok = ctypes.windll.user32.LockWorkStation()
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't lock the screen: {exc}"
    return "Screen locked." if ok else "The lock command didn't take -- try again."


@register(
    name="list_capabilities",
    description=(
        "List what REYES can actually do right now -- the real, currently "
        "available tools, grouped. Use when the user asks what you can do, "
        "what you're capable of, or how you can help, so the answer "
        "reflects what's truly wired up instead of a guess."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def list_capabilities() -> str:
    from reyes_agent.tools import TOOLS

    # Curated grouping of the real registered tools -- keeps the answer
    # honest (derived from what's registered) without dumping raw names.
    groups: dict[str, list[str]] = {
        "Conversation & memory": ["remember", "list_memories", "forget_fact"],
        "Notes & knowledge (Obsidian vault)": [
            "search_notes", "list_notes", "write_note", "link_notes",
            "create_canvas", "create_database_view", "setup_vault_structure",
            "vault_structure_report",
        ],
        "Building things": ["write_project_file", "list_project_files", "generate_image"],
        "Desktop control": [
            "open_app", "open_path", "list_dir", "read_file", "list_processes",
            "run_command", "delete_file", "move_file", "set_volume",
            "lock_screen", "media_control", "read_clipboard", "write_clipboard",
        ],
        "Seeing": ["take_screenshot", "take_webcam_photo"],
        "Web": ["web_search"],
        "Messaging": ["send_slack_message", "send_telegram_message"],
        "Scheduling & reminders": [
            "add_calendar_event", "list_calendar_events", "cancel_calendar_event",
            "schedule_check", "list_scheduled_checks", "cancel_scheduled_check",
        ],
        "Delegation": ["delegate"],
        "Time": ["get_datetime"],
    }
    lines = []
    for group, names in groups.items():
        available = [n for n in names if n in TOOLS]
        if available:
            lines.append(f"{group}: {', '.join(available)}")
    # Catch anything registered but not in the curated map, so this never
    # silently under-reports a newly added tool.
    mapped = {n for names in groups.values() for n in names}
    extra = sorted(n for n in TOOLS if n not in mapped)
    if extra:
        lines.append(f"Other: {', '.join(extra)}")
    return "\n".join(lines)
