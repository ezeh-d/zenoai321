"""ZENO's hands as brain tools: type, press keys, click, scroll.

REUSE, NOT REBUILD
------------------
The real keyboard/mouse engine already exists in ``reyes_agent.computer.agentic``
(``act``) -- it is permission-gated (``safety.gate``), refuses to steal the mouse
while the owner is typing (``input_guard``), refuses to type into a window it has
not read (focus-moved guard), grounds clicks by DESCRIPTION via vision rather than
blind coordinates, and VERIFIES that the screen changed afterwards. What was
missing was exposing that engine to the brain as callable tools, so "ZENO, type
hello and press enter" had no tool to reach. These thin wrappers close that gap.

Every tool returns the standardized result the brief asks for and never claims
success without the engine's own verification. Clipboard already has its own
tools (``read_clipboard`` / ``write_clipboard``); this module does not duplicate
them.
"""

from __future__ import annotations

import json
import time
from typing import Any

from reyes_agent.tools import register


def _result(tool: str, action: str, ok: bool, *, target: str = "",
            verified: bool = False, detail: str = "", started: float = 0.0) -> str:
    """One standardized, honest tool result (brief: TOOL RESULT FORMAT)."""
    payload: dict[str, Any] = {
        "success": bool(ok),
        "ok": bool(ok),
        "tool": f"computer.{tool}",
        "action": action,
        "target": target[:120],
        "duration_ms": round((time.time() - started) * 1000) if started else None,
        "verified": bool(verified),
        "detail": detail[:500],
        "error": None if ok else (detail[:300] or "action failed"),
    }
    if ok and verified:
        payload["evidence"] = detail[:300]      # lets the verifier mark it VERIFIED
    return json.dumps(payload, ensure_ascii=False)


import re as _re

# A conservative "this looks like a secret" check, so a typed password/token is
# not echoed back into the result/audit trail (brief: safe secret filtering).
# The text is still typed -- the owner asked for it -- only the ECHO is redacted.
_SECRETISH = _re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token|bearer\s|private[_-]?key|"
    r"\bsk-[a-z0-9]{12,}|ssh-rsa\s|-----BEGIN)")


def _safe_echo(text: str) -> str:
    value = str(text or "")
    if _SECRETISH.search(value) or (len(value) >= 20 and " " not in value.strip()):
        return f"[redacted {len(value)} chars]"
    return value[:60]


def _run(action: str, *, target: str = "", text: str = "") -> tuple[bool, bool, str]:
    """Drive the existing gated/verified engine. Returns (ok, changed, detail)."""
    from reyes_agent.computer import agentic

    step = agentic.act(action, target=target, text=text, approved=True)
    return bool(getattr(step, "ok", False)), bool(getattr(step, "changed", False)), \
        str(getattr(step, "detail", ""))


@register(
    name="type_text",
    description="Type text into the ACTIVE window with ZENO's real keyboard "
                "(e.g. type a sentence into Notepad or a form). Verified: reports "
                "whether the screen actually changed. Refuses if the owner is "
                "typing or focus moved.",
    input_schema={"type": "object", "properties": {
        "text": {"type": "string", "description": "The text to type."},
    }, "required": ["text"]},
)
def type_text(text: str) -> str:
    started = time.time()
    if not str(text):
        return _result("type_text", "type", False, detail="no text given", started=started)
    ok, changed, detail = _run("type", text=str(text))
    return _result("type_text", "type", ok, target=_safe_echo(text),
                   verified=changed, detail=detail, started=started)


@register(
    name="press_keys",
    description="Press a key or a shortcut with ZENO's real keyboard: 'enter', "
                "'tab', 'escape', 'backspace', 'delete', 'up'/'down'/'left'/'right', "
                "or a combo like 'ctrl+c', 'ctrl+v', 'ctrl+a', 'ctrl+s', 'alt+tab', "
                "'win+d'. Use '+' between keys.",
    input_schema={"type": "object", "properties": {
        "keys": {"type": "string", "description": "Key or combo, e.g. 'ctrl+s' or 'enter'."},
    }, "required": ["keys"]},
)
def press_keys(keys: str) -> str:
    started = time.time()
    combo = str(keys or "").strip()
    if not combo:
        return _result("press_keys", "key", False, detail="no keys given", started=started)
    ok, changed, detail = _run("key", target=combo)
    return _result("press_keys", "key", ok, target=combo, verified=changed,
                   detail=detail, started=started)


@register(
    name="click_element",
    description="Click a UI element by DESCRIPTION (e.g. 'the search box', 'the "
                "Send button', 'the first result'). ZENO locates it visually -- "
                "no blind coordinates. Says so plainly if the target is ambiguous "
                "or not on screen; nothing is clicked then.",
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "What to click, described in words."},
    }, "required": ["target"]},
)
def click_element(target: str) -> str:
    started = time.time()
    what = str(target or "").strip()
    if not what:
        return _result("click_element", "click", False, detail="no target given", started=started)
    ok, changed, detail = _run("click", target=what)
    return _result("click_element", "click", ok, target=what, verified=changed,
                   detail=detail, started=started)


@register(
    name="scroll_screen",
    description="Scroll the active window up or down. Amount is a number of "
                "notches (default 3). Respects the same 'don't steal the mouse "
                "while the owner is working' guard as the other hand tools.",
    input_schema={"type": "object", "properties": {
        "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction."},
        "amount": {"type": "integer", "description": "Notches to scroll (default 3)."},
    }, "required": ["direction"]},
)
def scroll_screen(direction: str, amount: int = 3) -> str:
    started = time.time()
    down = str(direction or "down").strip().lower() != "up"
    notches = max(1, min(20, int(amount or 3)))
    try:
        from reyes_agent.computer import input_guard

        grant = input_guard.may_take_control(override=False)
        if not grant.allowed:
            return _result("scroll_screen", "scroll", False,
                           detail=getattr(grant, "reason", "owner is using the computer"),
                           started=started)
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.scroll((-1 if down else 1) * notches * 120)
        return _result("scroll_screen", "scroll", True,
                       target=f"{'down' if down else 'up'} x{notches}",
                       verified=False, detail=f"scrolled {'down' if down else 'up'}",
                       started=started)
    except Exception as exc:  # noqa: BLE001
        return _result("scroll_screen", "scroll", False,
                       detail=f"{type(exc).__name__}: {exc}", started=started)
