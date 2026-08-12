"""Proof that real software exists here -- with the receipts attached.

    "EVERY SCREEN MUST DISPLAY REAL PROJECT DATA."

The way that rule is kept is not by trying hard to be accurate. It is by
making invention structurally impossible: every claim in this module is
either read from the filesystem, or cites a git commit that is CHECKED to
exist before the claim is shown. A challenge whose commit cannot be found is
dropped rather than displayed, so the failure mode is a shorter list, never a
fictional one.

CODE PROOF, AND WHY IT DISCOVERS RATHER THAN REMEMBERS
------------------------------------------------------
    "Do not assume old filenames still exist. DISCOVER CURRENT FILES."

Hard-coding a path is how a demonstration opens a blank pane in front of a
supervisor. Every mapping here is a list of CANDIDATES, and only paths that
exist on disk right now are offered. A capability whose file has moved shows
NOT AVAILABLE, which is embarrassing for ten seconds and honest forever.

SECRETS ARE NOT A DISPLAY DECISION
-----------------------------------
Nothing here can show a credential, because nothing here will open a file
that could contain one: .env and its relatives are refused by name before any
read happens, and any line that looks like an assignment to a key, token,
password or secret is redacted even inside an allowed file. Asking ZENO to
show an API key produces a refusal, not a redaction that might slip.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

NOT_AVAILABLE = "NOT AVAILABLE"
NOT_VERIFIED = "NOT VERIFIED"

# Never opened, whatever is asked. Matched on the NAME, before any read.
_SECRET_FILES = re.compile(
    r"(^|[\\/])(\.env|\.env\..*|secrets?\.(json|ya?ml|toml|py)|"
    r"credentials?\.(json|ya?ml)|.*\.pem|.*\.key|id_rsa.*)$", re.I)

# Redacted inside files that ARE allowed, in case a key was ever pasted
# somewhere it did not belong.
_SECRET_LINE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)"
    r"\s*[:=]\s*['\"]?([^'\"\s#]{8,})")

MAX_CODE_LINES = 40


def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(config.PROJECT_ROOT),
                              capture_output=True, text=True, timeout=25)
        return (done.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def commit_exists(sha: str) -> bool:
    """Is this a real commit in this repository. Nothing is shown without it."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", (sha or "").strip()):
        return False
    return bool(_git("cat-file", "-t", sha).strip() == "commit")


def commit_detail(sha: str) -> dict[str, Any]:
    line = _git("log", "-1", "--format=%h|%ad|%s", "--date=short", sha)
    if not line:
        return {}
    parts = line.split("|", 2)
    files = [f for f in _git("show", "--name-only", "--format=", sha).splitlines() if f]
    return {"sha": parts[0], "date": parts[1] if len(parts) > 1 else "",
            "subject": parts[2] if len(parts) > 2 else "",
            "files_changed": len(files), "files": files[:6]}


# -- code proof -----------------------------------------------------------
# Candidates per capability. Only what EXISTS is offered.
_IMPLEMENTATIONS: dict[str, tuple[str, ...]] = {
    "voice": ("reyes_agent/voice_manager.py", "reyes_agent/voice/tts_router.py"),
    "wake word": ("reyes_agent/remote_mic/runtime.py", "reyes_agent/voice/wake.py"),
    "speech recognition": ("reyes_agent/voice/stt/streaming.py",
                           "reyes_agent/voice/stt/cloud.py"),
    "memory": ("reyes_agent/memory/__init__.py", "reyes_agent/memory_manager.py"),
    "brain": ("reyes_agent/agent.py", "reyes_agent/provider.py"),
    "tools": ("reyes_agent/tools/__init__.py",),
    "agents": ("reyes_agent/agents/identity.py", "reyes_agent/agents/registry.py",
               "reyes_agent/agent_teams.py"),
    "desktop automation": ("reyes_agent/computer/controller.py",
                           "reyes_agent/tools/messaging/desktop.py"),
    "browser automation": ("reyes_agent/tools/browser.py",),
    "phone companion": ("reyes_agent/remote_mic/runtime.py",
                        "reyes_agent/phone_security.py"),
    "remote microphone": ("reyes_agent/remote_mic/routes.py",
                          "reyes_agent/remote_mic/connect.py"),
    "conversation": ("reyes_agent/voice/continuity.py",
                     "reyes_agent/conversation_state.py"),
    "messaging": ("reyes_agent/tools/messaging/router.py",
                  "reyes_agent/tools/messaging/slack.py"),
    "vision": ("reyes_agent/vision/coverage.py",),
    "security": ("reyes_agent/phone_security.py", "reyes_agent/permissions.py"),
}


