"""Blender as a headless render backend, driven by its Python API.

Found through the install registry rather than PATH, because desktop
applications on Windows are not on PATH. Every render is verified after the
fact -- Blender exits 0 having written nothing often enough that the exit
code is not evidence.
"""

from __future__ import annotations

from reyes_agent.creative.blender import backend
from reyes_agent.creative.blender.backend import CYCLES, EEVEE, Result

__all__ = ["backend", "Result", "EEVEE", "CYCLES",
           "available", "executable", "render_spin", "run_script", "status"]

available = backend.available
executable = backend.executable
render_spin = backend.render_spin
run_script = backend.run_script
status = backend.status
