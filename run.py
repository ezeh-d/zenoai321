"""
Start REYES (terminal):  python run.py
Start the HUD:           python main.py

Puts the REYES folder on sys.path so all modules — brain, core, agents,
security, skills, memory, server — share one absolute-import model, then
hands off to the CLI.
"""
from __future__ import annotations
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import cli  # noqa: E402
    cli.main()


if __name__ == "__main__":
    main()
