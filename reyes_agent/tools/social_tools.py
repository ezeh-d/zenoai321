"""The tools that let ZENO reach its own social subsystem.

WHY THIS FILE IS THE POINT
--------------------------
The social package was written in full -- store, adapters, pipeline, leads,
safety, control -- and then registered nowhere. No tool, no route, no test.
ZENO could not answer "how are your socials doing?" because nothing connected
the question to the code. These registrations are that connection.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
There is no tool that creates an account, types a password, submits a
verification code or answers a CAPTCHA. Account creation is assisted by
opening the official page and handing the owner a checklist -- the typing of
credentials stays with the owner, always. `social_setup` is that assistant.

Publishing is gated three times over: SOCIAL_DRY_RUN, the owner's mode, and
`requires_confirmation` on the publish tool itself.
"""

from __future__ import annotations

import json
import time
from typing import Any

from reyes_agent.social import (
    control, dashboard, identity as social_identity, leads as social_leads,
    pipeline as social_pipeline, store as social_store,
)
from reyes_agent.social.adapters import all_adapters, health as adapter_health
from reyes_agent.social.content import ContentIdeaEngine
from reyes_agent.tools import register

PLATFORMS = (social_store.INSTAGRAM, social_store.TIKTOK)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _platform(value: str) -> str | None:
    low = (value or "").strip().casefold()
    if low in {"ig", "insta", "instagram"}:
        return social_store.INSTAGRAM
    if low in {"tt", "tiktok", "tik tok"}:
        return social_store.TIKTOK
    return None


# --- status -------------------------------------------------------------
@register(
    "social_status",
    "How ZENO's own Instagram and TikTok are doing: followers, recent post "
    "performance, best content, scheduled posts and new client leads. Every "
    "number comes from a real platform API call; anything never collected is "
    "reported as NOT AVAILABLE rather than as zero.",
    {"type": "object", "properties": {
        "detail": {"type": "string", "enum": ["summary", "full"],
                   "description": "summary is spoken prose; full is the raw dashboard"},
    }},
    light=True,
)
def social_status(detail: str = "summary") -> str:
    if detail == "full":
        return _json(dashboard.overview())
    return dashboard.spoken_summary()


@register(
    "social_health",
    "Health of each social integration: HEALTHY, DEGRADED, AUTH_REQUIRED, "
    "RATE_LIMITED, NOT_CONFIGURED or OFFLINE, with the reason.",
    {"type": "object", "properties": {}},
    light=True,
)
def social_health() -> str:
    return _json({"platforms": adapter_health(),
                  "system": control.panel()})


# --- content ------------------------------------------------------------
@register(
    "social_ideas",
    "Generate content ideas for ZENO's socials, grounded in REAL development "
    "evidence: recent commits, measured performance facts and test counts. "
    "Returns nothing when no real evidence exists rather than inventing a topic.",
    {"type": "object", "properties": {
        "platform": {"type": "string", "description": "instagram or tiktok"},
        "limit": {"type": "integer", "description": "how many ideas (default 5)"},
        "save": {"type": "boolean",
                 "description": "persist the ideas as content records"},
    }},
)
def social_ideas(platform: str = "tiktok", limit: int = 5,
                 save: bool = False) -> str:
    target = _platform(platform) or social_store.TIKTOK
    engine = ContentIdeaEngine()
    ideas = engine.generate(platform=target, limit=max(1, min(int(limit), 20)))
    if not ideas:
        return ("No content ideas generated. The idea engine builds from real "
                "evidence -- recent commits, measured facts, test counts -- and "
                "found none it could stand behind. It will not invent a topic.")

    out = []
    for idea in ideas:
        record = idea.as_dict()
        if save:
            record["content_id"] = engine.save(idea)
        out.append(record)
    header = (f"{len(out)} idea(s) for {target}"
              + (" (saved as content records)" if save else " (not saved)"))
    return f"{header}\n\n{_json(out)}"


