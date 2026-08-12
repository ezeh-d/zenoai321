"""The vocabulary every messaging adapter shares.

The statuses are the important part of this file. "I pressed Enter" and "the
message is in the conversation" are different claims, and only the second one
is SENT. Everything here exists so an adapter cannot accidentally report the
first while meaning the second.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Platforms.
SLACK, WHATSAPP, TELEGRAM, DISCORD = "slack", "whatsapp", "telegram", "discord"
PLATFORMS = (SLACK, WHATSAPP, TELEGRAM, DISCORD)

# Destination kinds.
CHANNEL, GROUP, DM, CONTACT, THREAD = "CHANNEL", "GROUP", "DM", "CONTACT", "THREAD"

# Outcomes. SENT is the only one that means the message exists in the
# conversation; everything else says precisely how far it got.
SENT = "SENT"                        # verified present in the conversation
TYPED = "TYPED"                      # in the composer, deliberately not sent
SEND_UNVERIFIED = "SEND_UNVERIFIED"  # submitted, could not confirm arrival
SEND_FAILED = "SEND_FAILED"
AUTH_REQUIRED = "AUTH_REQUIRED"      # app open but logged out
PLATFORM_OFFLINE = "PLATFORM_OFFLINE"
APP_NOT_FOUND = "APP_NOT_FOUND"
DESTINATION_NOT_FOUND = "DESTINATION_NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"              # more than one plausible destination
CANCELLED = "CANCELLED"              # the owner said stop in time

# Statuses that must never be spoken as success.
NOT_SUCCESS = {SEND_UNVERIFIED, SEND_FAILED, AUTH_REQUIRED, PLATFORM_OFFLINE,
               APP_NOT_FOUND, DESTINATION_NOT_FOUND, AMBIGUOUS, CANCELLED}


@dataclass
class Destination:
    name: str = ""
    kind: str = ""              # CHANNEL | GROUP | DM | CONTACT | THREAD
    platform: str = ""
    resolved_label: str = ""    # what the app actually showed once opened

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "platform": self.platform,
                "resolved_label": self.resolved_label}


@dataclass
class SendRequest:
    platform: str = ""
    destination: str = ""
    message: str = ""
    destination_type: str = ""
    account: str = ""
    send: bool = True           # False means TYPE ONLY -- do not submit

    def as_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "destination": self.destination,
                "message": self.message, "destination_type": self.destination_type,
                "account": self.account, "send": self.send}


@dataclass
class SendResult:
    status: str = SEND_FAILED
    platform: str = ""
    destination: str = ""
    message: str = ""
    verified: bool = False
    detail: str = ""
    failing_step: str = ""
    candidates: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (SENT, TYPED)

    def say(self) -> str:
        """One sentence for the owner. Never claims more than was verified."""
        quoted = f"'{self.message}'" if self.message else "the message"
        if self.status == SENT:
            return f"Done. I sent {quoted} to {self.destination}."
        if self.status == TYPED:
            return (f"I typed {quoted} into the {self.destination} composer "
                    "and left it unsent.")
        if self.status == SEND_UNVERIFIED:
            return (f"I submitted {quoted} to {self.destination}, but I could "
                    f"not confirm it appeared. {self.detail}".strip())
        if self.status == AMBIGUOUS:
            return (f"I found more than one {self.destination}: "
                    f"{', '.join(self.candidates)}. Which one?")
        if self.status == AUTH_REQUIRED:
            return (f"{self.platform.title()} is open but signed out, so I did "
                    "not send anything.")
        if self.status == PLATFORM_OFFLINE:
            return (f"{self.platform.title()} says it is offline, so the "
                    "message would not have gone out. I did not send it.")
        if self.status == APP_NOT_FOUND:
            return (f"I could not find {self.platform.title()} on this "
                    f"computer. {self.detail}".strip())
        if self.status == DESTINATION_NOT_FOUND:
            return (f"I could not find {self.destination} on "
                    f"{self.platform.title()}. {self.detail}".strip())
        if self.status == CANCELLED:
            return "Stopped. Nothing was sent."
        return (f"I could not send {quoted} to {self.destination}. "
                f"Failed at: {self.failing_step or 'unknown step'}. "
                f"{self.detail}").strip()

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "platform": self.platform,
                "destination": self.destination, "message": self.message,
                "verified": self.verified, "detail": self.detail,
                "failing_step": self.failing_step,
                "candidates": self.candidates, "steps": self.steps,
                "spoken": self.say()}
