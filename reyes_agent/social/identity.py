"""ZENO's social identity: one account, presented as what it actually is.

THE RULE THAT SHAPES EVERYTHING HERE
------------------------------------
ZENO is presented as an AI assistant. Not as a person, not as a team, not as
a company that does not exist. That is not only the brief's instruction --
Instagram and TikTok both require AI accounts to be identifiable, and a
profile that implies a human is a profile that can be removed.

So `bio()` always contains an AI marker, and `validate()` refuses a bio that
reads as a human being.

WHY THE BIOGRAPHY IS NOT HARD-CODED
-----------------------------------
The brief supplies a candidate description and says explicitly not to fix it
in place if a better one is written. So the default lives in one constant,
the owner can override it, and the override is stored rather than edited into
this file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.social import store as social_store

DEFAULT_DISPLAY_NAME = "ZENO"
DEFAULT_BIO = ("AI assistant being built to think, speak, automate and learn.\n"
               "Follow the build.")

# Content themes, matching the strategy categories.
DEFAULT_THEMES = ("BUILDING_ZENO", "ZENO_IN_ACTION", "AI_EDUCATION",
                  "CHALLENGES", "BEHIND_THE_SCENES", "BUSINESS_PRODUCTIVITY")

# Any one of these makes the account identifiable as an AI.
_AI_MARKERS = ("ai assistant", "ai project", "digital assistant", "ai agent",
               "artificial intelligence", "ai-built", "built with ai",
               "an ai ", "i'm an ai", "am an ai")

# Phrasing that would present ZENO as a human being.
_HUMAN_CLAIMS = (
    r"\b(?:i\s+am|i'm)\s+a\s+(?:developer|engineer|founder|guy|girl|man|woman|"
    r"student|person|human)\b",
    r"\b(?:my\s+(?:wife|husband|kids|children|family))\b",
    r"\b(?:born\s+in\s+\d{4}|years?\s+old)\b",
)
_COMPILED_HUMAN = tuple(re.compile(p, re.IGNORECASE) for p in _HUMAN_CLAIMS)


@dataclass
class SocialIdentity:
    username: str = ""
    display_name: str = DEFAULT_DISPLAY_NAME
    bio: str = DEFAULT_BIO
    website: str = ""
    contact_email: str = ""
    profile_image: str = ""
    brand_description: str = ""
    themes: tuple[str, ...] = DEFAULT_THEMES

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username, "display_name": self.display_name,
            "bio": self.bio, "website": self.website,
            "contact_email": self.contact_email,
            "profile_image": self.profile_image,
            "brand_description": self.brand_description,
            "themes": list(self.themes),
        }


@dataclass
class IdentityCheck:
    valid: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "problems": self.problems,
                "warnings": self.warnings}


class SocialIdentityManager:
    """Reads and writes the one ZENO identity."""

    _KEYS = ("username", "display_name", "bio", "website", "contact_email",
             "profile_image", "brand_description")

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()

    def current(self) -> SocialIdentity:
        def value(key: str, env: str, default: str = "") -> str:
            stored = self._store.setting(f"identity.{key}", "")
            return stored or os.environ.get(env, default)

        return SocialIdentity(
            username=value("username", "ZENO_SOCIAL_HANDLE"),
            display_name=value("display_name", "ZENO_SOCIAL_DISPLAY_NAME",
                               DEFAULT_DISPLAY_NAME),
            bio=self._store.setting("identity.bio", "") or DEFAULT_BIO,
            website=value("website", "ZENO_SOCIAL_WEBSITE"),
            contact_email=value("contact_email", "ZENO_SOCIAL_CONTACT_EMAIL"),
            profile_image=self._store.setting("identity.profile_image", ""),
            brand_description=self._store.setting("identity.brand_description", ""),
        )

    def update(self, **fields: str) -> tuple[bool, str]:
        unknown = [key for key in fields if key not in self._KEYS]
        if unknown:
            return False, f"unknown identity field(s): {', '.join(unknown)}"

        candidate = self.current()
        for key, value in fields.items():
            setattr(candidate, key, value)

        check = self.validate(candidate)
        if not check.valid:
            return False, "; ".join(check.problems)

        for key, value in fields.items():
            self._store.set_setting(f"identity.{key}", str(value))
        self._store.audit("SocialIdentityManager", "identity_updated",
                          target=", ".join(sorted(fields)), result="applied")
        return True, f"updated: {', '.join(sorted(fields))}"

    def validate(self, identity: SocialIdentity | None = None) -> IdentityCheck:
        target = identity or self.current()
        problems: list[str] = []
        warnings: list[str] = []

        bio = (target.bio or "").strip()
        if not bio:
            problems.append("bio is empty")
        elif not any(marker in bio.casefold() for marker in _AI_MARKERS):
            problems.append(
                "the bio does not identify ZENO as an AI. Both platforms expect "
                "an AI account to be identifiable, and presenting ZENO as a "
                "person is not allowed")

        for pattern in _COMPILED_HUMAN:
            if pattern.search(bio):
                problems.append(
                    f"the bio claims something only a human could claim "
                    f"({pattern.pattern.split(chr(92) + 'b')[1][:30]}...)")
                break

        # Instagram's bio limit is 150 characters; TikTok's is 80.
        if len(bio) > 150:
            problems.append(f"bio is {len(bio)} characters; Instagram allows 150")
        elif len(bio) > 80:
            warnings.append(
                f"bio is {len(bio)} characters -- fits Instagram (150) but will "
                f"be cut on TikTok (80)")

        username = (target.username or "").strip()
        if not username:
            warnings.append("no username chosen yet")
        elif not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            problems.append(
                "username may only contain letters, numbers, full stops and "
                "underscores, up to 30 characters")

        if not target.profile_image:
            warnings.append("no profile image set")
        if not target.contact_email:
            warnings.append("no contact email set")

        return IdentityCheck(valid=not problems, problems=problems, warnings=warnings)

    def summary(self) -> dict[str, Any]:
        identity = self.current()
        check = self.validate(identity)
        return {"identity": identity.as_dict(), "check": check.as_dict()}


_MANAGER: SocialIdentityManager | None = None


def get_identity_manager() -> SocialIdentityManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = SocialIdentityManager()
    return _MANAGER
