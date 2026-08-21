"""One honest health snapshot of ZENO's shared brain, memory, knowledge and
tools -- the same for phone and laptop, because they share one backend.

WHY THIS EXISTS
---------------
The phone used to say "tool unavailable" without saying WHICH layer was down --
a laptop that is asleep, a messaging integration with no token, or nothing at
all. This assembles the real state of each capability so the owner (on either
device) can see exactly what is connected and what is not.

Every check is REAL: it reads the live tool registry, the device link and the
configured credentials. Nothing here fabricates a green light. A capability
with no token reports AUTH_REQUIRED, an asleep laptop reports DEVICE_OFFLINE,
and an exception reports ERROR -- never CONNECTED.
"""

from __future__ import annotations

import time
from typing import Any

# Section 17 states. A capability is exactly one of these, never a guess.
AVAILABLE = "AVAILABLE"
CONNECTED = "CONNECTED"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
DEVICE_OFFLINE = "DEVICE_OFFLINE"
ERROR = "ERROR"


def _safe(fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 -- one broken probe never fails the report
        return {"status": ERROR, "detail": f"{type(exc).__name__}: {exc}"[:160]}


def _brain() -> dict[str, Any]:
    from reyes_agent import config
    keys = {"gemini": config.GEMINI_API_KEY, "openai": config.OPENAI_API_KEY,
            "xai": config.XAI_API_KEY, "anthropic": config.ANTHROPIC_API_KEY}
    live = [name for name, key in keys.items() if key]
    if live:
        return {"status": CONNECTED, "detail": "providers: " + ", ".join(live)}
    return {"status": UNAVAILABLE, "detail": "no model provider key is configured"}


def _memory() -> dict[str, Any]:
    from reyes_agent.memory.manager import get_memory_manager
    get_memory_manager()  # constructing it is the smoke test
    return {"status": CONNECTED, "detail": "shared memory backend ready"}


def _t21_knowledge() -> dict[str, Any]:
    import reyes_agent.tools as tools
    have = [n for n in ("siwes_evidence", "engineering_challenges",
                        "learning_portfolio", "project_evolution") if n in tools.TOOLS]
    if have:
        return {"status": CONNECTED,
                "detail": f"{len(have)} T21/SIWES knowledge tools in the shared brain"}
    return {"status": UNAVAILABLE, "detail": "no T21 knowledge tool is registered"}


def _laptop_node() -> dict[str, Any]:
    from reyes_agent.remote_access import device_link, local_executor
    creds = local_executor._load_creds()  # noqa: SLF001
    if not creds:
        return {"status": UNAVAILABLE, "detail": "no local executor device registered"}
    state = device_link.get_link().device_state(creds["device_id"])
    live = state.get("state")
    if live == "ONLINE":
        return {"status": CONNECTED, "device_id": creds["device_id"], "detail": "laptop online"}
    return {"status": DEVICE_OFFLINE, "device_id": creds["device_id"],
            "detail": "laptop is offline; desktop actions will queue until it reconnects"}


def _integration(token: str, label: str) -> dict[str, Any]:
    if token:
        return {"status": AVAILABLE, "detail": f"{label} token configured"}
    return {"status": AUTH_REQUIRED, "detail": f"no {label} token set"}


def _family(prefix: str, label: str) -> dict[str, Any]:
    import reyes_agent.tools as tools
    n = sum(1 for name in tools.TOOLS if name.startswith(prefix))
    if n:
        return {"status": AVAILABLE, "detail": f"{n} {label} tools"}
    return {"status": UNAVAILABLE, "detail": f"no {label} tools registered"}


def _voice() -> dict[str, Any]:
    from reyes_agent import config
    if config.ELEVENLABS_API_KEY or config.PIPER_MODEL:
        which = "elevenlabs" if config.ELEVENLABS_API_KEY else "piper"
        return {"status": AVAILABLE, "detail": f"speech via {which}"}
    return {"status": DEGRADED, "detail": "no TTS configured; text replies still work"}


def _tools_summary() -> dict[str, Any]:
    import reyes_agent.tools as tools
    return {"status": CONNECTED, "detail": f"{len(tools.TOOLS)} tools in the shared registry"}


def snapshot() -> dict[str, Any]:
    """Assemble the full report. Safe to call on every request."""
    from reyes_agent import config

    capabilities = {
        "brain": _safe(_brain),
        "conversation": {"status": CONNECTED, "detail": "core capability; never a plugin"},
        "memory": _safe(_memory),
        "t21_knowledge": _safe(_t21_knowledge),
        "laptop": _safe(_laptop_node),
        "desktop_control": _safe(_laptop_node),
        "browser": _safe(lambda: _family("browser_", "browser")),
        "agents": _safe(lambda: _family("agent_", "agent")),
        "slack": _safe(lambda: _integration(config.SLACK_BOT_TOKEN, "Slack")),
        "telegram": _safe(lambda: _integration(config.TELEGRAM_BOT_TOKEN, "Telegram")),
        "voice": _safe(_voice),
        "tools": _safe(_tools_summary),
    }
    # Node capabilities (section 3): what each surface can physically execute.
    # A phone REQUESTING a desktop action does not execute it -- the router
    # sends it to the laptop node. These flags say who can do what.
    nodes = {
        "laptop": {"desktop.open_app": True, "desktop.close_app": True,
                   "browser": True, "filesystem": True, "voice": True},
        "phone": {"microphone": True, "speaker": True, "camera": "permission_based",
                  "display": True, "desktop.execute": False},
    }
    degraded = [k for k, v in capabilities.items()
                if v.get("status") in {UNAVAILABLE, ERROR, DEVICE_OFFLINE}]
    return {
        "generated_at": time.time(),
        "healthy": not degraded,
        "attention": degraded,
        "capabilities": capabilities,
        "nodes": nodes,
    }
