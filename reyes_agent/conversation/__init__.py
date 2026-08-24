"""Human conversation & social intelligence (Pack 6).

Pure-logic, dependency-light engines that give ZENO natural conversational
behaviour WITHOUT the frontier realtime stack (LiveKit/pyannote/WhisperX stay
deferred behind the gated pipeline). Every engine here obeys the pack's safety
rules: no mind-reading, no guessing real-world identity from voice/appearance,
explicit facts only, and honest uncertainty.

Components:
    identity.SpeakerIdentityManager     -- session speaker labels & explicit names
    social.AddresseeResolver            -- who is being addressed
    social.SocialRegisterEngine         -- tone from explicit relationship/setting
    social.StayQuietPolicy              -- speak vs. stay silent
    explanation.ExplanationAdapter      -- how to explain, for the audience
    consent.ConsentStateManager         -- privacy/consent flags
    planner.ConversationResponsePlanner -- composes all of the above into a plan
"""

from __future__ import annotations

# Preserve the original guest/presentation conversation contract while the
# newer Pack 6 engines live beside it.  These exports were accidentally removed
# when the package was expanded, breaking every existing `reyes_agent.conversation`
# caller even though `targets.py` remained intact.
from reyes_agent.conversation import targets
from reyes_agent.conversation.targets import (GROUP, GROUP_MODE, GUEST_MODE, OWNER,
                                              OWNER_MODE, PRESENTATION_MODE, Target)

__all__ = ["targets", "Target", "OWNER", "GROUP", "OWNER_MODE", "GUEST_MODE",
           "PRESENTATION_MODE", "GROUP_MODE", "speak_to", "introduce", "redirect",
           "may_answer", "current", "status"]

speak_to = targets.speak_to
introduce = targets.introduce
redirect = targets.redirect
may_answer = targets.may_answer
current = targets.current
status = targets.status
