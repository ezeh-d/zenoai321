"""One launcher for ZENO's authoritative front doors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BANNER = r"""
  ______  ______ _   _  ____
 |___  / |  ____| \ | |/ __ \
    / /  | |__  |  \| | |  | |
   / /   |  __| | . ` | |  | |
  / /__  | |____| |\  | |__| |
 /_____| |______|_| \_|\____/   launcher
"""

MENU = [
    ("ZENO desktop", "Mini Orb + lazy dashboard (recommended)", ["-m", "reyes_agent.desktop_app"]),
    ("Terminal assistant", "Same ZENO brain in this window", ["-m", "reyes_agent.cli"]),
    ("Voice terminal", "Push-to-talk front door", ["-m", "reyes_agent.voice_cli"]),
    ("Local web backend", "Loopback diagnostics; not a remote bridge", ["-m", "reyes_agent.web"]),
    ("Telegram remote", "Authenticated Telegram bot integration", ["-m", "reyes_agent.telegram_bridge"]),
    ("Doctor (preflight)", "Check installed and configured components", ["doctor.py"]),
]


def _run(args: list[str]) -> int:
    command = [sys.executable, *(
        [str(ROOT / args[0])] if args[0].endswith(".py") else args
    )]
    print(f"\nLaunching: {' '.join(command[1:])}\n")
    try:
        return subprocess.call(command, cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


def _pick(choice: str) -> int | None:
    if not choice.isdigit():
        return None
    index = int(choice) - 1
    return index if 0 <= index < len(MENU) else None


def main() -> None:
    print(BANNER)
    if len(sys.argv) > 1:
        index = _pick(sys.argv[1])
        if index is not None:
            raise SystemExit(_run(MENU[index][2]))
    for number, (name, description, _) in enumerate(MENU, 1):
        print(f"  {number}. {name:<22} {description}")
    print("  0. Quit")
    while True:
        try:
            choice = input(f"\nChoose a mode [0-{len(MENU)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice.casefold() in {"0", "q", "quit", "exit"}:
            return
        index = _pick(choice)
        if index is None:
            print("  Please enter a number from the list.")
            continue
        _run(MENU[index][2])
        return


if __name__ == "__main__":
    main()
