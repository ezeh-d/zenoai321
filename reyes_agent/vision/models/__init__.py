"""Choosing a vision backend by cost, with accessibility first.

`router.route(question)` answers which tier should handle a question.
Hardware is measured (real RAM, real nvidia-smi) rather than assumed, so
the reported profile is what this machine can actually run.
"""

from __future__ import annotations

from reyes_agent.vision.models import router
from reyes_agent.vision.models.router import (ACCESSIBILITY, BALANCED, CLOUD, LIGHT,
                                              STRONG, TIERS, Route, hardware, route)

__all__ = ["router", "Route", "route", "hardware", "status", "TIERS",
           "ACCESSIBILITY", "LIGHT", "BALANCED", "STRONG", "CLOUD"]

status = router.status
