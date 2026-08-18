"""The Windows half of the device link: an OUTBOUND worker.

WHY POLLING AND NOT A LISTENING SOCKET
--------------------------------------
The requirement is that the owner's machine is never reachable from the
internet. That rules out any design where the cloud connects inward -- no
port forward, no inbound tunnel, no listening service. So the desktop dials
out and asks for work, which needs nothing open, survives NAT and CGNAT, and
fails safe: if the gateway disappears, this loop just stops getting work.

An HTTP long-poll is used rather than a WebSocket because it reconnects
trivially, needs no keepalive tuning, and a dropped request costs one cycle
rather than a session. A WebSocket transport can replace `_claim` later
without changing anything else here.

WHAT THIS LOOP WILL NOT DO
--------------------------
It does not evaluate strings from the network. `EXECUTORS` maps a registered
action name to a Python callable, and an action that is not in that dict is
reported back as REJECTED. There is no branch that runs shell text, imports a
named module, or formats a caller-supplied string into a command line.

Results are what actually happened. Every executor returns the real outcome,
and a failure is reported as a failure -- ZENO does not tell the owner that
Chrome opened because a function returned without raising.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Backoff: fast enough to feel live, slow enough not to hammer a gateway that
# is down. Jitter stops every device retrying in lockstep after an outage.
POLL_IDLE_S = 3.0
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
HEARTBEAT_EVERY_S = 20.0


@dataclass
class AgentConfig:
    gateway: str
    device_id: str
    token: str
    label: str = "Windows"
    verify_tls: bool = True


@dataclass
class AgentState:
    connected: bool = False
    last_success: float = 0.0
    consecutive_failures: int = 0
    commands_done: int = 0
    commands_failed: int = 0
    last_error: str = ""
    backoff_s: float = 0.0
    seen: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {"connected": self.connected, "last_success": self.last_success,
                "consecutive_failures": self.consecutive_failures,
                "commands_done": self.commands_done,
                "commands_failed": self.commands_failed,
                "last_error": self.last_error[:200], "backoff_s": round(self.backoff_s, 1)}


# --- executors -----------------------------------------------------------
# Each registered action maps to exactly one ZENO TOOL. Routing through the
# tool registry rather than calling internals directly means the remote path
# inherits the permission and confirmation architecture the desktop already
# has -- a tool marked `requires_confirmation` still requires it.
#
# The FIRST version of this file called reyes_agent.agent.Agent(),
# desktop_app.open_application(), memory_manager.recall() and
# agent_space.roster(). FOUR OF THOSE FIVE DO NOT EXIST. They would have been
# executors that failed every single time while looking implemented. The
# names below were read out of the live registry, and a test asserts every one
# of them is still registered.

ACTION_TOOLS: dict[str, str] = {
    "status": "system_health",
    "memory_recall": "search_notes",
    "agent_status": "agent_roster",
    "open_app": "open_app",
}

_DEFAULT_REMOTE_APPS = {
    "calculator": "calculator", "calc": "calculator",
    "chrome": "chrome", "google chrome": "chrome",
    "visual studio code": "Visual Studio Code", "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code", "notepad": "notepad",
    "file explorer": "explorer", "explorer": "explorer",
}


def _remote_apps() -> dict[str, str]:
    allowed = dict(_DEFAULT_REMOTE_APPS)
    for item in os.environ.get("ZENO_REMOTE_APP_ALLOWLIST", "").split(","):
        clean = " ".join(item.split())[:64]
        if clean and not any(ch in clean for ch in ';&|<>$`\n\r"\''):
            allowed[clean.casefold()] = clean
    return allowed

# Argument builders: the network supplies DATA, never an argument dict. A
# payload cannot name a tool parameter that these functions do not pass.
def _args_status(_p: dict[str, Any]) -> dict[str, Any]:
    return {}


def _args_memory(p: dict[str, Any]) -> dict[str, Any]:
    return {"query": str(p.get("query", ""))[:400]}


def _args_agents(_p: dict[str, Any]) -> dict[str, Any]:
    return {}


def _args_open_app(p: dict[str, Any]) -> dict[str, Any]:
    # The parameter is `name_or_path`, NOT `name`. The first version of this
    # builder guessed `name` and every open_app command failed with
    # "unexpected keyword argument". Read from the live input_schema, and
    # asserted by test_action_arguments_match_the_real_tool_schemas.
    requested = " ".join(str(p.get("name", "")).split())[:64]
    selected = _remote_apps().get(requested.casefold())
    if selected is None:
        raise ValueError("application is not in the remote allow-list")
    return {"name_or_path": selected}


ACTION_ARGS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "status": _args_status,
    "memory_recall": _args_memory,
    "agent_status": _args_agents,
    "open_app": _args_open_app,
}

# ZENO's tools return prose, not status codes, so failure has to be read out
# of the text. Matching a bare substring ANYWHERE is wrong in both directions
# and this code has now been bitten by both:
#
#   * The browser harness scored "Browser error: TimeoutError" as SUCCESS
#     because it only matched a LEADING "error".
#   * The first version here scored `agent_roster` as FAILURE because one
#     agent's description contains the words "explains errors".
#
# A real failure announces itself at the START of the output or at the start
# of a line -- "Error: ...", "Failed to ...", "Could not ...". A word buried
# in the middle of a successful payload is data, not a status.
_FAILURE_PATTERN = re.compile(
    r"^\s*(?:error\b|failed\b|failure\b|could ?n.t\b|could not\b|"
    r"can.t\b|cannot\b|did ?n.t\b|was ?n.t\b|wo ?n.t\b|"
    r"unable to\b|not found\b|no such\b|unavailable\b|timed? ?out\b|"
    r"denied\b|refused\b|not registered\b|[A-Za-z ]{0,24}error:)",
    re.IGNORECASE | re.MULTILINE)


def _run_tool(action: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    from reyes_agent.tools import TOOLS, run_tool

    tool_name = ACTION_TOOLS.get(action)
    if tool_name is None:
        return False, {"error": f"action '{action}' has no executor here"}
    entry = TOOLS.get(tool_name)
    if entry is None:
        return False, {"error": f"tool '{tool_name}' is not registered on this desktop"}

    try:
        builder = ACTION_ARGS.get(action)
        args = builder(payload) if builder else {}
        # `run_tool`, not the raw executor: remote commands must retain the
        # permission engine, capability profile, confirmation gate and audit.
        output = str(run_tool(tool_name, args))
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"{type(exc).__name__}: {exc}"[:400]}

    failed = bool(_FAILURE_PATTERN.search(output))
    return (not failed), {"tool": tool_name, "detail": output[:4000]}


def _exec_ask(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Put a question to ZENO through the same turn loop the desktop uses."""
    question = str(payload.get("text", "")).strip()
    if not question:
        return False, {"error": "no question supplied"}
    try:
        from reyes_agent import web

        class _RemoteContext:
            @staticmethod
            def check_cancelled() -> None:
                return None

            @staticmethod
            def progress(_stage: str) -> None:
                return None

        result = web._conversation_turn(_RemoteContext(), question)  # noqa: SLF001
        return True, {"answer": str(result.get("reply", ""))[:8000],
                      "tool_calls": result.get("tool_calls", [])[:20]}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"{type(exc).__name__}: {exc}"[:400]}


