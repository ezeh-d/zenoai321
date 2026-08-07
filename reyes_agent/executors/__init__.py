"""Real executors -- the layer that makes an instruction happen.

Each module here does one kind of actual work and reports what it
observed, never what it intended:

* ``desktop``     -- resolve real Windows Known Folders (Desktop, Documents)
* ``filesystem``  -- atomic writes, verified after the fact
* ``terminal``    -- allow-listed processes with live output and exit codes
* ``coding``      -- syntax and reference checks over generated project files
* ``preview``     -- serve the project, open it, confirm it actually responds
* ``application`` -- open Explorer/editor/browser without stacking windows

The shared contract: an executor returns a result object carrying `ok` and
the evidence behind it. No executor returns success it did not observe, and
none of them print a step as done before doing it -- the Live Activity panel
is fed from these same observations (see ``reyes_agent.task_engine``).
"""

from __future__ import annotations

from reyes_agent.executors import application, coding, desktop, filesystem, preview, terminal

__all__ = ["application", "coding", "desktop", "filesystem", "preview", "terminal"]
