"""Obsidian vault tools beyond search: writing notes, canvases, links, and
a database-style view (Obsidian "Bases").

Safe by design, same rule as the old REYES build: writing to an existing
note APPENDS a dated block, it never overwrites or deletes what's there.

Note on Bases (.base) files: the format is newer and thinly documented.
The generated file matches the confirmed-valid structure already present
in this vault (Untitled.base) plus a best-effort filter block -- open it
in Obsidian and adjust the filter in the UI if the syntax has moved on.
"""

from __future__ import annotations

import json
import os
import re
import time

from reyes_agent import config
from reyes_agent.tools import register


@register(
    name="setup_vault_structure",
    description=(
        "Create REYES's standard vault folder structure (Inbox, Knowledge, "
        "Projects, Daily, Outputs, Resources, Archive, System/memory) if "
        "it doesn't already exist. Safe to run anytime -- only creates "
        "missing folders, never touches existing files or folders."
    ),
    input_schema={"type": "object", "properties": {}},
)
def setup_vault_structure() -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    folders = [
        "00-Inbox",
        "01-Knowledge",
        "02-Projects",
        "03-Daily",
        "04-Reyes-Outputs/briefings",
        "04-Reyes-Outputs/connections",
        "04-Reyes-Outputs/patterns",
        "04-Reyes-Outputs/reviews",
        "05-Resources/templates",
        "06-Archive",
        "07-System/memory",
    ]
    created = []
    for folder in folders:
        path = os.path.join(config.VAULT_PATH, folder)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            created.append(folder)
    if not created:
        return "Vault structure already exists -- nothing to create."
    return f"Created {len(created)} folder(s): {', '.join(created)}"


def _slug(title: str) -> str:
    keep = re.sub(r"[^\w\s-]", "", title).strip()
    return re.sub(r"\s+", " ", keep) or "note"


def _note_path(title: str) -> str:
    return os.path.join(config.VAULT_PATH, f"{_slug(title)}.md")


@register(
    name="write_note",
    description=(
        "Create or update a note in the Obsidian vault, with proper "
        "frontmatter (tags) and [[wiki links]] to related notes. If the "
        "note already exists, appends a dated block instead of "
        "overwriting -- existing content is never destroyed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Note title (becomes the filename)."},
            "content": {"type": "string", "description": "The note body, in markdown."},
            "tags": {"type": "string", "description": "Comma-separated tags, no # needed."},
            "links": {
                "type": "string",
                "description": "Comma-separated titles of related notes to link to.",
            },
        },
        "required": ["title", "content"],
    },
)
def write_note(title: str, content: str, tags: str = "", links: str = "") -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    path = _note_path(title)
    today = time.strftime("%Y-%m-%d %H:%M")
    link_line = ""
    if links:
        names = [f"[[{name.strip()}]]" for name in links.split(",") if name.strip()]
        if names:
            link_line = "\nRelated: " + " ".join(names) + "\n"

    if os.path.exists(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n## {today}\n{content}\n{link_line}")
        return f"Appended to existing note '{title}.md'."

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    frontmatter = "---\n" f"tags: [{', '.join(tag_list)}]\n" f"created: {today}\n" "---\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{frontmatter}# {title}\n\n{content}\n{link_line}")
    return f"Created note '{title}.md'."


@register(
    name="link_notes",
    description=(
        "Connect two existing notes with a real [[wiki link]] -- appends a "
        "'Related' line to each note pointing at the other, so the "
        "connection shows up in both notes and in Obsidian's graph view."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "note_a": {"type": "string", "description": "First note's title."},
            "note_b": {"type": "string", "description": "Second note's title."},
        },
        "required": ["note_a", "note_b"],
    },
)
def link_notes(note_a: str, note_b: str) -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    results = []
    for src, dst in ((note_a, note_b), (note_b, note_a)):
        path = _note_path(src)
        if not os.path.isfile(path):
            results.append(f"'{src}' doesn't exist -- skipped.")
            continue
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\nRelated: [[{dst}]]\n")
        results.append(f"Linked '{src}' -> '{dst}'.")
    return " ".join(results)


