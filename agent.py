from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from app import open_app
from desktop_control import (
    click_mouse,
    close_current_window,
    double_click,
    hotkey,
    maximize_window,
    minimize_window,
    move_mouse,
    press_key,
    right_click,
    scroll_down,
    scroll_up,
    show_desktop,
    switch_window,
    type_text,
)
from vision import analyze_screen, describe_screen, read_screen_text
from web_tools import google_search, open_website


# =========================================================
# AGENT RESULT MODELS
# =========================================================

@dataclass
class AgentStep:
    number: int
    instruction: str


@dataclass
class AgentStepResult:
    number: int
    instruction: str
    success: bool
    response: str


# =========================================================
# SAFETY
# =========================================================

BLOCKED_PHRASES = (
    "enter my password",
    "type my password",
    "send money",
    "transfer money",
    "buy ",
    "purchase ",
    "delete everything",
    "format drive",
    "factory reset",
    "disable antivirus",
    "turn off antivirus",
    "bypass security",
    "steal ",
    "hack ",
)

CONFIRMATION_REQUIRED_PHRASES = (
    "delete ",
    "remove ",
    "send email",
    "send message",
    "submit form",
    "place order",
    "checkout",
    "pay ",
)


def safety_check(goal: str) -> tuple[bool, str]:
    """
    Check whether a goal is safe enough for automatic execution.
    """
    lower = goal.lower()

    for phrase in BLOCKED_PHRASES:
        if phrase in lower:
            return (
                False,
                "I will not execute that task automatically because it "
                "contains a blocked or high-risk action.",
            )

    for phrase in CONFIRMATION_REQUIRED_PHRASES:
        if phrase in lower:
            return (
                False,
                "This task includes an action that requires confirmation. "
                "Please perform or approve the sensitive step manually.",
            )

    return True, ""


# =========================================================
# PLAN CREATION
# =========================================================

def create_plan(goal: str) -> list[AgentStep]:
    """
    Convert a natural-language goal into simple ordered steps.

    The parser intentionally stays conservative. It only splits commands;
    it does not invent extra actions.
    """
    clean_goal = " ".join(goal.strip().split())

    if not clean_goal:
        return []

    normalized = re.sub(
        r"\bthen\b",
        ";",
        clean_goal,
        flags=re.IGNORECASE,
    )

    normalized = re.sub(
        r",\s+and\s+",
        ";",
        normalized,
        flags=re.IGNORECASE,
    )

    normalized = re.sub(
        r"\band after that\b",
        ";",
        normalized,
        flags=re.IGNORECASE,
    )

    raw_steps = [
        item.strip(" ,.")
        for item in normalized.split(";")
        if item.strip(" ,.")
    ]

    if len(raw_steps) == 1:
        raw_steps = [
            item.strip(" ,.")
            for item in re.split(
                r"\s+\band\b\s+",
                clean_goal,
                flags=re.IGNORECASE,
            )
            if item.strip(" ,.")
        ]

    return [
        AgentStep(number=index, instruction=instruction)
        for index, instruction in enumerate(raw_steps, start=1)
    ]


def format_plan(steps: list[AgentStep]) -> str:
    if not steps:
        return "I could not create a plan from that goal."

    return "Plan:\n" + "\n".join(
        f"{step.number}. {step.instruction}"
        for step in steps
    )


# =========================================================
# STEP EXECUTION
# =========================================================

