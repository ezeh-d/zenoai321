"""Bounded source parsing and GitHub/local repository acquisition.

Acquisition here means read-only inspection. It never clones, installs or
executes a repository and never follows repository-authored instructions.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from reyes_agent.extensions.models import (
    GITHUB_DIRECTORY, GITHUB_FILE, GITHUB_RELEASE, GITHUB_REPOSITORY,
    LOCAL_DIRECTORY, LOCAL_FILE, MCP_SERVER, MODEL_ADAPTER, NODE_PACKAGE, PLUGIN,
    PYTHON_PACKAGE, SKILL, TOOL_ADAPTER, RepositorySnapshot, SourceReference,
)

_GITHUB = re.compile(
    r"^https?://github\.com/([^/]+)/([^/#?]+)(?:\.git)?(?:/(blob|tree)/([^/]+)/(.+)|/(releases)(?:/(?:tag/)?([^/?#]+))?)?/?$",
    re.IGNORECASE,
)
_TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".toml", ".yaml", ".yml", ".md", ".rst", ".txt", ".ini",
    ".cfg", ".conf", ".sh", ".ps1", ".bat", ".cmd", ".dockerfile",
}
_PRIORITY_NAMES = {
    "readme", "readme.md", "license", "license.md", "copying", "security.md",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "pipfile.lock", "poetry.lock", "package.json", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml", "dockerfile", "docker-compose.yml",
    "mcp.json", "plugin.json", "skill.md",
}
_SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", ".next", "coverage"}


class SourceError(ValueError):
    pass


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise SourceError("GitHub inspection refused a redirect to an unexpected endpoint.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_source(value: str | Path) -> SourceReference:
    original = str(value or "").strip()
    if not original:
        raise SourceError("An extension source is required.")
    local = Path(original).expanduser()
    if local.exists():
        return SourceReference(original, LOCAL_DIRECTORY if local.is_dir() else LOCAL_FILE,
                               local_path=str(local.resolve()))
    prefixes = {
        "pip:": PYTHON_PACKAGE, "python:": PYTHON_PACKAGE, "npm:": NODE_PACKAGE,
        "node:": NODE_PACKAGE, "mcp:": MCP_SERVER, "plugin:": PLUGIN, "skill:": SKILL,
        "model:": MODEL_ADAPTER, "adapter:": TOOL_ADAPTER, "tool:": TOOL_ADAPTER,
    }
    for prefix, kind in prefixes.items():
        if original.casefold().startswith(prefix):
            package = original[len(prefix):].strip()
            if not package or not re.fullmatch(r"[A-Za-z0-9@_./-]{1,200}", package):
                raise SourceError("The package/server reference is invalid.")
            if ".." in PurePosixPath(package).parts:
                raise SourceError("The package/server reference contains path traversal.")
            return SourceReference(original, kind, package=package)
    match = _GITHUB.match(original)
    if not match:
        raise SourceError("Supported sources are GitHub URLs, package references, MCP/plugin/skill references, or existing local files.")
    owner, repo, mode, ref, subpath, releases, release_ref = match.groups()
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo):
        raise SourceError("GitHub owner/repository name is invalid.")
    if owner in {".", ".."} or repo in {".", ".."}:
        raise SourceError("GitHub owner/repository name is invalid.")
    if mode == "blob":
        kind = GITHUB_FILE
    elif mode == "tree":
        kind = GITHUB_DIRECTORY
    elif releases:
        kind, ref = GITHUB_RELEASE, release_ref or "latest"
    else:
        kind = GITHUB_REPOSITORY
    return SourceReference(original, kind, owner, repo, ref or "", subpath or "")


class GitHubImportEngine:
    MAX_FILES = 160
    MAX_FILE_BYTES = 256 * 1024
    MAX_TOTAL_BYTES = 8 * 1024 * 1024
    MAX_RESPONSE_BYTES = 10 * 1024 * 1024

    def parse(self, source: str | Path) -> SourceReference:
        return parse_source(source)

    def inspect_source(self, source: str | Path | SourceReference) -> RepositorySnapshot:
        reference = source if isinstance(source, SourceReference) else self.parse(source)
        if reference.kind in {LOCAL_FILE, LOCAL_DIRECTORY}:
            return self._local(reference)
        if reference.kind in {PYTHON_PACKAGE, NODE_PACKAGE, MCP_SERVER, PLUGIN, SKILL,
                              MODEL_ADAPTER, TOOL_ADAPTER}:
            return RepositorySnapshot(reference, metadata={"package": reference.package,
                                                           "metadata_only": True}, truncated=True)
        return self._github(reference)

    def search_repositories(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        phrase = str(query or "").strip()
        if not phrase or len(phrase) > 200:
            raise SourceError("GitHub search query must contain 1-200 characters.")
        count = max(1, min(10, int(limit)))
        encoded = urllib.parse.urlencode({
            "q": phrase, "sort": "stars", "order": "desc", "per_page": count,
        })
        payload = self._request(f"https://api.github.com/search/repositories?{encoded}")
        rows = []
        for item in list(payload.get("items") or [])[:count]:
            rows.append({
                "name": item.get("full_name"), "url": item.get("html_url"),
                "description": item.get("description"), "stars": item.get("stargazers_count"),
                "archived": item.get("archived"), "pushed_at": item.get("pushed_at"),
                "license": (item.get("license") or {}).get("spdx_id"),
                "automatic_install": False,
            })
        return rows

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ZENO-Extension-Inspector/1"}
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, url: str, *, json_result: bool = True) -> Any:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise SourceError("GitHub inspection refused an unexpected endpoint.")
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            opener = urllib.request.build_opener(_GitHubRedirectHandler())
            with opener.open(request, timeout=12) as response:
                data = response.read(self.MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise SourceError(f"GitHub inspection failed: {type(exc).__name__}: {exc}") from exc
        if len(data) > self.MAX_RESPONSE_BYTES:
            raise SourceError("GitHub response exceeded the bounded inspection limit.")
        return json.loads(data) if json_result else data.decode("utf-8", errors="replace")

    def _github(self, source: SourceReference) -> RepositorySnapshot:
        base = f"https://api.github.com/repos/{urllib.parse.quote(source.owner)}/{urllib.parse.quote(source.repository)}"
        metadata = self._request(base)
        ref = source.ref or str(metadata.get("default_branch") or "HEAD")
        if source.kind == GITHUB_RELEASE and source.ref == "latest":
            release = self._request(f"{base}/releases/latest")
            ref = str(release.get("tag_name") or "")
            if not ref:
                raise SourceError("Latest GitHub release has no inspectable tag.")
            metadata = {**metadata, "release": {
                "tag_name": ref, "published_at": release.get("published_at"),
                "draft": release.get("draft"), "prerelease": release.get("prerelease"),
            }}
        commit_row = self._request(f"{base}/commits/{urllib.parse.quote(ref, safe='')}")
        commit_sha = str(commit_row.get("sha") or "")
        if not commit_sha:
            raise SourceError("GitHub reference did not resolve to a commit.")
        if source.kind == GITHUB_FILE:
            encoded = urllib.parse.quote(source.subpath, safe="/")
            item = self._request(f"{base}/contents/{encoded}?ref={urllib.parse.quote(ref)}")
            if item.get("encoding") != "base64":
                raise SourceError("GitHub file content was not available as bounded text.")
            raw = base64.b64decode(item.get("content") or "", validate=False)
            if len(raw) > self.MAX_FILE_BYTES:
                raise SourceError("GitHub file exceeds the bounded inspection size.")
            metadata = {**metadata, "blob_sha": str(item.get("sha") or "")}
            return RepositorySnapshot(source, {source.subpath: raw.decode("utf-8", errors="replace")},
                                      [source.subpath], [], metadata, commit_sha, False, len(raw))

        tree = self._request(f"{base}/git/trees/{urllib.parse.quote(ref, safe='')}?recursive=1")
        rows = [row for row in tree.get("tree", []) if row.get("type") == "blob"]
        prefix = source.subpath.rstrip("/") + "/" if source.kind == GITHUB_DIRECTORY and source.subpath else ""
        if prefix:
            rows = [row for row in rows if str(row.get("path") or "").startswith(prefix)]
        paths = [str(row.get("path") or "") for row in rows]
        selected = sorted(rows, key=lambda row: self._priority(str(row.get("path") or "")))[:self.MAX_FILES]
        files: dict[str, str] = {}
        binary: list[str] = []
        total = 0
        for row in selected:
            path = str(row.get("path") or "")
            size = int(row.get("size") or 0)
            if size > self.MAX_FILE_BYTES or not self._is_text(path):
                binary.append(path)
                continue
            blob = self._request(str(row.get("url") or ""))
            if blob.get("encoding") != "base64":
                continue
            raw = base64.b64decode(blob.get("content") or "", validate=False)
            if total + len(raw) > self.MAX_TOTAL_BYTES:
                break
            files[path] = raw.decode("utf-8", errors="replace")
            total += len(raw)
        metadata = {key: metadata.get(key) for key in (
            "full_name", "description", "default_branch", "archived", "disabled",
            "fork", "pushed_at", "stargazers_count", "open_issues_count", "license", "release",
        )}
        return RepositorySnapshot(source, files, paths, binary, metadata,
                                  commit_sha,
                                  bool(tree.get("truncated") or len(rows) > len(selected)), total)

    @staticmethod
    def _priority(path: str) -> tuple[int, int, str]:
        name = PurePosixPath(path).name.casefold()
        if name in _PRIORITY_NAMES or path.casefold().startswith(".github/workflows/"):
            return (0, len(path), path)
        return (1 if GitHubImportEngine._is_text(path) else 2, len(path), path)

    @staticmethod
    def _is_text(path: str) -> bool:
        name = PurePosixPath(path).name.casefold()
        return name in _PRIORITY_NAMES or Path(name).suffix in _TEXT_SUFFIXES

    def _local(self, source: SourceReference) -> RepositorySnapshot:
        root = Path(source.local_path)
        if root.is_file() and (root.suffix.casefold() in {".zip", ".whl"}):
            return self._zip(source, root)
        if root.is_file() and (root.suffix.casefold() in {".tar", ".tgz"}
                               or root.name.casefold().endswith(".tar.gz")):
            return self._tar(source, root)
        paths = iter((root,)) if root.is_file() else (item for item in root.rglob("*") if item.is_file())
        files: dict[str, str] = {}
        all_paths: list[str] = []
        binary: list[str] = []
        total = 0
        truncated = False
        for item in paths:
            if root.is_dir():
                try:
                    item.resolve().relative_to(root.resolve())
                except ValueError:
                    continue
            rel = item.name if root.is_file() else item.relative_to(root).as_posix()
            if set(PurePosixPath(rel).parts) & _SKIP_PARTS:
                continue
            if len(all_paths) >= self.MAX_FILES * 5:
                truncated = True
                break
            all_paths.append(rel)
            if item.stat().st_size > self.MAX_FILE_BYTES or not self._is_text(rel):
                binary.append(rel)
                continue
            raw = item.read_bytes()
            if total + len(raw) > self.MAX_TOTAL_BYTES:
                truncated = True
                break
            files[rel] = raw.decode("utf-8", errors="replace")
            total += len(raw)
        return RepositorySnapshot(source, files, all_paths, binary,
                                  {"local": True}, "", truncated, total)

    def _zip(self, source: SourceReference, path: Path) -> RepositorySnapshot:
        files: dict[str, str] = {}
        all_paths: list[str] = []
        binary: list[str] = []
        total = 0
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist()[: self.MAX_FILES * 5]:
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise SourceError("Archive contains an unsafe path and was rejected.")
                if info.is_dir():
                    continue
                name = member.as_posix()
                all_paths.append(name)
                if info.file_size > self.MAX_FILE_BYTES or not self._is_text(name):
                    binary.append(name)
                    continue
                raw = archive.read(info)
                if total + len(raw) > self.MAX_TOTAL_BYTES:
                    break
                files[name] = raw.decode("utf-8", errors="replace")
                total += len(raw)
        return RepositorySnapshot(source, files, all_paths, binary,
                                  {"archive": path.name}, "", len(all_paths) >= self.MAX_FILES * 5, total)

    def _tar(self, source: SourceReference, path: Path) -> RepositorySnapshot:
        files: dict[str, str] = {}
        all_paths: list[str] = []
        binary: list[str] = []
        total = 0
        with tarfile.open(path, mode="r:*") as archive:
            members = archive.getmembers()[: self.MAX_FILES * 5]
            for info in members:
                member = PurePosixPath(info.name.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise SourceError("Archive contains an unsafe path and was rejected.")
                if not info.isfile():
                    continue
                name = member.as_posix()
                all_paths.append(name)
                if info.size > self.MAX_FILE_BYTES or not self._is_text(name):
                    binary.append(name)
                    continue
                handle = archive.extractfile(info)
                if handle is None:
                    continue
                raw = handle.read(self.MAX_FILE_BYTES + 1)
                if len(raw) > self.MAX_FILE_BYTES:
                    binary.append(name)
                    continue
                if total + len(raw) > self.MAX_TOTAL_BYTES:
                    break
                files[name] = raw.decode("utf-8", errors="replace")
                total += len(raw)
        return RepositorySnapshot(source, files, all_paths, binary,
                                  {"archive": path.name}, "", len(members) >= self.MAX_FILES * 5, total)