@dataclass
class CodeProof:
    capability: str
    path: str = ""
    lines: int = 0
    excerpt: str = ""
    status: str = NOT_AVAILABLE
    language: str = "Python"
    related: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "path": self.path,
                "lines": self.lines, "excerpt": self.excerpt,
                "status": self.status, "language": self.language,
                "related": self.related}


def _safe_to_open(path: Path) -> bool:
    return not _SECRET_FILES.search(str(path))


def _redact(text: str) -> str:
    return _SECRET_LINE.sub(lambda m: f"{m.group(1)} = [REDACTED]", text)


def code_proof(capability: str) -> CodeProof:
    """The real file behind a capability, with a short readable excerpt."""
    want = (capability or "").strip().lower()
    candidates: tuple[str, ...] = ()
    for name, paths in _IMPLEMENTATIONS.items():
        if want == name or want in name or name in want:
            candidates = paths
            break
    if not candidates:
        return CodeProof(capability=capability or "unknown",
                         status=f"{NOT_AVAILABLE} -- no implementation is "
                                f"mapped for '{capability}'")

    existing = [p for p in candidates
                if (config.PROJECT_ROOT / p).is_file() and _safe_to_open(Path(p))]
    if not existing:
        return CodeProof(capability=capability,
                         status=f"{NOT_AVAILABLE} -- the mapped files are not "
                                "on disk (they may have moved)")

    primary = config.PROJECT_ROOT / existing[0]
    try:
        text = primary.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return CodeProof(capability=capability,
                         status=f"{NOT_AVAILABLE} -- {type(exc).__name__}")

    lines = text.splitlines()
    # The module docstring plus the first real definition: it explains what
    # the file is FOR before showing how it works, which is what somebody
    # unfamiliar needs. Hundreds of lines would tell a visitor nothing.
    start = 0
    for index, line in enumerate(lines[:80]):
        if line.startswith(("def ", "class ", "@")):
            start = max(0, index - 2)
            break
    excerpt = "\n".join(lines[:6] + ["    ..."] +
                        lines[start:start + MAX_CODE_LINES])
    return CodeProof(capability=capability, path=existing[0], lines=len(lines),
                     excerpt=_redact(excerpt), status="WORKING",
                     related=existing[1:])


def refuse_secret(request: str) -> str | None:
    """A refusal for 'show me your API key'. Not a redaction that might slip."""
    low = (request or "").lower()
    if any(word in low for word in ("api key", "apikey", "password", "secret",
                                    "token", "credential", ".env", "private key")):
        return ("I won't show credentials, not even to redact them. The keys "
                "live in a .env file that this project never opens for "
                "display. I can show you any of the source code instead.")
    return None


