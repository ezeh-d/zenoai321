"""Fast, deterministic bootstrap for the desktop-owned ZENO backend.

This child is deliberately launched with ``pythonw -S``.  It restores only
ZENO's virtual-environment site-packages, avoiding the machine-global startup
hook that can otherwise stall before :mod:`reyes_agent.web` is imported.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"


def _prepare() -> None:
    os.chdir(ROOT)
    if SITE_PACKAGES.is_dir():
        # Process only this venv's trusted .pth files (not the machine-global
        # sitecustomize). pywin32 needs its venv-local DLL paths for DPAPI.
        site.addsitedir(str(SITE_PACKAGES))
    paths = [str(ROOT)]
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)


def main() -> None:
    _prepare()
    from reyes_agent.web import main as run_web

    run_web()


if __name__ == "__main__":
    main()
