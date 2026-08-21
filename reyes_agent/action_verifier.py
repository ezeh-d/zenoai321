"""Independent post-condition checks for consequential actions.

WHY
---
A tool returning normally is not proof its effect happened -- see
``tools.classify_tool_result``. This module is ONE uniform verdict layer: given
an action, its arguments and its result, it looks for real evidence and returns
a structured :class:`Verdict`. Evidence is taken, in order:

  1. explicit evidence the tool already reported (``ok`` + ``evidence``);
  2. an independent OS-level check (the app's process is running, the file is
     on disk).

When it cannot check, it says so (``verifiable=False``) instead of inventing
success. It never raises, and it never turns an unknown into a pass -- the same
safety rule the result classifier follows. Other subsystems can contribute
their own checks with :func:`register`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Verdict:
    verified: bool          # the effect is confirmed to have happened
    verifiable: bool        # a check was actually possible at all
    method: str             # how judged: "evidence" | "process" | "path" | "none"
    evidence: str = ""      # short, human-readable proof or reason

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_UNVERIFIABLE = Verdict(False, False, "none", "no independent check available")


# --- primitives -------------------------------------------------------------
def _running_processes() -> list[str]:
    """Case-folded names of running processes. Empty on any failure."""
    try:
        import psutil

        names = []
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "")
            if name:
                names.append(name.casefold())
        return names
    except Exception:  # noqa: BLE001 -- verification must never raise
        return []


# Common app -> process-image hints. A partial, case-insensitive match against
# the running-process list is enough; the point is evidence, not a registry of
# every binary on earth. An unknown app falls back to its own name.
_APP_PROCESS_HINTS = {
    "chrome": ["chrome"], "google chrome": ["chrome"],
    "edge": ["msedge"], "microsoft edge": ["msedge"],
    "firefox": ["firefox"],
    "slack": ["slack"],
    "notepad": ["notepad"],
    "calculator": ["calculatorapp", "calc"], "calc": ["calculatorapp", "calc"],
    "explorer": ["explorer"], "file explorer": ["explorer"],
    "code": ["code"], "vs code": ["code"], "visual studio code": ["code"],
    "word": ["winword"], "excel": ["excel"], "powerpoint": ["powerpnt"],
    "outlook": ["outlook"], "teams": ["teams", "ms-teams"],
    "spotify": ["spotify"], "discord": ["discord"], "telegram": ["telegram"],
    "terminal": ["windowsterminal"], "cmd": ["cmd"], "powershell": ["powershell"],
}


def app_is_running(app: str) -> tuple[bool, str]:
    """True (with evidence) if a process plausibly matching ``app`` is running."""
    app_l = str(app or "").strip().casefold()
    if not app_l:
        return False, ""
    procs = _running_processes()
    if not procs:
        return False, ""
    hints = _APP_PROCESS_HINTS.get(app_l) or [app_l.replace(" ", "")]
    for hint in hints:
        for name in procs:
            if hint and hint in name:
                return True, f"process '{name}' is running"
    return False, ""


# --- evidence already in the result -----------------------------------------
def _parse(result: Any) -> Any:
    if isinstance(result, str):
        stripped = result.strip()
        if stripped[:1] in "{[":
            try:
                return json.loads(stripped)
            except (TypeError, ValueError, json.JSONDecodeError):
                return result
    return result


def _explicit_evidence(result: Any) -> Verdict | None:
    parsed = _parse(result)
    if isinstance(parsed, dict):
        evidence = parsed.get("evidence") or parsed.get("verification_evidence")
        if parsed.get("ok") is True and evidence:
            return Verdict(True, True, "evidence", str(evidence)[:200])
        if (parsed.get("verified") is True or
                str(parsed.get("verification_state", "")).casefold() == "verified"):
            return Verdict(True, True, "evidence", "tool reported verified")
        if parsed.get("ok") is False or parsed.get("success") is False:
            return Verdict(False, True, "evidence", "tool reported failure")
    return None


# --- action-specific checks -------------------------------------------------
def _arg(args: dict, *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _verify_open_app(args: dict, result: Any) -> Verdict:
    app = _arg(args, "app", "app_name", "name", "target")
    if not app and isinstance(result, str):
        # Read it back from a phrase like "Opened Slack." when no arg was given.
        low = result.casefold()
        for token in ("opened ", "launched ", "starting ", "started "):
            index = low.find(token)
            if index >= 0:
                app = result[index + len(token):].strip(" .\n")
                break
    if not app:
        return _UNVERIFIABLE
    running, why = app_is_running(app)
    if running:
        return Verdict(True, True, "process", why)
    return Verdict(False, True, "process", f"no running process matches '{app}'")


def _verify_path(args: dict, _result: Any) -> Verdict:
    path = _arg(args, "path", "file", "filename", "dest", "destination", "target")
    if not path:
        return _UNVERIFIABLE
    try:
        exists = os.path.exists(path)
    except Exception:  # noqa: BLE001
        return _UNVERIFIABLE
    return (Verdict(True, True, "path", f"'{path}' exists")
            if exists else Verdict(False, True, "path", f"'{path}' is missing"))


# action keyword -> checker
_CHECKS: dict[str, Callable[[dict, Any], Verdict]] = {
    "open_app": _verify_open_app,
    "launch_app": _verify_open_app,
    "open_application": _verify_open_app,
    "create_file": _verify_path,
    "write_file": _verify_path,
    "save_file": _verify_path,
    "create_folder": _verify_path,
    "make_folder": _verify_path,
    "download": _verify_path,
}


def register(action: str, checker: Callable[[dict, Any], Verdict]) -> None:
    """Let a subsystem contribute its own post-condition check for an action."""
    _CHECKS[str(action).strip().casefold()] = checker


def verify(action: str, args: dict | None = None, result: Any = None) -> Verdict:
    """Judge whether ``action`` actually took effect. Never raises.

    Explicit tool evidence wins; otherwise an independent check runs when one is
    registered for the action (a bare tail like ``open_app`` also matches a
    dotted ``desktop.open_app``). With no way to check, the verdict is
    ``verifiable=False`` -- never a false pass.
    """
    try:
        args = args if isinstance(args, dict) else {}
        evidence = _explicit_evidence(result)
        if evidence is not None:
            return evidence
        key = str(action or "").strip().casefold()
        checker = _CHECKS.get(key) or _CHECKS.get(key.rsplit(".", 1)[-1])
        if checker is not None:
            return checker(args, result)
        return _UNVERIFIABLE
    except Exception:  # noqa: BLE001 -- a verifier must never break the caller
        return _UNVERIFIABLE
