"""Real, lightweight entry points for Design Intelligence and Learning Mode."""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="learning_mode",
    description=(
        "Start, continue, update, or show a persistent owner learning path. Use for an explicit lesson or when the user "
        "asks to continue a named subject. Stores only subject, level, completed topic, optional struggle/exercise and next "
        "lesson locally; it does not create a separate agent or infer private facts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "continue", "progress", "map", "status"]},
            "subject": {"type": "string", "description": "For example: graphic design, logo design, UI UX, or Python."},
            "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced", "unsure"]},
            "goal": {"type": "string"},
            "completed_topic": {"type": "string", "description": "Only a topic the learner actually completed."},
            "struggle": {"type": "string", "description": "An explicitly reported difficulty."},
            "exercise": {"type": "string", "description": "Current agreed practical exercise."},
        },
        "required": ["action", "subject"],
    },
    light=True,
)
def learning_mode(action: str, subject: str, level: str = "", goal: str = "", completed_topic: str = "",
                  struggle: str = "", exercise: str = "") -> str:
    from reyes_agent import learning_mode as learning

    op = str(action or "").strip().lower()
    if op == "start":
        return learning.format_path(learning.start(subject, level=level or "beginner", goal=goal))
    current = learning.status(subject)
    if current is None:
        current = learning.start(subject, level=level or "beginner", goal=goal)
    if op == "progress":
        current = learning.update(subject, completed_topic=completed_topic, struggle=struggle,
                                  exercise=exercise, level=level)
    if op in {"continue", "status", "progress", "map"}:
        return learning.format_path(current)
    return "Unknown learning action. Use start, continue, progress, map, or status."


@register(
    name="creator_project",
    description=("Start, update, or inspect one connected owner creative project. Records only project goal, current/completed "
                 "stages, real files, decisions and open tasks in ZENO's existing state database."),
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["start", "update", "status", "portfolio"]},
        "project_id": {"type": "string"}, "name": {"type": "string"}, "goal": {"type": "string"},
        "stage": {"type": "string", "enum": ["IDEA", "AUDIENCE", "POSITIONING", "IDENTITY", "CONCEPTS", "ASSETS", "LAUNCH"]},
        "completed_stage": {"type": "string"}, "file": {"type": "string", "description": "Only a verified created/modified file."},
        "decision": {"type": "string"}, "open_task": {"type": "string"},
    }, "required": ["action"]}, light=True,
)
def creator_project(action: str, project_id: str = "", name: str = "", goal: str = "", stage: str = "",
                    completed_stage: str = "", file: str = "", decision: str = "", open_task: str = "") -> str:
    from reyes_agent import creator_mode
    if action == "start":
        return creator_mode.format_project(creator_mode.start_project(name, goal, project_id=project_id))
    if action == "update":
        state = creator_mode.update_project(project_id, stage=stage, completed_stage=completed_stage, file=file,
                                            decision=decision, open_task=open_task)
        return creator_mode.format_project(state) if state else "No creator project found for that project_id."
    if action == "status":
        state = creator_mode.project_status(project_id)
        return creator_mode.format_project(state) if state else "No creator project found for that project_id."
    if action == "portfolio":
        return creator_mode.portfolio_case_study(project_id) or "No creator project found for that project_id."
    return "Unknown creator action. Use start, update, status, or portfolio."


@register(
    name="mastery_mode",
    description=("Track an owner-requested practical mastery path. Evidence and weak areas must be explicitly supplied; this "
                 "never fabricates an assessment or promotes a learner automatically."),
    input_schema={"type": "object", "properties": {
        "subject": {"type": "string"},
        "level": {"type": "string", "enum": ["BEGINNER", "FOUNDATION", "PRACTICE", "INTERMEDIATE", "ADVANCED", "CLIENT_PROJECT", "ASSESSMENT"]},
        "evidence": {"type": "string"}, "weak_area": {"type": "string"}, "next_challenge": {"type": "string"},
    }, "required": ["subject"]}, light=True,
)
def mastery_mode(subject: str, level: str = "BEGINNER", evidence: str = "", weak_area: str = "", next_challenge: str = "") -> str:
    from reyes_agent import creator_mode
    state = creator_mode.update_mastery(subject, level=level, evidence=evidence, weak_area=weak_area, next_challenge=next_challenge)
    return (f"{state['subject'].upper()} â€” {state['level']}\nEvidence: {', '.join(state['evidence']) or 'none recorded'}\n"
            f"Weak areas: {', '.join(state['weak_areas']) or 'none recorded'}\nNext challenge: {state['next_challenge'] or 'not set'}")