@register(
    name="create_canvas",
    description=(
        "Generate an Obsidian canvas (a visual map) with a central topic "
        "node connected to a set of existing notes, laid out automatically. "
        "Good for visualizing how a project's notes relate."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Canvas title (becomes the filename)."},
            "topic": {"type": "string", "description": "Text for the central hub node."},
            "note_titles": {
                "type": "string",
                "description": "Comma-separated titles of existing notes to place around the hub.",
            },
        },
        "required": ["name", "topic", "note_titles"],
    },
)
def create_canvas(name: str, topic: str, note_titles: str) -> str:
    import math

    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    titles = [t.strip() for t in note_titles.split(",") if t.strip()]
    if not titles:
        return "No note titles given -- nothing to put on the canvas."

    nodes = [{"id": "hub", "type": "text", "text": topic, "x": 0, "y": 0, "width": 260, "height": 70}]
    edges = []
    radius = 420
    for i, title in enumerate(titles):
        angle = (2 * math.pi * i) / len(titles)
        x = round(radius * math.cos(angle)) - 125
        y = round(radius * math.sin(angle)) - 50
        node_id = f"n{i}"
        nodes.append(
            {"id": node_id, "type": "file", "file": f"{_slug(title)}.md", "x": x, "y": y, "width": 250, "height": 100}
        )
        edges.append({"id": f"e{i}", "fromNode": "hub", "toNode": node_id})

    canvas = {"nodes": nodes, "edges": edges}
    path = os.path.join(config.VAULT_PATH, f"{_slug(name)}.canvas")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, indent=2)
    return f"Created canvas '{name}.canvas' with {len(titles)} notes around '{topic}'."


@register(
    name="create_database_view",
    description=(
        "Generate an Obsidian Bases (.base) database-style table view over "
        "notes, optionally filtered by tag. Bases is a newer Obsidian "
        "feature -- open the result in Obsidian and adjust the filter in "
        "the UI if needed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "View name (becomes the filename)."},
            "tag_filter": {
                "type": "string",
                "description": "Optional tag to filter by (without #). Leave blank for all notes.",
            },
        },
        "required": ["name"],
    },
)
def create_database_view(name: str, tag_filter: str = "") -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    lines = ["views:", "  - type: table", f"    name: {name}"]
    if tag_filter.strip():
        lines += [
            "    filters:",
            "      and:",
            f'        - file.tags.contains("{tag_filter.strip()}")',
        ]
    path = os.path.join(config.VAULT_PATH, f"{_slug(name)}.base")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    note = f" filtered by tag '{tag_filter}'" if tag_filter.strip() else ""
    return f"Created database view '{name}.base'{note}. Check it opens correctly in Obsidian -- Bases syntax is still evolving."


@register(
    name="vault_structure_report",
    description=(
        "Audit the vault: lists every note's tags and how many notes link "
        "to it, and flags orphan notes with no links in or out. Use this "
        "when the user wants the vault organized or wants to know what's "
        "disconnected."
    ),
    input_schema={"type": "object", "properties": {}},
)
def vault_structure_report() -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    from reyes_agent.tools.notes import _iter_notes

    link_pattern = re.compile(r"\[\[([^\]|#]+)")
    tag_pattern = re.compile(r"^tags:\s*\[(.*?)\]", re.MULTILINE)

    notes = {}
    outgoing: dict[str, set[str]] = {}
    for path, title in _iter_notes():
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        tags_match = tag_pattern.search(text)
        tags = [t.strip() for t in tags_match.group(1).split(",") if t.strip()] if tags_match else []
        links = {m.strip() for m in link_pattern.findall(text)}
        notes[title] = tags
        outgoing[title] = links

    if not notes:
        return "Vault has no notes yet."

    incoming: dict[str, int] = {t: 0 for t in notes}
    for title, links in outgoing.items():
        for linked in links:
            if linked in incoming:
                incoming[linked] += 1

    lines = []
    orphans = []
    for title in sorted(notes):
        tags = notes[title]
        in_count = incoming[title]
        out_count = len(outgoing[title])
        tag_str = f"tags: {', '.join(tags)}" if tags else "no tags"
        lines.append(f"{title} -- {tag_str}, {in_count} incoming link(s), {out_count} outgoing")
        if in_count == 0 and out_count == 0:
            orphans.append(title)

    report = "\n".join(lines)
    if orphans:
        report += f"\n\nOrphans (no links in or out): {', '.join(orphans)}"
    return report
