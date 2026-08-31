"""VersionManager -- restore points, undo, redo, revert (#17).

The single most important safety property of content editing: an AI edit must
NEVER destroy the user's only recoverable copy. Before ZENO modifies a file it
takes a lightweight internal snapshot; undo/redo/revert restore from those
snapshots. Backups live in ZENO's own data dir keyed by a hash of the path --
the user never sees ``report.zv2`` next to ``report.docx``.

MODEL
-----
Each tracked file has a linear timeline of snapshots and a cursor pointing at
the snapshot currently on disk. `checkpoint` appends the current content;
`undo` steps the cursor back (capturing any uncheckpointed edit first, so it is
never lost); `redo` steps forward; `revert` returns to the original. The first
snapshot (the original) is never discarded.

Every method returns ``{"ok": bool, ...}`` and never raises: a versioning
failure must not be what breaks an edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config

_ROOT = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "content" / "versions"
_MAX_VERSIONS = 40           # bounded history per file
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024   # don't snapshot enormous files


def _abs(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class VersionManager:
    def __init__(self, root: Path = _ROOT) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    # -- store layout ------------------------------------------------------
    def _dir_for(self, path: Path) -> Path:
        key = hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:16]
        return self._root / key

    def _manifest_path(self, path: Path) -> Path:
        return self._dir_for(path) / "manifest.json"

    def _load(self, path: Path) -> dict[str, Any]:
        mp = self._manifest_path(path)
        if mp.exists():
            try:
                return json.loads(mp.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        return {"source": str(path), "versions": [], "cursor": -1}

    def _save(self, path: Path, manifest: dict[str, Any]) -> None:
        d = self._dir_for(path)
        d.mkdir(parents=True, exist_ok=True)
        tmp = self._manifest_path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, self._manifest_path(path))

    def _store_snapshot(self, path: Path, manifest: dict[str, Any],
                        note: str) -> dict[str, Any]:
        data = path.read_bytes()
        vid = f"v{len(manifest['versions']):04d}"
        dest = self._dir_for(path) / f"{vid}{path.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"id": vid, "file": dest.name, "sha256": _sha256_bytes(data),
                "size": len(data), "time": self._now(), "note": str(note)[:200]}

    @staticmethod
    def _now() -> float:
        try:
            return time.time()
        except Exception:  # noqa: BLE001
            return 0.0

    def _restore_version(self, path: Path, version: dict[str, Any]) -> None:
        src = self._dir_for(path) / version["file"]
        shutil.copyfile(src, path)

    def _trim(self, path: Path, manifest: dict[str, Any]) -> None:
        # Keep the original (index 0) plus the most recent _MAX_VERSIONS-1.
        versions = manifest["versions"]
        if len(versions) <= _MAX_VERSIONS:
            return
        keep = [versions[0]] + versions[-(_MAX_VERSIONS - 1):]
        drop = [v for v in versions if v not in keep]
        for v in drop:
            try:
                (self._dir_for(path) / v["file"]).unlink(missing_ok=True)
            except OSError:
                pass
        manifest["versions"] = keep
        manifest["cursor"] = len(keep) - 1

    # -- public API --------------------------------------------------------
    def checkpoint(self, path: str | Path, *, note: str = "") -> dict[str, Any]:
        """Save the file's current content as a restore point. A no-op (still
        ok) if the content is identical to the latest snapshot."""
        try:
            with self._lock:
                p = _abs(path)
                if not p.exists() or not p.is_file():
                    return {"ok": False, "error": f"'{p}' is not a file"}
                if p.stat().st_size > _MAX_SNAPSHOT_BYTES:
                    return {"ok": False, "error": "file too large to version"}
                manifest = self._load(p)
                versions = manifest["versions"]
                current_sha = _sha256_file(p)
                cursor = manifest.get("cursor", -1)
                if versions and 0 <= cursor < len(versions) and \
                        versions[cursor]["sha256"] == current_sha:
                    return {"ok": True, "unchanged": True, "version": versions[cursor]["id"]}
                # a new checkpoint invalidates any redo future
                if 0 <= cursor < len(versions) - 1:
                    for v in versions[cursor + 1:]:
                        try:
                            (self._dir_for(p) / v["file"]).unlink(missing_ok=True)
                        except OSError:
                            pass
                    manifest["versions"] = versions = versions[:cursor + 1]
                snap = self._store_snapshot(p, manifest, note)
                versions.append(snap)
                manifest["cursor"] = len(versions) - 1
                self._trim(p, manifest)
                self._save(p, manifest)
                return {"ok": True, "version": snap["id"],
                        "count": len(manifest["versions"])}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    def undo(self, path: str | Path) -> dict[str, Any]:
        """Restore the previous snapshot. Any uncheckpointed edit is captured
        first, so 'undo' can always be redone and nothing is lost."""
        try:
            with self._lock:
                p = _abs(path)
                manifest = self._load(p)
                versions = manifest["versions"]
                if not versions:
                    return {"ok": False, "error": "no restore points for this file"}
                cursor = manifest.get("cursor", len(versions) - 1)
                # capture a dirty (uncheckpointed) edit so it becomes redo-able
                if p.exists() and _sha256_file(p) != versions[cursor]["sha256"]:
                    snap = self._store_snapshot(p, manifest, note="pre-undo")
                    versions.append(snap)
                    cursor = len(versions) - 1
                if cursor <= 0:
                    manifest["cursor"] = cursor
                    self._save(p, manifest)
                    return {"ok": False, "error": "already at the earliest version"}
                cursor -= 1
                self._restore_version(p, versions[cursor])
                manifest["cursor"] = cursor
                self._save(p, manifest)
                return {"ok": True, "restored": versions[cursor]["id"],
                        "can_redo": cursor < len(versions) - 1}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    def redo(self, path: str | Path) -> dict[str, Any]:
        try:
            with self._lock:
                p = _abs(path)
                manifest = self._load(p)
                versions = manifest["versions"]
                cursor = manifest.get("cursor", len(versions) - 1)
                if not versions or cursor >= len(versions) - 1:
                    return {"ok": False, "error": "nothing to redo"}
                cursor += 1
                self._restore_version(p, versions[cursor])
                manifest["cursor"] = cursor
                self._save(p, manifest)
                return {"ok": True, "restored": versions[cursor]["id"]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    def revert(self, path: str | Path) -> dict[str, Any]:
        """Restore the ORIGINAL (first) snapshot. The original is never lost."""
        try:
            with self._lock:
                p = _abs(path)
                manifest = self._load(p)
                versions = manifest["versions"]
                if not versions:
                    return {"ok": False, "error": "no original on record"}
                # capture current so revert itself is redo-able
                if p.exists() and _sha256_file(p) != versions[-1]["sha256"]:
                    versions.append(self._store_snapshot(p, manifest, note="pre-revert"))
                self._restore_version(p, versions[0])
                manifest["cursor"] = 0
                self._save(p, manifest)
                return {"ok": True, "restored": versions[0]["id"]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    def history(self, path: str | Path) -> dict[str, Any]:
        with self._lock:
            p = _abs(path)
            manifest = self._load(p)
            versions = manifest["versions"]
            cursor = manifest.get("cursor", len(versions) - 1)
            return {"ok": True, "source": str(p), "cursor": cursor,
                    "versions": [{"id": v["id"], "time": v["time"],
                                  "note": v["note"], "size": v["size"],
                                  "current": i == cursor}
                                 for i, v in enumerate(versions)]}


_manager: VersionManager | None = None
_manager_lock = threading.Lock()


def get_version_manager() -> VersionManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = VersionManager()
    return _manager