@register(
    "social_content",
    "List or inspect ZENO's social content items and their pipeline status "
    "(IDEA, SCRIPTING, READY_FOR_REVIEW, APPROVED, SCHEDULED, PUBLISHED, FAILED).",
    {"type": "object", "properties": {
        "content_id": {"type": "string", "description": "inspect one item"},
        "status": {"type": "string", "description": "filter by status"},
        "platform": {"type": "string", "description": "instagram or tiktok"},
    }},
    light=True,
)
def social_content(content_id: str = "", status: str = "",
                   platform: str = "") -> str:
    store = social_store.get_store()
    if content_id:
        item = store.content(content_id.strip())
        if item is None:
            return f"No content item {content_id!r}."
        item["analytics"] = store.analytics_for(content_id.strip())
        return _json(item)
    items = store.list_content(
        status=(status.strip().upper() or None),
        platform=_platform(platform), limit=40)
    if not items:
        return "No content items match."
    return _json([{k: v for k, v in item.items()
                   if k in ("content_id", "platform", "title", "status",
                            "category", "scheduled_for", "post_url")}
                  for item in items])


@register(
    "social_advance",
    "Advance one content item through the pipeline: SCRIPT, CAPTION, "
    "HASHTAGS, POLICY CHECK, then stop at READY_FOR_REVIEW for owner approval. "
    "This never publishes.",
    {"type": "object", "properties": {
        "content_id": {"type": "string"},
    }, "required": ["content_id"]},
)
def social_advance(content_id: str) -> str:
    results = social_pipeline.ContentPipeline().advance(content_id.strip())
    if not results:
        return f"Nothing to advance for {content_id!r}."
    lines = [f"{r.stage}: {'ok' if r.ok else 'STOPPED'} -- {r.detail}"
             for r in results]
    return "\n".join(lines)


# --- approval and publishing --------------------------------------------
@register(
    "social_approval_card",
    "Show the owner approval screen for a post: platform, caption, hashtags, "
    "scheduled time, media, policy warnings and why ZENO thinks it should be "
    "posted.",
    {"type": "object", "properties": {
        "content_id": {"type": "string"},
    }, "required": ["content_id"]},
    light=True,
)
def social_approval_card(content_id: str) -> str:
    return _json(social_pipeline.ContentPipeline().approval_card(content_id.strip()))


@register(
    "social_approve",
    "Record the OWNER's approval or rejection of a post. Approval alone does "
    "not publish; it moves the item to APPROVED so it can be scheduled.",
    {"type": "object", "properties": {
        "content_id": {"type": "string"},
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "reason": {"type": "string", "description": "required when rejecting"},
    }, "required": ["content_id", "decision"]},
    requires_confirmation=True,
)
def social_approve(content_id: str, decision: str, reason: str = "") -> str:
    worker = social_pipeline.ContentPipeline()
    if decision.strip().casefold() == "reject":
        result = worker.reject(content_id.strip(), reason)
    else:
        result = worker.approve(content_id.strip())
    return f"{result.stage}: {'ok' if result.ok else 'refused'} -- {result.detail}"


@register(
    "social_schedule",
    "Schedule an APPROVED post for a future time. Respects quiet hours and "
    "the configured posts-per-week limit.",
    {"type": "object", "properties": {
        "content_id": {"type": "string"},
        "minutes_from_now": {"type": "integer"},
    }, "required": ["content_id", "minutes_from_now"]},
)
def social_schedule(content_id: str, minutes_from_now: int) -> str:
    when = time.time() + max(0, int(minutes_from_now)) * 60
    result = social_pipeline.ContentPipeline().schedule(content_id.strip(), when)
    return f"{result.stage}: {'ok' if result.ok else 'refused'} -- {result.detail}"


