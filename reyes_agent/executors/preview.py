"""Browser Preview Executor -- run it, open it, prove it responded.

Two modes, chosen from what is actually on disk and actually installed:

* A project with a `package.json` dev script AND Node.js present gets its
  real dev server (`npm run dev`).
* Everything else -- and any project on a machine without Node.js -- is
  served by an in-process static server. This is the honest fallback the
  brief asks for: a plain HTML/CSS/JS site does not need Node.js, so a
  missing Node.js is reported as information, not as a failed build.

The port is chosen by binding to 0, so "address already in use" cannot
happen and there is no retry loop pretending to be one. One server per
project folder: asking twice reuses the running one instead of stacking
servers and browser tabs.
"""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from reyes_agent import task_engine
from reyes_agent.executors import terminal

_lock = threading.Lock()
_servers: dict[str, "Preview"] = {}


@dataclass
class Preview:
    url: str
    mode: str                      # "static" | "npm"
    root: str
    stop: object = None            # callable
    process: object = None
    opened_in_browser: bool = False
    checks: list[dict] = field(default_factory=list)
    port: int | None = None
    pid: int | None = None
    thread_id: int | None = None
    started_at: float = field(default_factory=time.time)
    task_ids: set[str] = field(default_factory=set)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler that does not spam the console for every asset."""

    def log_message(self, *_args) -> None:  # noqa: D102
        return


def _static_server(root: Path) -> tuple[Preview | None, str]:
    handler = functools.partial(_QuietHandler, directory=str(root))
    try:
        # Port 0 -> the OS hands back a free one.
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    except OSError as exc:
        return None, f"Could not start a local server: {exc}"
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, name=f"zeno-preview-{port}", daemon=True)
    thread.start()

    def stop() -> None:
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()

    return Preview(url=f"http://127.0.0.1:{port}/", mode="static", root=str(root), stop=stop,
                   port=port, thread_id=thread.ident), ""


def _npm_dev_script(root: Path) -> str:
    package = root / "package.json"
    if not package.is_file():
        return ""
    try:
        scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""
    for name in ("dev", "start", "serve"):
        if name in scripts:
            return name
    return ""


def _npm_server(task_id: str, root: Path) -> tuple[Preview | None, str]:
    script = _npm_dev_script(root)
    if not script:
        return None, "no dev script in package.json"
    if not terminal.tool_available("npm"):
        return None, "npm is not installed"
    background, error = terminal.spawn(
        task_id, f"npm run {script}", root,
        ready_markers=("localhost:", "127.0.0.1:", "Local:", "ready in", "listening"),
        ready_timeout=90,
    )
    if background is None:
        return None, error
    url = _url_from_output(background.output())
    if not url:
        background.stop()
        return None, "the dev server started but never printed a local URL"
    parsed = urllib.parse.urlparse(url)
    return Preview(url=url, mode="npm", root=str(root), stop=background.stop, process=background,
                   port=parsed.port, pid=getattr(background.process, "pid", None)), ""


def _url_from_output(output: str) -> str:
    import re

    match = re.search(r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?(?:/\S*)?", output or "")
    return match.group(0).rstrip(".,)") if match else ""


def start(task_id: str, project_dir: Path) -> tuple[Preview | None, str]:
    """Serve the project. Returns (preview, error)."""
    root = Path(project_dir)
    if not root.is_dir():
        return None, f"{root} does not exist."
    key = str(root.resolve()).casefold()
    with _lock:
        existing = _servers.get(key)
    if existing is not None:
        ok, _ = probe(existing.url)
        if ok:
            existing.task_ids.add(task_id)
            task_engine.record_terminal(task_id, f"[preview] reusing server at {existing.url}")
            return existing, ""
        with _lock:
            _servers.pop(key, None)

    preview, error = _npm_server(task_id, root)
    if preview is None:
        if error and error not in {"no dev script in package.json"}:
            task_engine.record_warning(task_id, f"Dev server unavailable ({error}) -- serving the files directly.")
        preview, error = _static_server(root)
        if preview is None:
            return None, error

    with _lock:
        preview.task_ids.add(task_id)
        _servers[key] = preview
    if callable(preview.stop):
        task_engine.register_closer(task_id, f"preview {preview.url}", _closer_for(key, preview))
    task_engine.set_preview_url(task_id, preview.url)
    task_engine.record_terminal(task_id, f"[preview] {preview.mode} server on {preview.url}")
    return preview, ""


def _closer_for(key: str, preview: Preview):
    def close() -> None:
        try:
            if callable(preview.stop):
                preview.stop()
        finally:
            with _lock:
                _servers.pop(key, None)
    return close


def probe(url: str, timeout: float = 6.0) -> tuple[bool, str]:
    """Actually fetch the page. This is the evidence behind 'it works'."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 -- localhost only
            status = response.status
            body = response.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, f"{url} returned HTTP {exc.code}."
    except Exception as exc:  # noqa: BLE001 -- URLError, socket errors, timeouts
        return False, f"{url} did not respond: {exc}"
    if status != 200:
        return False, f"{url} returned HTTP {status}."
    if not body.strip():
        return False, f"{url} responded but the page was empty."
    return True, f"{url} responded HTTP 200 ({len(body)} bytes)."


