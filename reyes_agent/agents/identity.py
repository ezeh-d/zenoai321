"""Who ZENO's agents ARE -- answerable without waking any of them.

THE ACTUAL BUG THIS FIXES
-------------------------
ZENO said "I don't know Apex" while APEX was defined in three separate
places. Nothing had been lost and nothing needed recovering: `AGENT_ROLES`
in agent_runtime carries the titles, `_SPECIALISTS` in tools/subagents
carries the descriptions and toolsets, `_TEAMS` in agent_teams carries the
workers, and agents/registry joins them to live health.

What did not exist was a way for the BRAIN to ask. Every one of those is a
Python dict read by executor code; none was exposed as a tool. So the
identity was on disk and unreachable from a conversation -- which looks
exactly like amnesia from the outside.

METADATA IS NOT RUNTIME
-----------------------
Everything here reads dictionaries. It never imports a model, never starts a
worker, never touches the supervisor. "Who is Apex" costs nothing and works
while APEX is asleep, which is the whole point: an agent that is not loaded
is still a member of the team.

DIVINE IS NOT AN AGENT
----------------------
The team hierarchy in agent_teams reads DIVINE -> ZENO -> PRIMARY -> WORKER.
Divine is the OWNER, at the top. Listing Divine as a thirteenth specialist
would invent a role the project never defined, so this does not do it.
"""

from __future__ import annotations

from typing import Any

# Names people actually say, mapped to the canonical id. HERMES is the one
# that genuinely bites: the id is `hermes_comm`, so a plain "hermes" would
# otherwise miss.
ALIASES: dict[str, str] = {
    "hermes": "hermes_comm",
    "hermes comm": "hermes_comm",
    "comms": "hermes_comm",
    "communications": "hermes_comm",
    "gaming": "apex",
    "gaming agent": "apex",
    "security": "stark",
    "research": "aris",
    "engineering": "tosin",
    "code": "tosin",
    "finance": "titan",
    "money": "titan",
    "education": "kate",
    "teaching": "kate",
    "strategy": "ultron",
    "creative": "zeal",
    "design": "zeal",
    "vision": "nova",
    "wellness": "helios",
    "health": "helios",
    "analytics": "oracle",
    "data": "oracle",
    "mission control": "atlas",
    "missions": "atlas",
    "systems": "jarvis",
    "integration": "jarvis",
}

# Not agents. Naming one should produce a correction, not a lookup failure.
NOT_AGENTS: dict[str, str] = {
    "divine": ("Divine is you -- the owner. You sit above me in the "
               "hierarchy, not among my specialists."),
    "zeno": ("That's me. I'm the executive; the specialists below me are "
             "the agents."),
}


def _roles() -> dict[str, str]:
    try:
        from reyes_agent.agent_runtime import AGENT_ROLES

        return dict(AGENT_ROLES)
    except Exception:  # noqa: BLE001
        return {}


def _specialists() -> dict[str, dict]:
    try:
        from reyes_agent.tools.subagents import _SPECIALISTS

        return dict(_SPECIALISTS)
    except Exception:  # noqa: BLE001
        return {}


def _teams() -> dict[str, list]:
    try:
        from reyes_agent import agent_teams

        return agent_teams.teams()
    except Exception:  # noqa: BLE001
        return {}


def canonical(name: str) -> str:
    """Resolve whatever the owner said to a canonical agent id.

    Tries the literal name, then aliases, then a prefix match -- so "herm"
    and "HERMES" and "the comms agent" all land on hermes_comm.
    """
    raw = (name or "").strip().lower().replace("-", " ").replace("_", " ")
    if not raw:
        return ""
    known = set(_roles()) | set(_specialists())

    direct = raw.replace(" ", "_")
    if direct in known:
        return direct
    if raw in ALIASES:
        return ALIASES[raw]

    # Strip filler the owner naturally uses: "who is the stark agent"
    stripped = " ".join(w for w in raw.split()
                        if w not in {"the", "agent", "my", "a", "an", "is", "who"})
    if stripped.replace(" ", "_") in known:
        return stripped.replace(" ", "_")
    if stripped in ALIASES:
        return ALIASES[stripped]

    for candidate in sorted(known):
        if candidate.startswith(stripped) or stripped.startswith(candidate.split("_")[0]):
            if stripped:
                return candidate
    return ""


