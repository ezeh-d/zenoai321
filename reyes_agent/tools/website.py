"""Compact Website Builder controls over existing build infrastructure."""
from __future__ import annotations
from pathlib import Path
from reyes_agent.tools import register

@register(name="website_project", description="Website Studio project controls. `list` shows registered sites; `find` resolves 'continue my restaurant website' to real candidates; `checkpoint` saves a restore point BEFORE a redesign; `checkpoints` lists them; `variant` copies a site to a new folder so 'make another version, keep this one' never overwrites the original; `inspect` runs static SEO/accessibility checks; `visual_inspect` renders ZENO's running local preview at desktop and mobile sizes and captures real screenshots/layout evidence. Reuses existing build folders and never starts a second server.", input_schema={"type":"object","properties":{"action":{"type":"string","enum":["list","find","checkpoint","checkpoints","variant","inspect","visual_inspect"]},"location":{"type":"string","description":"Project folder (not needed for list/find)."},"label":{"type":"string","description":"Checkpoint label, variant name, or search text for find."}} ,"required":["action"]})
def website_project(action: str, location: str = "", label: str = "") -> str:
    from reyes_agent import website_builder as wb
    if not wb.enabled(): return "Website Builder Mode is disabled by configuration."
    if action == "list":
        items=wb.projects(); return "No website projects are registered yet." if not items else "\n".join(f"{x['project_name']} — {x['framework']} — {x['status']} — {x['location']}" for x in items)
    if action == "find":
        matches=wb.find_project(label or location)
        if not matches: return f"No registered website matches '{label or location}'. Use action='list' to see them all."
        if len(matches) == 1:
            only=matches[0]; return f"One match: {only['project_name']} — {only['framework']} — {only['location']}"
        # Deliberately NOT auto-picking: editing the wrong site is the
        # destructive mistake this whole subsystem exists to avoid.
        return ("Several websites match -- ask which one before editing:\n"
                + "\n".join(f"{x['project_name']} — {x['framework']} — {x['location']}" for x in matches))
    root=Path(location).expanduser()
    if action == "checkpoint":
        item=wb.checkpoint(root,label)
        note=" (capped -- does not cover the whole project)" if item.get("truncated") else ""
        return f"Checkpoint {item['version']} created with {len(item['files'])} file(s){note}."
    if action == "checkpoints":
        items=wb.checkpoints(root); return "No checkpoints found." if not items else "\n".join(f"{x['version']}: {x['label']} ({len(x['files'])} files){' [capped]' if x.get('truncated') else ''}" for x in items)
    if action == "variant":
        item=wb.variant(root,label)
        note=" (capped -- some files were not copied)" if item.get("truncated") else ""
        return (f"Created '{item['name']}' as a separate project at {item['location']} with "
                f"{len(item['files'])} file(s){note}. The original at {item['source']} is untouched.")
    if action == "inspect":
        findings=wb.inspect(root); return "Static inspection found no basic title, description, or image-alt issues." if not findings else "Static inspection findings:\n"+"\n".join(findings)
    if action == "visual_inspect":
        report = wb.visual_inspect(root)
        lines = [f"Rendered {report['url']} at {len(report['captures'])} viewport(s)."]
        for capture in report["captures"]:
            size = capture["viewport"]
            lines.append(f"{size['width']}x{size['height']}: screenshot={capture['screenshot']} "
                         f"({capture['screenshot_bytes']} bytes), horizontal_overflow={capture['horizontal_overflow']}, "
                         f"title={capture['title']!r}.")
        lines.append("This is render/layout evidence, not an aesthetic or usability claim.")
        return "\n".join(lines)
    return "Unknown website_project action."

@register(name="website_check", description=(
    "Run a website project's REAL checks (npm run build, typecheck, lint -- whichever it actually has) "
    "plus static analysis, repair what is safely repairable, and report the errors that remain as "
    "structured items with category, file, line and likely cause. Use this after building or editing a "
    "site, and whenever the owner says it is broken. It repairs only deterministic things (installing "
    "declared dependencies, repointing an asset reference); anything needing a real code change is "
    "returned to you to fix deliberately -- take a checkpoint first."),
    input_schema={"type": "object", "properties": {
        "location": {"type": "string", "description": "The project folder."},
        "auto_fix": {"type": "boolean", "description": "Apply safe automatic repairs. Default true."},
    }, "required": ["location"]})
