from __future__ import annotations

import re

from app import open_app
from agent import create_plan, format_plan, run_goal
from assistant_mode import (
    enable_normal_mode,
    enable_serious_mode,
    get_mode_description,
)
from commands import execute_command
from desktop_control import (
    click_mouse,
    close_current_window,
    double_click,
    get_mouse_position,
    get_screen_size,
    hotkey,
    maximize_window,
    minimize_window,
    move_mouse,
    open_task_view,
    press_key,
    right_click,
    scroll_down,
    scroll_up,
    show_desktop,
    switch_window,
    type_text,
)
from memory import (
    forget,
    list_memory,
    load_notes,
    recall,
    remember,
    save_note,
    search_memory,
)
from ollama_ai import ask_ai
from vision import (
    analyze_screen,
    analyze_screen_error,
    capture_screen,
    describe_screen,
    read_screen_text,
)
from core.orchestrator import handle_core_command

from web_tools import (
    github_search,
    google_search,
    open_website,
    stackoverflow_search,
    wikipedia_search,
    youtube_search,
)


def _extract_coordinates(command: str) -> tuple[int, int] | None:
    """
    Extract x and y coordinates from a command.
    """
    match = re.search(
        r"\bx\s*(-?\d+)\s*[, ]+\s*y\s*(-?\d+)\b",
        command,
        flags=re.IGNORECASE,
    )

    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(
        r"\b(-?\d+)\s*[, ]+\s*(-?\d+)\b",
        command,
    )

    if match:
        return int(match.group(1)), int(match.group(2))

    return None


