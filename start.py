"""
REYES launcher — one friendly entry point.

Run:  python start.py

Pick a mode from the menu instead of remembering separate commands. Pass a
number as an argument to skip the menu, e.g.  python start.py 1
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BANNER = r"""
  ____  _____ _   _ _____ ____
 |  _ \| ____| | | | ____/ ___|
 | |_) |  _| | | | |  _| \___ \
 |  _ <| |___| |_| | |___ ___) |
 |_| \_\_____|\___/|_____|____/   launcher
"""

MENU = [
    ("Terminal assistant", "Chat with REYES in this window", ["run.py"]),
    ("Voice assistant", "Always-on — call his name to talk", ["assistant.py"]),
    ("HUD (graphical)", "The futuristic desktop interface", ["main.py"]),
    ("Mobile bridge", "Open REYES on your phone (same Wi-Fi)", ["server.py"]),
    ("Telegram remote", "Control REYES from Telegram", ["-m", "mobile.telegram_bridge"]),
    ("Doctor (preflight)", "Check what's installed / what each mode needs", ["doctor.py"]),
]


def _ensure_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _run(args: list[str]) -> int:
    """Launch a mode as a child process using the same Python interpreter."""
    cmd = [sys.executable, *([str(ROOT / args[0])] if args[0].endswith(".py") else args)]
    print(f"\n▶ launching: {' '.join(a.split('/')[-1] for a in cmd[1:])}\n")
    try:
        return subprocess.call(cmd, cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


def _pick(choice: str) -> int | None:
    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    return idx if 0 <= idx < len(MENU) else None


def main() -> None:
    _ensure_path()
    print(BANNER)

    # allow: python start.py 1
    if len(sys.argv) > 1:
        idx = _pick(sys.argv[1])
        if idx is not None:
            sys.exit(_run(MENU[idx][2]))

    for i, (name, desc, _) in enumerate(MENU, 1):
        print(f"  {i}. {name:<22} {desc}")
    print("  0. Quit")

    while True:
        try:
            choice = input(f"\nChoose a mode [0-{len(MENU)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in ("0", "q", "quit", "exit"):
            return
        idx = _pick(choice)
        if idx is None:
            print("  Please enter a number from the list.")
            continue
        _run(MENU[idx][2])
        break


if __name__ == "__main__":
    main()
