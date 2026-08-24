"""Model-free emergency control path for STOP/STANDBY/CANCEL/MUTE."""
from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_last_command = ""
_last_at = 0.0


def execute(command: str) -> dict[str, Any]:
    """Execute only fixed safe controls. No provider, browser or agent planning."""
    global _last_command, _last_at
    action = " ".join(str(command or "").strip().upper().split())
    if action.startswith("ZENO "):
        action = action[5:]
    if action not in {"STOP", "STANDBY", "CANCEL", "MUTE", "DISCONNECT REMOTE CONTROL"}:
        return {"ok": False, "command": action, "reason": "unknown emergency command"}
    with _lock:
        _last_command, _last_at = action, time.time()
    stopped = 0
    if action in {"STOP", "CANCEL", "MUTE", "STANDBY"}:
        try:
            from reyes_agent import voice_manager
            stopped += int(voice_manager.cancel_current() or 0)
        except Exception:
            pass
    if action in {"STOP", "CANCEL", "STANDBY"}:
        try:
            from reyes_agent import agent_runtime
            stopped += int(agent_runtime.cancel_active("owner emergency control") or 0)
        except Exception:
            pass
    if action == "STANDBY":
        try:
            from reyes_agent.wake import get_wake_engine
            get_wake_engine().standby()
        except Exception:
            pass
    if action in {"STOP", "DISCONNECT REMOTE CONTROL"}:
        try:
            from reyes_agent.remote_access import live_desktop_node
            stopped += int(bool(live_desktop_node.terminate_current()))
        except Exception:
            pass
    try:
        from reyes_agent import event_bus
        event_bus.publish("emergency.control", {"command": action, "stopped": stopped},
                          source="emergency_control")
    except Exception:
        pass
    return {"ok": True, "command": action, "stopped": stopped, "model_used": False}


def status() -> dict[str, Any]:
    with _lock:
        return {"last_command": _last_command, "last_at": _last_at}
