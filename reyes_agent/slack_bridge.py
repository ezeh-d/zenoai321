"""Team front door: control REYES from Slack.

Same `agent.run_agent` core as every other front door, per-channel history
(DMs and @-mentions get their own conversation, same as Telegram gets
per-chat). Uses Slack's Socket Mode -- no public URL/webhook needed, same
reason Telegram uses long-polling instead of a webhook: this runs on your
own machine, not a reachable server.

Gated by an allow-list (SLACK_ALLOWED_USER_IDS in config.py): being in the
workspace and able to DM or @-mention the bot is not the same as being
allowed to command it. Unrecognized users get a polite decline instead of
a live agent turn -- see step 7 below.

Setup (interactive -- only you can do this part, it's your Slack account):
1. Create an app at https://api.slack.com/apps -- "From scratch", pick
   your workspace.
2. Settings -> Socket Mode: turn it on. Generate an App-Level Token with
   the `connections:write` scope (this is SLACK_APP_TOKEN, starts `xapp-`).
3. Features -> OAuth & Permissions -> Bot Token Scopes, add:
   `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`.
4. Features -> Event Subscriptions: turn on, subscribe to bot events
   `message.im` and `app_mention`.
5. Install the app to your workspace (Settings -> Install App). Copy the
   Bot User OAuth Token (SLACK_BOT_TOKEN, starts `xoxb-`).
6. Put both in .env:
     SLACK_BOT_TOKEN=xoxb-...
     SLACK_APP_TOKEN=xapp-...
7. Access control -- run the bridge once and DM the bot anything. It'll
   decline and (since you're the one testing) that decline also lands in
   the audit log (REYES/07-System/logs/audit.log) with your Slack user
   ID attached, or just grab it straight from Slack: profile -> More ->
   Copy member ID. Then add it to .env:
     SLACK_ALLOWED_USER_IDS=U0123ABC
   Comma-separate more IDs to let teammates in too. Leave it blank and
   REYES stays connected but won't act on anyone -- fails closed.

Run: python -m reyes_agent.slack_bridge
"""

from __future__ import annotations

from reyes_agent import audit, config, warmup
from reyes_agent.agent import run_agent
from reyes_agent.provider import ProviderError

_histories: dict[str, list[dict]] = {}

_DECLINE = (
    "I only take requests from my owner right now. If that should be you, "
    "add your Slack user ID to SLACK_ALLOWED_USER_IDS in .env (see this "
    "file's docstring, step 7)."
)


def _authorized(user_id: str | None) -> bool:
    return bool(user_id) and user_id in config.SLACK_ALLOWED_USER_IDS


def _handle(channel_id: str, text: str, say) -> None:
    text = text.strip()
    if not text:
        return

    history = _histories.setdefault(channel_id, [])
    turn_start = len(history)
    history.append({"role": "user", "content": text})

    tool_notes: list[str] = []

    def on_tool_call(name: str, _tool_input: dict, _id: str) -> None:
        tool_notes.append(f"_using {name}_")

    try:
        run_agent(history, on_tool_call=on_tool_call)
        reply = history[-1]["content"]
    except ProviderError as exc:
        del history[turn_start:]
        reply = f"Sorry, I couldn't respond: {exc}"

    if tool_notes:
        reply = "\n".join(tool_notes) + "\n" + reply
    say(reply or "(no reply)")


def main() -> None:
    if not config.SLACK_BOT_TOKEN or not config.SLACK_APP_TOKEN:
        print(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must both be set in .env -- "
            "see reyes_agent/slack_bridge.py's docstring for the setup steps "
            "(you need to create a Slack app yourself, this can't be done for you)."
        )
        return

    if not config.SLACK_ALLOWED_USER_IDS:
        print(
            "SLACK_ALLOWED_USER_IDS is empty in .env -- REYES will connect but won't "
            "act on messages from anyone yet (see step 7 in this file's docstring)."
        )

    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=config.SLACK_BOT_TOKEN)

    @app.event("message")
    def on_message(event: dict, say) -> None:
        # Only DMs -- if REYES gets added to a regular channel, it should
        # not reply to every message in it, only when spoken to directly.
        if event.get("channel_type") != "im" or event.get("bot_id"):
            return
        if not _authorized(event.get("user")):
            audit.log("slack_unauthorized", user=event.get("user"), channel=event["channel"])
            say(_DECLINE)
            return
        _handle(event["channel"], event.get("text", ""), say)

    @app.event("app_mention")
    def on_mention(event: dict, say) -> None:
        if not _authorized(event.get("user")):
            audit.log("slack_unauthorized", user=event.get("user"), channel=event["channel"])
            say(_DECLINE)
            return
        # Strip the leading @REYES mention token, keep the rest as the message.
        text = " ".join(w for w in event.get("text", "").split() if not w.startswith("<@"))
        _handle(event["channel"], text, say)

    warmup.start_background_keepalive()
    print(f"{config.ASSISTANT_NAME} Slack bridge connecting...")
    SocketModeHandler(app, config.SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()
