"""Who ZENO is speaking to.

A guest can hold a conversation; only the owner can change what the
conversation is. Identity comes from an explicit introduction and never
from a face, and guests are temporary unless the owner asks otherwise.
"""

from __future__ import annotations

from reyes_agent.conversation import targets
from reyes_agent.conversation.targets import (GROUP, GROUP_MODE, GUEST_MODE, OWNER,
                                              OWNER_MODE, PRESENTATION_MODE, Target)

__all__ = ["targets", "Target", "OWNER", "GROUP", "OWNER_MODE", "GUEST_MODE",
           "PRESENTATION_MODE", "GROUP_MODE",
           "speak_to", "introduce", "redirect", "may_answer", "current", "status"]

speak_to = targets.speak_to
introduce = targets.introduce
redirect = targets.redirect
may_answer = targets.may_answer
current = targets.current
status = targets.status
