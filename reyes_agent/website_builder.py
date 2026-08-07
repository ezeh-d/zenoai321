"""Website Builder integration over ZENO's existing build/task runtime.

This module is intentionally metadata, routing policy and reversible local
checkpoints only. Files are still written by ``build_project``, commands by
the terminal executor, previews by the preview executor, and tasks by the one
managed task engine.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from reyes_agent import config

_LOCK = threading.RLock()
_WEB_RE = re.compile(r"\b(website mode|web builder|build (?:me )?(?:a )?(?:website|site|portfolio|landing page)|(?:website|site|homepage|hero|navbar|mobile layout|dark mode|dashboard)\b)", re.I)
_SKIP = {"node_modules", ".git", ".zeno", "dist", "build", ".next", "__pycache__"}
_MAX_SNAPSHOT_FILES = int(getattr(config, "WEBSITE_CHECKPOINT_MAX_FILES", 750))
_MAX_SNAPSHOT_BYTES = int(getattr(config, "WEBSITE_CHECKPOINT_MAX_MB", 12)) * 1024 * 1024

def enabled() -> bool:
    return bool(getattr(config, "WEBSITE_BUILDER_ENABLED", True))

def safe_project_root(root: Path) -> Path:
    """Reject ZENO's own source/vault from Website Studio mutation paths."""
    candidate = Path(root).resolve()
    protected = (Path(config.PROJECT_ROOT).resolve(), Path(config.VAULT_PATH).resolve())
    for base in protected:
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        raise ValueError("Website Studio refuses to use the ZENO installation or vault as a generated project folder.")
    return candidate

def is_website_request(message: str) -> bool:
    return bool(_WEB_RE.search(str(message or "")))

_NEEDS_APP = ("dashboard", "admin panel", "admin area", "log in", "login", "sign up",
              "signup", "authentication", "user account", "crud", "realtime", "real time",
              "chart", "analytics", "search filter", "shopping cart", "checkout", "booking system")
_NEEDS_SERVER = ("database", "backend", "api endpoint", "server side", "server-side", "cms",
                 "payment", "stripe", "authentication", "user accounts", "newsletter signup",
                 "contact form that sends", "store data", "save submissions")

def recommend_stack(message: str) -> dict[str, Any]:
    """Pick the SMALLEST stack that actually does the job.

    The brief is explicit that Next.js must not be the answer to everything.
    A restaurant page with a menu and a phone number does not need a build
    step, a router and 200MB of node_modules -- and on a machine without
    Node.js installed, recommending one produces a project that cannot run
    at all. Node availability is checked, not assumed.
    """
    text = str(message or "").casefold()
    has_node = False
    try:
        from reyes_agent.executors import terminal
        has_node = terminal.tool_available("node") and terminal.tool_available("npm")
    except Exception:  # noqa: BLE001 -- an unavailable check means "assume not"
        has_node = False

    app_hits = [h for h in _NEEDS_APP if h in text]
    server_hits = [h for h in _NEEDS_SERVER if h in text]

    if not has_node:
        return {"stack": "static", "framework": "HTML/CSS/JavaScript", "commands": [],
                "reason": ("Node.js is not installed on this machine, so a build-step stack could not "
                           "run. Plain HTML/CSS/JS needs nothing installed and opens immediately."),
                "signals": app_hits + server_hits}
    if server_hits:
        return {"stack": "next", "framework": "Next.js + TypeScript + Tailwind",
                "commands": ["npm install"],
                "reason": f"Needs server-side work ({', '.join(server_hits[:3])}).",
                "signals": server_hits}
    if app_hits:
        return {"stack": "vite-react", "framework": "React + Vite + TypeScript + Tailwind",
                "commands": ["npm install"],
                "reason": f"Interactive app behaviour ({', '.join(app_hits[:3])}) justifies a component framework.",
                "signals": app_hits}
    return {"stack": "static", "framework": "HTML/CSS/JavaScript", "commands": [],
            "reason": "A content site with no app behaviour or server needs -- the smallest stack that does the job.",
            "signals": []}

