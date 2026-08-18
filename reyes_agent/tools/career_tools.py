"""Career-profile tools for TITAN and the main ZENO router.

These tools keep facts and policy separate from browser execution.  Browser
actions still pass through the existing permission/runtime boundary; this
module never handles passwords, MFA codes, CAPTCHA, or final job submissions.
"""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.career_profile import (
    AUTHENTICATION_REQUIRED,
    CareerProfileError,
    get_career_profile,
)
from reyes_agent.tools import register


PLATFORMS = (
    "indeed", "linkedin", "upwork", "fiverr", "freelancer",
    "remote_job_board", "company_career_portal", "other",
)
OPERATIONS = ("create", "complete", "maintain", "optimize", "audit")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _error(exc: CareerProfileError) -> str:
    return f"Career profile not changed: {exc}"


_PROFILE_PROPERTIES: dict[str, dict[str, Any]] = {
    "full_name": {"type": "string"},
    "professional_title": {"type": "string"},
    "professional_summary": {"type": "string"},
    "skills": {"type": "array", "items": {}},
    "employment_history": {"type": "array", "items": {}},
    "education": {"type": "array", "items": {}},
    "certifications": {"type": "array", "items": {}},
    "projects": {"type": "array", "items": {}},
    "portfolio": {"type": "array", "items": {}},
    "languages": {"type": "array", "items": {}},
    "availability": {"type": "string"},
    "preferred_job_types": {"type": "array", "items": {}},
    "preferred_industries": {"type": "array", "items": {}},
    "remote_on_site_preference": {"type": "string"},
    "salary_rate_expectations": {"type": "string"},
    "notice_period": {"type": "string"},
    "work_authorization": {"type": "string"},
    "cv_versions": {"type": "array", "items": {}},
    "cover_letter_templates": {"type": "array", "items": {}},
    "portfolio_links": {"type": "array", "items": {}},
    "professional_social_links": {"type": "array", "items": {}},
    "location": {"type": "string"},
    "contact_information": {
        "type": "object",
        "properties": {
            "email": {"type": "string"}, "phone": {"type": "string"},
            "city": {"type": "string"}, "region": {"type": "string"},
            "country": {"type": "string"}, "website": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "registered_gmail": {"type": "string"},
}


@register(
    name="career_profile_status",
    description=(
        "Inspect ZENO's authoritative career-profile completeness and list the "
        "facts Divine still needs to provide. Returns masked account details and "
        "never guesses missing employment, education, project, or identity data."
    ),
    input_schema={"type": "object", "properties": {}},
)
def career_profile_status() -> str:
    try:
        return _json(get_career_profile().status())
    except CareerProfileError as exc:
        return _error(exc)


@register(
    name="career_profile_read",
    description=(
        "Read owner-confirmed career facts for a CV/profile draft. Contact and "
        "registered Gmail values are masked; ask Divine to handle sensitive form "
        "fields directly. Never turn missing fields into plausible-sounding facts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["professional", "preferences", "assets", "contact", "all"],
            }
        },
    },
)
def career_profile_read(section: str = "all") -> str:
    try:
        return _json(get_career_profile().read(section))
    except CareerProfileError as exc:
        return _error(exc)


@register(
    name="career_profile_update",
    description=(
        "Save career facts Divine explicitly supplied and confirmed. Never call "
        "this with inferred, invented, or merely drafted qualifications, employers, "
        "dates, salaries, certifications, references, or projects. Passwords, "
        "tokens, MFA codes, cookies, passkeys and private keys are rejected."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "properties": _PROFILE_PROPERTIES,
                "additionalProperties": False,
            },
            "owner_confirmed": {
                "type": "boolean",
                "description": "True only when Divine explicitly confirmed these exact facts.",
            },
        },
        "required": ["fields", "owner_confirmed"],
    },
    requires_confirmation=True,
)
def career_profile_update(fields: dict[str, Any], owner_confirmed: bool) -> str:
    try:
        return _json(get_career_profile().update(fields, owner_confirmed=owner_confirmed))
    except CareerProfileError as exc:
        return _error(exc)


