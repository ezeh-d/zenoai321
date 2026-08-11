"""External services ZENO knows how to connect -- and what each one costs you.

WHY A CATALOG AND NOT JUST "INSTALL COMPOSIO"
---------------------------------------------
Composio and its equivalents give standardised access to hundreds of SaaS
APIs, which is genuinely valuable: nobody should hand-write a Gmail REST
client in 2026. But "standardised access" is also standardised REACH. A
connector that can read every message in a mailbox is one OAuth consent away
from being a connector that can send as you, and the consent screen is the
only place anyone reads the scopes.

So the catalog exists to make the trade explicit BEFORE anything is
connected: what the service is for, which scopes it needs for each level of
use, and which capability it would unblock. `connections.py` then grants the
narrowest set that does the job.

READ IS NOT WRITE, AND WRITE IS NOT SEND
----------------------------------------
Every entry separates its scopes into tiers. Connecting a mailbox to
summarise it should not also authorise sending mail as the owner, and the
common failure is that it does -- because one broad scope was easier to ask
for. `minimum_for()` returns the smallest tier that satisfies an intent.

NOTHING HERE CONNECTS ANYTHING
------------------------------
This module is data plus the rules for reading it. Connecting requires an
OAuth flow the owner completes themselves; ZENO cannot and must not click
through a consent screen on someone's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Categories, as the brief lists them.
EMAIL = "email"
CALENDAR = "calendar"
CRM = "crm"
PROJECT = "project_management"
STORAGE = "cloud_storage"
DEVELOPER = "developer_tools"
COMMUNICATION = "communication"
DOCUMENTS = "documents"
MARKETING = "marketing"

CATEGORIES = (EMAIL, CALENDAR, CRM, PROJECT, STORAGE, DEVELOPER,
              COMMUNICATION, DOCUMENTS, MARKETING)

# Scope tiers, narrowest first. The order IS the privilege ladder.
READ = "read"
WRITE = "write"
SEND = "send"
ADMIN = "admin"

TIERS = (READ, WRITE, SEND, ADMIN)

# Tiers that change something outside ZENO and always need explicit consent.
CONSEQUENTIAL = frozenset({SEND, ADMIN})


@dataclass(frozen=True)
class Service:
    key: str
    name: str
    category: str
    description: str
    # tier -> the scopes that tier actually requires
    scopes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unlocks: tuple[str, ...] = ()          # capability names in the registry
    auth: str = "oauth"                    # oauth | api_key | app_password
    provider_hint: str = ""

    def tiers(self) -> list[str]:
        return [t for t in TIERS if t in self.scopes]

    def scopes_up_to(self, tier: str) -> list[str]:
        """Every scope needed to reach `tier`, cumulatively."""
        wanted = []
        for level in TIERS:
            if level in self.scopes:
                wanted.extend(self.scopes[level])
            if level == tier:
                break
        return sorted(set(wanted))

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "category": self.category,
                "description": self.description, "auth": self.auth,
                "tiers": self.tiers(), "unlocks": list(self.unlocks),
                "provider_hint": self.provider_hint}


_SERVICES: tuple[Service, ...] = (
    Service("gmail", "Gmail", EMAIL,
            "read, search, draft and (with consent) send mail",
            {READ: ("gmail.readonly",),
             WRITE: ("gmail.modify",),
             SEND: ("gmail.send",)},
            unlocks=("email_provider",), provider_hint="Google account"),
    Service("outlook", "Outlook / Microsoft 365", EMAIL,
            "read, search, draft and (with consent) send mail",
            {READ: ("Mail.Read",), WRITE: ("Mail.ReadWrite",), SEND: ("Mail.Send",)},
            unlocks=("email_provider",), provider_hint="Microsoft account"),
    Service("imap", "Any IMAP mailbox", EMAIL,
            "read and search mail from a standard mailbox",
            {READ: ("imap",), SEND: ("smtp",)},
            unlocks=("email_provider",), auth="app_password",
            provider_hint="host, username and an app password"),
    Service("google_calendar", "Google Calendar", CALENDAR,
            "read your schedule and (with consent) create events",
            {READ: ("calendar.readonly",), WRITE: ("calendar.events",)},
            unlocks=("calendar",), provider_hint="Google account"),
    Service("hubspot", "HubSpot", CRM,
            "read contacts and deals, and create records",
            {READ: ("crm.objects.contacts.read",),
             WRITE: ("crm.objects.contacts.write",)},
            provider_hint="HubSpot private app token", auth="api_key"),
    Service("notion", "Notion", PROJECT,
            "read and write pages and databases",
            {READ: ("read_content",), WRITE: ("update_content", "insert_content")},
            provider_hint="Notion integration token", auth="api_key"),
    Service("linear", "Linear", PROJECT,
            "read and create issues",
            {READ: ("read",), WRITE: ("write",)},
            provider_hint="Linear API key", auth="api_key"),
    Service("google_drive", "Google Drive", STORAGE,
            "read and write files",
            {READ: ("drive.readonly",), WRITE: ("drive.file",)},
            unlocks=("docling",), provider_hint="Google account"),
    Service("github", "GitHub", DEVELOPER,
            "read repositories, open pull requests",
            {READ: ("repo:status", "public_repo"), WRITE: ("repo",),
             ADMIN: ("admin:org",)},
            unlocks=("github",), auth="api_key",
            provider_hint="a fine-grained personal access token"),
    Service("slack", "Slack", COMMUNICATION,
            "read channels and (with consent) post messages",
            {READ: ("channels:history", "channels:read"),
             SEND: ("chat:write",)},
            provider_hint="Slack app token"),
    Service("google_docs", "Google Docs", DOCUMENTS,
            "read and edit documents",
            {READ: ("documents.readonly",), WRITE: ("documents",)},
            unlocks=("docling",), provider_hint="Google account"),
    Service("mailchimp", "Mailchimp", MARKETING,
            "read audiences and (with consent) send campaigns",
            {READ: ("audience:read",), SEND: ("campaigns:send",)},
            auth="api_key", provider_hint="Mailchimp API key"),
)

_BY_KEY = {service.key: service for service in _SERVICES}

# What an intent needs. Used to grant the narrowest sufficient tier.
_INTENT_TIER = (
    # SEND means it LEAVES. A bare "reply" does not belong here: "draft a
    # reply" is composing, and classifying it as SEND would hand out
    # send-as-the-owner access to write a draft -- exactly the wrong
    # direction to err under least privilege. Only an explicit dispatch verb
    # reaches this tier.
    (SEND, ("send", "post ", "publish", "email them", "message them",
            "campaign", "fire off", "deliver")),
    (WRITE, ("create", "update", "edit", "draft", "compose", "reply", "respond",
             "add", "schedule", "file", "label", "archive", "move",
             # Destructive verbs are WRITE-tier at the provider. Leaving them
             # out mapped "delete everything" to READ -- which fails safe, but
             # a scope decision should be right rather than accidentally
             # harmless. Whether the deletion is ALLOWED is a permission
             # question, decided elsewhere; this only sizes the OAuth grant.
             "delete", "remove", "trash", "empty")),
    (READ, ("read", "search", "find", "summarise", "summarize", "check",
            "look at", "review", "list", "analyse", "analyze")),
)


def all_services(category: str = "") -> list[Service]:
    services = list(_SERVICES)
    if category:
        services = [s for s in services if s.category == category]
    return sorted(services, key=lambda s: (s.category, s.name))


def get(key: str) -> Service | None:
    return _BY_KEY.get(str(key or "").strip().lower())


def for_capability(capability_name: str) -> list[Service]:
    """Which services would unblock this capability. The answer to
    'what would I have to connect?'"""
    return [s for s in _SERVICES if capability_name in s.unlocks]


def minimum_for(intent: str) -> str:
    """The narrowest tier that satisfies this intent.

    Defaults to READ, deliberately. An unrecognised intent should get the
    least privilege, not the most -- the failure mode of guessing high is
    handing out send access to summarise an inbox.
    """
    text = str(intent or "").lower()
    for tier, markers in _INTENT_TIER:
        if any(marker in text for marker in markers):
            return tier
    return READ


def describe(category: str = "") -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for service in all_services(category):
        grouped.setdefault(service.category, []).append(service.as_dict())
    return {"categories": grouped, "total": len(all_services()),
            "tiers": list(TIERS), "consequential": sorted(CONSEQUENTIAL)}


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "services": len(_SERVICES),
        "categories": {c: len(all_services(c)) for c in CATEGORIES if all_services(c)},
        "note": ("A catalogue of what could be connected and what each would cost "
                 "in access. Nothing here connects anything -- OAuth consent is "
                 "yours to give, and ZENO must never click through it for you."),
        "least_privilege": ("an unrecognised intent gets READ, because guessing high "
                            "hands out send access to summarise an inbox"),
    }