def _coordinates(text: str) -> tuple[int, int] | None:
    match = re.search(
        r"\bx\s*(-?\d+)\s*[, ]+\s*y\s*(-?\d+)\b",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(r"\b(-?\d+)\s*[, ]+\s*(-?\d+)\b", text)

    if match:
        return int(match.group(1)), int(match.group(2))

    return None


def execute_step(instruction: str) -> str:
    """
    Execute one allowlisted desktop step.
    """
    clean = instruction.strip()
    lower = clean.lower()

    if not clean:
        return "Empty step."

    if lower.startswith("open "):
        target = clean[5:].strip()

        app_result = open_app(target)

        if not app_result.startswith("I could not find"):
            return app_result

        return open_website(target)

    if lower.startswith("search google for "):
        return google_search(clean[18:].strip())

    if lower.startswith("google "):
        return google_search(clean[7:].strip())

    if lower.startswith("type "):
        return type_text(clean[5:].strip())

    if lower.startswith("write "):
        return type_text(clean[6:].strip())

    if lower.startswith("press "):
        key = clean[6:].strip().lower()

        shortcuts: dict[str, tuple[str, ...]] = {
            "ctrl s": ("ctrl", "s"),
            "control s": ("ctrl", "s"),
            "ctrl a": ("ctrl", "a"),
            "control a": ("ctrl", "a"),
            "ctrl c": ("ctrl", "c"),
            "control c": ("ctrl", "c"),
            "ctrl v": ("ctrl", "v"),
            "control v": ("ctrl", "v"),
            "alt tab": ("alt", "tab"),
        }

        if key in shortcuts:
            return hotkey(*shortcuts[key])

        return press_key(key)

    if lower.startswith("move mouse"):
        point = _coordinates(clean)

        if point is None:
            return "Use coordinates such as: move mouse to x 500 y 300."

        return move_mouse(*point)

    if lower.startswith("double click"):
        point = _coordinates(clean)
        return double_click(*point) if point else double_click()

    if lower.startswith("right click"):
        point = _coordinates(clean)
        return right_click(*point) if point else right_click()

    if lower.startswith("click"):
        point = _coordinates(clean)
        return click_mouse(*point) if point else click_mouse()

    if lower in {"scroll down", "go down", "page down"}:
        return scroll_down()

    if lower in {"scroll up", "go up", "page up"}:
        return scroll_up()

    if lower in {"switch window", "switch application"}:
        return switch_window()

    if lower in {"maximize window", "maximize this window"}:
        return maximize_window()

    if lower in {"minimize window", "minimize this window"}:
        return minimize_window()

    if lower in {"close current window", "close this window"}:
        return close_current_window()

    if lower in {"show desktop", "go to desktop"}:
        return show_desktop()

    if lower in {
        "describe the screen",
        "describe my screen",
        "look at my screen",
        "what is on my screen",
    }:
        return describe_screen()

    if lower in {
        "read the screen",
        "read my screen",
        "read the text on my screen",
    }:
        return read_screen_text()

    if lower.startswith("check the screen for "):
        prompt = clean[len("check the screen for "):].strip()
        return analyze_screen(prompt)

    if lower.startswith("wait "):
        match = re.search(r"(\d+(?:\.\d+)?)", lower)

        if not match:
            return "Tell me how many seconds to wait."

        seconds = min(float(match.group(1)), 15.0)
        time.sleep(seconds)
        return f"Waited {seconds:g} seconds."

    return (
        "Unsupported autonomous step. "
        "Try an explicit action such as open, type, press, click, "
        "scroll, switch window, wait, or inspect the screen."
    )


# =========================================================
# GOAL EXECUTION
# =========================================================

def run_goal(
    goal: str,
    status_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Plan and execute a safe multi-step goal.
    """
    allowed, safety_message = safety_check(goal)

    if not allowed:
        return safety_message

    steps = create_plan(goal)

    if not steps:
        return "I could not create a plan from that goal."

    results: list[AgentStepResult] = []

    for step in steps:
        if status_callback:
            status_callback(
                f"Executing step {step.number}: {step.instruction}"
            )

        response = execute_step(step.instruction)

        success = not (
            response.startswith("Unsupported autonomous step")
            or response.startswith("I could not")
            or response.startswith("Empty step")
        )

        results.append(
            AgentStepResult(
                number=step.number,
                instruction=step.instruction,
                success=success,
                response=response,
            )
        )

        if not success:
            break

        time.sleep(0.35)

    completed = sum(result.success for result in results)
    total = len(steps)

    report_lines = [
        f"Agent completed {completed} of {total} steps."
    ]

    for result in results:
        marker = "OK" if result.success else "STOPPED"
        report_lines.append(
            f"{result.number}. [{marker}] {result.instruction} — "
            f"{result.response}"
        )

    return "\n".join(report_lines)