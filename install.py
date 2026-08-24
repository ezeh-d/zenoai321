"""ZENO/REYES dependency installer.

The installer is deliberately conservative: it installs declared capability
groups but never upgrades an already-compatible environment unless
``--upgrade`` is explicitly supplied. Optional catalog integrations are a
small, supported adapter set -- not every repository named in the research
catalog.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent
IS_WIN = sys.platform.startswith("win")

GROUPS: dict[str, list[str]] = {
    "core (terminal brain)": [
        "litellm>=1.40", "pydantic-settings>=2.0", "python-dotenv>=1.0",
        "requests>=2.31", "psutil>=5.9",
    ],
    "GUI HUD": ["PySide6>=6.6"],
    "voice": [
        "SpeechRecognition>=3.10", "PyAudio>=0.2.14", "pyttsx3>=2.90",
        "faster-whisper>=1.0", "onnxruntime>=1.17", "soundfile>=0.12",
    ],
    "automation": ["pyautogui>=0.9.54", "pyperclip>=1.8", "mss>=9.0"],
    "browser": ["playwright>=1.44"],
}

WINDOWS_ONLY = ["pycaw>=20240210", "comtypes>=1.4"]

# Optional packages with an existing ZENO adapter and a small dependency
# footprint. Heavy/duplicative catalog entries (Torch stacks, competing agent
# frameworks, extra vector databases, untrusted MCP servers) stay feature-
# flagged and are not installed into the production runtime automatically.
CATALOG_SAFE = [
    "pywinauto>=0.6.9,<0.7; sys_platform == 'win32'",
    "PyMuPDF>=1.26,<2",
    "python-docx>=1.1,<2",
    "openpyxl>=3.1,<4",
    "python-pptx>=1.0,<2",
]

EXTRAS = [
    "openwakeword>=0.6,<0.7",
    "opencv-python>=4.10,<5",
    "duckduckgo-search>=6,<9",
]
MINIMAL_ONLY = {"core (terminal brain)"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install ZENO dependency groups without destabilizing compatible packages.",
    )
    parser.add_argument("--minimal", action="store_true",
                        help="install only the terminal brain")
    parser.add_argument("--all", action="store_true",
                        help="install supported catalog adapters and optional extras")
    parser.add_argument("--catalog-safe", action="store_true",
                        help="install only the lightweight catalog adapters ZENO implements")
    parser.add_argument("--venv", action="store_true",
                        help="create .venv and print the command to continue")
    parser.add_argument("--upgrade", action="store_true",
                        help="allow pip to upgrade packages (off by default for stability)")
    parser.add_argument("--upgrade-pip", action="store_true",
                        help="upgrade pip explicitly")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the operations without changing the environment")
    parser.add_argument("--skip-browser-download", action="store_true",
                        help="do not run Playwright's Chromium installer")
    parser.add_argument("--skip-doctor", action="store_true",
                        help="do not run the read-only environment doctor")
    return parser


def _run(command: Sequence[str], *, dry_run: bool = False) -> bool:
    print("   $", subprocess.list2cmdline(list(command)))
    if dry_run:
        return True
    return subprocess.run(list(command), check=False).returncode == 0


def pip_install(pkgs: list[str], *, upgrade: bool = False,
                dry_run: bool = False) -> bool:
    """Install one bounded dependency group and return its real result."""
    if not pkgs:
        return True
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if upgrade:
        command.append("--upgrade")
    command.extend(pkgs)
    return _run(command, dry_run=dry_run)


def ensure_pip(*, upgrade: bool = False, dry_run: bool = False) -> bool:
    if upgrade:
        return _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                    dry_run=dry_run)
    return _run([sys.executable, "-m", "pip", "--version"], dry_run=dry_run)


def make_venv(*, dry_run: bool = False) -> bool:
    venv_dir = ROOT / ".venv"
    if venv_dir.exists():
        print(f".venv already exists at {venv_dir}")
        ok = True
    else:
        print("Creating virtual environment in .venv ...")
        ok = _run([sys.executable, "-m", "venv", str(venv_dir)], dry_run=dry_run)
    py = venv_dir / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
    print("\nVirtual environment ready. Re-run the installer with it:")
    print(f"   {py} install.py")
    return ok


def setup_env(*, dry_run: bool = False) -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        print(".env already present - leaving it unchanged.")
    elif example.exists():
        if not dry_run:
            env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Would create" if dry_run else "Created", ".env from .env.example.")
    else:
        print("No .env.example found; skipping .env creation.")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.minimal and (args.all or args.catalog_safe):
        _parser().error("--minimal cannot be combined with --all/--catalog-safe")
    if args.venv:
        return 0 if make_venv(dry_run=args.dry_run) else 1

    catalog_only = args.catalog_safe and not args.all

    print(f"ZENO installer - Python {sys.version_info.major}.{sys.version_info.minor} "
          f"- {sys.platform}\n")
    if not ensure_pip(upgrade=args.upgrade_pip, dry_run=args.dry_run):
        print("pip is unavailable; no packages were changed.")
        return 1

    results: dict[str, bool] = {}
    for name, pkgs in GROUPS.items():
        if catalog_only:
            continue
        if args.minimal and name not in MINIMAL_ONLY:
            continue
        print(f"\nInstalling {name} ...")
        results[name] = pip_install(pkgs, upgrade=args.upgrade, dry_run=args.dry_run)

    if IS_WIN and not args.minimal and not catalog_only:
        print("\nInstalling Windows audio adapters ...")
        results["windows audio"] = pip_install(
            WINDOWS_ONLY, upgrade=args.upgrade, dry_run=args.dry_run)

    if args.catalog_safe or args.all:
        print("\nInstalling supported lightweight catalog adapters ...")
        results["catalog-safe adapters"] = pip_install(
            CATALOG_SAFE, upgrade=args.upgrade, dry_run=args.dry_run)

    if args.all:
        print("\nInstalling optional extras ...")
        results["optional extras"] = pip_install(
            EXTRAS, upgrade=args.upgrade, dry_run=args.dry_run)

    if (not args.minimal and not args.skip_browser_download
            and results.get("browser")):
        print("\nEnsuring Playwright Chromium is available ...")
        results["Playwright Chromium"] = _run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            dry_run=args.dry_run,
        )

    print("\n" + "=" * 54)
    print("Install summary:")
    for name, ok in results.items():
        print(f"   {'OK' if ok else 'FAILED':6} {name}")
    print("=" * 54)

    if not args.minimal and not catalog_only:
        setup_env(dry_run=args.dry_run)

    if not args.skip_doctor and not args.dry_run:
        print("\nRunning the read-only doctor ...\n")
        results["doctor"] = _run([sys.executable, str(ROOT / "doctor.py")])

    if not args.dry_run:
        print("\nChecking dependency consistency ...")
        results["pip check"] = _run([sys.executable, "-m", "pip", "check"])

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        print("\nFailed groups:", ", ".join(failed))
        return 1
    print("\nDone. Start ZENO with: python start.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
