"""Validated application of model-proposed repairs.

WHY THE MODEL NEVER TOUCHES THE FILESYSTEM
------------------------------------------
The autonomous repair loop needs changes only a model can write -- a
missing import, a wrong type, a bad prop. What it must NOT do is hand the
model a filesystem. So the model returns DATA (a patch), and this module is
the only thing that turns data into writes, after checking every one of:

  * the path resolves inside the project and nowhere else,
  * the file is one the reported errors actually named,
  * it is not a lockfile, a dependency folder, or ZENO's own history,
  * the content is a plausible size and not empty,
  * the number of files touched is small.

A patch that fails any check is REJECTED whole. Partially applying a
suspicious patch is worse than applying none, because it leaves a project
in a state neither the model nor the checkpoint describes.

The brief calls this out directly: "If the model proposes suspicious or
unrelated modifications, reject them."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.executors import filesystem

# Files a repair may never write, whatever it claims to be fixing.
FORBIDDEN_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock"}
FORBIDDEN_PARTS = {"node_modules", ".git", ".zeno", "dist", "build", ".next", "__pycache__"}
# A generated source file well over this is a rewrite, not a repair.
MAX_FILE_BYTES = 400_000
MAX_FILES_PER_PATCH = 6


@dataclass
class PatchFile:
    path: str
    content: str


@dataclass
class PatchResult:
    ok: bool
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "applied": list(self.applied),
                "rejected": list(self.rejected), "reason": self.reason}


def coerce(patch: Any) -> list[PatchFile]:
    """Accept the shapes a model realistically returns."""
    files: list[PatchFile] = []
    if isinstance(patch, dict):
        entries = patch.get("files") if isinstance(patch.get("files"), list) else None
        if entries is None:
            # {"src/App.tsx": "...contents..."}
            for path, content in patch.items():
                if isinstance(path, str) and isinstance(content, str):
                    files.append(PatchFile(path, content))
            return files
        patch = entries
    if isinstance(patch, list):
        for entry in patch:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path") or entry.get("file") or entry.get("filename") or ""
            content = entry.get("content") or entry.get("contents") or entry.get("body")
            if isinstance(path, str) and isinstance(content, str) and path.strip():
                files.append(PatchFile(path.strip(), content))
    return files


def validate(root: Path, files: list[PatchFile], *, allowed_files: set[str] | None = None
             ) -> tuple[bool, str, list[str]]:
    """(ok, reason, rejected_paths). Whole-patch decision, never partial."""
    root = Path(root).resolve()
    if not files:
        return False, "the patch contained no files", []
    if len(files) > MAX_FILES_PER_PATCH:
        return False, f"the patch touches {len(files)} files; a targeted repair should touch few", []

    rejected: list[str] = []
    for item in files:
        raw = item.path.replace("\\", "/").lstrip("/")
        if not raw or raw.startswith("../") or "/../" in raw:
            rejected.append(f"{item.path}: path traversal")
            continue
        target = (root / raw)
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            rejected.append(f"{item.path}: resolves outside the project")
            continue
        parts = set(Path(raw).parts)
        if parts & FORBIDDEN_PARTS:
            rejected.append(f"{item.path}: writes into a managed directory")
            continue
        if Path(raw).name in FORBIDDEN_NAMES:
            rejected.append(f"{item.path}: lockfiles are managed by the package manager, not by a patch")
            continue
        if not item.content.strip():
            rejected.append(f"{item.path}: empty content")
            continue
        if len(item.content.encode("utf-8")) > MAX_FILE_BYTES:
            rejected.append(f"{item.path}: {len(item.content)} chars is a rewrite, not a repair")
            continue
        if allowed_files is not None and raw.casefold() not in allowed_files:
            # The core "unrelated modification" guard: a repair may only
            # touch files the errors actually pointed at.
            rejected.append(f"{item.path}: not one of the files the errors named")
            continue

    if rejected:
        return False, "the patch was rejected: " + "; ".join(rejected[:4]), rejected
    return True, "", []


def apply(root: Path, files: list[PatchFile], *, allowed_files: set[str] | None = None) -> PatchResult:
    """Validate the whole patch, then write it. Nothing is written on failure."""
    ok, reason, rejected = validate(root, files, allowed_files=allowed_files)
    if not ok:
        return PatchResult(False, rejected=rejected, reason=reason)

    written: list[str] = []
    for item in files:
        result = filesystem.write_file(Path(root), item.path, item.content)
        if not result.ok:
            # A write failed after validation passed. Report honestly rather
            # than claiming the repair landed; the caller restores its
            # checkpoint.
            return PatchResult(False, applied=written,
                               reason=f"{item.path} could not be written: {result.message}")
        written.append(item.path)
    return PatchResult(True, applied=written, reason=f"applied {len(written)} file(s)")


def context_for(root: Path, errors: list[Any], *, max_files: int = 3,
                max_chars: int = 12_000) -> dict[str, Any]:
    """What the model needs to write a targeted fix, and nothing more.

    Deliberately bounded: sending the whole project invites a rewrite, and
    the brief asks for a targeted change. Only files the errors named are
    included.
    """
    root = Path(root)
    named: list[str] = []
    for error in errors:
        name = getattr(error, "file", "") or ""
        if name and name not in named:
            named.append(name)
    sources: dict[str, str] = {}
    budget = max_chars
    for name in named[:max_files]:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sources[name] = text[:budget]
        budget -= min(len(text), budget)
        if budget <= 0:
            break

    metadata: dict[str, Any] = {"project": root.name}
    package = root / "package.json"
    if package.is_file():
        try:
            import json

            data = json.loads(package.read_text(encoding="utf-8"))
            metadata["dependencies"] = sorted((data.get("dependencies") or {}).keys())[:30]
            metadata["scripts"] = sorted((data.get("scripts") or {}).keys())
        except (OSError, ValueError):
            pass
    metadata["framework"] = ("Next.js" if (root / "next.config.js").exists() or (root / "next.config.mjs").exists()
                             else "Vite" if (root / "vite.config.js").exists() or (root / "vite.config.ts").exists()
                             else "static" if (root / "index.html").exists() else "unknown")
    return {"files": sources, "named": named, "metadata": metadata}