def route(command: str) -> str:
    """
    Route a user's command to the appropriate REYES module.
    """

    clean_command = command.strip()

    if not clean_command:
        return "Please give me a command."

    lower = clean_command.lower()


    # =====================================================
    # AUTONOMOUS AGENT
    # =====================================================

    if lower.startswith("plan "):
        goal = clean_command[5:].strip()
        return format_plan(create_plan(goal))

    if lower.startswith("agent "):
        goal = clean_command[6:].strip()

        if not goal:
            return "Tell me the goal you want the agent to complete."

        return run_goal(goal)

    if lower.startswith("complete this task "):
        goal = clean_command[19:].strip()

        if not goal:
            return "Tell me the task you want completed."

        return run_goal(goal)


    # =====================================================
    # ASSISTANT MODES
    # =====================================================

    if lower in {
        "serious mode",
        "activate serious mode",
        "enable serious mode",
        "go serious",
        "be serious",
        "professional mode",
    }:
        return enable_serious_mode()

    if lower in {
        "normal mode",
        "activate normal mode",
        "enable normal mode",
        "disable serious mode",
        "stop serious mode",
        "be normal",
    }:
        return enable_normal_mode()

    if lower in {
        "what mode are you in",
        "what mode is active",
        "current mode",
        "show mode",
    }:
        return get_mode_description()


    # =====================================================
    # VISION
    # =====================================================

    if lower in {
        "what is on my screen",
        "what's on my screen",
        "what can you see",
        "describe my screen",
        "describe the screen",
        "look at my screen",
        "analyze my screen",
        "analyse my screen",
    }:
        return describe_screen()

    if lower in {
        "read my screen",
        "read the screen",
        "read what is on my screen",
        "read what's on my screen",
        "read the text on my screen",
    }:
        return read_screen_text()

    if lower in {
        "what is the error on my screen",
        "what's the error on my screen",
        "read the error on my screen",
        "analyze the error on my screen",
        "analyse the error on my screen",
        "explain the error on my screen",
    }:
        return analyze_screen_error()

    if lower in {
        "take a screenshot",
        "capture my screen",
        "capture the screen",
        "screenshot my screen",
    }:
        try:
            path = capture_screen()
            return f"Screenshot saved to {path}"
        except Exception as error:
            return (
                "I could not capture the screen. "
                f"{type(error).__name__}: {error}"
            )

    vision_prefixes = (
        "look at my screen and ",
        "analyze my screen and ",
        "analyse my screen and ",
        "look at the screen and ",
        "check my screen for ",
    )

    for prefix in vision_prefixes:
        if lower.startswith(prefix):
            prompt = clean_command[len(prefix):].strip()
            return analyze_screen(prompt) if prompt else describe_screen()


    # =====================================================
    # DESKTOP CONTROL
    # =====================================================

    if lower in {
        "what is my screen size",
        "what's my screen size",
        "screen size",
        "screen resolution",
    }:
        return get_screen_size()

    if lower in {
        "where is my mouse",
        "mouse position",
        "cursor position",
        "where is the cursor",
    }:
        return get_mouse_position()

    if lower.startswith("move mouse"):
        coordinates = _extract_coordinates(clean_command)

        if coordinates is None:
            return "Use this format: move mouse to x 500 y 300."

        return move_mouse(*coordinates)

    if lower.startswith("double click"):
        coordinates = _extract_coordinates(clean_command)

        if coordinates is None:
            return double_click()

        return double_click(*coordinates)

    if lower.startswith("right click"):
        coordinates = _extract_coordinates(clean_command)

        if coordinates is None:
            return right_click()

        return right_click(*coordinates)

    if lower.startswith("click"):
        coordinates = _extract_coordinates(clean_command)

        if coordinates is None:
            return click_mouse()

        return click_mouse(*coordinates)

    if lower.startswith("type "):
        text = clean_command[5:].strip()
        return type_text(text)

    if lower.startswith("write "):
        text = clean_command[6:].strip()
        return type_text(text)

    if lower.startswith("press "):
        key = clean_command[6:].strip()

        shortcut_map = {
            "enter": ("enter",),
            "escape": ("esc",),
            "esc": ("esc",),
            "tab": ("tab",),
            "space": ("space",),
            "backspace": ("backspace",),
            "delete": ("delete",),
            "control s": ("ctrl", "s"),
            "ctrl s": ("ctrl", "s"),
            "control c": ("ctrl", "c"),
            "ctrl c": ("ctrl", "c"),
            "control v": ("ctrl", "v"),
            "ctrl v": ("ctrl", "v"),
            "control x": ("ctrl", "x"),
            "ctrl x": ("ctrl", "x"),
            "control z": ("ctrl", "z"),
            "ctrl z": ("ctrl", "z"),
            "control a": ("ctrl", "a"),
            "ctrl a": ("ctrl", "a"),
            "alt tab": ("alt", "tab"),
            "windows d": ("win", "d"),
            "win d": ("win", "d"),
        }

        if key in shortcut_map:
            return hotkey(*shortcut_map[key])

        return press_key(key)

    if lower in {
        "scroll up",
        "go up",
        "page up",
    }:
        return scroll_up()

    if lower in {
        "scroll down",
        "go down",
        "page down",
    }:
        return scroll_down()

    if lower in {
        "switch window",
        "switch application",
        "next window",
    }:
        return switch_window()

    if lower in {
        "minimize window",
        "minimize this window",
    }:
        return minimize_window()

    if lower in {
        "maximize window",
        "maximize this window",
    }:
        return maximize_window()

    if lower in {
        "close current window",
        "close this window",
    }:
        return close_current_window()

    if lower in {
        "show desktop",
        "go to desktop",
    }:
        return show_desktop()

    if lower in {
        "open task view",
        "show task view",
    }:
        return open_task_view()


    # =====================================================
    # NOTES
    # =====================================================

    if lower.startswith("note "):
        note_text = clean_command[5:].strip()

        if not note_text:
            return "Please tell me what note to save."

        if save_note(note_text):
            return "Note saved."

        return "I could not save the note."

    if lower.startswith("save note "):
        note_text = clean_command[10:].strip()

        if not note_text:
            return "Please tell me what note to save."

        if save_note(note_text):
            return "Note saved."

        return "I could not save the note."

    if lower in {
        "show my notes",
        "show notes",
        "list notes",
        "what are my notes",
    }:
        notes = load_notes()

        if not notes:
            return "You do not have any saved notes."

        return "Your saved notes:\n" + "\n".join(
            f"{index}. {note}"
            for index, note in enumerate(notes, start=1)
        )


    # =====================================================
    # MEMORY
    # =====================================================

    if lower.startswith("remember "):
        memory_text = clean_command[9:].strip()

        try:
            key, value = memory_text.split(" is ", 1)
        except ValueError:
            return "Use this format: remember favorite color is blue."

        key = key.strip()
        value = value.strip()

        if not key or not value:
            return "Use this format: remember favorite color is blue."

        if remember(key, value):
            return f"I will remember that {key} is {value}."

        return "I could not save that memory."

    if lower.startswith("recall "):
        key = clean_command[7:].strip()

        if not key:
            return "Tell me what to recall."

        value = recall(key)

        if value is None:
            return f"I do not have a memory named '{key}'."

        return f"{key} is {value}."

    if lower.startswith("what is "):
        key = clean_command[8:].strip()
        value = recall(key)

        if value is not None:
            return f"{key} is {value}."

        return ask_ai(clean_command)

    if lower.startswith("forget "):
        key = clean_command[7:].strip()

        if not key:
            return "Tell me what to forget."

        if forget(key):
            return f"I forgot {key}."

        return f"I could not find a memory named '{key}'."

    if lower in {
        "what do you remember",
        "show memory",
        "show memories",
        "list memory",
        "list memories",
    }:
        memories = list_memory()

        if not memories:
            return "I do not have any saved memories."

        return "Saved memories:\n" + "\n".join(
            f"- {key}: {value}"
            for key, value in memories.items()
        )

    if lower.startswith("search memory "):
        query = clean_command[14:].strip()

        if not query:
            return "Tell me what to search for in memory."

        results = search_memory(query)

        if not results:
            return f"No memories matched '{query}'."

        return "Matching memories:\n" + "\n".join(
            f"- {key}: {value}"
            for key, value in results.items()
        )


    # =====================================================
    # WEB SEARCH
    # =====================================================

    if lower.startswith("search google for "):
        return google_search(clean_command[18:].strip())

    if lower.startswith("google "):
        return google_search(clean_command[7:].strip())

    if lower.startswith("search youtube for "):
        return youtube_search(clean_command[19:].strip())

    if lower.startswith("youtube "):
        return youtube_search(clean_command[8:].strip())

    if lower.startswith("search github for "):
        return github_search(clean_command[18:].strip())

    if lower.startswith("github search "):
        return github_search(clean_command[14:].strip())

    if lower.startswith("search stack overflow for "):
        return stackoverflow_search(clean_command[26:].strip())

    if lower.startswith("stackoverflow "):
        return stackoverflow_search(clean_command[14:].strip())

    if lower.startswith("search wikipedia for "):
        return wikipedia_search(clean_command[21:].strip())

    if lower.startswith("wikipedia "):
        return wikipedia_search(clean_command[10:].strip())

    if lower.startswith("search "):
        return google_search(clean_command[7:].strip())


    # =====================================================
    # OPEN APPS OR WEBSITES
    # =====================================================

    if lower.startswith("open "):
        target = clean_command[5:].strip()

        if not target:
            return "Tell me what to open."

        app_response = open_app(target)

        if not app_response.startswith("I could not find"):
            return app_response

        return open_website(target)


    # =====================================================
    # EXISTING DESKTOP COMMANDS
    # =====================================================

    desktop_prefixes = (
        "close ",
        "create folder ",
        "create text file ",
        "send slack message ",
        "send a slack message ",
        "send message ",
        "message ",
        "tell ",
    )

    desktop_commands = {
        "list apps",
        "show apps",
        "detected apps",
        "what apps can you open",
        "date",
        "today's date",
        "what is the date",
        "time",
        "current time",
        "what time is it",
    }

    if lower.startswith(desktop_prefixes):
        return execute_command(clean_command)

    if lower in desktop_commands:
        return execute_command(clean_command)


    # =====================================================
    # CORE ORCHESTRATOR / PLUGINS / AI FALLBACK
    # =====================================================

    core_response = handle_core_command(clean_command)
    if core_response is not None:
        return core_response

    return ask_ai(clean_command)