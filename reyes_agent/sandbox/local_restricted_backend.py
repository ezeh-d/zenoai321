"""Bounded local process fallback.

This is useful for trusted generated calculations. It deliberately reports
that policy restriction is *not* equivalent to a container/VM boundary.
Truly untrusted code requires AIO Sandbox or E2B.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .interface import SandboxResult
from .policy import inspect_python


class LocalRestrictedBackend:
    name = "local-restricted"

    @staticmethod
    def status() -> dict:
        return {"state": "PARTIAL", "available": True, "backend": "local-restricted",
                "containment": "policy + clean environment + workspace cwd; not an OS security boundary",
                "untrusted_code": False}

    def execute_python(self, script: str, *, workspace: str, timeout_s: float = 45.0) -> SandboxResult:
        started = time.perf_counter()
        root = Path(workspace).resolve(strict=True)
        target = Path(script).resolve(strict=True)
        if root not in target.parents or target.suffix.casefold() != ".py":
            return SandboxResult(False, "DENIED", self.name, None, "", "script is outside the mounted workspace",
                                 int((time.perf_counter() - started) * 1000), self.status()["containment"])
        source = target.read_text(encoding="utf-8", errors="replace")
        allowed, reason = inspect_python(source)
        if not allowed:
            return SandboxResult(False, "DENIED", self.name, None, "", reason,
                                 int((time.perf_counter() - started) * 1000), self.status()["containment"])
        clean_env = {key: value for key, value in os.environ.items()
                     if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        clean_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1", "ZENO_SANDBOX": "1"})
        try:
            proc = subprocess.run([sys.executable, "-I", str(target)], cwd=root, env=clean_env,
                                  capture_output=True, text=True,
                                  timeout=max(1.0, min(float(timeout_s), 120.0)), shell=False,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0
            return SandboxResult(ok, "COMPLETED" if ok else "FAILED", self.name, proc.returncode,
                                 proc.stdout[:1_000_000], proc.stderr[:1_000_000],
                                 int((time.perf_counter() - started) * 1000), self.status()["containment"],
                                 verified=ok)
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(False, "TIMED_OUT", self.name, None,
                                 str(exc.stdout or "")[:1_000_000], str(exc.stderr or "")[:1_000_000],
                                 int((time.perf_counter() - started) * 1000), self.status()["containment"])
