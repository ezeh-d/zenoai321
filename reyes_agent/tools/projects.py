"""General project files -- websites, scripts, small apps -- as opposed to
notes.py's markdown-only `write_note`. Lives under 02-Projects in the
vault so it shows up alongside everything else REYES manages, but any
file type is fair game: .html, .css, .js, .py, whatever the task needs.

Path safety matters here more than in write_note: the filename comes from
model output, so it's resolved and checked against the project folder
before every write -- no "../../" escaping into the rest of the filesystem.
"""

from __future__ import annotations

import re
from pathlib import Path

from reyes_agent import config
from reyes_agent.tools import register


def _slug(name: str) -> str:
    keep = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"\s+", "-", keep).lower() or "project"


@register(
    name="write_project_file",
    description=(
        "Write a file into a project folder -- HTML, CSS, JS, Python, or "
        "any text format. For building websites, scripts, or small apps. "
        "Creates the project folder if needed; overwrites the file if it "
        "already exists at that path."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_name": {
                "type": "string",
                "description": "Project folder name, e.g. 'portfolio-site'.",
            },
            "filename": {
                "type": "string",
                "description": "File path within the project, e.g. 'index.html' or 'css/style.css'.",
            },
            "content": {"type": "string", "description": "The full file content."},
        },
        "required": ["project_name", "filename", "content"],
    },
)
def write_project_file(project_name: str, filename: str, content: str) -> str:
    if not config.VAULT_PATH.is_dir():
        return f"No vault found at {config.VAULT_PATH}. Check VAULT_PATH in .env."

    project_dir = (config.VAULT_PATH / "02-Projects" / _slug(project_name)).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    target = (project_dir / filename).resolve()
    if project_dir not in target.parents:
        return f"Invalid filename '{filename}' -- must stay inside the project folder."

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    # Coding workspace overlay (see index.html #code-overlay): a real-time
    # view of what's actually being built, not a description of it -- same
    # notification_bus -> SSE -> panel pattern show_map already uses.
    # Best-effort: a browser tab may not even be open (CLI/voice/Telegram
    # paths write project files too), so this never blocks the write itself.
    try:
        from reyes_agent import notification_bus

        files = sorted(str(p.relative_to(project_dir)) for p in project_dir.rglob("*") if p.is_file())
        notification_bus.publish(
            {
                "type": "workspace_code",
                "project": project_name,
                "file": filename,
                "content": content[:6000],
                "files": files,
            }
        )
    except Exception:  # noqa: BLE001
        pass

    return f"Wrote {target.relative_to(config.VAULT_PATH)} ({len(content)} chars)."


@register(
    name="list_project_files",
    description="List the files in a project folder under 02-Projects.",
    input_schema={
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "Project folder name."},
        },
        "required": ["project_name"],
    },
)
def list_project_files(project_name: str) -> str:
    project_dir = config.VAULT_PATH / "02-Projects" / _slug(project_name)
    if not project_dir.is_dir():
        return f"No project folder named '{project_name}' yet."
    files = sorted(str(p.relative_to(project_dir)) for p in project_dir.rglob("*") if p.is_file())
    if not files:
        return f"Project '{project_name}' exists but has no files yet."
    return "\n".join(files)
