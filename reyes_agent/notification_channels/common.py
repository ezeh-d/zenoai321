from __future__ import annotations

import urllib.parse

from reyes_agent.security.privacy.redactor import EXTERNAL_API, redact


SEVERITIES = {"INFO", "SUCCESS", "WARNING", "ERROR", "APPROVAL_REQUIRED"}


def safe_payload(title: str, summary: str, severity: str, source: str, task_id: str = "") -> dict:
    level = str(severity or "INFO").upper()
    if level not in SEVERITIES:
        level = "INFO"
    # Push is for a bounded summary, never a second copy of a private message.
    clean_title = redact(str(title)[:120], destination=EXTERNAL_API).text
    clean_summary = redact(str(summary)[:500], destination=EXTERNAL_API).text
    return {"title": clean_title, "summary": clean_summary, "severity": level,
            "source": str(source or "zeno")[:80], "task_id": str(task_id or "")[:80]}


def valid_endpoint(url: str, *, allow_path: bool = True) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return True, ""
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return True, ""
    return False, "push endpoints must use HTTPS (loopback HTTP is allowed for local testing)"
