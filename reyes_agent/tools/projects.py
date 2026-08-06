"""General project files -- websites, scripts, small apps -- as opposed to
notes.py's markdown-only `write_note`. Existing projects stay under
02-Projects, while a NEW project asks Divine for an explicit save location
before it writes anything substantial. Any text file type is fair game:
.html, .css, .js, .py, whatever the task needs.

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
            "destination": {
                "type": "string",
                "description": (
                    "Required before creating a NEW project unless Divine already chose one in the Live Activity View. "
                    "Use Desktop, Documents, ZENO Projects, or a full folder path. "
                    "Do not guess a destination; ask Divine first."
                ),
            },
        },
        "required": ["project_name", "filename", "content"],
    },
)
def write_project_file(project_name: str, filename: str, content: str, destination: str = "") -> str:
    """Write one real file, with a visible destination and activity trail.

    A legacy project can continue without interruption. A project folder
    that does not exist must have a user-selected destination; this prevents
    the old silent default write from scattering new work where Divine cannot
    find it.
    """
    from reyes_agent import project_activity

    legacy_dir = (config.VAULT_PATH / "02-Projects" / _slug(project_name)).resolve()
    try:
        if destination.strip():
            selected = project_activity.select_destination(project_name, destination)
            project_dir = Path(selected["project_path"])
        else:
            selected_root = project_activity.saved_destination(project_name)
            if selected_root is not None:
                project_dir = (selected_root / _slug(project_name)).resolve()
            elif project_activity.is_known_project_dir(project_name, legacy_dir):
                # Preserve previously created ZENO projects exactly where
                # they are. The destination question applies to NEW work.
                project_dir = legacy_dir
            else:
                project_activity.request_destination(project_name)
                return (
                    f"Before creating '{project_name}', ask Divine where to save it: "
                    "Desktop, Documents, ZENO Projects, or another full folder path. "
                    "No project files were created."
                )
        project_activity.begin(project_name, project_dir)
    except (OSError, ValueError) as exc:
        project_activity.failed(project_name, str(exc))
        return f"Could not use that project destination: {exc}"

    try:
        project_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        project_activity.failed(project_name, f"Could not create folder: {exc}")
        return f"Could not create project folder '{project_dir}': {exc}"

    target = (project_dir / filename).resolve()
    if project_dir not in target.parents:
        project_activity.failed(project_name, f"Invalid filename '{filename}'")
        return f"Invalid filename '{filename}' -- must stay inside the project folder."

    project_activity.file_started(project_name, filename)
    # Capture a small, non-sensitive before-state immediately before the
    # actual write. This is the only write path with an implemented inverse;
    # other actions remain honestly marked non-reversible.
    try:
        from reyes_agent import intelligence

        action_id = intelligence.begin_project_write(target)
    except Exception:  # noqa: BLE001 -- undo history must never block a file write
        action_id = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        project_activity.file_completed(project_name, filename, content)
    except OSError as exc:
        try:
            from reyes_agent import intelligence

            intelligence.abandon_project_write(action_id, f"Could not write {filename}: {exc}")
        except Exception:  # noqa: BLE001
            pass
        project_activity.failed(project_name, f"Could not write {filename}: {exc}")
        return f"Could not write '{filename}': {exc}"

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

    try:
        shown = str(target.relative_to(config.VAULT_PATH))
    except ValueError:
        shown = str(target)
    result = f"Wrote {shown} ({len(content)} chars)."
    try:
        from reyes_agent import intelligence

        intelligence.complete_project_write(action_id, target, result)
    except Exception:  # noqa: BLE001
        pass
    return result


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
    from reyes_agent import project_activity

    selected_root = project_activity.saved_destination(project_name)
    project_dir = (selected_root / _slug(project_name) if selected_root else
                   config.VAULT_PATH / "02-Projects" / _slug(project_name))
    if not project_dir.is_dir():
        return f"No project folder named '{project_name}' yet."
    files = sorted(str(p.relative_to(project_dir)) for p in project_dir.rglob("*") if p.is_file())
    if not files:
        return f"Project '{project_name}' exists but has no files yet."
    return "\n".join(files)
