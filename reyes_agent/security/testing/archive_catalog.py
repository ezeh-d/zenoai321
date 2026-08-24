"""Safe AVA inventory for the owner-supplied AllHackingTools archive.

The upstream bundle is a Termux/Linux installer menu, not a trusted Python
library.  It contains useful security references next to phishing, spam,
credential theft, camera/location capture, denial-of-service projects and an
embedded executable.  ZENO therefore never imports, extracts, installs or runs
archive content.  This module gives AVA a complete, lazy, integrity-hashed
inventory and routes legitimate candidates through AVA's existing scope gate.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import zipfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any


BLOCKED = "BLOCKED"
AUTHORIZED_TESTING = "AUTHORIZED_TESTING"
DEFENSIVE_REFERENCE = "DEFENSIVE_REFERENCE"
QUARANTINED_INSTALLER = "QUARANTINED_INSTALLER"
DOCUMENTATION = "DOCUMENTATION"
STATES = (DEFENSIVE_REFERENCE, AUTHORIZED_TESTING, BLOCKED,
          QUARANTINED_INSTALLER, DOCUMENTATION)

_MAX_ENTRIES = 2_000
_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_TOOLS_MANIFEST = "AllHackingTools-main/.github/TOOLS.md"
_LINK_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', re.IGNORECASE)

# These projects are not assessment helpers.  Scope authorization cannot make
# indiscriminate harm, credential theft, deceptive collection or malware safe.
_BLOCKED_TERMS = (
    "ddos", "ddoser", "dos attack", "sms-bomber", "aresbomb", "anon-sms",
    "spymer", "tbomb", "anonymoussms", "spammer", "emailpyspam",
    "email-spammer", "phish", "blackeye", "hiddeneye", "saycheese",
    "grabcam", "cam-hack", "camhack", "wishfish", "hack-gmail",
    "gmail-hack", "facebook-bruteforce", "pyshell", "remote trojan",
    "infect", "virus creation", "i-see-you", "seeker", "trape", "evilurl",
    "weeman", "iphack", "sh33ll",
)
_BLOCKED_CATEGORIES = (
    "cam hacking", "remote trojan", "sms spaming", "phishing and iphack",
    "sniffing and spoofing",
)
_DEFENSIVE_TERMS = (
    "whatweb", "nikto", "pwnedornot", "sherlock", "userfinder",
    "littlebrother", "darkdump", "hash generator", "rang3r", "tm-scanner",
)
_INSTALLER_SUFFIXES = (".sh", ".php")


@dataclass(frozen=True)
class ArchiveTool:
    name: str
    category: str
    source_url: str
    state: str
    reason: str
    native_matches: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["native_matches"] = list(self.native_matches)
        return row


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    size: int
    state: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_archive_path() -> Path:
    configured = os.environ.get("ZENO_ALL_HACKING_TOOLS_ARCHIVE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Downloads" / "AllHackingTools-main.zip"


def _safe_member(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and not path.is_absolute() and ".." not in path.parts


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _classify_tool(name: str, category: str, source_url: str) -> tuple[str, str]:
    text = f"{name} {category} {source_url}".casefold()
    if any(term in text for term in _BLOCKED_TERMS) or any(
            term in category.casefold() for term in _BLOCKED_CATEGORIES):
        return BLOCKED, (
            "Blocked: deceptive collection, credential theft, malware, spam, "
            "camera/location abuse or indiscriminate disruption is never executable."
        )
    if any(term in text for term in _DEFENSIVE_TERMS):
        return DEFENSIVE_REFERENCE, (
            "Defensive/diagnostic reference; use a reviewed ZENO-native equivalent."
        )
    return AUTHORIZED_TESTING, (
        "Reference for a specific owner-authorized target; execution must use "
        "AVA's scope, confirmation, timeout and evidence gates."
    )


def _native_matches(name: str) -> tuple[str, ...]:
    try:
        from reyes_agent.security.testing import catalog

        words = [word for word in re.split(r"[^a-zA-Z0-9]+", name) if len(word) >= 4]
        found: list[str] = []
        for word in words[:4]:
            for item in catalog.find(word):
                if item.name not in found:
                    found.append(item.name)
        return tuple(found[:5])
    except Exception:  # inventory remains available if the main catalog degrades
        return ()


def _classify_entry(info: zipfile.ZipInfo) -> tuple[str, str]:
    name = info.filename.replace("\\", "/")
    folded = name.casefold()
    if not _safe_member(name):
        return BLOCKED, "Unsafe archive path; never extract."
    if info.is_dir():
        return DOCUMENTATION, "Archive directory metadata."
    if folded.endswith("/castom/ngrok") or folded.endswith((".exe", ".dll", ".so")):
        return QUARANTINED_INSTALLER, "Embedded executable/binary is untrusted and never launched."
    if folded.endswith(_INSTALLER_SUFFIXES) or "/files/" in folded:
        return QUARANTINED_INSTALLER, "Self-installing or command script; inventory only, never sourced or executed."
    if folded.endswith((".md", ".txt", ".yml", ".yaml", ".jpg", ".png", ".flf", ".tlf")):
        return DOCUMENTATION, "Non-executable reference or visual asset."
    return QUARANTINED_INSTALLER, "Unreviewed archive content; no import or execution authority."


def _parse_tools(markdown: str) -> tuple[ArchiveTool, ...]:
    category = "Uncategorised"
    tools: list[ArchiveTool] = []
    seen: set[tuple[str, str]] = set()
    for line in markdown.splitlines():
        if line.startswith("## "):
            category = line[3:].strip()[:120]
            continue
        match = _LINK_RE.search(line)
        if not match:
            continue
        source_url, name = match.group(1).strip(), match.group(2).strip()
        key = (name.casefold(), source_url.casefold())
        if key in seen or category.casefold() == "supporters":
            continue
        seen.add(key)
        state, reason = _classify_tool(name, category, source_url)
        tools.append(ArchiveTool(name[:120], category, source_url[:500], state,
                                 reason, _native_matches(name)))
    return tuple(tools)


@lru_cache(maxsize=4)
def _inspect_cached(path_text: str, size: int, modified_ns: int) -> dict[str, Any]:
    del size, modified_ns  # cache-key inputs; content is read below exactly once
    path = Path(path_text)
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise ValueError(f"Archive has {len(infos)} entries; limit is {_MAX_ENTRIES}.")
        total = sum(max(0, int(info.file_size)) for info in infos)
        if total > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Archive exceeds the bounded uncompressed-size limit.")
        if any(not _safe_member(info.filename) for info in infos):
            raise ValueError("Archive contains an unsafe absolute or traversal path.")

        entries = tuple(ArchiveEntry(info.filename, int(info.file_size),
                                     *_classify_entry(info)) for info in infos)
        try:
            manifest_info = archive.getinfo(_TOOLS_MANIFEST)
        except KeyError:
            manifest = ""
        else:
            if manifest_info.file_size > _MAX_MANIFEST_BYTES:
                raise ValueError("TOOLS.md exceeds the bounded manifest-size limit.")
            manifest = archive.read(manifest_info).decode("utf-8", errors="replace")
        tools = _parse_tools(manifest)

    tool_counts = {state: sum(1 for item in tools if item.state == state) for state in STATES}
    entry_counts = {state: sum(1 for item in entries if item.state == state) for state in STATES}
    return {
        "archive": path.name,
        "sha256": _digest(path),
        "entry_count": len(entries),
        "uncompressed_bytes": total,
        "tool_count": len(tools),
        "tool_counts": tool_counts,
        "entry_counts": entry_counts,
        "tools": tools,
        "entries": entries,
        "execution_policy": (
            "Archive content is never imported, extracted, installed or executed. "
            "Authorized candidates route through AVA's existing scoped security plan."
        ),
    }


def inspect(archive_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(archive_path).expanduser() if archive_path else default_archive_path()
    if not path.is_file():
        return {"available": False, "archive": path.name, "reason": "Archive file not found."}
    stat = path.stat()
    try:
        result = dict(_inspect_cached(str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return {"available": False, "archive": path.name,
                "reason": f"{type(exc).__name__}: {exc}"[:500]}
    result["available"] = True
    return result


def query(query_text: str = "", *, state: str = "", limit: int = 50,
          include_entries: bool = False, archive_path: str | Path | None = None) -> dict[str, Any]:
    report = inspect(archive_path)
    if not report.get("available"):
        return report
    wanted = str(state or "").strip().upper()
    needle = str(query_text or "").strip().casefold()
    capped = max(1, min(200, int(limit or 50)))
    tools = list(report.pop("tools"))
    entries = list(report.pop("entries"))
    if wanted:
        tools = [item for item in tools if item.state == wanted]
        entries = [item for item in entries if item.state == wanted]
    if needle:
        tools = [item for item in tools if needle in (
            f"{item.name} {item.category} {item.source_url} {item.state}").casefold()]
        entries = [item for item in entries if needle in item.path.casefold()]
    report["matches"] = [item.as_dict() for item in tools[:capped]]
    report["match_count"] = len(tools)
    if include_entries:
        report["entries"] = [item.as_dict() for item in entries[:capped]]
        report["entry_match_count"] = len(entries)
    return report


def route(tool_name: str, target: str = "", *, archive_path: str | Path | None = None) -> dict[str, Any]:
    result = query(tool_name, limit=10, archive_path=archive_path)
    matches = result.get("matches") or []
    exact = next((item for item in matches if item["name"].casefold() == tool_name.casefold()),
                 matches[0] if len(matches) == 1 else None)
    if exact is None:
        return {"allowed": False, "state": "UNKNOWN", "reason": "No unique archive tool matched."}
    if exact["state"] in {BLOCKED, QUARANTINED_INSTALLER}:
        return {"allowed": False, "state": exact["state"], "tool": exact,
                "reason": exact["reason"]}
    if exact["state"] == AUTHORIZED_TESTING:
        from reyes_agent.security.testing import authorization

        scoped = authorization.get_scope().check(target)
        return {"allowed": scoped.allowed, "state": exact["state"], "tool": exact,
                "scope": scoped.as_dict(),
                "reason": ("Use security_plan and the reviewed native candidate; archive code stays quarantined."
                           if scoped.allowed else scoped.reason)}
    return {"allowed": True, "state": exact["state"], "tool": exact,
            "reason": "Reference is available; use a reviewed ZENO-native defensive capability."}


def clear_cache() -> None:
    with _cache_lock:
        _inspect_cached.cache_clear()


_cache_lock = threading.Lock()