def roster() -> list[dict[str, Any]]:
    """Every registered main agent, with role, workers and live status.

    Status comes from the registry when it can be read, but a registry that
    is unreachable must NOT erase the roster -- an agent whose health is
    unknown is still registered. That distinction is the difference between
    "APEX is asleep" and "I don't know Apex".
    """
    roles, specialists, teams = _roles(), _specialists(), _teams()
    health: dict[str, str] = {}
    try:
        from reyes_agent.agents import registry

        health = {a.name: a.status for a in registry.agents()}
    except Exception:  # noqa: BLE001
        health = {}

    out = []
    for agent_id in sorted(set(roles) | set(specialists) | set(teams)):
        workers = [getattr(w, "name", str(w)) for w in teams.get(agent_id, [])]
        entry = specialists.get(agent_id, {})
        out.append({
            "id": agent_id,
            "name": agent_id.split("_")[0].upper(),
            "role": roles.get(agent_id, ""),
            "description": entry.get("description", ""),
            "workers": workers,
            "worker_count": len(workers),
            "tools": sorted(entry.get("tools", set())),
            "status": health.get(agent_id, "REGISTERED"),
            "aliases": sorted(a for a, t in ALIASES.items() if t == agent_id),
        })
    return out


def identity(name: str) -> dict[str, Any]:
    """Answer "who is X" from configuration alone."""
    said = (name or "").strip()
    low = said.lower()
    if low in NOT_AGENTS:
        return {"found": False, "is_agent": False, "asked": said,
                "spoken": NOT_AGENTS[low]}

    agent_id = canonical(said)
    if not agent_id:
        known = ", ".join(a["name"] for a in roster())
        return {"found": False, "asked": said,
                "spoken": (f"I have no agent called {said}. My registered "
                           f"agents are: {known}."),
                "registered": [a["name"] for a in roster()]}

    for entry in roster():
        if entry["id"] == agent_id:
            bits = [f"{entry['name']} is my {entry['role']}."
                    if entry["role"] else f"{entry['name']} is one of my agents."]
            if entry["description"]:
                bits.append(entry["description"].split("--", 1)[-1].strip())
            if entry["workers"]:
                bits.append(f"{len(entry['workers'])} workers report to "
                            f"{entry['name']}: {', '.join(entry['workers'])}.")
            # Say the status only when it is NOT the resting state -- "APEX is
            # registered" is noise, "APEX is degraded" is news.
            if entry["status"] not in ("REGISTERED", "unknown", ""):
                bits.append(f"Currently {entry['status']}.")
            return {"found": True, **entry, "spoken": " ".join(bits)}
    return {"found": False, "asked": said, "spoken": f"I have no agent called {said}."}


def role_call() -> dict[str, Any]:
    """Every main agent announcing itself. Metadata only -- nothing wakes."""
    team = roster()
    lines = ["ZENO AGENT ECOSYSTEM", ""]
    for entry in team:
        lines.append(f"{entry['name']:<8} {entry['status']:<12} {entry['role']}")
        if entry["workers"]:
            lines.append(f"{'':<8} {'':<12} {entry['worker_count']} workers: "
                         f"{', '.join(entry['workers'])}")
    lines += ["", f"{len(team)} main agents, "
                  f"{sum(e['worker_count'] for e in team)} workers.",
              "Divine is the owner; ZENO is the executive."]
    return {"count": len(team),
            "worker_count": sum(e["worker_count"] for e in team),
            "agents": team, "display": "\n".join(lines),
            "spoken": ("I have " + str(len(team)) + " agents: "
                       + ", ".join(e["name"] for e in team) + ".")}


def workers_of(name: str) -> dict[str, Any]:
    """Who reports to an agent."""
    agent_id = canonical(name)
    if not agent_id:
        return {"found": False, "spoken": f"I have no agent called {name}."}
    teams = _teams()
    workers = teams.get(agent_id, [])
    display = agent_id.split("_")[0].upper()
    if not workers:
        return {"found": True, "id": agent_id, "name": display, "workers": [],
                "spoken": f"{display} has no workers of its own."}
    detail = [{"name": getattr(w, "name", str(w)),
               "role": getattr(w, "role", "")} for w in workers]
    return {"found": True, "id": agent_id, "name": display, "workers": detail,
            "spoken": (f"{len(detail)} workers report to {display}: "
                       + ", ".join(f"{w['name']} ({w['role']})" if w["role"]
                                   else w["name"] for w in detail) + ".")}


def status() -> dict[str, Any]:
    team = roster()
    return {
        "state": "ONLINE" if team else "EMPTY",
        "main_agents": len(team),
        "workers": sum(e["worker_count"] for e in team),
        "source": ("agent_runtime.AGENT_ROLES + tools.subagents._SPECIALISTS "
                   "+ agent_teams._TEAMS, joined to agents.registry health"),
        "loads_runtime": False,
        "note": ("Identity is configuration, not conversation memory. It "
                 "survives restart because it is read from code, and it is "
                 "answerable while every agent is asleep."),
    }
