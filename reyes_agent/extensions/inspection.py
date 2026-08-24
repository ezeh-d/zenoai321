"""Static repository, security, license, compatibility and usefulness review."""

from __future__ import annotations

import ast
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any

from reyes_agent.extensions.models import (
    Component, CompatibilityReport, Finding, InspectionReport, IntegrationPlan,
    PermissionProfile, RepositorySnapshot,
)

_LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".jsx": "JavaScript", ".rs": "Rust", ".go": "Go",
    ".java": "Java", ".cs": "C#", ".php": "PHP", ".sh": "Shell", ".ps1": "PowerShell",
}
_MANIFESTS = {
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "dockerfile",
    "docker-compose.yml", "mcp.json", "plugin.json", "skill.md",
}
_PROHIBITED = re.compile(
    r"(?i)\b(?:credential theft|steal (?:passwords?|cookies?|tokens?)|phish(?:ing|er)?|"
    r"ransomware|keylog(?:ger|ging)?|ddos|sms bomber|spam bomber|remote access trojan|"
    r"covert (?:surveillance|tracking)|camera hijack|location tracking|rootkit|botnet)\b"
)
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"),
)
_ENDPOINT = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")


class RepositoryStructureAnalyzer:
    def analyze(self, snapshot: RepositorySnapshot) -> tuple[str, ...]:
        paths = {path.casefold() for path in snapshot.all_paths}
        names = {PurePosixPath(path).name.casefold() for path in snapshot.all_paths}
        kinds: list[str] = []
        package = self._package_json(snapshot)
        if "mcp.json" in names or any("mcp" in name and name.endswith(("server.py", "server.js", "server.ts")) for name in names):
            kinds.append("MCP_SERVER")
        if "package.json" in names and ("bin" in package or any("cli" in path for path in paths)):
            kinds.append("CLI")
        if any(name in names for name in ("setup.py", "pyproject.toml", "package.json")):
            kinds.append("LIBRARY")
        if any(name in names for name in ("dockerfile", "docker-compose.yml")) or any("server" in name for name in names):
            kinds.append("SERVER")
        if any(path.endswith(("app.html", "index.html")) for path in paths):
            kinds.append("FRONTEND")
        if any(path.endswith(("main.py", "app.py", "index.js", "server.py")) for path in paths):
            kinds.append("BACKEND")
        if any("plugin" in name for name in names):
            kinds.append("PLUGIN")
        if "skill.md" in names:
            kinds.append("SKILL")
        if any("agent" in path for path in paths):
            kinds.append("AGENT")
        return tuple(dict.fromkeys(kinds or ["UTILITY"]))

    @staticmethod
    def _package_json(snapshot: RepositorySnapshot) -> dict[str, Any]:
        item = next((text for path, text in snapshot.files.items()
                     if PurePosixPath(path).name.casefold() == "package.json"), "")
        try:
            return json.loads(item) if item else {}
        except ValueError:
            return {}


