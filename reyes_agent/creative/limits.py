"""What ZENO can actually DO with design work -- measured, not asserted.

THE GAP THIS CLOSES
-------------------
`design_intelligence.CAPABILITY_LIBRARY` is a dictionary of sentences. One of
them reads:

    "3D_DESIGN: PARTIAL -- existing Blender path when installed/configured;
     availability is checked at execution."

Nothing checked. Blender has been installed on this machine the whole time
(5.2.0 LTS, in Program Files), and the string said PARTIAL regardless --
because a string cannot look. The same sentence would have said PARTIAL on a
machine with no Blender at all, which means it carried no information either
way.

That is the difference between a limit that is DOCUMENTED and one that is
ENFORCED. A documented limit is a promise in prose; an enforced limit is a
function that returns UNAVAILABLE and a reason. Only the second one can stop
ZENO claiming something.

HOW A CAPABILITY EARNS "AVAILABLE"
----------------------------------
By a probe of the thing that would do the work: an executable that exists and
answers `--version`, a provider with a key, an MCP server that is enabled AND
credentialed AND allowlisted. Never by being listed here. Adding a name to
this file grants nothing.

WHAT STAYS UNAVAILABLE, AND WHY THAT IS THE POINT
-------------------------------------------------
Figma, Canva, Photoshop, Illustrator, printers and vector editors have no
connector in this project. They are listed so that asking for them produces a
specific "there is no connector for X" rather than silence -- an unknown name
and an unconnected tool are different answers, and conflating them is how
"I'll open Photoshop and fix the kerning" gets said by something that cannot
open Photoshop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

AVAILABLE = "AVAILABLE"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"

# CACHE ONLY WHAT IS SLOW, AND ONLY WHAT DOES NOT CHANGE.
#
# The first version cached every capability for two minutes. That is wrong in
# the one direction that matters: a credential revoked, or an allowlist entry
# removed, would still read AVAILABLE for the rest of the window -- a gate
# answering from memory after the thing it guards has gone.
#
# Measured: launching Blender to read its version costs ~283ms, and every
# other probe costs under a millisecond because it reads an environment
# variable or a small file. So the expensive one is cached and the cheap ones
# -- which are precisely the ones that change while ZENO is running -- are
# measured on every call.
_EXPENSIVE = frozenset({"3D_DESIGN"})
_TTL_S = 120.0
_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class Capability:
    """One thing ZENO might be asked to do, and whether it genuinely can."""

    name: str
    state: str = UNAVAILABLE
    backend: str = ""
    evidence: str = ""
    detail: str = ""
    connector: bool = False

    @property
    def usable(self) -> bool:
        return self.state in (AVAILABLE, PARTIAL)

    def refusal(self) -> str:
        """What to say instead of claiming it. Never vague."""
        if self.state == AVAILABLE:
            return ""
        if not self.connector:
            return (f"I have no connector for {self.name.replace('_', ' ').lower()} "
                    f"on this computer, so I cannot drive it. {self.detail}").strip()
        return (f"{self.name.replace('_', ' ').title()} is only partly available: "
                f"{self.detail}").strip()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state, "backend": self.backend,
                "evidence": self.evidence, "detail": self.detail,
                "connector": self.connector, "usable": self.usable}


# -- probes ---------------------------------------------------------------
# Each returns (state, backend, evidence, detail, connector_exists).

def _blender() -> tuple[str, str, str, str, bool]:
    try:
        from reyes_agent.creative.blender import backend

        if backend.available():
            path = backend.executable() or ""
            return (AVAILABLE, "blender", f"{backend.version()} at {path}",
                    "Headless scripting and render-to-file.", True)
        return (UNAVAILABLE, "blender", "not found",
                "Blender is not installed where I can find it.", True)
    except Exception as exc:  # noqa: BLE001
        return (UNAVAILABLE, "blender", f"probe failed: {type(exc).__name__}",
                "I could not check whether Blender is installed.", True)


def _vision() -> tuple[str, str, str, str, bool]:
    """Critique needs a vision provider. Without one it must say so."""
    try:
        from reyes_agent import config

        for name, key in (("anthropic", getattr(config, "ANTHROPIC_API_KEY", "")),
                          ("openai", getattr(config, "OPENAI_API_KEY", "")),
                          ("gemini", getattr(config, "GEMINI_API_KEY", ""))):
            if str(key or "").strip():
                return (AVAILABLE, f"vision:{name}", f"{name} key configured",
                        "Screen capture plus a vision model.", True)
        return (UNAVAILABLE, "vision", "no provider key",
                "No vision provider is configured, so I would be guessing at "
                "what is on screen rather than looking at it.", True)
    except Exception as exc:  # noqa: BLE001
        return (UNAVAILABLE, "vision", f"probe failed: {type(exc).__name__}",
                "I could not check the vision provider.", True)


def _mcp_server(server: str, label: str) -> tuple[str, str, str, str, bool]:
    """An MCP server counts as connected only when it could actually START.

    Registered is not connected. This one is registered and enabled, and npx
    exists -- but it also needs a credential and a place on the allowlist, and
    without either it cannot run. Reporting it as available because it appears
    in a config file is precisely the class of claim this module exists to
    stop.
    """
    try:
        import json

        from reyes_agent import config

        path = config.VAULT_PATH / "07-System" / "mcp" / "servers.json"
        if not path.exists():
            return (UNAVAILABLE, server, "no server registry",
                    f"{label} is not registered.", False)
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else raw.get("servers", [])
        entry = next((e for e in entries if e.get("name") == server), None)
        if entry is None:
            return (UNAVAILABLE, server, "not registered",
                    f"{label} is not registered.", False)

        missing = []
        if not entry.get("enabled", False):
            missing.append("it is disabled")
        for env_name in entry.get("env_names", []):
            if not os.environ.get(env_name, "").strip():
                missing.append(f"{env_name} is not set")
        allowlist = {i.strip() for i in
                     os.environ.get("ZENO_MCP_ALLOWLIST", "").split(",") if i.strip()}
        if server not in allowlist:
            missing.append("it is not in ZENO_MCP_ALLOWLIST")

        if missing:
            return (UNAVAILABLE, server, "registered but cannot start",
                    f"{label} is registered but " + ", and ".join(missing) + ".",
                    True)
        return (AVAILABLE, server, "registered, credentialed and allowlisted",
                f"{label} can be started on demand.", True)
    except Exception as exc:  # noqa: BLE001
        return (UNAVAILABLE, server, f"probe failed: {type(exc).__name__}",
                f"I could not check {label}.", True)


def _tool_registered(tool: str, label: str,
                     detail: str) -> tuple[str, str, str, str, bool]:
    try:
        from reyes_agent.tools import TOOLS

        if tool in TOOLS:
            return (AVAILABLE, tool, "tool registered", detail, True)
        return (UNAVAILABLE, tool, "tool not registered",
                f"{label} is not available in this build.", True)
    except Exception as exc:  # noqa: BLE001
        return (UNAVAILABLE, tool, f"probe failed: {type(exc).__name__}",
                f"I could not check {label}.", True)


def _no_connector(what: str) -> tuple[str, str, str, str, bool]:
    return (UNAVAILABLE, "", "no connector in this project",
            f"Nothing in ZENO drives {what}. I can produce files it opens, "
            f"and direct the work, but I cannot operate {what} itself.", False)


PROBES = {
    "3D_DESIGN": _blender,
    "DESIGN_CRITIQUE": _vision,
    "UI_COMPONENTS": lambda: _mcp_server("21st-magic", "Magic MCP (21st.dev)"),
    "IMAGE_GENERATION": lambda: _tool_registered(
        "generate_image", "Image generation",
        "Generates a real image file through the existing tool."),
    "PROJECT_ASSETS": lambda: _tool_registered(
        "write_project_file", "Project file writing",
        "Writes real SVG/HTML/CSS assets to disk."),
    "FIGMA": lambda: _no_connector("Figma"),
    "CANVA": lambda: _no_connector("Canva"),
    "PHOTOSHOP": lambda: _no_connector("Photoshop"),
    "ILLUSTRATOR": lambda: _no_connector("Illustrator"),
    "VECTOR_EDITOR": lambda: _no_connector("a vector editor"),
    "PRINTER": lambda: _no_connector("a printer"),
}


def capabilities(*, refresh: bool = False) -> dict[str, Capability]:
    """Every design capability with its measured state."""
    import time

    now = time.time()
    found: dict[str, Capability] = {}
    for name, probe in PROBES.items():
        cached = _cache.get(name)
        if (not refresh and name in _EXPENSIVE and cached
                and now - cached[0] < _TTL_S):
            found[name] = cached[1]
            continue
        try:
            state, backend, evidence, detail, connector = probe()
        except Exception as exc:  # noqa: BLE001
            # A probe that breaks must not grant a capability. Failing closed
            # is the whole contract -- an exception in a Blender lookup read
            # as "Blender is available" is the worst direction for the
            # mistake to go.
            state, backend, evidence, connector = (
                UNAVAILABLE, "", f"probe error: {type(exc).__name__}", False)
            detail = f"I could not verify {name.lower()}."
        capability = Capability(name=name, state=state, backend=backend,
                                evidence=evidence, detail=detail,
                                connector=connector)
        found[name] = capability
        if name in _EXPENSIVE:
            _cache[name] = (now, capability)
    return found


def check(name: str) -> Capability:
    """One capability. Unknown names are UNAVAILABLE, never assumed."""
    key = (name or "").strip().upper().replace(" ", "_").replace("-", "_")
    found = capabilities()
    if key in found:
        return found[key]
    return Capability(name=key or "UNKNOWN", state=UNAVAILABLE,
                      evidence="not a capability ZENO tracks",
                      detail="I do not have that as a design capability.",
                      connector=False)


def require(name: str) -> tuple[bool, str]:
    """(allowed, refusal). The gate a tool calls before claiming anything."""
    capability = check(name)
    return capability.usable, capability.refusal()


def connected() -> list[str]:
    return sorted(n for n, c in capabilities().items() if c.state == AVAILABLE)


def status() -> dict[str, Any]:
    found = capabilities()
    return {
        "state": "ONLINE",
        "connected": connected(),
        "unavailable": sorted(n for n, c in found.items() if not c.usable),
        "capabilities": {n: c.as_dict() for n, c in found.items()},
        "rule": ("A capability is AVAILABLE only when the thing that would do "
                 "the work answers a probe. Being listed here grants nothing."),
    }
