"""Agent-facing tools for the Campaign Engine (reyes_agent/campaigns.py).

The flow is deliberately a ratchet, and ZENO cannot skip a step:
draft -> add actions -> PREVIEW -> approve -> run -> monitor -> report.
`run_campaign` refuses anything that hasn't been approved, so there is no
path from "here are 100 emails" straight to sending them.
"""

from __future__ import annotations

from reyes_agent import campaigns
from reyes_agent.tools import register


@register(
    name="create_campaign",
    description=(
        "Start a new campaign (a reviewable batch of actions) in DRAFT. "
        "Use for repetitive bulk work: applying to many roles, publishing "
        "to several platforms, researching a list of companies, sending "
        "outreach. Nothing runs until the user previews and approves it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "kind": {"type": "string", "description": "e.g. jobs, outreach, content, research."},
            "description": {"type": "string"},
            "batch_size": {"type": "integer", "description": "Actions per batch before pausing for the delay. Default 1."},
            "delay_seconds": {"type": "number", "description": "Pause between actions/batches. Use for rate limits."},
        },
        "required": ["name"],
    },
    light=True,
)
def create_campaign(name: str, kind: str = "", description: str = "",
                    batch_size: int = 1, delay_seconds: float = 0) -> str:
    cid = campaigns.create_campaign(name, kind, description, batch_size, delay_seconds)
    return (f"Campaign #{cid} '{name}' created as a draft. Add its actions with "
            "add_campaign_actions, then show the user preview_campaign before approving.")


@register(
    name="add_campaign_actions",
    description=(
        "Add actions to a DRAFT campaign. Each action names a real tool "
        "and the exact parameters it will run with. Tool names are "
        "validated now, so the preview can't show something that would "
        "never work."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "campaign_id": {"type": "integer"},
            "actions": {
                "type": "array",
                "description": "The actions to queue.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Human-readable description of this one action."},
                        "tool": {"type": "string", "description": "Registered tool name to call."},
                        "params": {"type": "object", "description": "Exact arguments for that tool."},
                    },
                    "required": ["tool"],
                },
            },
        },
        "required": ["campaign_id", "actions"],
    },
)
def add_campaign_actions(campaign_id: int, actions: list) -> str:
    added, rejected = campaigns.add_items(campaign_id, actions or [])
    out = [f"Added {added} action(s) to campaign #{campaign_id}."]
    if rejected:
        out.append("Rejected:")
        out.extend(f"  - {r}" for r in rejected)
    if added:
        out.append("Now show the user preview_campaign before anything runs.")
    return "\n".join(out)


@register(
    name="preview_campaign",
    description=(
        "Show EVERY action a campaign will perform, with its real "
        "arguments. Always show this to the user and get their explicit "
        "go-ahead before calling approve_campaign."
    ),
    input_schema={
        "type": "object",
        "properties": {"campaign_id": {"type": "integer"}},
        "required": ["campaign_id"],
    },
    light=True,
)
def preview_campaign(campaign_id: int) -> str:
    c = campaigns.get_campaign(campaign_id)
    if c is None:
        return f"No campaign #{campaign_id}."
    if not c["items"]:
        return f"Campaign #{campaign_id} '{c['name']}' has no actions yet."
    lines = [
        f"CAMPAIGN #{c['id']} -- {c['name']}  [{c['status']}]",
        f"{len(c['items'])} action(s)"
        + (f", {c['batch_size']} per batch" if c["batch_size"] > 1 else "")
        + (f", {c['delay_seconds']}s between" if c["delay_seconds"] else ""),
        "",
    ]
    for i in c["items"]:
        mark = {"done": "[done]", "failed": "[FAILED]", "skipped": "[skipped]",
                "running": "[running]"}.get(i["status"], "")
        lines.append(f"{i['seq']:>3}. {mark} {i['label']}")
        lines.append(f"      {i['tool']}({i['params']})")
        if i["error"]:
            lines.append(f"      error: {i['error']}")
    lines.append("")
    if c["status"] == "draft":
        lines.append("This is a DRAFT -- nothing has run. Read it to the user, and only "
                     "call approve_campaign if they explicitly say yes.")
    return "\n".join(lines)


