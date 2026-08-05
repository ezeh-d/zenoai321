"""Background job-email watcher: checks Gmail every few minutes and
announces ONLY genuinely job-related mail (application updates, interview
invites, recruiters) -- not newsletters or noise.

Dedicated background service (like notification_listener), not an
agent-turn scheduled check -- so it costs no model calls per poll and is
reliable. Baselines existing mail on first run so it never announces the
old backlog; tracks seen Message-IDs so nothing gets announced twice;
respects quiet hours and the heartbeat kill switch.
"""

from __future__ import annotations

import email
import sqlite3
import threading
import time

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_CHECK_INTERVAL_S = 300  # 5 minutes
_SCAN_RECENT = 25        # newest N messages scanned each poll

# Targeted so newsletters/sales don't trip it -- real job-reply signals in
# the subject, plus sender domains that mean "a jobs/recruiting system".
_JOB_SUBJECT_HINTS = (
    "application", "applied", "interview", "shortlist", "shortlisted",
    "vacancy", "vacancies", "recruitment", "recruiter", "job offer",
    "your candidacy", "hiring", "position you applied", "assessment",
    "your job", "interview invitation", "application update",
    "thank you for applying", "we received your application", "jobs.nhs",
)
_JOB_SENDER_HINTS = (
    "jobs", "recruit", "nhs", "trac", "workday", "greenhouse", "lever",
    "indeed", "no-reply@jobs", "careers", "talent",
)


def _connect_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen_job_emails (msgid TEXT PRIMARY KEY)")
    return conn


def _seen(msgid: str) -> bool:
    with _connect_db() as conn:
        return conn.execute("SELECT 1 FROM seen_job_emails WHERE msgid = ?", (msgid,)).fetchone() is not None


def _mark(msgid: str) -> None:
    with _connect_db() as conn:
        conn.execute("INSERT OR IGNORE INTO seen_job_emails (msgid) VALUES (?)", (msgid,))


def _is_job_related(subject: str, sender: str) -> bool:
    subj = subject.lower()
    frm = sender.lower()
    if any(h in subj for h in _JOB_SUBJECT_HINTS):
        return True
    return any(h in frm for h in _JOB_SENDER_HINTS)


def _scan_headers(mark_only: bool, speak_fn) -> None:
    """One pass over recent mail. mark_only=True is the first-run baseline
    (record everything, announce nothing)."""
    from reyes_agent import heartbeat
    from reyes_agent.tools import email_tools

    if not (config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD):
        return

    m = email_tools._connect()
    try:
        m.select("INBOX")
        typ, data = m.search(None, "ALL")
        scan_n = 50 if mark_only else _SCAN_RECENT
        ids = data[0].split()[-scan_n:]
        for i in ids:
            typ, md = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
            if not md or not md[0]:
                continue
            hdr = email.message_from_bytes(md[0][1])
            msgid = (hdr.get("Message-ID") or f"noid-{i.decode(errors='replace')}").strip()
            if _seen(msgid):
                continue
            subject = email_tools._decode_header(hdr.get("Subject")) or "(no subject)"
            sender = email_tools._decode_header(hdr.get("From"))
            _mark(msgid)  # mark every scanned message so we don't re-inspect it
            if mark_only:
                continue
            if _is_job_related(subject, sender):
                note = f"Job email: {subject} -- from {sender}"
                heartbeat._add_notice("job-email", note)
                if not heartbeat._in_quiet_hours():
                    speak_fn(f"New job-related email. {subject}. From {sender}.")
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def _speak(text: str) -> None:
    from reyes_agent.voice.tts import TTSError, speak

    try:
        speak(text, threading.Event())
    except TTSError:
        pass


def _baseline() -> None:
    _scan_headers(mark_only=True, speak_fn=_speak)


def _tick() -> None:
    from reyes_agent import heartbeat

    if not heartbeat.is_killed():
        _scan_headers(mark_only=False, speak_fn=_speak)


def start_background() -> None:
    if not (config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD):
        return  # nothing to watch without Gmail configured
    from reyes_agent.scheduler import get_scheduler

    scheduler = get_scheduler()
    scheduler.schedule("email-watcher-baseline", _baseline, delay=5.0, priority=80, timeout=90)
    scheduler.schedule(
        "email-watcher", _tick, delay=_CHECK_INTERVAL_S, interval=_CHECK_INTERVAL_S,
        priority=80, timeout=90,
    )
