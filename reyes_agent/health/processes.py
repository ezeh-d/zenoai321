"""What ZENO's own processes are actually doing, via psutil.

Scoped deliberately to ZENO: this process, its children, and other python
processes running this project. A watchdog that reports on the whole machine
is a task manager, and it is also a privacy problem -- the owner's other
applications are none of ZENO's business.

`psutil` is installed here, so these numbers are measured rather than
estimated. Every call degrades to an empty/º-valued answer instead of
raising, because health reporting must never be the thing that breaks.
"""

from __future__ import annotations

import os
from typing import Any

# A worker holding more than this is worth flagging, not killing.
HIGH_MEMORY_MB = 1500.0
HIGH_CPU_PERCENT = 85.0


def _psutil():
    try:
        import psutil

        return psutil
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    return _psutil() is not None


def self_metrics() -> dict[str, Any]:
    """This process. The one number the owner most often wants."""
    psutil = _psutil()
    if psutil is None:
        return {"available": False}
    try:
        process = psutil.Process(os.getpid())
        with process.oneshot():
            memory = process.memory_info().rss / (1024 * 1024)
            return {
                "available": True,
                "pid": process.pid,
                "memory_mb": round(memory, 1),
                "cpu_percent": round(process.cpu_percent(interval=0.0), 1),
                "threads": process.num_threads(),
                # ``psutil.Process.open_files()`` can fault inside the native
                # Windows handle walker when another thread closes a handle
                # mid-enumeration (observed during the Phase 22 full-suite
                # health probe).  ZENO needs a leak trend, not every file
                # name: Windows' process handle counter is safe, cheap and
                # covers files, sockets and other kernel resources.
                "open_files": None,
                "handles": _safe(process.num_handles) if os.name == "nt" else None,
                "connections": _safe(lambda: len(process.net_connections(kind="inet"))),
                "children": len(process.children(recursive=True)),
                "uptime_s": round(_safe(lambda: __import__("time").time()
                                        - process.create_time()) or 0.0, 1),
                "high_memory": memory > HIGH_MEMORY_MB,
            }
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"}


def _safe(call):
    try:
        return call()
    except Exception:  # noqa: BLE001 -- permission denied on some handles is normal
        return None


def children() -> list[dict[str, Any]]:
    """Processes ZENO started. These are the ones it is responsible for."""
    psutil = _psutil()
    if psutil is None:
        return []
    try:
        parent = psutil.Process(os.getpid())
        found = []
        for child in parent.children(recursive=True):
            try:
                with child.oneshot():
                    found.append({
                        "pid": child.pid, "name": child.name(),
                        "memory_mb": round(child.memory_info().rss / (1024 * 1024), 1),
                        "cpu_percent": round(child.cpu_percent(interval=0.0), 1),
                        "status": child.status(),
                        "cmdline": " ".join(child.cmdline())[:120],
                    })
            except Exception:  # noqa: BLE001 -- it exited between listing and reading
                continue
        return found
    except Exception:  # noqa: BLE001
        return []


def duplicates(marker: str = "reyes_agent") -> list[dict[str, Any]]:
    """Other python processes running this project.

    Two ZENOs on one machine fight over the microphone, the vault and the
    port. Worth noticing; never worth killing automatically, because one of
    them might be the one the owner is talking to.
    """
    psutil = _psutil()
    if psutil is None:
        return []
    mine = os.getpid()
    found = []
    try:
        for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                info = process.info
                if info["pid"] == mine or not info.get("cmdline"):
                    continue
                if "python" not in (info.get("name") or "").lower():
                    continue
                command = " ".join(info["cmdline"])
                if marker in command:
                    # Keep the proof of ownership inside the bounded receipt.
                    # Prefix-only truncation could find ``reyes_agent`` near
                    # the end of a long launcher command and then remove the
                    # very marker that justified listing the process.
                    index = command.index(marker)
                    start = max(0, index - 60)
                    end = min(len(command), index + len(marker) + 60)
                    snippet = (("…" if start else "") + command[start:end]
                               + ("…" if end < len(command) else ""))
                    found.append({"pid": info["pid"], "cmdline": snippet,
                                  "started_at": info.get("create_time")})
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return []
    return found


def alive(pid: int) -> bool:
    psutil = _psutil()
    if psutil is None or not pid:
        return False
    try:
        return psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).is_running()
    except Exception:  # noqa: BLE001
        return False


def status() -> dict[str, Any]:
    metrics = self_metrics()
    kids = children()
    twins = duplicates()
    return {
        "state": "ONLINE" if metrics.get("available") else "DEGRADED",
        "psutil": available(),
        "self": metrics,
        "children": len(kids),
        "heaviest_child": max(kids, key=lambda c: c["memory_mb"], default=None),
        "duplicate_zeno_processes": twins,
        "warnings": ([f"another ZENO appears to be running (pid {t['pid']})" for t in twins]
                     + (["this process is holding a lot of memory"]
                        if metrics.get("high_memory") else [])),
        "scope": "ZENO's own process tree only -- other applications are not inspected",
    }
