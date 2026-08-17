"""Lazy Open Interpreter specialist adapter.

The process is finite, has no shell, inherits only a reduced environment, is
bounded by the managed worker timeout, and never enables auto-run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.coding_system import command_policy
from reyes_agent.coding_system.result_parser import parse_jsonl
from reyes_agent.coding_system.workspace import resolve_workspace
from reyes_agent.memory.privacy import redact


_MAX_STREAM_BYTES = 1_048_576


def _run_bounded(args: list[str], *, cwd: Path, env: dict[str, str], timeout_s: int) -> tuple[int, str, str, bool]:
    """Run without a shell and cap both captured streams."""
    process = subprocess.Popen(
        args, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = threading.Event()

    def drain(name: str, pipe: Any) -> None:
        try:
            while True:
                chunk = pipe.read(8192)
                if not chunk:
                    return
                remaining = _MAX_STREAM_BYTES - len(buffers[name])
                if remaining > 0:
                    buffers[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    # DAEMON. These are joined with a 5s timeout below, and a reader stuck on
    # a pipe that never closes would otherwise outlive that join and keep the
    # whole interpreter alive at exit -- which is how a "stopped" ZENO stays
    # in the process list and its microphone keeps listening.
    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout),
                         name="zeno-oi-stdout", daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr),
                         name="zeno-oi-stderr", daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        for reader in readers:
            reader.join(timeout=5)
    stdout = bytes(buffers["stdout"]).decode("utf-8", errors="replace")
    stderr = bytes(buffers["stderr"]).decode("utf-8", errors="replace")
    return return_code, stdout, stderr, overflow.is_set()


def _safe_environment() -> dict[str, str]:
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC",
               "PYTHONIOENCODING", "LANG", "LOCALAPPDATA", "APPDATA"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


class InterpreterClient:
    def __init__(self) -> None:
        self.enabled = os.environ.get("ZENO_OPEN_INTERPRETER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.command = os.environ.get("ZENO_OPEN_INTERPRETER_COMMAND", "interpreter").strip() or "interpreter"
        self.timeout_s = max(15, min(600, int(os.environ.get("ZENO_OPEN_INTERPRETER_TIMEOUT_S", "180"))))
        self._lock = threading.Lock()
        self._last: dict[str, Any] = {}

    def executable(self) -> str | None:
        return shutil.which(self.command)

    def run(self, goal: str, *, workspace: str | Path | None = None,
            read_only: bool = True) -> dict[str, Any]:
        decision = command_policy.classify(goal, read_only=read_only)
        if not decision.allowed:
            return {"ok": False, "blocked": True, "reason": decision.reason,
                    "autonomy_level": decision.autonomy_level}
        root = resolve_workspace(workspace)
        executable = self.executable()
        if not self.enabled or not executable:
            return {
                "ok": False, "available": False, "blocked": False,
                "reason": ("Open Interpreter is disabled" if not self.enabled else "Open Interpreter executable is not installed"),
                "fallback": "TOSIN's existing permission-gated file and command tools",
                "autonomy_level": decision.autonomy_level,
            }
        args = command_policy.safe_args(executable, goal, read_only=read_only, timeout_s=self.timeout_s)
        started = time.perf_counter()
        with self._lock:
            try:
                return_code, stdout, stderr, output_limited = _run_bounded(
                    args, cwd=root, env=_safe_environment(), timeout_s=self.timeout_s + 10,
                )
                parsed = parse_jsonl(stdout)
                result = {
                    "ok": return_code == 0 and not output_limited,
                    "available": True,
                    "return_code": return_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "workspace": str(root),
                    "purpose": redact(goal, limit=500),
                    "command": [Path(args[0]).name, *args[1:-1], "[GOAL]"],
                    "summary": parsed["final"],
                    "events": parsed["events"],
                    "stderr": redact(stderr, limit=4000),
                    "output_limited": output_limited,
                    "autonomy_level": decision.autonomy_level,
                }
                if output_limited:
                    result["reason"] = "Process output exceeded the 1 MiB safety limit and was stopped"
            except subprocess.TimeoutExpired:
                result = {"ok": False, "available": True, "reason": f"Timed out after {self.timeout_s}s",
                          "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                          "workspace": str(root), "autonomy_level": decision.autonomy_level}
            except Exception as exc:
                result = {"ok": False, "available": True,
                          "reason": f"{type(exc).__name__}: {redact(exc, limit=300)}",
                          "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                          "workspace": str(root), "autonomy_level": decision.autonomy_level}
            self._last = result
            self._audit(result)
            return result

    def _audit(self, result: dict[str, Any]) -> None:
        try:
            path = config.VAULT_PATH / "07-System" / "audit" / "coding_interpreter.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {key: result.get(key) for key in (
                "ok", "return_code", "duration_ms", "workspace", "purpose", "command", "autonomy_level", "reason")}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass

    def status(self) -> dict[str, Any]:
        executable = self.executable()
        return {
            "state": "READY" if self.enabled and executable else ("DISABLED" if not self.enabled else "UNAVAILABLE"),
            "enabled": self.enabled,
            "installed": bool(executable),
            "command": Path(executable).name if executable else self.command,
            "timeout_s": self.timeout_s,
            "auto_run": False,
            "last": {key: self._last.get(key) for key in ("ok", "duration_ms", "return_code", "reason")},
        }


_client: InterpreterClient | None = None
_client_lock = threading.Lock()


def get_interpreter_client() -> InterpreterClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = InterpreterClient()
    return _client