def check_page(url: str, project_dir: Path) -> list[dict]:
    """Fetch the page and every local asset it references.

    'Styles are loading' is answered by requesting the stylesheet over HTTP
    and reading the status, not by noting that a .css file exists.
    """
    import re

    checks: list[dict] = []
    ok, detail = probe(url)
    checks.append({"check": "Main page responds", "ok": ok, "detail": detail})
    if not ok:
        return checks

    try:
        with urllib.request.urlopen(url, timeout=6) as response:  # noqa: S310
            html = response.read(400_000).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "Read main page", "ok": False, "detail": str(exc)})
        return checks

    from reyes_agent.executors.coding import _REF_PATTERNS, _REMOTE

    refs: list[str] = []
    for pattern in _REF_PATTERNS:
        for ref in pattern.findall(html):
            ref = ref.strip()
            if ref and not _REMOTE.match(ref) and ref not in refs:
                refs.append(ref)

    styles = [r for r in refs if r.split("?")[0].lower().endswith(".css")]
    scripts = [r for r in refs if r.split("?")[0].lower().endswith(".js")]
    for ref in refs[:12]:
        asset_ok, asset_detail = probe(urllib.parse.urljoin(url, ref), timeout=5)
        checks.append({"check": f"Asset {ref}", "ok": asset_ok, "detail": asset_detail})

    checks.append({
        "check": "Stylesheet referenced",
        "ok": bool(styles),
        "detail": ", ".join(styles) if styles else "The page links no local stylesheet.",
    })
    checks.append({
        "check": "Script referenced",
        "ok": bool(scripts),
        "detail": ", ".join(scripts) if scripts else "The page loads no local script.",
    })
    _ = project_dir
    return checks


def open_in_browser(task_id: str, preview: Preview) -> tuple[bool, str]:
    """Open the running preview once. Repeat calls do not stack tabs."""
    if preview.opened_in_browser:
        return True, f"Already open in the browser: {preview.url}"
    try:
        opened = webbrowser.open(preview.url, new=2)
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not open the browser: {exc}"
    preview.opened_in_browser = bool(opened)
    if not opened:
        return False, f"No browser handler accepted {preview.url}."
    task_engine.record_terminal(task_id, f"[browser] opened {preview.url}")
    return True, f"Opened {preview.url} in your default browser."


def running() -> list[dict[str, object]]:
    with _lock:
        return [{"url": p.url, "mode": p.mode, "root": p.root, "port": p.port,
                 "pid": p.pid, "thread_id": p.thread_id, "started_at": p.started_at,
                 "task_ids": sorted(p.task_ids)} for p in _servers.values()]


def for_project(project_dir: Path) -> dict | None:
    """Return the actual managed preview record for one project, if alive."""
    key = str(Path(project_dir).resolve()).casefold()
    with _lock:
        preview = _servers.get(key)
        if preview is None:
            return None
        return {"url": preview.url, "mode": preview.mode, "root": preview.root,
                "port": preview.port, "pid": preview.pid, "thread_id": preview.thread_id,
                "started_at": preview.started_at, "task_ids": sorted(preview.task_ids)}


def stop_all() -> None:
    with _lock:
        previews = list(_servers.values())
        _servers.clear()
    for preview in previews:
        try:
            if callable(preview.stop):
                preview.stop()
        except Exception:  # noqa: BLE001
            pass
