"""Gmail read access over IMAP, using an App Password (never the real
account password -- see config.GMAIL_APP_PASSWORD).

Read-only by design right now: check, search, and read the inbox. It does
NOT send email -- sending on the user's behalf is a separate, heavier
decision (and would be confirmation-gated when built). Listing uses
BODY.PEEK so simply checking the inbox never marks the user's mail as
read behind their back.
"""

from __future__ import annotations

import email
import imaplib
from email.header import decode_header

from reyes_agent import config
from reyes_agent.tools import register

_IMAP_HOST = "imap.gmail.com"
_MAX_BODY_CHARS = 3000


def _connect() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(_IMAP_HOST)
    m.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    return m


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    out = ""
    for text, enc in decode_header(raw):
        if isinstance(text, bytes):
            out += text.decode(enc or "utf-8", errors="replace")
        else:
            out += text
    return out.strip()


def _plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            if part.get_content_type() == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


def _configured() -> bool:
    return bool(config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD)


@register(
    name="check_email",
    description=(
        "Check the Gmail inbox -- recent emails, unread only, or matching a "
        "search word (e.g. a company name or 'interview'). Returns sender, "
        "subject, and date for each. Read-only and does NOT mark anything "
        "read. Use for 'any new emails', 'check for job replies', etc."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional word/phrase to search for across emails."},
            "unread_only": {"type": "boolean", "description": "Only unread emails. Default false."},
            "limit": {"type": "integer", "description": "Max emails to return. Default 10."},
        },
    },
    light=True,
)
def check_email(query: str = "", unread_only: bool = False, limit: int = 10) -> str:
    if not _configured():
        return "Gmail isn't connected -- no GMAIL_ADDRESS/GMAIL_APP_PASSWORD set."
    try:
        limit = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        limit = 10
    try:
        m = _connect()
        m.select("INBOX")
        if query.strip():
            typ, data = m.search(None, "TEXT", query.strip())
        elif unread_only:
            typ, data = m.search(None, "UNSEEN")
        else:
            typ, data = m.search(None, "ALL")
        ids = data[0].split()[-limit:][::-1]  # most recent first
        lines = []
        for i in ids:
            typ, md = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not md or not md[0]:
                continue
            hdr = email.message_from_bytes(md[0][1])
            frm = _decode_header(hdr.get("From"))
            subj = _decode_header(hdr.get("Subject")) or "(no subject)"
            date = (hdr.get("Date") or "").strip()
            lines.append(f"- {subj}\n    from: {frm}  |  {date}")
        m.logout()
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't check email: {exc}"
    if not lines:
        return "No matching emails." if (query or unread_only) else "Inbox is empty."
    header = f"{len(lines)} email(s)"
    if query.strip():
        header += f" matching '{query.strip()}'"
    elif unread_only:
        header += " unread"
    return header + ":\n" + "\n".join(lines)


@register(
    name="read_email",
    description=(
        "Read the full text of a specific email, found by a word in its "
        "subject or sender (most recent match). Use after check_email when "
        "the user wants the actual contents of one email."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "match": {"type": "string", "description": "A word/phrase from the subject or sender to find the email."},
        },
        "required": ["match"],
    },
    light=True,
)
def read_email(match: str) -> str:
    if not _configured():
        return "Gmail isn't connected -- no GMAIL_ADDRESS/GMAIL_APP_PASSWORD set."
    try:
        m = _connect()
        m.select("INBOX")
        typ, data = m.search(None, "TEXT", match.strip())
        ids = data[0].split()
        if not ids:
            m.logout()
            return f"No email found matching '{match}'."
        typ, md = m.fetch(ids[-1], "(BODY.PEEK[])")
        msg = email.message_from_bytes(md[0][1])
        frm = _decode_header(msg.get("From"))
        subj = _decode_header(msg.get("Subject")) or "(no subject)"
        date = (msg.get("Date") or "").strip()
        body = _plain_body(msg).strip()
        m.logout()
    except Exception as exc:  # noqa: BLE001
        return f"Couldn't read the email: {exc}"
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n... [truncated]"
    return f"Subject: {subj}\nFrom: {frm}\nDate: {date}\n\n{body or '(no plain-text body)'}"
