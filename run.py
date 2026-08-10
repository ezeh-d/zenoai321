"""Compatibility launcher for the authoritative ZENO terminal front door."""

from __future__ import annotations


def main() -> None:
    from reyes_agent.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