class RepositoryInspector:
    def __init__(self) -> None:
        self.structure_analyzer = RepositoryStructureAnalyzer()

    def inspect(self, snapshot: RepositorySnapshot) -> InspectionReport:
        languages: dict[str, int] = {}
        manifests: list[str] = []
        entrypoints: list[str] = []
        dependencies: set[str] = set()
        findings: list[Finding] = []
        endpoints: set[str] = set()
        capabilities: set[str] = set()
        permission = {
            "filesystem": "NONE", "network": set(), "camera": False,
            "microphone": False, "browser": False, "desktop": False,
            "messages": False, "accounts": set(), "location": False,
            "subprocess": False,
        }
        combined_docs = ""
        for path, text in snapshot.files.items():
            name = PurePosixPath(path).name.casefold()
            suffix = PurePosixPath(path).suffix.casefold()
            language = _LANGUAGES.get(suffix)
            if language:
                languages[language] = languages.get(language, 0) + 1
            if name in _MANIFESTS or path.casefold().startswith(".github/workflows/"):
                manifests.append(path)
            if name in {"main.py", "app.py", "cli.py", "index.js", "server.js", "server.py", "__main__.py"}:
                entrypoints.append(path)
            if name.startswith(("readme", "security")):
                combined_docs += "\n" + text[:200_000]
            endpoints.update(item.rstrip("'\"),.;") for item in _ENDPOINT.findall(text[:500_000]))
            self._inspect_text(path, text, findings, permission)
            dependencies.update(self._dependencies(name, text))
        if snapshot.binary_paths:
            findings.append(Finding("HIGH", "binary", f"{len(snapshot.binary_paths)} binary/unreadable files require independent provenance review."))
        purpose = " ".join((snapshot.source.original, str(snapshot.metadata.get("description") or ""), combined_docs[:400_000]))
        if _PROHIBITED.search(purpose):
            findings.append(Finding("CRITICAL", "prohibited_purpose",
                                    "Repository describes a prohibited purpose such as credential theft, phishing, malware, covert surveillance or indiscriminate disruption."))
        if snapshot.truncated:
            findings.append(Finding("HIGH", "inspection_coverage",
                                    "Inspection was bounded/truncated; uninspected source cannot be promoted."))
        license_name, implication = self._license(snapshot)
        structures = self.structure_analyzer.analyze(snapshot)
        capabilities.update(item.casefold() for item in structures)
        for name in dependencies:
            token = re.split(r"[<>=!~\[\]]", name, 1)[0].strip().casefold()
            if token:
                capabilities.add(token)
        profile = PermissionProfile(
            filesystem=permission["filesystem"], network=tuple(sorted(permission["network"])),
            camera=permission["camera"], microphone=permission["microphone"],
            browser=permission["browser"], desktop=permission["desktop"],
            messages=permission["messages"], accounts=tuple(sorted(permission["accounts"])),
            location=permission["location"], subprocess=permission["subprocess"],
        )
        dependency_rows = list(dependencies)
        unpinned = [item for item in dependency_rows if self._is_unpinned(item)]
        install_scripts = sum(
            text.casefold().count(marker)
            for path, text in snapshot.files.items()
            if PurePosixPath(path).name.casefold() == "package.json"
            for marker in ('"preinstall"', '"install"', '"postinstall"')
        )
        if install_scripts:
            findings.append(Finding("HIGH", "install_script",
                                    "Package lifecycle install scripts require isolated manual review."))
        if unpinned:
            findings.append(Finding("MEDIUM", "unpinned_dependencies",
                                    f"{len(unpinned)} dependencies are not exactly pinned."))
        supply_chain = {
            "dependency_count": len(dependency_rows),
            "unpinned_count": len(unpinned),
            "install_script_count": install_scripts,
            "lockfiles": sorted(path for path in manifests if "lock" in path.casefold()),
            "known_vulnerability_scan": "NOT_RUN_NO_ADVISORY_PROVIDER",
            "note": "Static review is not a live vulnerability/advisory database lookup.",
        }
        return InspectionReport(
            structures, languages, tuple(sorted(manifests)), tuple(sorted(dependencies)),
            tuple(sorted(entrypoints)), license_name, implication, profile,
            tuple(findings), tuple(sorted(endpoints))[:100], tuple(sorted(capabilities))[:100],
            "PARTIAL" if snapshot.truncated else "COMPLETE_WITHIN_BOUNDS", supply_chain,
        )

    @staticmethod
    def _is_unpinned(dependency: str) -> bool:
        value = dependency.strip()
        if value.startswith("npm:"):
            version = value.rsplit("@", 1)[-1]
            return not bool(re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?", version))
        return "==" not in value

    def _inspect_text(self, path: str, text: str, findings: list[Finding], permission: dict[str, Any]) -> None:
        folded = text.casefold()
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(Finding("CRITICAL", "hard_coded_secret", "Possible embedded credential or private key.", path))
                break
        behavior = (
            ("credential_access", "HIGH", ("login data", "cookies.sqlite", "keychain", "credential manager", "browser cookies")),
            ("persistence", "HIGH", ("currentversion\\run", "schtasks", "startup folder", "launch agent", "systemd")),
            ("privilege_escalation", "HIGH", ("runas", "sudo ", "se_debug_privilege", "uac bypass")),
            ("shell_execution", "MEDIUM", ("subprocess.", "os.system(", "child_process", "shell=true", "powershell -")),
            ("dynamic_download", "MEDIUM", ("wget ", "curl ", "invoke-webrequest", "downloadfile(")),
            ("location", "HIGH", ("geolocation", "gps", "latitude", "longitude")),
            ("camera", "HIGH", ("getusermedia", "videocapture", "camera")),
            ("microphone", "HIGH", ("microphone", "audiorecord", "pyaudio")),
        )
        for category, severity, markers in behavior:
            if any(marker in folded for marker in markers):
                findings.append(Finding(severity, category, f"Static marker for {category.replace('_', ' ')}; requires least-privilege review.", path))
        if any(marker in folded for marker in ("subprocess.", "os.system(", "child_process", "shell=true")):
            permission["subprocess"] = True
        if _ENDPOINT.search(text):
            permission["network"].update(urllib_host(item) for item in _ENDPOINT.findall(text) if urllib_host(item))
        if any(marker in folded for marker in ("open(", "read_text(", "write_text(", "readfile", "writefile")):
            permission["filesystem"] = "PROJECT_ONLY"
        permission["camera"] |= any(marker in folded for marker in ("getusermedia", "videocapture", "camera"))
        permission["microphone"] |= any(marker in folded for marker in ("microphone", "audiorecord", "pyaudio"))
        permission["browser"] |= any(marker in folded for marker in ("playwright", "selenium", "puppeteer"))
        permission["desktop"] |= any(marker in folded for marker in ("pyautogui", "pywinauto", "uiautomation"))
        permission["location"] |= any(marker in folded for marker in ("geolocation", "latitude", "longitude"))

    @staticmethod
    def _dependencies(name: str, text: str) -> set[str]:
        if name == "requirements.txt":
            return {line.strip() for line in text.splitlines()
                    if line.strip() and not line.lstrip().startswith(("#", "-"))}
        if name == "package.json":
            try:
                package = json.loads(text)
                return {f"npm:{key}@{value}" for group in ("dependencies", "devDependencies", "peerDependencies")
                        for key, value in (package.get(group) or {}).items()}
            except (TypeError, ValueError):
                return set()
        return set()

    @staticmethod
    def _license(snapshot: RepositorySnapshot) -> tuple[str, str]:
        license_text = "\n".join(text for path, text in snapshot.files.items()
                                 if PurePosixPath(path).name.casefold().startswith(("license", "copying")))[:200_000].casefold()
        metadata = snapshot.metadata.get("license") or {}
        spdx = str(metadata.get("spdx_id") if isinstance(metadata, dict) else metadata or "").upper()
        if "AGPL" in spdx or "affero" in license_text:
            return "AGPL", "Network copyleft; do not copy code into ZENO without an explicit license decision."
        if "GPL" in spdx or "gnu general public license" in license_text:
            return "GPL", "Copyleft obligations require an explicit compatibility decision before copying."
        if "APACHE" in spdx or "apache license" in license_text:
            return "Apache-2.0", "Permissive with notice/patent obligations."
        if "MIT" in spdx or "mit license" in license_text:
            return "MIT", "Permissive; retain copyright and license notice."
        if "BSD" in spdx or "redistribution and use in source and binary forms" in license_text:
            return "BSD", "Permissive; retain required notices."
        return "UNKNOWN", "Unknown/proprietary license: adapter use only; do not copy source."


class CompatibilityAnalyzer:
    def analyze(self, snapshot: RepositorySnapshot, report: InspectionReport) -> CompatibilityReport:
        docs = "\n".join(snapshot.files.values()).casefold()[:500_000]
        windows = "SUPPORTED"
        conflicts: list[str] = []
        requirements: list[str] = []
        if ("termux" in docs or "apt-get" in docs) and not any(name in report.languages for name in ("PowerShell", "C#")):
            windows = "INCOMPATIBLE_LINUX_OR_TERMUX_ONLY"
            conflicts.append("Repository appears to require Termux/Linux system tooling.")
        python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        node = self._node_version()
        for dependency in report.dependencies:
            if dependency.startswith("npm:"):
                continue
            package = re.split(r"[<>=!~\[\]]", dependency, 1)[0].strip()
            if not package:
                continue
            try:
                installed = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                requirements.append(f"isolated environment needs {dependency}")
            else:
                requirements.append(f"main environment has {package}=={installed}; extension requested {dependency}")
        compatible = windows == "SUPPORTED" and not any(item.severity == "CRITICAL" for item in report.findings)
        reason = "Compatible for isolated adapter evaluation." if compatible else "; ".join(conflicts) or "Critical security finding."
        return CompatibilityReport(compatible, windows, python, node, conflicts, requirements, reason)

    @staticmethod
    def _node_version() -> str:
        binary = shutil.which("node")
        if not binary:
            return "NOT_INSTALLED"
        try:
            return subprocess.run([binary, "--version"], capture_output=True, text=True,
                                  timeout=3, shell=False).stdout.strip()[:50] or "UNKNOWN"
        except Exception:
            return "UNKNOWN"


class UsefulComponentExtractor:
    def extract(self, snapshot: RepositorySnapshot, report: InspectionReport, focus: str = "") -> list[Component]:
        needle = str(focus or "").strip().casefold()
        components: list[Component] = []
        for structure in report.structure:
            paths = tuple(path for path in snapshot.all_paths
                          if not needle or needle in path.casefold())[:20]
            if needle and not paths and needle not in structure.casefold():
                continue
            components.append(Component(structure.casefold(), structure, paths,
                                        "Smallest bounded component matching repository structure and requested focus."))
        return components[:12]


class IntegrationPlanner:
    def __init__(self) -> None:
        self.extractor = UsefulComponentExtractor()

    def plan(self, snapshot: RepositorySnapshot, report: InspectionReport,
             compatibility: CompatibilityReport, focus: str = "") -> IntegrationPlan:
        components = self.extractor.extract(snapshot, report, focus)
        matches: list[str] = []
        try:
            from reyes_agent.tools.universal_registry import get_global_tool_registry
            registry = get_global_tool_registry()
            for capability in report.capabilities[:20]:
                matches.extend(item.metadata().name for item in registry.find_by_capability(capability)[:3])
        except Exception:
            pass
        matches = list(dict.fromkeys(matches))[:20]
        critical = any(item.severity == "CRITICAL" for item in report.findings)
        if critical:
            classification = "INCOMPATIBLE"
        elif not compatibility.compatible:
            classification = "INCOMPATIBLE"
        elif matches and not focus:
            classification = "DUPLICATE"
        elif matches:
            classification = "FALLBACK"
        elif components:
            classification = "NEW"
        else:
            classification = "NOT_NEEDED"
        adapter_kind = ("MCPAdapter" if "MCP_SERVER" in report.structure else
                        "CLIAdapter" if "CLI" in report.structure else
                        "CapabilityAdapter")
        reasons = []
        if matches:
            reasons.append("Existing ZENO capability matches must be benchmarked before replacement.")
        if report.license == "UNKNOWN":
            reasons.append("Unknown license prevents source copying; prefer a process/API adapter.")
        if snapshot.truncated:
            reasons.append("Bounded inspection did not cover every source file.")
        return IntegrationPlan(classification, components, matches, report.permissions,
                               adapter_kind, feature_flag_for(snapshot), False, reasons)


def feature_flag_for(snapshot: RepositorySnapshot) -> str:
    base = snapshot.source.repository or snapshot.source.package or PurePosixPath(snapshot.source.local_path).stem or "extension"
    slug = re.sub(r"[^a-z0-9]+", "_", base.casefold()).strip("_")[:50] or "extension"
    return f"extension_{slug}"


def urllib_host(value: str) -> str:
    try:
        from urllib.parse import urlparse
        return str(urlparse(value).hostname or "")
    except Exception:
        return ""
