"""Find sensitive data on the way out, and remove what the destination
must not receive -- without breaking the task that needed it.

Credentials are always removed. Everything else depends on where the text
is going and what the owner actually asked for.
"""

from __future__ import annotations

from reyes_agent.security.privacy import detector      # no intra-package deps
from reyes_agent.security.privacy import redactor      # needs detector

__all__ = ["detector", "redactor", "detect", "redact",
           "safe_for_log", "safe_for_model", "status"]

detect = detector.detect
redact = redactor.redact
safe_for_log = redactor.safe_for_log
safe_for_model = redactor.safe_for_model
status = redactor.status
