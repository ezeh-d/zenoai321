"""File System Executor -- writes that are verified, not assumed.

Every function here returns a `FileResult` whose `ok` reflects a check made
AFTER the operation: the file was re-read from disk and its size and first
bytes compared to what was requested. "write_text did not raise" is not the
same as "the file is on disk with the right contents", and the difference is
exactly what made ZENO's reports untrustworthy.

Writes are atomic where the platform allows: content goes to a temporary
file in the same directory, is flushed and fsync'd, then `os.replace`d over
the target. A crash mid-write leaves the previous file intact rather than a
truncated one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileResult:
    ok: bool
    path: str
    message: str
    bytes_written: int = 0
    verified: bool = False


def _inside(root: Path, target: Path) -> bool:
    """Path containment check -- blocks '../..' escapes from model output."""
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def ensure_folder(path: Path) -> FileResult:
    """Create a folder and confirm it exists afterwards."""
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return FileResult(False, str(path), f"Could not create folder: {exc}")
    if not path.is_dir():
        return FileResult(False, str(path), "Folder still does not exist after mkdir.")
    if not os.access(path, os.W_OK):
        return FileResult(False, str(path), f"Folder '{path}' is not writable.")
    return FileResult(True, str(path), f"Folder ready: {path}", verified=True)


def write_file(root: Path, relative_path: str, content: str) -> FileResult:
    """Atomically write one file inside `root`, then verify it landed.

    The filename comes from model output, so it is resolved and checked
    against `root` before anything is created.
    """
    root = Path(root)
    raw = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        return FileResult(False, "", "No filename was given.")
    target = (root / raw)
    if not _inside(root, target):
        return FileResult(False, str(target), f"Refused '{relative_path}' -- it escapes the project folder.")
    target = target.resolve()

    folder = ensure_folder(target.parent)
    if not folder.ok:
        return FileResult(False, str(target), folder.message)

    data = str(content)
    encoded = data.encode("utf-8")
    handle = None
    tmp_path = ""
    try:
        # Same directory as the target so os.replace stays atomic (a rename
        # across volumes is not).
        handle, tmp_path = tempfile.mkstemp(dir=str(target.parent), prefix=".zeno-", suffix=".tmp")
        with os.fdopen(handle, "wb") as stream:
            handle = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, target)
        tmp_path = ""
    except OSError as exc:
        return FileResult(False, str(target), f"Could not write {raw}: {exc}")
    finally:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    ok, detail = verify_file(target, expected_bytes=len(encoded), expected_head=data[:200])
    if not ok:
        return FileResult(False, str(target), f"Wrote {raw} but verification failed: {detail}", len(encoded))
    return FileResult(True, str(target), f"Wrote and verified {raw} ({len(encoded)} bytes).", len(encoded), True)


def verify_file(path: Path, *, expected_bytes: int | None = None, expected_head: str = "") -> tuple[bool, str]:
    """Re-read from disk. This is the only thing that justifies "saved"."""
    path = Path(path)
    if not path.is_file():
        return False, f"{path} does not exist."
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"Could not stat {path}: {exc}"
    if expected_bytes is not None and size != expected_bytes:
        return False, f"{path.name} is {size} bytes on disk, expected {expected_bytes}."
    if expected_head:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:len(expected_head)]
        except OSError as exc:
            return False, f"Could not read {path} back: {exc}"
        if head != expected_head:
            return False, f"{path.name} contents differ from what was written."
    return True, f"{path.name} verified on disk ({size} bytes)."


def read_file(path: Path, limit: int = 200_000) -> FileResult:
    path = Path(path)
    if not path.is_file():
        return FileResult(False, str(path), f"{path} is not a file.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError as exc:
        return FileResult(False, str(path), f"Could not read {path}: {exc}")
    return FileResult(True, str(path), text, len(text), True)


def move_within(root: Path, source: str, destination: str) -> FileResult:
    """Rename/move inside the project. Both ends are containment-checked."""
    root = Path(root)
    src = (root / str(source).replace("\\", "/").lstrip("/"))
    dst = (root / str(destination).replace("\\", "/").lstrip("/"))
    if not _inside(root, src) or not _inside(root, dst):
        return FileResult(False, str(dst), "Refused -- source or destination leaves the project folder.")
    if not src.exists():
        return FileResult(False, str(src), f"{source} does not exist.")
    folder = ensure_folder(dst.parent)
    if not folder.ok:
        return FileResult(False, str(dst), folder.message)
    try:
        shutil.move(str(src), str(dst))
    except (OSError, shutil.Error) as exc:
        return FileResult(False, str(dst), f"Could not move {source}: {exc}")
    if not dst.exists():
        return FileResult(False, str(dst), f"Move reported success but {destination} does not exist.")
    return FileResult(True, str(dst), f"Moved {source} -> {destination}.", verified=True)


def list_files(root: Path, limit: int = 400) -> list[str]:
    """The project tree, as it really is on disk."""
    root = Path(root)
    if not root.is_dir():
        return []
    skip = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build"}
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= limit:
            break
        if any(part in skip for part in path.parts):
            continue
        if path.is_file():
            try:
                found.append(str(path.relative_to(root)).replace("\\", "/"))
            except ValueError:
                continue
    return found


def folder_report(root: Path) -> dict[str, object]:
    """Evidence bundle for the final verification step."""
    root = Path(root)
    files = list_files(root)
    total = 0
    empty: list[str] = []
    for name in files:
        try:
            size = (root / name).stat().st_size
        except OSError:
            continue
        total += size
        if size == 0:
            empty.append(name)
    return {
        "exists": root.is_dir(),
        "path": str(root),
        "files": files,
        "file_count": len(files),
        "total_bytes": total,
        "empty_files": empty,
    }
