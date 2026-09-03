"""Presence-aware, deterministic delivery for proactive notices.

This module decides *when* a persisted notice may surface.  It deliberately
does not own another queue, event loop, voice session, or notification system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from reyes_agent.proactive_models import DeliveryState, Importance, ProactiveNotice
from reyes_agent.proactive_store import ProactiveStore


@dataclass(frozen=True)
class PresenceSnapshot:
    """Minimal local interaction signals; unknown signals default to safe silence."""

    quiet_hours: bool = False
    focus_mode: bool = False
    gaming_active: bool = False
    voice_active: bool = False
    locked: bool = False
    idle_seconds: float = 0.0


@dataclass(frozen=True)
class DeliveryDecision:
    action: str
    reason: str
    notify: bool
    voice_now: bool


Notifier = Callable[..., dict[str, Any]]
PresenceProvider = Callable[[], PresenceSnapshot]


def _default_presence() -> PresenceSnapshot:
    """Use safe local signals if available; failures defer instead of interrupting."""
    quiet_hours = False
    idle_seconds = 0.0
    try:
        from reyes_agent import heartbeat

        quiet_hours = heartbeat._in_quiet_hours()
    except Exception:  # noqa: BLE001 -- optional local signal
        pass
    try:
        from reyes_agent import activity_monitor

        idle_seconds = float(activity_monitor._idle_seconds())
    except Exception:  # noqa: BLE001 -- platform API is optional
        pass
    return PresenceSnapshot(quiet_hours=quiet_hours, idle_seconds=max(0.0, idle_seconds))


def _default_notifier(**payload: Any) -> dict[str, Any]:
    from reyes_agent.notifications import notify

    return notify(**payload)


class ProactiveDeliveryService:
    """Deliver persisted notices with quiet-by-default interruption rules."""

    def __init__(
        self,
        store: ProactiveStore,
        *,
        notifier: Notifier | None = None,
        presence: PresenceProvider | None = None,
    ) -> None:
        self.store = store
        self._notifier = notifier or _default_notifier
        self._presence = presence or _default_presence
        self.last_decisions: dict[str, DeliveryDecision] = {}

    @staticmethod
    def decide(notice: ProactiveNotice, presence: PresenceSnapshot) -> DeliveryDecision:
        """Classify delivery without calling a model or inspecting private content."""
        if notice.importance in {Importance.IGNORE, Importance.LOG}:
            return DeliveryDecision("hold", "non-interrupting importance", False, False)
        hold_reason = ""
        if presence.locked:
            hold_reason = "screen locked"
        elif presence.focus_mode:
            hold_reason = "focus mode"
        elif presence.gaming_active:
            hold_reason = "gaming active"
        elif presence.quiet_hours:
            hold_reason = "quiet hours"
        if hold_reason and notice.importance is not Importance.URGENT:
            return DeliveryDecision("hold", hold_reason, False, False)
        notify = notice.importance in {Importance.NOTIFY, Importance.URGENT}
        # Speech is a separate, opt-in renderer.  A current voice turn always
        # wins; urgent visual delivery never barges into the user speaking.
        voice_now = notice.importance is Importance.URGENT and not presence.voice_active
        return DeliveryDecision("surface", "urgent override" if hold_reason else "appropriate now", notify, voice_now)

    def surface_pending(self, *, limit: int = 50) -> list[ProactiveNotice]:
        """Evaluate fresh notices once; held updates remain available for catch-up."""
        presence = self._presence()
        surfaced: list[ProactiveNotice] = []
        for notice in self.store.list_notices(state=DeliveryState.NEW, limit=limit):
            decision = self.decide(notice, presence)
            self.last_decisions[notice.id] = decision
            if decision.action == "hold":
                self.store.transition_notice(notice.id, DeliveryState.HELD)
                continue
            delivered = self.store.transition_notice(notice.id, DeliveryState.SURFACED)
            surfaced.append(delivered)
            if decision.notify:
                try:
                    self._notifier(
                        title=delivered.title,
                        body=delivered.summary,
                        source="proactive",
                        priority="urgent" if delivered.importance is Importance.URGENT else "high",
                    )
                except Exception:  # noqa: BLE001 -- durable inbox is still available
                    pass
        return surfaced

    def catch_up(self, *, limit: int = 5) -> dict[str, Any]:
        """Return a bounded visual catch-up, never a burst of old interruptions."""
        held = self.store.list_notices(state=DeliveryState.HELD, limit=max(1, min(limit, 20)))
        for notice in held:
            self.store.transition_notice(notice.id, DeliveryState.SURFACED)
        count = len(held)
        return {
            "count": count,
            "summary": f"{count} update{'s' if count != 1 else ''} while you were focused." if count else "No held updates.",
            "items": [self.store.public_notice(item) for item in held],
        }
