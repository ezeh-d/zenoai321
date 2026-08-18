"""Every environment variable the code reads must exist in .env.example.

WHY THIS IS A SECURITY CHECK AND NOT A DOCUMENTATION CHORE
----------------------------------------------------------
An undocumented variable is a variable the owner cannot know to set. The
failure does not appear here -- it appears in production, as a feature that
silently took its default. For a social system that default might be
"publishing disabled", which is safe, or it might be a missing token that
turns a verified publish into an unverified one, which is not.

.env.example is the contract. This enforces it mechanically.

WHAT IT DELIBERATELY IGNORES
----------------------------
Standard variables owned by the operating system or the runtime
(LOCALAPPDATA, PATH, HOME), and pytest/CI variables. ZENO does not document
Windows.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"

# Owned by the OS, the runtime, or the CI provider -- not by ZENO.
EXTERNAL = {
    "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "SYSTEMROOT",
    "COMPUTERNAME", "USERNAME", "USERDOMAIN", "NUMBER_OF_PROCESSORS",
    "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONHASHSEED",
    "VIRTUAL_ENV", "CONDA_PREFIX", "COMSPEC", "SHELL", "TERM", "LANG",
    "CI", "GITHUB_ACTIONS", "GITHUB_TOKEN", "GITHUB_SHA", "GITHUB_REF",
    "RUNNER_OS", "PYTEST_CURRENT_TEST", "NO_COLOR", "DISPLAY",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY",
    "NO_PROXY", "TZ", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY",
}

# os.environ.get("X"), os.environ["X"], os.getenv("X")
PATTERNS = (
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]"""),
    re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    # config.py's own helpers
    re.compile(r"""_flag\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""_env\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
)


def documented() -> set[str]:
    if not EXAMPLE.exists():
        print(f"::error::{EXAMPLE.name} does not exist")
        raise SystemExit(1)
    names = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # A commented-out variable still documents it -- "# MEM0_API_KEY="
        # tells the owner the name and that it is optional.
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        if "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                names.add(name)
    return names


def used() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    here = Path(__file__).resolve()
    for path in list(ROOT.joinpath("reyes_agent").rglob("*.py")) + \
                list(ROOT.joinpath("tools").rglob("*.py")):
        # This file's own docstring contains example patterns; scanning it
        # would report the examples as undocumented variables.
        if "__pycache__" in str(path) or path.resolve() == here:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in PATTERNS:
            for name in pattern.findall(text):
                if name in EXTERNAL:
                    continue
                found.setdefault(name, set()).add(
                    str(path.relative_to(ROOT)).replace("\\", "/"))
    return found


def main() -> int:
    known = documented()
    references = used()
    missing = {name: files for name, files in references.items() if name not in known}

    print(f"{len(known)} variables documented in .env.example")
    print(f"{len(references)} variables read by the code")

    if not missing:
        print("every environment variable the code reads is documented.")
        return 0

    print(f"\n{len(missing)} undocumented variable(s):")
    for name in sorted(missing):
        where = ", ".join(sorted(missing[name])[:3])
        print(f"  ::error::{name} -- read in {where}")
    print("\nAdd each to .env.example (an empty or commented entry is fine).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