@register(
    name="career_profile_fill_field",
    description=(
        "Fill one browser form field directly from an owner-confirmed career fact "
        "without exposing its value to the model or audit input. Use selector or "
        "label, and item_index/subfield for structured entries. This cannot access "
        "passwords or security codes and never clicks Save, Submit, Apply, or Publish."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": list(_PROFILE_PROPERTIES)},
            "selector": {"type": "string"},
            "label": {"type": "string"},
            "item_index": {"type": "integer", "minimum": 0, "maximum": 199},
            "subfield": {"type": "string"},
        },
        "required": ["field"],
    },
)
def career_profile_fill_field(
    field: str,
    selector: str = "",
    label: str = "",
    item_index: int = -1,
    subfield: str = "",
) -> str:
    if not str(selector or "").strip() and not str(label or "").strip():
        return "Give either selector or label for the browser field."
    try:
        profile, provenance = get_career_profile().raw_profile()
    except CareerProfileError as exc:
        return _error(exc)
    chosen = str(field or "").strip()
    if chosen not in _PROFILE_PROPERTIES:
        return "That is not a career-profile field."
    if chosen not in provenance or chosen not in profile:
        return f"{chosen} is missing; ask Divine instead of inventing it."

    value: Any = profile[chosen]
    if isinstance(value, list):
        if item_index < 0 or item_index >= len(value):
            return f"Give a valid item_index for {chosen} (0 to {max(0, len(value) - 1)})."
        value = value[item_index]
    if isinstance(value, dict):
        key = str(subfield or "").strip()
        if not key:
            return f"Give subfield for structured field {chosen}."
        if key not in value:
            return f"{chosen}.{key} is missing; ask Divine instead of inventing it."
        value = value[key]
    if isinstance(value, (list, dict)) or value is None:
        return "That entry is structured; select one scalar item/subfield to fill."
    text_value = str(value)
    if not text_value:
        return f"{chosen} is explicitly empty; nothing was filled."

    # Deferred import avoids a second browser owner and keeps Chromium lazy.
    # The browser tool returns only target/postcondition evidence, not value.
    from reyes_agent.tools.browser import browser_fill

    return browser_fill(text_value, selector=selector, label=label)


@register(
    name="career_platform_plan",
    description=(
        "Create a safe, platform-aware plan for creating, completing, maintaining, "
        "optimizing, or auditing a legitimate job/freelance profile. It marks live "
        "terms review, owner-authentication boundaries, missing facts, and final-save "
        "confirmation; it does not claim an external profile was changed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": list(PLATFORMS)},
            "operation": {"type": "string", "enum": list(OPERATIONS)},
            "platform_name": {
                "type": "string",
                "description": "Required only when platform is other.",
            },
            "target_role": {"type": "string"},
        },
        "required": ["platform", "operation"],
    },
)
def career_platform_plan(
    platform: str,
    operation: str,
    platform_name: str = "",
    target_role: str = "",
) -> str:
    chosen = str(platform or "").strip().lower()
    action = str(operation or "").strip().lower()
    if chosen not in PLATFORMS:
        return f"Unknown platform. Use one of: {', '.join(PLATFORMS)}."
    if action not in OPERATIONS:
        return f"Unknown operation. Use one of: {', '.join(OPERATIONS)}."
    if chosen == "other" and not str(platform_name or "").strip():
        return "Give platform_name when platform is other."

    status = get_career_profile().status()
    label = str(platform_name).strip() if chosen == "other" else chosen.replace("_", " ").title()
    google_available = status["registered_gmail"] != "[not configured]"
    return _json({
        "platform": label,
        "operation": action,
        "target_role": str(target_role or "").strip(),
        "external_state": "NOT_CHANGED",
        "terms_status": "LIVE_TERMS_CHECK_REQUIRED",
        "profile_source": "ZenoCareerProfile owner-confirmed fields only",
        "missing_fields_to_ask_divine": status["missing_fields"],
        "sign_in": {
            "registered_gmail": status["registered_gmail"],
            "prefer_continue_with_google": google_available,
            "password_handling": "Never request, reveal, store, fill, or log a Gmail password.",
        },
        "authentication_boundary": {
            "display_exactly": AUTHENTICATION_REQUIRED,
            "triggers": [
                "password", "MFA", "one-time code", "passkey", "fingerprint",
                "security prompt", "CAPTCHA",
            ],
            "action": "Pause automation immediately and let Divine complete authentication.",
        },
        "allowed_sequence": [
            "Check the platform's current rules before browser automation.",
            "Read only owner-confirmed profile facts; ask for every missing fact.",
            "Open the legitimate platform and prefer Continue with Google when offered.",
            "Pause at any authentication or anti-bot challenge.",
            "Draft or fill only what current platform rules and Divine's request allow.",
            "Show the completed fields and evidence for review.",
            "Require Divine to approve the final external save/publish action.",
        ],
        "prohibited": [
            "inventing jobs, qualifications, degrees, references, companies, certifications, salaries, or projects",
            "mass applying, unsolicited spam, impersonation, or prohibited platform botting",
            "bypassing security, MFA, CAPTCHA, passkeys, fingerprint, or device checks",
            "claiming the account/profile changed without observed postcondition evidence",
        ],
        "job_application_boundary": "Applications and proposals remain owner-reviewed; no unattended submission.",
    })


__all__ = [
    "career_platform_plan", "career_profile_fill_field", "career_profile_read",
    "career_profile_status", "career_profile_update",
]