@register(
    "social_publish",
    "Publish an approved post to the real platform. Refuses while "
    "SOCIAL_DRY_RUN is on, while the kill switch is engaged, or without owner "
    "approval. Reports PUBLISHED only after asking the platform for the post "
    "back by id.",
    {"type": "object", "properties": {
        "content_id": {"type": "string"},
        "owner_approved": {"type": "boolean",
                           "description": "the owner explicitly approved this publication"},
    }, "required": ["content_id"]},
    requires_confirmation=True,
)
def social_publish(content_id: str, owner_approved: bool = False) -> str:
    result = social_pipeline.ContentPipeline().publish(
        content_id.strip(), approved_by_owner=bool(owner_approved))
    lines = [f"{result.stage}: {'ok' if result.ok else 'FAILED'} -- {result.detail}"]
    if result.status:
        lines.append(f"status is now {result.status}")
    if result.blocking:
        lines.append("blocked by: " + "; ".join(result.blocking))
    return "\n".join(lines)


# --- leads and comments -------------------------------------------------
@register(
    "social_leads",
    "Potential client leads detected in ZENO's social comments and messages, "
    "with an evidence-based risk assessment. ZENO cannot know intent; it "
    "reports LOW/MEDIUM/HIGH risk with reasons.",
    {"type": "object", "properties": {
        "status": {"type": "string",
                   "description": "NEW, QUALIFYING, OWNER_REVIEW, NEGOTIATING, CONVERTED, DECLINED, SCAM"},
        "lead_id": {"type": "string"},
    }},
    light=True,
)
def social_leads(status: str = "", lead_id: str = "") -> str:
    store = social_store.get_store()
    if lead_id:
        matches = [row for row in store.leads(limit=200)
                   if row.get("lead_id") == lead_id.strip()]
        return _json(matches[0]) if matches else f"No lead {lead_id!r}."
    rows = store.leads(status=(status.strip().upper() or None), limit=40)
    if not rows:
        return "No leads recorded." if not status else f"No leads with status {status}."
    return _json(rows)


@register(
    "social_comments",
    "Comments on ZENO's posts, classified (QUESTION, COMPLIMENT, CRITICISM, "
    "CLIENT_LEAD, SPAM, SCAM, ABUSE...) with drafted replies awaiting owner "
    "approval. ZENO never sends a reply automatically from here.",
    {"type": "object", "properties": {
        "reply_state": {"type": "string",
                        "description": "OWNER_REVIEW, DRAFTED, SENT, NONE"},
    }},
    light=True,
)
def social_comments(reply_state: str = "") -> str:
    rows = social_store.get_store().comments(
        reply_state=(reply_state.strip().upper() or None), limit=40)
    if not rows:
        return "No comments recorded."
    return _json(rows)


@register(
    "social_classify",
    "Classify one incoming social message and assess client-lead risk without "
    "storing it. Use to triage a comment or DM the owner pasted in.",
    {"type": "object", "properties": {
        "text": {"type": "string"},
    }, "required": ["text"]},
    light=True,
)
def social_classify(text: str) -> str:
    result = social_leads.classify(text)
    risk = social_leads.analyse_risk(text)
    return _json({
        "category": result.category,
        "confidence": result.confidence,
        "injection_flagged": bool(result.injection and result.injection.flagged),
        "risk": risk.risk,
        "reasons": risk.reasons,
        "request": social_leads.extract_request(text),
    })


# --- owner control ------------------------------------------------------
@register(
    "social_control",
    "The owner control panel: view or change social settings (mode, dry run, "
    "platform enable, posting frequency, comment mode, quiet hours), and "
    "engage or release the kill switch.",
    {"type": "object", "properties": {
        "action": {"type": "string",
                   "enum": ["show", "set", "kill", "release"]},
        "key": {"type": "string", "description": "setting name when action=set"},
        "value": {"type": "string", "description": "new value when action=set"},
    }},
    requires_confirmation=True,
)
def social_control(action: str = "show", key: str = "", value: str = "") -> str:
    verb = (action or "show").strip().casefold()
    if verb == "kill":
        return control.engage_kill_switch()
    if verb == "release":
        return control.release_kill_switch()
    if verb == "set":
        if not key:
            return "Which setting? Call with action=show to see the names."
        ok, detail = control.update_setting(key.strip(), value)
        return detail if ok else f"Not changed: {detail}"
    return _json(control.panel())


