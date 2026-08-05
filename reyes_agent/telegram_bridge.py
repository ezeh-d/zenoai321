"""Mobile front door: control REYES from Telegram on your phone.

Long-polls Telegram's getUpdates API and runs each message through the
exact same `agent.run_agent` the text/voice/web front doors use -- same
brain, same tools, same Tier 6 confirmation gate (a gated action queues
and tells you to approve it from the web panel, same as everywhere else).
Per-chat history, so your phone and anyone else messaging the bot don't
share state.

Gated by an allow-list (TELEGRAM_ALLOWED_CHAT_IDS in config.py), same
reasoning and shape as the Slack bridge's: knowing the bot's @handle and
being able to message it is not the same as being allowed to command it.
Unrecognized chats get a polite decline instead of a live agent turn.

Run: python -m reyes_agent.telegram_bridge
Setup: TELEGRAM_BOT_TOKEN must be set in .env (already is, reused from
earlier work on this project). Message your bot on Telegram to start --
then add your own chat ID to TELEGRAM_ALLOWED_CHAT_IDS in .env (the
decline reply tells you where to find it; comma-separate more IDs to let
someone else in too). Leave it blank and REYES stays online but won't act
on anyone -- fails closed.
"""

from __future__ import annotations

import time

import requests

from reyes_agent import audit, config, warmup
from reyes_agent.agent import run_agent
from reyes_agent.provider import ProviderError

_TELEGRAM_MAX_CHARS = 4000

_histories: dict[int, list[dict]] = {}

_DECLINE = (
    "I only take requests from my owner right now. If that should be you, "
    "add this chat's ID to TELEGRAM_ALLOWED_CHAT_IDS in .env -- find it at "
    "https://api.telegram.org/bot<token>/getUpdates under message.chat.id."
)


def _authorized(chat_id: int) -> bool:
    return chat_id in config.TELEGRAM_ALLOWED_CHAT_IDS


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _get_updates(token: str, offset: int) -> list[dict]:
    r = requests.get(
        _api(token, "getUpdates"), params={"offset": offset, "timeout": 25}, timeout=30
    )
    r.raise_for_status()
    return r.json()["result"]


def _send(token: str, chat_id: int, text: str) -> None:
    text = text or "(empty reply)"
    for i in range(0, len(text), _TELEGRAM_MAX_CHARS):
        chunk = text[i : i + _TELEGRAM_MAX_CHARS]
        try:
            requests.post(
                _api(token, "sendMessage"),
                json={"chat_id": chat_id, "text": chunk},
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"[couldn't send to {chat_id}: {exc}]")


def _handle_message(token: str, chat_id: int, text: str) -> None:
    history = _histories.setdefault(chat_id, [])
    turn_start = len(history)
    history.append({"role": "user", "content": text})

    tool_notes: list[str] = []

    def on_tool_call(name: str, tool_input: dict, _id: str) -> None:
        tool_notes.append(f"[using {name}]")

    try:
        run_agent(history, on_tool_call=on_tool_call)
        reply = history[-1]["content"]
    except ProviderError as exc:
        del history[turn_start:]
        reply = f"Sorry, I couldn't respond: {exc}"

    if tool_notes:
        reply = "\n".join(tool_notes) + "\n" + reply
    _send(token, chat_id, reply)


def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("No TELEGRAM_BOT_TOKEN set in .env -- can't start the Telegram bridge.")
        return

    me = requests.get(_api(token, "getMe"), timeout=15).json()
    if not me.get("ok"):
        print(f"Telegram rejected this token: {me}")
        return
    print(f"{config.ASSISTANT_NAME} Telegram bridge online as @{me['result']['username']}")

    if not config.TELEGRAM_ALLOWED_CHAT_IDS:
        print(
            "TELEGRAM_ALLOWED_CHAT_IDS is empty in .env -- REYES is online but won't "
            "act on messages from anyone yet (see this file's docstring)."
        )

    warmup.start_background_keepalive()

    offset = 0
    while True:
        try:
            updates = _get_updates(token, offset)
        except requests.RequestException as exc:
            print(f"[poll error: {exc}]")
            time.sleep(3)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or "text" not in message:
                continue
            text = message["text"].strip()
            if not text:
                continue
            chat_id = message["chat"]["id"]
            if not _authorized(chat_id):
                audit.log("telegram_unauthorized", chat_id=chat_id, text=text)
                _send(token, chat_id, _DECLINE)
                continue
            _handle_message(token, chat_id, text)


if __name__ == "__main__":
    main()
