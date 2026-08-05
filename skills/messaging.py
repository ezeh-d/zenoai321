"""Send & receive messages.

Wired and working out of the box:
  - Email  (any provider via SMTP/IMAP — Python stdlib, no extra install)
  - Telegram (Bot API over HTTP)

To add WhatsApp, Discord, Slack, etc. later: write a small adapter class with
send()/read() and register it in Brain the same way. The pattern is identical.
"""
from __future__ import annotations

import email
import imaplib
import smtplib
from email.mime.text import MIMEText

from config import settings


class Messaging:
    # ---------------- EMAIL ----------------
    def send_email(self, to: str, subject: str, body: str) -> str:
        if not (settings.smtp_host and settings.email_address and settings.email_password):
            return "Email not configured. Set SMTP_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD in .env."
        try:
            msg = MIMEText(body, _charset="utf-8")
            msg["Subject"] = subject
            msg["From"] = settings.email_address
            msg["To"] = to
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.email_address, settings.email_password)
                server.send_message(msg)
            return f"Email sent to {to}."
        except Exception as e:  # noqa: BLE001
            return f"Error sending email: {e}"

    def read_email(self, limit: int = 5, unread_only: bool = True) -> str:
        if not (settings.imap_host and settings.email_address and settings.email_password):
            return "Email reading not configured. Set IMAP_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD in .env."
        try:
            box = imaplib.IMAP4_SSL(settings.imap_host)
            box.login(settings.email_address, settings.email_password)
            box.select("INBOX")
            criterion = "UNSEEN" if unread_only else "ALL"
            _typ, data = box.search(None, criterion)
            ids = data[0].split()[-limit:]
            out = []
            for msg_id in reversed(ids):
                _typ, raw = box.fetch(msg_id, "(RFC822)")
                m = email.message_from_bytes(raw[0][1])
                subject = m.get("Subject", "(no subject)")
                sender = m.get("From", "(unknown)")
                out.append(f"From: {sender}\nSubject: {subject}")
            box.logout()
            return "\n\n".join(out) if out else "No messages found."
        except Exception as e:  # noqa: BLE001
            return f"Error reading email: {e}"

    # ---------------- TELEGRAM ----------------
    def send_telegram(self, text: str, chat_id: str | None = None) -> str:
        if not settings.telegram_bot_token:
            return "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env."
        chat_id = chat_id or settings.telegram_chat_id
        if not chat_id:
            return "No chat_id. Set TELEGRAM_CHAT_ID in .env or pass one."
        try:
            import requests

            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
            r.raise_for_status()
            return "Telegram message sent."
        except Exception as e:  # noqa: BLE001
            return f"Error sending Telegram message: {e}"

    def read_telegram(self, limit: int = 5) -> str:
        if not settings.telegram_bot_token:
            return "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env."
        try:
            import requests

            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            updates = r.json().get("result", [])[-limit:]
            out = []
            for u in updates:
                msg = u.get("message", {})
                who = msg.get("from", {}).get("first_name", "?")
                txt = msg.get("text", "")
                if txt:
                    out.append(f"{who}: {txt}")
            return "\n".join(out) if out else "No recent Telegram messages."
        except Exception as e:  # noqa: BLE001
            return f"Error reading Telegram: {e}"
