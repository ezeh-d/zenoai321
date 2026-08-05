"""
Defensive security tools. Safe, local, and non-destructive.

Everything here operates on THIS machine or files you point it at — the work a
blue-team / defender actually does: audit your own exposure and harden it.
"""
from __future__ import annotations

import hashlib
import re
import socket
from pathlib import Path


def passcheck(password: str) -> str:
    """Rate a password's strength locally (nothing leaves the machine)."""
    if not password:
        return "Give me a password to check."
    score, notes = 0, []
    if len(password) >= 16:
        score += 3
    elif len(password) >= 12:
        score += 2
    elif len(password) >= 8:
        score += 1
    else:
        notes.append("too short (<8)")
    if re.search(r"[a-z]", password):
        score += 1
    if re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"\d", password):
        score += 1
    if re.search(r"[^\w]", password):
        score += 1
    else:
        notes.append("no symbols")
    if password.lower() in {"password", "123456", "qwerty", "letmein", "admin", "welcome"}:
        score, notes = 0, ["this is a top-10 breached password"]
    verdict = ["Very weak", "Weak", "Fair", "Good", "Strong", "Very strong", "Excellent"][min(score, 6)]
    tail = " — " + "; ".join(notes) if notes else ""
    return f"Strength: {verdict} ({score}/7){tail}"


def hash_file(path: str, algo: str = "sha256") -> str:
    """Integrity hash of a file."""
    p = Path(path).expanduser()
    if not p.is_file():
        return f"No such file: {p}"
    try:
        h = hashlib.new(algo)
    except ValueError:
        return f"Unknown algorithm '{algo}'. Try sha256, sha1, md5."
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"{algo}({p.name}) = {h.hexdigest()}"


def scan_ports(start: int = 1, end: int = 1024, host: str = "127.0.0.1") -> str:
    """List open TCP ports on the local machine so you can spot exposure."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        return ("For safety this only scans your own machine (localhost). "
                "Scanning other hosts requires their explicit authorization.")
    open_ports = []
    for port in range(start, end + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.04)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                open_ports.append(port)
        except OSError:
            pass
        finally:
            s.close()
    if not open_ports:
        return f"No open ports on localhost in {start}-{end}."
    return (f"Open ports on localhost ({start}-{end}): "
            + ", ".join(map(str, open_ports))
            + "\nReview anything you don't recognize.")


_SUSPICIOUS = [
    r"failed password", r"authentication failure", r"invalid user",
    r"error 500", r"sql syntax", r"union\s+select", r"\.\./\.\./",
    r"sudo:.*COMMAND", r"segfault", r"permission denied",
]


def scan_log(path: str) -> str:
    """Flag suspicious lines in a log for a human to review."""
    p = Path(path).expanduser()
    if not p.is_file():
        return f"No such file: {p}"
    pattern = re.compile("|".join(_SUSPICIOUS), re.IGNORECASE)
    hits = []
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    hits.append(f"  L{i}: {line.strip()[:120]}")
                if len(hits) >= 50:
                    hits.append("  ... (stopped at 50 matches)")
                    break
    except OSError as e:
        return f"Could not read file: {e}"
    if not hits:
        return "No suspicious patterns found (that this checks for)."
    return f"Flagged {len(hits)} line(s):\n" + "\n".join(hits)