def _exec_memory(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    query = str(payload.get("query", "")).strip()
    if not query:
        return False, {"error": "no memory query supplied"}
    try:
        from reyes_agent.memory.manager import get_memory_manager

        return True, {"results": get_memory_manager().retrieve(query, limit=8)}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"{type(exc).__name__}: {exc}"[:400]}


def _exec_tasks(_payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    try:
        from reyes_agent import task_engine

        return True, {"tasks": task_engine.active()[-25:]}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"{type(exc).__name__}: {exc}"[:400]}


def _exec_conversation(_payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    try:
        from reyes_agent import web

        messages = []
        for item in list(web._history)[-80:]:  # noqa: SLF001
            role, content = item.get("role"), item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content[:8000]})
        return True, {"conversation_id": "zeno-primary", "messages": messages}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"{type(exc).__name__}: {exc}"[:400]}


def _executor_for(action: str) -> Callable[[dict[str, Any]], tuple[bool, dict[str, Any]]] | None:
    if action == "ask":
        return _exec_ask
    if action == "memory_recall":
        return _exec_memory
    if action == "task_status":
        return _exec_tasks
    if action == "conversation_snapshot":
        return _exec_conversation
    if action in ACTION_TOOLS:
        return lambda payload: _run_tool(action, payload)
    return None


