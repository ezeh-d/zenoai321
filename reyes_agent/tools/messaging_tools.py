"""The messaging capability, exposed to ZENO.

    "ZENO currently reports that it does not have a messaging tool."

It does now. One tool sends, one drafts without sending, one plans a compound
sentence, one reports platform state.

ON CONFIRMATION: "send good night to General" IS the authorisation for that
message -- asking "are you sure" afterwards is noise the owner explicitly
does not want. What DOES stop and ask is genuine ambiguity: two channels
called General, or a destination that cannot be found. That distinction is
enforced by the router returning AMBIGUOUS rather than picking one.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register
from reyes_agent.tools.messaging import intent, models, router


@register(name="send_message",
          description=("Send a real message through a desktop chat app: "
                       "Slack, WhatsApp, Telegram or Discord. Opens or "
                       "focuses the app, navigates to the destination, types "
                       "and sends, then VERIFIES the message appeared. "
                       "Destination can be a channel, group, contact or DM in "
                       "any language -- or a bare follow-up reference such as "
                       "'him'/'her'/'them' (or omitted) to mean 'the person I "
                       "was just messaging on this platform'; that still "
                       "opens, navigates to, and verifies the resolved name "
                       "fresh, so it never sends to the wrong chat. Returns "
                       "SENT only after verification."),
          input_schema={"type": "object", "properties": {
              "platform": {"type": "string",
                           "enum": list(models.PLATFORMS)},
              "destination": {"type": "string",
                              "description": "Channel, group or person name, "
                                             "exactly as the owner said it -- "
                                             "or 'him'/'her'/'them' for a "
                                             "follow-up to the last person "
                                             "messaged on this platform."},
              "message": {"type": "string"},
              "destination_type": {"type": "string",
                                   "enum": [models.CHANNEL, models.GROUP,
                                            models.DM, models.CONTACT,
                                            models.THREAD]},
              "account": {"type": "string"}},
              "required": ["platform", "destination", "message"]})
def send_message(platform: str, destination: str, message: str,
                 destination_type: str = "", account: str = "") -> str:
    from reyes_agent.tools.messaging.context import get_context

    ctx = get_context()
    resolution = ctx.resolve(platform, destination)
    if not resolution.ok:
        return json.dumps({"status": "NEEDS_CLARIFICATION", "detail": resolution.reason,
                           "spoken": f"Who do you mean? {resolution.reason}."}, default=str)
    resolved_type = destination_type or resolution.destination_type
    result = router.send(models.SendRequest(
        platform=(platform or "").strip().lower(), destination=resolution.destination,
        message=message, destination_type=resolved_type, account=account,
        send=True))
    if result.status == models.SENT:
        # Record only a VERIFIED destination -- never a guess, and never one
        # that only got as far as TYPED/SEND_UNVERIFIED/failed.
        ctx.record(result.platform, result.destination, resolved_type)
    return json.dumps(result.as_dict(), default=str)


@register(name="type_message",
          description=("Type a message into a chat app's composer WITHOUT "
                       "sending it. Use for 'draft this', 'type it but don't "
                       "send'. The message is left for the owner to send."),
          input_schema={"type": "object", "properties": {
              "platform": {"type": "string", "enum": list(models.PLATFORMS)},
              "destination": {"type": "string"},
              "message": {"type": "string"},
              "destination_type": {"type": "string"}},
              "required": ["platform", "destination", "message"]})
def type_message(platform: str, destination: str, message: str,
                 destination_type: str = "") -> str:
    from reyes_agent.tools.messaging.context import get_context

    resolution = get_context().resolve(platform, destination)
    if not resolution.ok:
        return json.dumps({"status": "NEEDS_CLARIFICATION", "detail": resolution.reason,
                           "spoken": f"Who do you mean? {resolution.reason}."}, default=str)
    result = router.send(models.SendRequest(
        platform=(platform or "").strip().lower(), destination=resolution.destination,
        message=message, destination_type=destination_type or resolution.destination_type,
        send=False))
    return json.dumps(result.as_dict(), default=str)


@register(name="plan_message_request",
          description=("Decompose one compound sentence such as 'open Slack, "
                       "go to General and send good night' into ordered "
                       "messaging steps. Use when unsure how to split a "
                       "request; the parse is best-effort and reports whether "
                       "it is confident."),
          input_schema={"type": "object", "properties": {
              "request": {"type": "string"},
              "default_platform": {"type": "string"}},
              "required": ["request"]})
def plan_message_request(request: str, default_platform: str = "") -> str:
    return json.dumps(intent.plan(request, default_platform=default_platform),
                      default=str)


@register(name="messaging_status",
          description=("Report which chat apps ZENO can drive on this "
                       "computer, and whether each is running."),
          input_schema={"type": "object", "properties": {}})
def messaging_status() -> str:
    from reyes_agent.tools.messaging.context import get_context

    status = router.status()
    status["last_destination"] = get_context().snapshot()
    return json.dumps(status, default=str)
