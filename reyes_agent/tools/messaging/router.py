"""One entry point; the platform decides only which adapter runs.

    "Do NOT put every platform's logic inside brain.py."

The router owns the SEQUENCE -- open, navigate, compose, send, verify -- and
each adapter owns only what that means on its own client. That is why adding
Signal or Teams later is a new module rather than an edit to the brain.

CANCELLATION
------------
The owner can say "stop" mid-flight. The check happens before each
irreversible step, and the last irreversible step is the Enter key: once a
message is submitted it cannot be recalled by pretending it was not.
"""

from __future__ import annotations

import threading
from typing import Any

from reyes_agent.tools.messaging import desktop, models

_cancel = threading.Event()


def request_stop() -> None:
    """Ask an in-flight send to abort. Safe to call from any thread."""
    _cancel.set()


def clear_stop() -> None:
    _cancel.clear()


def _adapter(platform: str):
    from reyes_agent.tools.messaging import discord, slack, telegram, whatsapp

    return {models.SLACK: slack, models.WHATSAPP: whatsapp,
            models.TELEGRAM: telegram, models.DISCORD: discord}.get(platform)


def send(request: models.SendRequest) -> models.SendResult:
    """Open the app, reach the destination, and send -- verifying each stage."""
    clear_stop()
    trace = desktop.Trace()
    result = models.SendResult(platform=request.platform,
                               destination=request.destination,
                               message=request.message)

    adapter = _adapter(request.platform)
    if adapter is None:
        result.status = models.SEND_FAILED
        result.failing_step = "platform"
        result.detail = (f"I have no adapter for '{request.platform}'. "
                         f"I support: {', '.join(models.PLATFORMS)}.")
        return result

    ready, detail = desktop.available()
    if not ready:
        result.status = models.SEND_FAILED
        result.failing_step = "automation"
        result.detail = f"Desktop automation is unavailable ({detail})."
        return result

    if not request.message.strip():
        result.status = models.SEND_FAILED
        result.failing_step = "message"
        result.detail = "There was no message text to send."
        return result

    # 1. OPEN_APP -- focuses an existing window rather than launching twice.
    handle, _title = adapter.open_slack(trace) if hasattr(adapter, "open_slack") \
        else adapter.open_app(trace)
    if not handle:
        result.status = models.APP_NOT_FOUND
        result.failing_step = trace.failing or "open_app"
        result.detail = _last_detail(trace)
        result.steps = trace.as_list()
        return result

    # 2. Refuse to type into an app that cannot deliver. Checked BEFORE
    #    composing, so a logged-out client never receives keystrokes.
    state = adapter.check_state(handle, trace)
    if state:
        result.status = state
        result.failing_step = trace.failing
        result.detail = _last_detail(trace)
        result.steps = trace.as_list()
        return result

    if _cancel.is_set():
        return _cancelled(result, trace)

    # 3. FIND + OPEN the destination, then confirm it really opened.
    opened, label, candidates = adapter.open_destination(
        handle, request.destination, trace)
    if not opened:
        result.status = (models.AMBIGUOUS if len(candidates) > 1
                         else models.DESTINATION_NOT_FOUND)
        result.candidates = candidates
        result.failing_step = trace.failing or "open_destination"
        result.detail = _last_detail(trace)
        result.steps = trace.as_list()
        return result
    if label:
        result.destination = label

    if _cancel.is_set():
        return _cancelled(result, trace)

    # 4. Compose.
    if not adapter.compose(handle, request.message, trace):
        result.status = models.SEND_FAILED
        result.failing_step = trace.failing or "compose"
        result.detail = _last_detail(trace)
        result.steps = trace.as_list()
        return result

    # TYPE and SEND are different actions. A draft stops here, deliberately.
    if not request.send:
        result.status = models.TYPED
        result.verified = True
        result.steps = trace.as_list()
        return result

    # Last chance to stop -- after this the message is out in the world.
    if _cancel.is_set():
        return _cancelled(result, trace)

    # 5. Send, then VERIFY. Enter alone is not evidence.
    status, verified, detail = adapter.send(handle, request.message, trace)
    result.status, result.verified, result.detail = status, verified, detail
    result.failing_step = "" if status == models.SENT else (trace.failing or "verify")
    result.steps = trace.as_list()
    return result


def _cancelled(result: models.SendResult, trace: desktop.Trace) -> models.SendResult:
    trace.add("cancelled", True, "the owner said stop before sending")
    result.status = models.CANCELLED
    result.steps = trace.as_list()
    return result


def _last_detail(trace: desktop.Trace) -> str:
    for step in reversed(trace.steps):
        if not step.ok and step.detail:
            return step.detail
    return trace.steps[-1].detail if trace.steps else ""


def status() -> dict[str, Any]:
    from reyes_agent.tools.messaging import discord, slack, telegram, whatsapp

    ready, detail = desktop.available()
    return {
        "state": "ONLINE" if ready else "UNAVAILABLE",
        "automation": detail,
        "platforms": {models.SLACK: slack.status(),
                      models.WHATSAPP: whatsapp.status(),
                      models.TELEGRAM: telegram.status(),
                      models.DISCORD: discord.status()},
        "verifies": ("a message counts as SENT only when it is found in the "
                     "conversation -- pressing Enter is not evidence"),
        "cancellable": "until the moment of submission",
    }
