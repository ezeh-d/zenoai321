"""Knowledge Graph tools + the Research Lab.

The Research Lab is a managed workspace rather than a one-shot answer: it
creates a real mission, runs real research through ARIS's live worker,
saves a real report file, and links it back. Every artefact it claims to
have produced exists on disk.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="knowledge_graph_stats",
    description=(
        "Overview of the vault's knowledge graph -- how many notes, tags "
        "and links exist, which notes are the biggest hubs, and which are "
        "orphans nothing links to. Built from real wikilinks, tags and "
        "folders, not inferred."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def knowledge_graph_stats() -> str:
    from reyes_agent import knowledge_graph as kg

    s = kg.stats()
    if not s["nodes"]:
        return "The vault has no notes yet, so there's no graph to show."
    lines = [
        f"Knowledge graph: {s['nodes']} nodes, {s['edges']} edges.",
        f"  {s['by_kind'].get('note', 0)} notes, {s['by_kind'].get('tag', 0)} tags, "
        f"{s['by_kind'].get('folder', 0)} folders",
        f"  edges: " + ", ".join(f"{k}={v}" for k, v in s["by_edge_kind"].items()),
    ]
    if s["hubs"]:
        lines.append("Most connected:")
        lines.extend(f"  {h['label']} ({h['connections']} connections)" for h in s["hubs"][:6])
    if s["orphan_count"]:
        lines.append(f"Orphans -- {s['orphan_count']} note(s) nothing links to:")
        lines.append("  " + ", ".join(s["orphans"][:10]))
        lines.append("  (Linking these in would make them findable by topic.)")
    return "\n".join(lines)


@register(
    name="explore_knowledge",
    description=(
        "Show everything in the vault connected to a topic, traced through "
        "real links and tags. Use for 'show me everything about X' or 'what "
        "relates to Y'. Complements search_vault_semantic: that finds "
        "similar TEXT, this finds actual CONNECTIONS."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "depth": {"type": "integer", "description": "How many hops out. 1-3, default 1."},
        },
        "required": ["topic"],
    },
    light=True,
)
def explore_knowledge(topic: str, depth: int = 1) -> str:
    from reyes_agent import knowledge_graph as kg

    r = kg.neighbourhood(topic, depth=depth)
    if r.get("error"):
        return r["error"]
    if not r.get("found"):
        return r.get("message", f"Nothing found for '{topic}'.")
    if not r["connections"]:
        return (f"'{topic}' exists in the vault ({', '.join(r['seeds'])}) but nothing "
                "links to or from it yet.")
    lines = [f"Connected to '{topic}' (from {', '.join(r['seeds'][:3])}):"]
    for c in r["connections"]:
        lines.append(f"  {c['from']} --{c['via']}--> {c['to']}" + (f"  [{c['path']}]" if c["path"] else ""))
    return "\n".join(lines)


@register(
    name="research_lab",
    description=(
        "Run a managed research project: creates a mission, dispatches ARIS "
        "to research the topic, saves a real report into the vault, and "
        "links it to the mission. Use for substantial research the user "
        "wants kept, not for a quick question."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "What to research."},
            "questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Specific questions the research must answer.",
            },
        },
        "required": ["topic"],
    },
)
def research_lab(topic: str, questions: list | None = None) -> str:
    from reyes_agent.tools.missions import create_mission, list_missions_dicts, update_mission
    from reyes_agent.tools.notes import write_note
    from reyes_agent.tools.subagents import delegate

    topic = topic.strip()
    qs = [q for q in (questions or []) if str(q).strip()]

    # 1. Real mission, so the work is tracked like any other objective.
    create_mission(
        name=f"Research: {topic}",
        description=f"Managed research project on {topic}.",
        mission_type="research",
        priority="medium",
        objectives=(qs or ["Gather sources", "Summarise findings", "Identify open questions"]),
    )
    missions = list_missions_dicts()
    mission_id = missions[0]["id"] if missions else None

    # 2. Real research through ARIS's live worker.
    brief = (
        f"Research this thoroughly: {topic}.\n"
        + ("Answer specifically:\n" + "\n".join(f"- {q}" for q in qs) if qs else "")
        + "\nSearch the vault and the web. Report: key findings, what the "
        "evidence actually supports, open questions, and where each claim "
        "came from. Say plainly when you could not verify something."
    )
    findings = delegate("aris", brief)

    # 3. Real report on disk.
    body = [
        f"# Research: {topic}", "",
        f"Mission: #{mission_id}" if mission_id else "",
        "", "## Questions", "",
    ]
    body += [f"- {q}" for q in qs] or ["- (none specified)"]
    body += ["", "## Findings", "", findings, "",
             "## Provenance", "",
             "Researched by ARIS via ZENO's Research Lab. Web results are pages "
             "opened for reading, not verified facts -- check anything load-bearing."]
    note_title = f"Research - {topic}"[:80]
    saved = write_note(title=note_title, content="\n".join(b for b in body if b is not None))

    if mission_id:
        update_mission(mission_id, note=f"Research completed; report saved as '{note_title}'.",
                       status="reviewing", progress=70)

    return (f"RESEARCH LAB -- {topic}\n"
            f"  Mission #{mission_id} created and updated.\n"
            f"  Report: {saved}\n\n"
            f"Findings:\n{findings}\n\n"
            "Summarise the key points for the user; the full report is saved in the vault.")
