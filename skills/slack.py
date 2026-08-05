"""Slack via the official Web API.

Setup:
  1. Create an app at https://api.slack.com/apps
  2. Add bot scopes: chat:write, channels:read, channels:history, im:write, users:read
  3. Install to your workspace, copy the "Bot User OAuth Token" (xoxb-...)
  4. Put it in .env as SLACK_BOT_TOKEN
  5. Invite the bot to any channel you want it to post in (/invite @yourbot)
"""
from __future__ import annotations

from config import settings

_BASE = "https://slack.com/api"


class Slack:
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.slack_bot_token}"}

    def _ready(self) -> str | None:
        if not settings.slack_bot_token:
            return "Slack not configured. Set SLACK_BOT_TOKEN (xoxb-...) in .env."
        return None

    def slack_channels(self) -> str:
        err = self._ready()
        if err:
            return err
        try:
            import requests

            r = requests.get(
                f"{_BASE}/conversations.list",
                headers=self._headers(),
                params={"limit": 100, "types": "public_channel,private_channel"},
                timeout=15,
            )
            data = r.json()
            if not data.get("ok"):
                return f"Slack error: {data.get('error')}"
            chans = data.get("channels", [])
            return "\n".join(f"#{c['name']}  (id: {c['id']})" for c in chans) or "No channels."
        except Exception as e:  # noqa: BLE001
            return f"Error listing channels: {e}"

    def slack_send(self, channel: str, text: str) -> str:
        """channel can be a channel ID (C…) or a #name that you pass as its ID."""
        err = self._ready()
        if err:
            return err
        try:
            import requests

            r = requests.post(
                f"{_BASE}/chat.postMessage",
                headers=self._headers(),
                json={"channel": channel, "text": text},
                timeout=15,
            )
            data = r.json()
            return "Slack message sent." if data.get("ok") else f"Slack error: {data.get('error')}"
        except Exception as e:  # noqa: BLE001
            return f"Error sending Slack message: {e}"

    def slack_read(self, channel: str, limit: int = 10) -> str:
        err = self._ready()
        if err:
            return err
        try:
            import requests

            r = requests.get(
                f"{_BASE}/conversations.history",
                headers=self._headers(),
                params={"channel": channel, "limit": limit},
                timeout=15,
            )
            data = r.json()
            if not data.get("ok"):
                return f"Slack error: {data.get('error')}"
            msgs = data.get("messages", [])
            lines = [m.get("text", "") for m in msgs if m.get("text")]
            return "\n---\n".join(reversed(lines)) if lines else "No messages."
        except Exception as e:  # noqa: BLE001
            return f"Error reading Slack: {e}"
