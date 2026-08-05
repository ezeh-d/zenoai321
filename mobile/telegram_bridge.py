"""
Telegram bridge — control REYES from your phone.

Uses the TELEGRAM_BOT_TOKEN already in your .env. Long-polls for messages,
runs each through the shared brain, and replies. Create a bot with @BotFather,
put the token in .env, then run:  python -m mobile.telegram_bridge
"""
from __future__ import annotations

import time

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    try:
        from config import settings
        return settings.telegram_bot_token
    except Exception:
        return None


def _call(token: str, method: str, **params):
    import requests  # lazy; in requirements
    url = API.format(token=token, method=method)
    r = requests.get(url, params=params, timeout=35)
    r.raise_for_status()
    return r.json()


def run() -> None:
    token = _token()
    if not token:
        print("No TELEGRAM_BOT_TOKEN in .env — set it to use the Telegram bridge.")
        return

    from brain import think  # shared JARVIS brain

    print("REYES Telegram bridge running. Message your bot from your phone.")
    offset = None
    while True:
        try:
            updates = _call(token, "getUpdates", timeout=30, offset=offset)
        except Exception as e:
            print(f"[telegram] poll error: {e}; retrying...")
            time.sleep(3)
            continue

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = (msg.get("chat") or {}).get("id")
            if not text or chat_id is None:
                continue
            try:
                reply = think(text)
            except Exception as e:
                reply = f"[REYES error: {e}]"
            try:
                _call(token, "sendMessage", chat_id=chat_id, text=reply[:4000])
            except Exception as e:
                print(f"[telegram] send error: {e}")


if __name__ == "__main__":
    run()