@register(
    name="approve_campaign",
    description=(
        "Approve an entire campaign in one confirmation -- ONLY after the "
        "user has seen preview_campaign and explicitly agreed. This is the "
        "single gate for the whole batch; do not call it on your own "
        "initiative."
    ),
    input_schema={
        "type": "object",
        "properties": {"campaign_id": {"type": "integer"}},
        "required": ["campaign_id"],
    },
)
def approve_campaign(campaign_id: int) -> str:
    ok, msg = campaigns.approve(campaign_id)
    return msg + (" Start it with run_campaign." if ok else "")


@register(
    name="run_campaign",
    description=(
        "Start (or resume) an APPROVED campaign. Runs on a background "
        "thread so ZENO stays responsive; check on it with "
        "campaign_status. Refuses to run anything unapproved."
    ),
    input_schema={
        "type": "object",
        "properties": {"campaign_id": {"type": "integer"}},
        "required": ["campaign_id"],
    },
)
def run_campaign(campaign_id: int) -> str:
    ok, msg = campaigns.start(campaign_id)
    return msg


@register(
    name="campaign_status",
    description="Progress of one campaign, or a list of all campaigns if no id is given.",
    input_schema={
        "type": "object",
        "properties": {"campaign_id": {"type": "integer", "description": "Omit to list all campaigns."}},
    },
    light=True,
)
def campaign_status(campaign_id: int = 0) -> str:
    if not campaign_id:
        rows = campaigns.list_campaigns()
        if not rows:
            return "No campaigns yet."
        return "\n".join(
            f"#{r['id']} {r['name']} -- {r['status']} ({r['done']}/{r['total']} done)" for r in rows
        )
    rep = campaigns.report(campaign_id)
    if rep is None:
        return f"No campaign #{campaign_id}."
    c = rep["counts"]
    lines = [
        f"Campaign #{rep['id']} '{rep['name']}' -- {rep['status']}",
        f"  {c.get('done',0)} done, {c.get('failed',0)} failed, {c.get('pending',0)} pending, "
        f"{c.get('skipped',0)} skipped, of {rep['total']} total",
    ]
    if rep["mission_id"]:
        lines.append(f"  tracked as mission #{rep['mission_id']}")
    if rep["failures"]:
        lines.append("  failures:")
        lines.extend(f"    {f['seq']}. {f['label']} -- {f['error']}" for f in rep["failures"][:10])
        lines.append("  retry_campaign_failures can reset these.")
    return "\n".join(lines)


@register(
    name="control_campaign",
    description="Pause, resume, or cancel a running campaign. Takes effect between actions.",
    input_schema={
        "type": "object",
        "properties": {
            "campaign_id": {"type": "integer"},
            "action": {"type": "string", "enum": ["pause", "resume", "cancel"]},
        },
        "required": ["campaign_id", "action"],
    },
)
def control_campaign(campaign_id: int, action: str) -> str:
    a = action.strip().lower()
    if a == "pause":
        return campaigns.pause(campaign_id)
    if a == "resume":
        return campaigns.resume(campaign_id)
    if a == "cancel":
        return campaigns.cancel(campaign_id)
    return "action must be pause, resume, or cancel."


@register(
    name="retry_campaign_failures",
    description="Reset a campaign's failed actions to pending so they can be run again.",
    input_schema={
        "type": "object",
        "properties": {"campaign_id": {"type": "integer"}},
        "required": ["campaign_id"],
    },
)
def retry_campaign_failures(campaign_id: int) -> str:
    _, msg = campaigns.retry_failed(campaign_id)
    return msg
