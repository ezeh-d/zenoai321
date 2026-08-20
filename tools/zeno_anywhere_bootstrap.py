"""Stable Task Scheduler entry point for ZENO Anywhere.

Task Scheduler does not guarantee the repository is the working directory.
This tiny launcher establishes that invariant before importing the supervisor.
It contains no credentials and is safe to reference by absolute path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Task Scheduler launches this file with ``-S``.  Reintroduce only the venv's
# packages.  Loading the global sitecustomize imports most of pip before our
# code runs and can stall pythonw for minutes under machine pressure.
if sys.flags.no_site:
    site_packages = ROOT / ".venv" / "Lib" / "site-packages"
    if site_packages.is_dir() and str(site_packages) not in sys.path:
        sys.path.insert(0, str(site_packages))

from reyes_agent.remote_access.anywhere import _main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(_main(["run"]))