def directive(message: str) -> str:
    if not enabled() or not is_website_request(message):
        return ""
    pick = recommend_stack(message)
    return ("[Website Builder Mode: use the existing build_project/task engine for actual work, and keep one project folder. "
            f"Recommended stack: {pick['framework']} -- {pick['reason']} Use a heavier stack only if the request truly needs it. "
            "Save generated sites with destination=\"websites\" unless the owner named a location. "
            "After building or editing a site, call website_check to run its REAL build/lint/typecheck and get "
            "structured errors back; fix only the files it names. "
            "Before a major redesign of an EXISTING site call website_project(action='checkpoint'); to undo, call "
            "website_restore_checkpoint; for 'another version, keep this one' call website_project(action='variant'). "
            "A HTTP/build check is not visual proof: use browser/screenshot inspection when available and report its absence "
            "honestly. Never claim build, preview, responsive behavior or a fix succeeded without executor evidence.]")

@contextmanager
def _db():
    path = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS website_projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, project_type TEXT NOT NULL, framework TEXT NOT NULL,
          location TEXT NOT NULL UNIQUE, status TEXT NOT NULL, pages_json TEXT NOT NULL, notes_json TEXT NOT NULL,
          last_modified REAL NOT NULL)""")
        yield conn; conn.commit()
    finally: conn.close()

def _emit(kind: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus
        event_bus.publish(kind, payload, source="website_builder")
    except Exception: pass

def _framework(root: Path) -> str:
    package = root / "package.json"
    if package.is_file():
        try:
            text = package.read_text(encoding="utf-8").lower()
            if "next" in text: return "Next.js"
            if "vite" in text: return "Vite"
            if "react" in text: return "React"
        except OSError: pass
    return "HTML/CSS/JavaScript" if (root / "index.html").is_file() else "Unknown"

def register_build(name: str, root: Path, *, status: str, files: list[str]) -> dict[str, Any] | None:
    root = Path(root).resolve()
    if not ((root / "index.html").is_file() or (root / "package.json").is_file()): return None
    pages = [f for f in files if re.search(r"(?:^|/)(?:index|.*page)\.(?:html|tsx?|jsx?)$", f, re.I)][:40]
    item = {"id": uuid.uuid5(uuid.NAMESPACE_URL, str(root).casefold()).hex[:12], "project_name": name[:120],
            "project_type": "website", "framework": _framework(root), "location": str(root), "status": status,
            "pages": pages, "notes": [], "last_modified": time.time()}
    with _LOCK, _db() as conn:
        conn.execute("INSERT INTO website_projects VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(location) DO UPDATE SET name=excluded.name,project_type=excluded.project_type,framework=excluded.framework,status=excluded.status,pages_json=excluded.pages_json,last_modified=excluded.last_modified", (item["id"], item["project_name"], item["project_type"], item["framework"], item["location"], item["status"], json.dumps(item["pages"]), "[]", item["last_modified"]))
    _emit("website.project_updated", item); return item

def projects() -> list[dict[str, Any]]:
    with _LOCK, _db() as conn: rows = conn.execute("SELECT id,name,project_type,framework,location,status,pages_json,notes_json,last_modified FROM website_projects ORDER BY last_modified DESC").fetchall()
    result=[]; stale=[]
    for r in rows:
        if not Path(r[4]).is_dir():
            stale.append(r[4]); continue
        try: pages=json.loads(r[6])
        except ValueError: pages=[]
        result.append({"project_id":r[0],"project_name":r[1],"project_type":r[2],"framework":r[3],"location":r[4],"status":r[5],"pages":pages,"last_modified":r[8]})
    if stale:
        with _LOCK, _db() as conn:
            conn.executemany("DELETE FROM website_projects WHERE location=?", [(item,) for item in stale])
    return result

def checkpoint(root: Path, label: str = "") -> dict[str, Any]:
    root=safe_project_root(root)
    if not root.is_dir(): raise ValueError("Website project folder does not exist.")
    version_id=f"v-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:5]}"
    target=root/".zeno"/"versions"/version_id; files=[]; total=0; truncated=False
    for source in root.rglob("*"):
        # A snapshot must not follow a symlink out of the project and copy
        # unrelated local data into a project checkpoint.
        if source.is_symlink() or not source.is_file() or any(part in _SKIP for part in source.relative_to(root).parts): continue
        size=source.stat().st_size
        if len(files)>=_MAX_SNAPSHOT_FILES or total+size>_MAX_SNAPSHOT_BYTES:
            # RECORDED, not silent. A capped snapshot is not a complete
            # picture of the project, and restore_checkpoint refuses to
            # delete anything on the authority of one. Measured 2026-08-07
            # before this flag existed: a 200-file project checkpointed 150,
            # its safety backup also captured 150, and restore deleted the
            # other 50 -- destroying them in both places at once.
            truncated=True; break
        relative=source.relative_to(root); destination=target/relative; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,destination); files.append(str(relative)); total+=size
    if not files: raise ValueError("No eligible project files were available to checkpoint.")
    manifest={"version":version_id,"label":" ".join(str(label).split())[:160] or "Checkpoint","created_at":time.time(),"files":files,"bytes":total,"truncated":truncated}
    (target/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    _emit("website.checkpoint_created", {"root":str(root),**manifest}); return manifest

def checkpoints(root: Path) -> list[dict[str, Any]]:
    base=safe_project_root(root)/".zeno"/"versions"; items=[]
    for path in sorted(base.glob("*/manifest.json"), reverse=True) if base.is_dir() else []:
        try: items.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError): pass
    return items[:20]

def inspect(root: Path) -> list[str]:
    root=safe_project_root(root); findings=[]
    for page in list(root.glob("*.html"))[:20]:
        if page.is_symlink():
            continue
        text=page.read_text(encoding="utf-8",errors="replace")
        if "<title" not in text.lower(): findings.append(f"{page.name}: missing page title")
        if "<meta name=\"description\"" not in text.lower() and "<meta name='description'" not in text.lower(): findings.append(f"{page.name}: missing meta description")
        if re.search(r"<img(?![^>]*\balt=)", text, re.I): findings.append(f"{page.name}: image without alt text")
    return findings


def visual_inspect(root: Path) -> dict[str, Any]:
    """Render a managed local preview and return screenshot/layout evidence.

    This is deliberately on-demand: starting Playwright for every file write
    would undermine the staged-startup and low-CPU rules. It opens no remote
    page and does not make an aesthetic success claim; it records what the
    browser actually rendered at two viewport sizes.
    """
    root = safe_project_root(root)
    from reyes_agent.executors import preview

    running = preview.for_project(root)
    if not running:
        raise ValueError("No managed preview server is running for this website. Start its preview before visual inspection.")
    url = str(running["url"])
    if not re.match(r"^http://127\.0\.0\.1(?::\d+)?/", url):
        raise ValueError("Visual inspection accepts only ZENO's managed loopback preview.")
    inspection_dir = root / ".zeno" / "inspection"
    inspection_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    def action() -> dict[str, Any]:
        from reyes_agent import browser_controller as controller

        owner_page = controller.get_page()
        page = owner_page.context.new_page()
        captures: list[dict[str, Any]] = []
        try:
            for label, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(url, timeout=controller.action_timeout_ms(30_000), wait_until="networkidle")
                metrics = page.evaluate("""() => ({
                    title: document.title || '',
                    bodyTextLength: (document.body?.innerText || '').trim().length,
                    scrollWidth: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
                    clientWidth: document.documentElement.clientWidth,
                    scrollHeight: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
                    viewportHeight: window.innerHeight,
                })""")
                filename = f"{stamp}-{label}.png"
                target = inspection_dir / filename
                page.screenshot(path=str(target), full_page=True, timeout=controller.action_timeout_ms(30_000))
                captures.append({
                    "viewport": {"width": width, "height": height}, "screenshot": str(target),
                    "screenshot_bytes": target.stat().st_size if target.is_file() else 0,
                    "title": str(metrics.get("title") or ""),
                    "body_text_length": int(metrics.get("bodyTextLength") or 0),
                    "horizontal_overflow": int(metrics.get("scrollWidth") or 0) > int(metrics.get("clientWidth") or 0),
                    "page_height": int(metrics.get("scrollHeight") or 0),
                })
        finally:
            page.close()
        return {"url": url, "preview": running, "captures": captures}

    from reyes_agent.browser_runtime import get_browser_runtime

    result = get_browser_runtime().run("website_visual_inspection", action, timeout=75.0)
    result["inspected_at"] = time.time()
    _emit("website.visual_inspected", {"root": str(root), **result})
    return result

def variant(root: Path, name: str) -> dict[str, Any]:
    """Copy a project into a NEW sibling folder so both designs survive.

    "Make another version but keep this one" must not be implemented as
    "edit in place and trust the checkpoint" -- that leaves one live design
    and a snapshot, not two projects. The original folder is never touched
    here, and the copy starts with its own empty history rather than
    inheriting the original's checkpoints.
    """
    root = safe_project_root(root)
    if not root.is_dir(): raise ValueError("Website project folder does not exist.")
    slug = re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", str(name or "")).strip()).lower()
    if not slug: raise ValueError("Give the new version a name.")
    target = safe_project_root(root.parent / slug)
    if target == root: raise ValueError("The new version needs a different name from the original.")
    if target.exists(): raise ValueError(f"'{target.name}' already exists beside the original -- choose another name.")
    copied=[]; total=0; truncated=False
    for source in sorted(root.rglob("*")):
        if source.is_symlink() or not source.is_file() or any(part in _SKIP for part in source.relative_to(root).parts): continue
        size=source.stat().st_size
        if len(copied)>=_MAX_SNAPSHOT_FILES or total+size>_MAX_SNAPSHOT_BYTES: truncated=True; break
        relative=source.relative_to(root); destination=target/relative
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source,destination)
        copied.append(str(relative).replace("\\","/")); total+=size
    if not copied: raise ValueError("There were no project files to copy into the new version.")
    register_build(name, target, status="variant", files=copied)
    item={"name":name,"location":str(target),"source":str(root),"files":copied,"truncated":truncated}
    _emit("website.variant_created", item); return item

def find_project(query: str) -> list[dict[str, Any]]:
    """Resolve "continue my restaurant website" to registered projects.

    Returns every plausible match instead of picking one. Guessing which
    project the owner meant and then editing it is the destructive shortcut
    the brief rules out; presenting candidates costs one question.
    """
    stop = {"the","and","for","with","please","continue","website","site","project",
            "keep","working","open","again","that","this","make","build","update","edit","my"}
    words = [w for w in re.split(r"\W+", str(query or "").casefold()) if len(w) > 2 and w not in stop]
    scored=[]
    for item in projects():
        haystack=f"{item['project_name']} {Path(item['location']).name}".casefold()
        score=sum(1 for w in words if w in haystack)
        if score: scored.append((score,item))
    scored.sort(key=lambda pair:(-pair[0], -pair[1]["last_modified"]))
    return [item for _s,item in scored[:5]]

def latest_restorable(root: Path) -> str:
    """Which checkpoint "undo" should mean.

    Prefers the most recent DELIBERATE checkpoint over the automatic backup
    that `restore_checkpoint` takes on its way in -- otherwise undoing twice
    just walks back into the state the owner was trying to leave.
    """
    saved = checkpoints(root)
    if not saved: raise ValueError("This project has no checkpoints yet.")
    deliberate = [m for m in saved if not str(m.get("label","")).startswith("Automatic backup before restoring")]
    return (deliberate or saved)[0]["version"]

LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")


def dependency_state(root: Path) -> dict[str, Any]:
    """What the project DECLARES it depends on, and how it is pinned.

    Recorded before dependency-changing work so a rollback has something to
    reconcile against. Manifests only -- never node_modules.
    """
    root = Path(root)
    package = root / "package.json"
    state: dict[str, Any] = {"has_package_json": package.is_file(), "lockfile": "",
                             "dependencies": {}, "installed": (root / "node_modules").is_dir()}
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
            state["dependencies"] = {**(data.get("dependencies") or {}),
                                     **(data.get("devDependencies") or {})}
        except (OSError, ValueError):
            pass
    for name in LOCKFILES:
        if (root / name).is_file():
            state["lockfile"] = name
            break
    return state


def reconcile_dependencies(root: Path, restored: list[str]) -> dict[str, Any]:
    """Make node_modules match the manifests that were just restored.

    Only runs when the restore actually put a manifest back -- restoring a
    CSS file must not trigger a reinstall. `npm ci` is preferred when a
    lockfile is present because it installs exactly what the lock pins;
    `npm install` is the fallback when there is no lock to obey.

    Runs as a BACKGROUND JOB, so a rollback never blocks the caller for the
    length of an install. Nothing is deleted here -- npm owns node_modules.
    """
    root = Path(root)
    touched = {Path(name).name for name in restored}
    manifests = {"package.json", *LOCKFILES}
    if not (touched & manifests):
        return {"needed": False, "reason": "no dependency manifest was part of this checkpoint"}

    state = dependency_state(root)
    if not state["has_package_json"]:
        return {"needed": False, "reason": "no package.json in the restored project"}
    if not state["dependencies"]:
        return {"needed": False, "reason": "the restored package.json declares no dependencies"}

    try:
        from reyes_agent.executors import jobs, terminal
    except Exception:  # noqa: BLE001
        return {"needed": True, "started": False, "reason": "the job runner is unavailable"}
    if not terminal.tool_available("npm"):
        return {"needed": True, "started": False,
                "reason": "npm is not installed, so node_modules cannot be reconciled",
                "command": "npm ci" if state["lockfile"] else "npm install"}

    # `npm ci` requires a lockfile AND that it agrees with package.json; it
    # fails loudly otherwise, which is why the fallback exists.
    command = "npm ci" if state["lockfile"] else "npm install"
    job, error = jobs.start(command, root, project=root.name, kind=jobs.INSTALL)
    if job is None:
        return {"needed": True, "started": False, "reason": error, "command": command}
    return {"needed": True, "started": True, "command": command, "job_id": job.id,
            "lockfile": state["lockfile"],
            "reason": f"reconciling node_modules with the restored manifests via `{command}`"}


def restore_checkpoint(root: Path, version: str) -> dict[str, Any]:
    """Restore one bounded checkpoint after first preserving the current tree.

    This intentionally removes only ordinary project files that were absent
    from the selected manifest. Dependencies, build output and `.zeno` remain
    untouched. The caller is confirmation-gated because it replaces files.
    """
    root = safe_project_root(root)
    if not re.fullmatch(r"v-[0-9]{8}-[0-9]{6}-[a-f0-9]{5}", str(version or "")):
        raise ValueError("Invalid checkpoint version identifier.")
    source = root / ".zeno" / "versions" / version
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Checkpoint does not exist.")
    try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc: raise ValueError(f"Checkpoint manifest is unreadable: {exc}") from exc
    names = [str(name).replace("\\", "/") for name in manifest.get("files", [])]
    if not names: raise ValueError("Checkpoint contains no project files.")
    validated: list[tuple[str, Path, Path]] = []
    for relative in names:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Checkpoint contains an unsafe file path.")
        origin = (source / relative_path).resolve()
        target = (root / relative_path).resolve()
        if origin != source and source not in origin.parents:
            raise ValueError("Checkpoint file escapes its version directory.")
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Checkpoint file escapes its project directory.") from exc
        if not origin.is_file() or origin.is_symlink():
            raise ValueError("Checkpoint contains an invalid file entry.")
        validated.append((relative, origin, target))
    current = checkpoint(root, f"Automatic backup before restoring {version}")
    allowed = set(names)

    # Restore FIRST, delete after. If anything fails part-way the tree is
    # left as a superset of both states rather than gutted -- deleting first
    # meant a failed copy left the project with neither version.
    restored=[]
    for relative, origin, target in validated:
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(origin,target); restored.append(relative)

    # A truncated snapshot never saw the whole project, and neither did the
    # backup taken moments ago (it caps identically). Deleting "files not in
    # the manifest" on that basis destroys them in both places at once, so
    # files are only copied back and the shortfall is reported instead.
    complete = not manifest.get("truncated", True) and not current.get("truncated", True)
    removed=[]; undeletable=[]
    if complete:
        for path in root.rglob("*"):
            if not path.is_file() or any(part in _SKIP for part in path.relative_to(root).parts): continue
            relative=str(path.relative_to(root)).replace("\\", "/")
            if relative in allowed: continue
            try: path.unlink(); removed.append(relative)
            except OSError as exc: undeletable.append(f"{relative}: {exc}")

    # Dependency reconciliation. The manifests ARE the source of truth --
    # node_modules is never snapshotted, because copying it per checkpoint
    # would be gigabytes for something npm can rebuild exactly.
    dependencies = reconcile_dependencies(root, restored)
    result={"version":version,"restored":restored,"removed":removed,"backup":current["version"],
            "dependencies":dependencies,
            "complete":complete,"undeletable":undeletable}
    _emit("website.checkpoint_restored", {"root":str(root),**result}); return result