class DesktopAgent:
    """Outbound worker. Start it, and the desktop becomes reachable."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.state = AgentState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- transport ------------------------------------------------------
    def _post(self, path: str, body: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        url = self.config.gateway.rstrip("/") + path
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("gateway must be an http(s) URL")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" and parsed.hostname not in {
                "127.0.0.1", "localhost", "::1"}:
            raise ValueError("a non-local gateway must use HTTPS")
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")

    def _auth(self) -> dict[str, str]:
        return {"device_id": self.config.device_id, "token": self.config.token}

    # ---- loop -----------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="zeno-desktop-agent",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self.state.connected = False

    def _run(self) -> None:
        last_heartbeat = 0.0
        while not self._stop.is_set():
            try:
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_EVERY_S:
                    self._post("/api/owner/device/heartbeat",
                               {**self._auth(), "state": "ONLINE"}, timeout=15.0)
                    last_heartbeat = now

                claimed = self._post("/api/owner/device/claim",
                                     {**self._auth(), "limit": 5}, timeout=30.0)
                self._on_success()

                commands = claimed.get("commands") or []
                for command in commands:
                    if self._stop.is_set():
                        break
                    self._handle(command)

                # Only idle when there was nothing to do.
                if not commands:
                    self._stop.wait(POLL_IDLE_S)
            except Exception as exc:  # noqa: BLE001
                self._on_failure(exc)

    def _on_success(self) -> None:
        self.state.connected = True
        self.state.last_success = time.time()
        self.state.consecutive_failures = 0
        self.state.backoff_s = 0.0
        self.state.last_error = ""

    def _on_failure(self, exc: Exception) -> None:
        self.state.connected = False
        self.state.consecutive_failures += 1
        self.state.last_error = f"{type(exc).__name__}: {exc}"
        # Exponential with full jitter. Without jitter, every device that lost
        # a gateway reconnects at the same instant and knocks it over again.
        delay = min(BACKOFF_MAX_S,
                    BACKOFF_START_S * (2 ** min(self.state.consecutive_failures - 1, 6)))
        self.state.backoff_s = random.uniform(0, delay)
        log.warning("desktop agent poll failed (%s); retrying in %.1fs",
                    self.state.last_error[:120], self.state.backoff_s)
        self._stop.wait(self.state.backoff_s)

    # ---- command handling -----------------------------------------------
    def _handle(self, command: dict[str, Any]) -> None:
        command_id = str(command.get("id", ""))
        action = str(command.get("action", ""))
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}

        # Duplicate suppression at the executing end as well as the queue.
        # A claim retried after a network blip must not run twice.
        if command_id in self.state.seen:
            return
        self.state.seen.add(command_id)
        if len(self.state.seen) > 2000:
            self.state.seen = set(list(self.state.seen)[-1000:])

        try:
            self._post("/api/owner/device/ack",
                       {**self._auth(), "command_id": command_id}, timeout=15.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("ack failed for %s: %s", command_id, exc)

        executor = _executor_for(action)
        if executor is None:
            self._report(command_id, False, {}, f"action '{action}' is not executable here")
            return

        try:
            ok, result = executor(payload)
        except Exception as exc:  # noqa: BLE001
            ok, result = False, {"error": f"{type(exc).__name__}: {exc}"[:400]}

        if ok:
            self.state.commands_done += 1
        else:
            self.state.commands_failed += 1
        self._report(command_id, ok, result, str(result.get("error", "")) if not ok else "")

    def _report(self, command_id: str, ok: bool, result: dict[str, Any], error: str) -> None:
        try:
            self._post("/api/owner/device/complete",
                       {**self._auth(), "command_id": command_id, "success": ok,
                        "result": result, "error": error}, timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            # The result is lost, but the queue times the command out rather
            # than leaving it pending forever, so the owner still learns the
            # truth: it did not complete.
            log.error("could not report result for %s: %s", command_id, exc)


_agent: DesktopAgent | None = None


def from_environment() -> DesktopAgent | None:
    """Build the agent from configuration, or None when it is not set up."""
    gateway = os.environ.get("ZENO_GATEWAY_URL", "").strip()
    device_id = os.environ.get("ZENO_DEVICE_ID", "").strip()
    token = os.environ.get("ZENO_DEVICE_TOKEN", "").strip()
    if not (gateway and device_id and token):
        return None
    return DesktopAgent(AgentConfig(
        gateway=gateway, device_id=device_id, token=token,
        label=os.environ.get("ZENO_DEVICE_LABEL", "Windows")))


def start_from_environment() -> DesktopAgent | None:
    global _agent
    if _agent is not None:
        return _agent
    agent = from_environment()
    if agent is None:
        return None
    agent.start()
    _agent = agent
    return agent


def configured() -> bool:
    """Whether all three connector credentials are present.

    This check deliberately does not construct or start a worker.  The Kernel
    uses it while registering startup stages, where a side effect would put
    network work back on the application startup path.
    """
    return all(os.environ.get(name, "").strip() for name in (
        "ZENO_GATEWAY_URL", "ZENO_DEVICE_ID", "ZENO_DEVICE_TOKEN"))


def stop_current(timeout: float = 5.0) -> None:
    """Stop the one managed connector, if configured and running."""
    global _agent
    agent = _agent
    if agent is not None:
        agent.stop(timeout=timeout)
    _agent = None


def current() -> DesktopAgent | None:
    return _agent


def reset_for_tests() -> None:
    stop_current(timeout=1.0)
