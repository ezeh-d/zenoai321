"""reyes_engine.py — bridge between the HUD and the powerful multi-skill engine.

The GUI calls brain.think(); brain.think() calls ask() here, which runs the
full reyes.brain.Brain (files, GUI control, browser, Slack, coder, Obsidian,
second brain, multi-model LLM with offline fallback).

Permission model (important — the HUD has no terminal to type y/n into):
  - Safe/read actions (chat, read files, search, browse, remember, recall,
    scaffold projects) run normally.
  - Destructive actions (delete/move/overwrite files, run shell commands,
    GUI click/type) are BLOCKED by default from the GUI for your safety.
  - To allow them from the HUD (at your own risk), set in your .env:
        REYES_GUI_AUTOAPPROVE=true
"""
from __future__ import annotations

import os
from threading import Lock

_engine = None
_lock = Lock()


def _gui_approver(action: str) -> bool:
    """No terminal in the GUI, so honor an explicit env opt-in; otherwise deny."""
    allow = os.environ.get("REYES_GUI_AUTOAPPROVE", "").strip().lower() in ("1", "true", "yes")
    return allow


def _personalize() -> None:
    """Let the powerful engine use your name/personality from the classic config."""
    try:
        import config as classic  # the root config.py (OWNER_NAME, ASSISTANT_NAME)

        os.environ.setdefault("USER_NAME", getattr(classic, "USER_NAME", "Boss"))
        os.environ.setdefault("ASSISTANT_NAME", getattr(classic, "ASSISTANT_NAME", "REYES"))
    except Exception:  # noqa: BLE001
        pass


def get_engine():
    """Lazily build a single shared Brain instance."""
    global _engine
    with _lock:
        if _engine is None:
            _personalize()
            from brain import Brain

            _engine = Brain(approver=_gui_approver, on_tool=lambda _info: None)
        return _engine


def ask(message: str) -> str:
    """Send one message to the powerful engine and return its reply."""
    return get_engine().chat(message)
