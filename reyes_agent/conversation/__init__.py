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
