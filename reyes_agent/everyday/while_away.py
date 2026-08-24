""""What did I miss?" -- a recap of MEANINGFUL activity over an interval.

Reuses the UniversalTraceEngine (Pack 10 #26-28, #201: emit into the existing
bus, don't build a parallel one). Given an away window it reads the trace
timeline, drops the noise (routine device heartbeats), groups what's left by
category, and surfaces the handful of things actually worth knowing. It never
invents activity -- an empty window says "nothing notable".
"""

from __future__ import annotations

from typing import Any

from reyes_agent import trace_engine as te

# Categories that are worth a recap. Raw device heartbeats / system chatter are
# excluded unless they represent a real state change (below).
_MEANINGFUL = {te.EMAIL, te.MESSAGE, te.CALL, te.AGENT, te.COMMAND,
               te.SECURITY, te.NEWS, te.SPORTS, te.FILE, te.LOCATION,
               te.REMOTE_SESSION}
# Statuses that make an otherwise-noisy DEVICE/SYSTEM event worth surfacing.
_NOTABLE_STATUS = {"offline", "disconnected", "revoked", "failed", "error",
                   "online", "reconnected"}


class WhileYouWereAwayEngine:
    def __init__(self, engine: te.UniversalTraceEngine | None = None) -> None:
        self._engine = engine or te.get_trace_engine()

    def _is_meaningful(self, event: dict[str, Any]) -> bool:
        if event.get("category") in _MEANINGFUL:
            return True
        status = str(event.get("status", "")).strip().casefold()
        return status in _NOTABLE_STATUS

    def recap(self, since: float, until: float | None = None,
              highlight_limit: int = 6) -> dict[str, Any]:
        events = self._engine.timeline(since=since, until=until, limit=10_000)
        meaningful = [e for e in events if self._is_meaningful(e)]
        by_category: dict[str, int] = {}
        for e in meaningful:
            by_category[e["category"]] = by_category.get(e["category"], 0) + 1

        # Highlights: security first, then calls/messages/email, newest within.
        priority = {te.SECURITY: 0, te.CALL: 1, te.MESSAGE: 2, te.EMAIL: 3,
                    te.AGENT: 4, te.COMMAND: 5}
        highlights = sorted(
            meaningful,
            key=lambda e: (priority.get(e["category"], 9), -e["timestamp"]))[:max(1, highlight_limit)]

        return {
            "interval": {"since": since, "until": until},
            "total_events": len(events),
            "meaningful": len(meaningful),
            "by_category": by_category,
            "highlights": [{"category": e["category"], "event_type": e["event_type"],
                            "source": e["source"], "status": e["status"],
                            "timestamp": e["timestamp"]} for e in highlights],
            "note": "Nothing notable happened while you were away."
                    if not meaningful else "",
        }

    def summary_line(self, since: float, until: float | None = None) -> str:
        r = self.recap(since, until)
        if not r["meaningful"]:
            return r["note"]
        parts = [f"{n} {cat.replace('_TRACE', '').lower()}"
                 for cat, n in sorted(r["by_category"].items(), key=lambda x: -x[1])]
        return "While you were away: " + ", ".join(parts) + "."
