"""Technically enforced, per-agent capability scopes.

Prompts describe an agent's role; this module enforces it.  Specialist and
worker runtimes enter a temporary scope containing the exact tool names that
were sent to the model.  ``tools.run_tool`` checks that scope again, so a
hallucinated or injected out-of-role call cannot reach the executor.
"""
from __future__ import annotations

import contextvars
import urllib.parse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class AgentCapabilityProfile:
    agent: str
    allowed_tools: frozenset[str]
    allowed_services: frozenset[str] = frozenset()
    filesystem_scopes: tuple[str, ...] = ()
    network_scopes: tuple[str, ...] = ()
    approval_level: int = 2
    secret_broker_rules: frozenset[str] = frozenset()

    def public(self) -> dict:
        value = asdict(self)
        for key in ("allowed_tools", "allowed_services", "network_scopes", "secret_broker_rules"):
            value[key] = sorted(value[key])
        return value


_scope: contextvars.ContextVar[AgentCapabilityProfile | None] = contextvars.ContextVar(
    "zeno_agent_capability_scope", default=None
)


@contextmanager
def agent_scope(
    agent: str,
    *,
    allowed_tools: Iterable[str],
    allowed_services: Iterable[str] = (),
    filesystem_scopes: Iterable[str | Path] = (),
    network_scopes: Iterable[str] = (),
    approval_level: int = 2,
    secret_broker_rules: Iterable[str] = (),
) -> Iterator[AgentCapabilityProfile]:
    profile = AgentCapabilityProfile(
        agent=str(agent or "unknown").strip().casefold(),
        allowed_tools=frozenset(str(item) for item in allowed_tools),
        allowed_services=frozenset(str(item).casefold() for item in allowed_services),
        filesystem_scopes=tuple(str(Path(item).resolve()) for item in filesystem_scopes),
        network_scopes=tuple(str(item).casefold() for item in network_scopes),
        approval_level=max(0, min(4, int(approval_level))),
        secret_broker_rules=frozenset(str(item).casefold() for item in secret_broker_rules),
    )
    token = _scope.set(profile)
    try:
        yield profile
    finally:
        _scope.reset(token)


def current_profile() -> AgentCapabilityProfile | None:
    return _scope.get()


def authorize_tool(tool: str) -> tuple[bool, str, str]:
    profile = current_profile()
    if profile is None:
        return True, "ZENO executive/local authority", "zeno"
    if tool not in profile.allowed_tools:
        return False, f"{profile.agent} is not allowed to use tool '{tool}'", profile.agent
    return True, "tool is inside the active capability profile", profile.agent


def authorize_service(service: str) -> tuple[bool, str, str]:
    profile = current_profile()
    if profile is None:
        return True, "ZENO executive/local authority", "zeno"
    name = str(service or "").casefold()
    allowed = name in profile.allowed_services or name in profile.secret_broker_rules
    return allowed, ("service is inside the active capability profile" if allowed else
                     f"{profile.agent} is not allowed to access service '{name}'"), profile.agent


def authorize_arguments(arguments: dict) -> tuple[bool, str, str]:
    """Enforce absolute file and explicit network targets inside the scope."""
    profile = current_profile()
    if profile is None:
        return True, "ZENO executive/local authority", "zeno"
    roots = tuple(Path(item) for item in profile.filesystem_scopes)
    hosts = {item.casefold() for item in profile.network_scopes}
    for key, value in (arguments or {}).items():
        if not isinstance(value, str) or not value.strip():
            continue
        label = str(key).casefold()
        if any(marker in label for marker in ("path", "file", "folder", "directory", "workspace", "location")):
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                target = candidate.resolve()
                if not roots or not any(target == root or root in target.parents for root in roots):
                    return False, f"{profile.agent} requested a path outside its filesystem scopes", profile.agent
        if label in {"url", "endpoint", "uri"}:
            host = (urllib.parse.urlparse(value).hostname or "").casefold()
            if host and host not in hosts:
                return False, f"{profile.agent} requested network host '{host}' outside its scope", profile.agent
    return True, "arguments are inside the active capability profile", profile.agent
