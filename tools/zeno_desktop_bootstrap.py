"""Fast, deterministic bootstrap for the native ZENO desktop shell.

The workstation has a global ``sitecustomize`` that imports a large part of
pip before application code runs.  Under memory pressure that work can park a
``pythonw`` process for minutes, before ZENO can render or write diagnostics.
``Open REYES.bat`` starts this file with ``-S`` and this bootstrap adds only
the repository plus its own virtual-environment packages.
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
    from reyes_agent.desktop_app import main as run_desktop

    run_desktop()


if __name__ == "__main__":
    main()