def _model_patcher(request: dict) -> object:
    """Ask the model for a TARGETED patch and return it as data.

    This is the only place the model participates in repair, and it never
    receives a filesystem or a shell -- it returns JSON, and
    `executors/patching.py` decides whether any of it may be written.

    Deliberately a plain provider call with no tools attached: a repair step
    that could call tools could do anything, which is exactly the
    unrestricted access the brief rules out.
    """
    import json

    from reyes_agent.provider import run_turn

    errors = request.get("errors", [])
    sources = request.get("sources", {})
    previous = request.get("previous_attempts", [])
    metadata = request.get("metadata", {})

    tried = ("\nAlready tried (do not repeat):\n"
             + "\n".join(f"- attempt {a.get('attempt')}: {a.get('detail')}"
                         f"{' (rolled back)' if a.get('rolled_back') else ''}" for a in previous)
             ) if previous else ""

    system = (
        "You repair a web project. Return ONLY a JSON object of the form "
        '{\"files\":[{\"path\":\"<existing path>\",\"content\":\"<complete new file>\"}]}. '
        "Change the FEWEST files that fix the reported errors, and only files listed under "
        "SOURCES. Return each changed file in full. Do not add dependencies, do not edit "
        "lockfiles or config you were not shown, and do not restructure the project. "
        "No prose, no markdown fences."
    )
    prompt = (
        f"PROJECT: {json.dumps(metadata)[:800]}\n"
        f"ERRORS:\n{json.dumps(errors, indent=1)[:4000]}\n"
        f"SOURCES:\n"
        + "\n".join(f"--- {name} ---\n{text}" for name, text in sources.items())
        + tried
    )
    turn = run_turn([{"role": "user", "content": prompt}], system=system, tools=[],
                    task_kind="coding")
    text = (turn.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return []


def website_check(location: str, auto_fix: bool = True) -> str:
    from reyes_agent import config, task_engine, website_builder as wb
    from reyes_agent.executors import build_check

    if not wb.enabled():
        return "Website Builder Mode is disabled by configuration."
    root = wb.safe_project_root(Path(location).expanduser())
    if not root.is_dir():
        return f"No project folder at {root}."

    # Runs inside a task so its commands and output appear in the Live
    # Activity panel as they happen, rather than surfacing only at the end.
    task = task_engine.create(f"Checking {root.name}", plan=["Checking the generated code"])
    try:
        enabled = bool(auto_fix) and config.WEBSITE_AUTO_FIX
        report = build_check.verify(
            task.id, root, auto_fix=enabled,
            max_attempts=config.WEBSITE_MAX_FIX_ATTEMPTS,
            # The owner should not have to ask a second time: when a
            # deterministic fix does not exist, ZENO requests the patch
            # itself, and patching.py decides whether it may be written.
            patcher=_model_patcher if enabled else None)
    except task_engine.TaskCancelled:
        return "The check was cancelled."
    except Exception as exc:  # noqa: BLE001 -- a broken project must not break ZENO
        task_engine.fail(task.id, f"{type(exc).__name__}: {exc}")
        return f"The check could not complete: {type(exc).__name__}: {exc}"
    finally:
        task_engine.cancel(task.id, "check finished")

    lines = [report.summary()]
    for entry in report.ledger:
        lines.append(f"  attempt {entry.get('attempt')}: {entry.get('confidence')} -- {entry.get('detail')}"
                     + (" [rolled back]" if entry.get("rolled_back") else ""))
    if report.exhausted:
        lines.append("AUTO_FIX_EXHAUSTED -- the repair budget is spent and the last checkpoint is preserved. "
                     "Report the remaining error to the owner instead of trying again.")
    elif not report.ok:
        lines.append("Fix these deliberately: take a checkpoint with website_project(action='checkpoint'), "
                     "then rewrite only the affected files with build_add_files.")
    return "\n".join(lines)


@register(name="website_restore_checkpoint", description="Undo a website change by restoring a Website Studio checkpoint. Omit `version` to undo to the most recent deliberate checkpoint -- that is what 'undo that' means. The current project is saved as a new checkpoint first, so the restore is itself reversible. Requires explicit confirmation because it removes files created after that version.", input_schema={"type":"object","properties":{"location":{"type":"string","description":"The project folder."},"version":{"type":"string","description":"Checkpoint id. Omit to undo to the latest deliberate checkpoint."}},"required":["location"]}, requires_confirmation=True)
def website_restore_checkpoint(location: str, version: str = "") -> str:
    from reyes_agent import website_builder as wb
    if not wb.enabled(): return "Website Builder Mode is disabled by configuration."
    root=Path(location).expanduser()
    target=str(version or "").strip() or wb.latest_restorable(root)
    result=wb.restore_checkpoint(root, target)
    lines=[f"Restored {result['version']}: {len(result['restored'])} file(s) restored, "
           f"{len(result['removed'])} later file(s) removed. Current state was saved first as {result['backup']}."]
    if not result["complete"]:
        # Stated plainly rather than implied: the owner needs to know this
        # was a partial restore, not a clean rewind.
        lines.append("NOTE: that checkpoint was capped, so it does not describe the whole project. "
                     "Files were copied back but nothing was deleted -- anything added since is still there.")
    if result["undeletable"]:
        lines.append("Could not remove: " + "; ".join(result["undeletable"][:3]))
    return "\n".join(lines)
