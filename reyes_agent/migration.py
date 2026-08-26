"""Prepare ZENO to move to another laptop -- export / inspect / restore.

Moving ZENO is three separate things, and conflating them is how people lose
data or leak keys:

  * CODE travels with git (clone on the new machine).
  * STATE (knowledge vault, spatial memory, vocabulary, voice) lives OUTSIDE
    git and must be exported/restored -- this module does that.
  * SECRETS (.env, owner auth, device tokens) must NEVER ride in an export
    bundle; the owner moves those by hand, over a secure channel. This module
    refuses to bundle them.

Everything else (venv, node_modules, model caches, browser cache) is rebuilt on
the new machine and is not worth copying.

`preflight()` inventories exactly what will move, what the owner must carry
separately, and what to rebuild. `export_profile()` writes a portable, secret-
free zip + manifest. `import_profile()` restores it (dry-run by default). Roots
are injectable so this is tested without touching the real machine.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

_LA = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO"

# Category -> what it means for a move.
PORTABLE = "portable"     # safe to bundle: knowledge/state, no secrets
BIOMETRIC = "biometric"   # sensitive personal data; bundled only on opt-in
SECRET = "secret"         # NEVER bundled; owner moves it securely by hand
REBUILD = "rebuild"       # recreate on the new machine; don't copy


@dataclass
class Item:
    name: str
    path: Path
    category: str
    note: str = ""


@dataclass
class MigrationManager:
    project_root: Path = field(default_factory=lambda: Path(config.PROJECT_ROOT))
    localapp: Path = field(default_factory=lambda: _LA)
    vault: Path | None = None

    def __post_init__(self) -> None:
        if self.vault is None:
            self.vault = Path(config.VAULT_PATH)

    # -- inventory -------------------------------------------------------
    def _items(self) -> list[Item]:
        la = self.localapp
        return [
            # PORTABLE -- the knowledge and learned state worth keeping.
            Item("knowledge vault", self.vault, PORTABLE, "notes, memory DBs, projects, daily logs"),
            Item("spatial memory", la / "spatial", PORTABLE, "eMEM spatial DB + place/object index"),
            Item("custom vocabulary", la / "Vocabulary", PORTABLE, "learned proper nouns / terms"),
            Item("language state", la / "language", PORTABLE, ""),
            Item("local models", la / "Models", PORTABLE, "speaker/embedding models cached under ZENO"),
            Item("orb position", la / "mini-orb-position.json", PORTABLE, "UI preference"),
            # BIOMETRIC -- personal, opt-in only.
            Item("voice profile", la / "Biometrics", BIOMETRIC, "owner voice enrollment (sensitive)"),
            # SECRET -- never in a bundle; carried by the owner over a secure channel.
            Item("environment secrets", self.project_root / ".env", SECRET, "API keys, tokens"),
            Item("owner auth + unlock", la / "auth", SECRET, "password/unlock hashes, sessions"),
            Item("ZENO Anywhere", la / "anywhere", SECRET, "executor + tunnel tokens"),
            Item("phone pairing", la / "phone", SECRET, "companion device tokens"),
            Item("social accounts", la / "social", SECRET, "provider tokens"),
            Item("security state", la / "security", SECRET, "scopes / authorizations"),
            # REBUILD -- recreate on the new machine.
            Item("python venv", self.project_root / ".venv", REBUILD, "recreate: python -m venv + pip install"),
            Item("node modules", self.project_root / "node_modules", REBUILD, "recreate: npm install"),
            Item("browser cache", la / "WebView2", REBUILD, "regenerates on first run"),
            Item("toolchains", la / "toolchains", REBUILD, "re-provisioned on demand"),
            Item("runtime lock", la / "runtime.lock", REBUILD, "runtime only; never copy"),
        ]

    @staticmethod
    def _size(path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
            if path.is_dir():
                return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        except OSError:
            pass
        return 0

    def preflight(self) -> dict[str, Any]:
        """What will move, what to carry separately, what to rebuild."""
        rows = []
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for it in self._items():
            exists = it.path.exists()
            # Only measure what actually moves. Walking node_modules/.venv (tens
            # of thousands of files) just to print a size we never use would make
            # preflight take minutes; REBUILD items are recreated, not copied.
            measured = it.category != REBUILD
            size = self._size(it.path) if (exists and measured) else 0
            row = {"name": it.name, "category": it.category, "path": str(it.path),
                   "exists": exists, "bytes": size,
                   "size": (_human(size) if measured else "rebuild") if exists else "-",
                   "note": it.note}
            rows.append(row)
            by_cat.setdefault(it.category, []).append(row)
        portable_bytes = sum(r["bytes"] for r in by_cat.get(PORTABLE, []))
        return {
            "hostname": _hostname(),
            "git_commit": _git_commit(self.project_root),
            "items": rows,
            "by_category": by_cat,
            "portable_bytes": portable_bytes,
            "portable_size": _human(portable_bytes),
            "checklist": self._checklist(by_cat),
        }

    def _checklist(self, by_cat: dict[str, list[dict[str, Any]]]) -> list[str]:
        secrets = [r["name"] for r in by_cat.get(SECRET, []) if r["exists"]]
        return [
            "1. On the NEW laptop: install git + Python 3.12, then `git clone` the repo.",
            "2. Recreate the environment: create the venv and `pip install -r requirements.txt`; `npm install`.",
            "3. Run `python -m reyes_agent.migrate export` on THIS laptop -> copy the .zip across.",
            "4. Run `python -m reyes_agent.migrate import <bundle.zip>` on the new laptop.",
            f"5. SECRETS ZENO will NOT move for you -- carry these by hand, securely: {', '.join(secrets) or '(none present)'}.",
            "6. Re-provision owner auth on the new device (`python -m reyes_agent.auth.provision`) and re-pair ZENO Anywhere / phone -- device tokens are per-machine and should be re-issued, not copied.",
            "7. First run re-downloads model caches (embeddings, voices) as needed.",
        ]

    # -- export ----------------------------------------------------------
    def export_profile(self, dest: str | Path, *, include_biometrics: bool = False) -> dict[str, Any]:
        """Write a portable, SECRET-FREE zip of ZENO's state + a manifest."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        wanted = {PORTABLE} | ({BIOMETRIC} if include_biometrics else set())
        included: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                for it in self._items():
                    if it.category not in wanted or not it.path.exists():
                        continue
                    # Hard guard: a SECRET path must never reach the archive.
                    if it.category == SECRET:
                        continue
                    count = self._add_to_zip(zf, it)
                    included.append({"name": it.name, "category": it.category,
                                     "arc": _arcname(it), "files": count})
                manifest = {
                    "kind": "zeno-profile", "version": 1,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "source_host": _hostname(),
                    "git_commit": _git_commit(self.project_root),
                    "provider": getattr(config, "MODEL_PROVIDER", ""),  # name only, never a key
                    "included": included,
                    "feature_flags": _feature_flags(),
                    "note": "Secrets (.env, auth, device tokens) are intentionally excluded.",
                }
                zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"export failed: {type(exc).__name__}: {exc}"[:200]}
        return {"ok": True, "bundle": str(dest), "bytes": dest.stat().st_size,
                "size": _human(dest.stat().st_size), "included": included,
                "excluded_secrets": [it.name for it in self._items() if it.category == SECRET]}

    def _add_to_zip(self, zf: zipfile.ZipFile, it: Item) -> int:
        arc = _arcname(it)
        if it.path.is_file():
            zf.write(it.path, f"{arc}/{it.path.name}")
            return 1
        count = 0
        for f in it.path.rglob("*"):
            if f.is_file():
                zf.write(f, f"{arc}/{f.relative_to(it.path).as_posix()}")
                count += 1
        return count

    # -- import ----------------------------------------------------------
    def import_profile(self, archive: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
        """Restore a bundle into this machine's ZENO locations. Dry-run by
        default: reports what WOULD be written without touching anything."""
        archive = Path(archive)
        if not archive.exists():
            return {"ok": False, "error": f"bundle not found: {archive}"}
        dest_for = {_arcname(it): it.path for it in self._items()
                    if it.category in {PORTABLE, BIOMETRIC}}
        planned: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                manifest = {}
                if "MANIFEST.json" in zf.namelist():
                    manifest = json.loads(zf.read("MANIFEST.json"))
                for name in zf.namelist():
                    if name == "MANIFEST.json" or name.endswith("/"):
                        continue
                    top = name.split("/", 1)[0]
                    target_root = dest_for.get(top)
                    if target_root is None:
                        continue  # unknown top-level entry -- never write outside known roots
                    rel = name.split("/", 1)[1] if "/" in name else ""
                    # A file-type item's target IS the file; a dir-type item joins rel.
                    target = target_root / rel if (rel and target_root.suffix == "") else target_root
                    planned.append({"from": name, "to": str(target)})
                    if not dry_run:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src, open(target, "wb") as out:
                            out.write(src.read())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"import failed: {type(exc).__name__}: {exc}"[:200]}
        return {"ok": True, "dry_run": dry_run, "manifest": manifest,
                "files": len(planned), "planned": planned[:50],
                "note": "Dry run -- nothing was written. Re-run with dry_run=False to apply."
                        if dry_run else "Restored. Re-provision auth + re-pair devices next."}


# -- helpers -----------------------------------------------------------------
def _arcname(it: Item) -> str:
    return it.name.replace(" ", "_").replace("/", "_")


def _human(n: int) -> str:
    step = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if step < 1024 or unit == "GB":
            return f"{step:.1f}{unit}" if unit != "B" else f"{int(step)}B"
        step /= 1024
    return f"{step:.1f}GB"


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:  # noqa: BLE001
        return ""


def _git_commit(root: Path) -> str:
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            return (root / ".git" / ref).read_text(encoding="utf-8").strip()[:12]
        return head[:12]
    except Exception:  # noqa: BLE001
        return ""


def _feature_flags() -> list[dict[str, Any]]:
    try:
        from reyes_agent import feature_flags
        return feature_flags.get_flags().all_flags()
    except Exception:  # noqa: BLE001
        return []


_instance: MigrationManager | None = None


def get_manager() -> MigrationManager:
    global _instance
    if _instance is None:
        _instance = MigrationManager()
    return _instance