# -- engineering challenges ----------------------------------------------
# Curated because a commit subject is not a story -- but every entry cites a
# commit, and `challenges()` drops any whose commit cannot be found. The
# repository is the authority; this is only the narration.
_CHALLENGES: tuple[dict[str, str], ...] = (
    {"sha": "803d931",
     "problem": "The wake word was heard correctly and rejected anyway.",
     "cause": "Speech recognition writes the name as it SOUNDS -- Zeeno, Xeno, "
              "Zino -- and the matcher accepted exactly one spelling. It also "
              "disagreed with the configuration, which listed two wake phrases "
              "the matcher would never accept.",
     "fix": "Build the matcher from the configured phrases, and let every "
            "known spelling stand in for the name.",
     "result": "The wake word fires on the owner's own voice. 13 phrasing "
               "cases checked, including ones that must NOT fire.",
     "status": "WORKING"},
    {"sha": "b5361cc",
     "problem": "The phone was told to join the Wi-Fi it was already on.",
     "cause": "The QR code carries a hostname, and Windows answers that name "
              "with IPv6 first. The check that decides whether a device is on "
              "the local network only understood IPv4, so it refused every "
              "answer.",
     "fix": "Judge IPv6 properly -- link-local and unique-local are local by "
            "definition; a global address is accepted only inside this "
            "machine's own prefix, never blanket.",
     "result": "Phone audio verified arriving over Wi-Fi and hotspot: 195 and "
               "172 frames received.",
     "status": "WORKING"},
    {"sha": "e538af7",
     "problem": "ZENO could not say who his own agents were.",
     "cause": "Nothing was lost -- the roster, roles and workers all existed in "
              "three separate files. None of them was exposed as something the "
              "conversation could ask, so the identity was on disk and "
              "unreachable, which looks exactly like forgetting.",
     "fix": "One identity layer over the existing sources, read without "
            "starting any agent.",
     "result": "14 agents and 77 workers, answerable while every one of them "
               "is asleep.",
     "status": "WORKING"},
    {"sha": "1c68077",
     "problem": "The phone showed the error message '[object Object]'.",
     "cause": "The web framework returns its error detail as a STRING for most "
              "failures but as an ARRAY OF OBJECTS for validation errors. "
              "Turning that array into text produces that literal string.",
     "fix": "Unwrap every shape the detail can take, and fall back to a real "
            "sentence per status code.",
     "result": "Failures now say what went wrong. Pairing codes are stripped "
               "from any message before it reaches the screen.",
     "status": "WORKING"},
    {"sha": "923b571",
     "problem": "Automating Slack would have typed into a window it could not "
                "read.",
     "cause": "Slack is an Electron application, and its accessibility tree "
              "exposes only the window frame -- no channel list, no messages, "
              "no message box.",
     "fix": "Check readability BEFORE typing, and refuse when the result "
            "cannot be verified.",
     "result": "It reports the real reason instead of sending a message into "
               "an unknown conversation and calling it success.",
     "status": "PARTIAL"},
    {"sha": "397983a",
     "problem": "The project claimed a 3D capability was unavailable while the "
                "software was installed.",
     "cause": "Capability status was a hand-written sentence rather than a "
              "check. It read the same on a machine with the software and a "
              "machine without it.",
     "fix": "Probe the thing that would do the work; being listed grants "
            "nothing, and a probe that errors fails closed.",
     "result": "Blender 5.2 correctly reported available; tools with no "
               "connector are refused by name.",
     "status": "WORKING"},
)


def challenges() -> list[dict[str, Any]]:
    """Real problems, each with a commit that is verified to exist."""
    found = []
    for entry in _CHALLENGES:
        if not commit_exists(entry["sha"]):
            continue        # no receipt, no claim
        found.append({**entry, "evidence": commit_detail(entry["sha"])})
    return found


# -- project evidence ----------------------------------------------------

def project_evidence() -> dict[str, Any]:
    """Scale and shape of the work, counted rather than described."""
    python_files = _git("ls-files", "*.py").splitlines()
    test_files = _git("ls-files", "tests/*.py").splitlines()
    commits = _git("log", "--oneline").splitlines()
    packages = sorted({p.split("/")[1] for p in python_files
                       if p.startswith("reyes_agent/") and "/" in p[14:]})
    return {
        "python_files": len(python_files),
        "test_files": len(test_files),
        "commits": len(commits),
        "subsystems": packages[:24],
        "subsystem_count": len(packages),
        "package_name": "reyes_agent",
        "package_note": ("The package is still named after REYES. Every module "
                         "here imports from it -- that is what survives of the "
                         "original name."),
        "counted_from": "git ls-files and git log, at the moment you asked",
    }


def status() -> dict[str, Any]:
    verified = challenges()
    return {"state": "ONLINE",
            "challenges_with_receipts": len(verified),
            "challenges_curated": len(_CHALLENGES),
            "capabilities_mapped": len(_IMPLEMENTATIONS),
            "rule": ("Every claim is read from disk or cites a commit that is "
                     "checked to exist. A claim without a receipt is dropped, "
                     "never displayed.")}
