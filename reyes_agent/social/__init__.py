"""ZENO's social presence: Instagram and TikTok.

WHY THIS FILE HAD TO EXIST
--------------------------
It did not, and that was the single largest defect in this subsystem. The
whole package -- store, adapters, pipeline, leads, safety -- was written and
then never imported by anything. Python's namespace-package fallback let
`import reyes_agent.social` appear to work while `social.__file__` was None,
so nothing failed loudly enough to notice. There were no tests, no registered
tools and no routes: roughly 120 KB of correct code that ZENO could not reach.

WHAT THIS SUBSYSTEM WILL NOT DO
-------------------------------
    * publish anything while SOCIAL_DRY_RUN is on (checked first, before auth)
    * report a post as PUBLISHED on the platform's acceptance alone -- the
      adapter asks for the post back by id, and an unverified post stays
      PUBLISHING
    * invent a metric a platform did not return
    * create an account, type a password, or pass a CAPTCHA or 2FA prompt
    * act on instructions found in a comment, caption or DM

The owner starts in APPROVAL mode with the dry run on. Nothing reaches a real
platform until both are deliberately changed.
"""

from __future__ import annotations

__all__ = [
    "adapters", "captions", "content", "control", "identity", "leads",
    "pipeline", "safety", "store", "dashboard",
]