@register(
    "social_identity",
    "ZENO's own social identity: username, display name, bio, profile image, "
    "website and content themes. ZENO presents itself as an AI assistant, "
    "never as a human.",
    {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["show", "check"]},
    }},
    light=True,
)
def social_identity_tool(action: str = "show") -> str:
    manager = social_identity.get_identity_manager()
    if action.strip().casefold() == "check":
        return _json([c.as_dict() if hasattr(c, "as_dict") else c
                      for c in [manager.check()]])
    return _json(manager.current().as_dict())


@register(
    "social_setup",
    "Assisted setup for a ZENO Instagram or TikTok account. Opens the official "
    "signup or settings page and returns the exact approved values to enter. "
    "ZENO will NOT type passwords, answer CAPTCHAs, enter 2FA codes or submit "
    "the account form -- those stay with the owner.",
    {"type": "object", "properties": {
        "platform": {"type": "string", "description": "instagram or tiktok"},
        "open_browser": {"type": "boolean",
                         "description": "open the official page in the browser"},
    }, "required": ["platform"]},
    requires_confirmation=True,
)
def social_setup(platform: str, open_browser: bool = False) -> str:
    target = _platform(platform)
    if target is None:
        return f"Unknown platform {platform!r}. Use instagram or tiktok."

    manager = social_identity.get_identity_manager()
    ident = manager.current()
    adapter = all_adapters().get(target)
    state = adapter.auth_state() if adapter else None

    urls = {
        social_store.INSTAGRAM: "https://www.instagram.com/accounts/emailsignup/",
        social_store.TIKTOK: "https://www.tiktok.com/signup",
    }
    opened = ""
    if open_browser:
        try:
            from reyes_agent import browser_controller
            browser_controller.open_url(urls[target])
            opened = f"Opened {urls[target]} in the browser.\n"
        except Exception as exc:  # noqa: BLE001
            opened = f"Could not open the browser ({type(exc).__name__}). "\
                     f"Go to {urls[target]} yourself.\n"

    lines = [
        opened,
        f"OWNER ACTION REQUIRED -- {target} account setup",
        "",
        "ZENO cannot complete this itself. Creating an account means entering a",
        "password and clearing CAPTCHA, email and phone verification. ZENO does",
        "not type credentials and does not bypass those gates, by design.",
        "",
        "Enter these approved values:",
        f"  username:      {ident.username}",
        f"  display name:  {ident.display_name}",
        f"  bio:           {ident.bio}",
        f"  website:       {ident.website or '(none)'}",
        f"  contact email: {ident.contact_email or '(none)'}",
        f"  profile image: {ident.profile_image or '(not set)'}",
        "",
        "Then, for the API to work afterwards, ZENO needs:",
    ]
    if target == social_store.INSTAGRAM:
        lines += [
            "  1. Switch the account to Professional (Creator or Business).",
            "  2. Link it to a Facebook Page.",
            "  3. Create a Meta app with instagram_content_publish and",
            "     instagram_manage_insights.",
            "  4. Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID.",
            "  See ZENO_INSTAGRAM_SETUP.md.",
        ]
    else:
        lines += [
            "  1. Register at developers.tiktok.com and create an app.",
            "  2. Request Content Posting API access (this needs review).",
            "  3. Complete OAuth to get a user access token.",
            "  4. Set TIKTOK_ACCESS_TOKEN (and TIKTOK_CLIENT_KEY/SECRET).",
            "  See ZENO_TIKTOK_SETUP.md.",
        ]
    if state is not None:
        lines += ["", f"Current API state: {state.state} -- {state.detail}"]
    return "\n".join(lines)