@register(
    name="foodie_mode",
    description=("Start or advance an owner-requested step-by-step cooking session, show its truthful current step, or scale a "
                 "structured ingredient list. Does not create a separate food memory or claim a timer was set."),
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["start", "next", "status", "scale"]}, "dish": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "ingredients": {"type": "array", "items": {"type": "object"}},
        "from_servings": {"type": "number"}, "to_servings": {"type": "number"},
    }, "required": ["action"]}, light=True,
)
def foodie_mode(action: str, dish: str = "", steps: list[str] | None = None, ingredients: list[dict] | None = None,
                from_servings: float = 0, to_servings: float = 0) -> str:
    from reyes_agent import foodie_intelligence as foodie
    if action == "start":
        state = foodie.start_session(dish, steps or [])
    elif action == "next":
        state = foodie.advance_session()
    elif action == "status":
        state = foodie.session_status()
    elif action == "scale":
        scaled = foodie.scale(ingredients or [], from_servings, to_servings)
        return "Scaled ingredients: " + "; ".join(f"{item['amount'] if item['amount'] is not None else 'adjust to taste'} {item['unit']} {item['name']}".strip() for item in scaled) + ". Adjust salt, spices, leavening and thickeners gradually."
    else:
        return "Unknown Foodie action. Use start, next, status, or scale."
    if state is None:
        return "No active cooking session. Start one only after agreeing the practical steps."
    return f"{state['dish']} â€” step {state['step_index'] + 1} of {len(state['steps'])}: {state['current_step']}"


@register(
    name="design_capabilities",
    description="List ZENO's connected design capabilities and their honest execution limits.",
    input_schema={"type": "object", "properties": {}},
)
def design_capabilities() -> str:
    """Measured state first, guidance second.

    CAPABILITY_LIBRARY is prose, and prose cannot look at the machine -- it
    said 3D_DESIGN was "PARTIAL ... when installed/configured" while Blender
    5.2 sat in Program Files, and would have said exactly the same on a
    machine with no Blender. Anything `limits` can probe is reported from the
    probe; the rest stays as written guidance, clearly marked as such.
    """
    from reyes_agent import design_intelligence
    from reyes_agent.creative import limits

    measured = limits.capabilities()
    lines = ["MEASURED ON THIS COMPUTER"]
    for name, capability in sorted(measured.items()):
        lines.append(f"  {name}: {capability.state} -- {capability.evidence}"
                     + (f" ({capability.detail})" if capability.detail else ""))

    probed = set(measured)
    guidance = [(n, d) for n, d in design_intelligence.CAPABILITY_LIBRARY.items()
                if n not in probed]
    if guidance:
        lines.append("")
        lines.append("DESIGN GUIDANCE (advice, not connected software)")
        lines += [f"  {name}: {detail}" for name, detail in guidance]
    return "\n".join(lines)


@register(
    name="design_tool_check",
    description=("Check whether ZENO can actually drive a specific design tool "
                 "or capability before promising it -- Figma, Canva, "
                 "Photoshop, Illustrator, a printer, a vector editor, Blender "
                 "3D, UI components, image generation or design critique. "
                 "Returns the real reason when it cannot."),
    input_schema={"type": "object", "properties": {
        "capability": {"type": "string",
                       "description": "e.g. FIGMA, PHOTOSHOP, 3D_DESIGN, "
                                      "DESIGN_CRITIQUE, UI_COMPONENTS"}},
        "required": ["capability"]},
)
def design_tool_check(capability: str) -> str:
    import json

    from reyes_agent.creative import limits

    found = limits.check(capability)
    allowed, refusal = limits.require(capability)
    return json.dumps({**found.as_dict(), "allowed": allowed,
                       "say_instead": refusal,
                       "connected_now": limits.connected()}, default=str)


@register(
    name="critique_current_design",
    description=(
        "Capture and critique the currently visible design using the existing screenshot/vision capability. Use only when the "
        "user has asked ZENO to inspect/rate the visible design. Returns the vision result; if vision is unavailable it says so."
    ),
    input_schema={"type": "object", "properties": {}},
)
def critique_current_design() -> str:
    from reyes_agent import design_intelligence
    from reyes_agent.tools.vision import take_screenshot

    return take_screenshot(design_intelligence.critique_prompt())
