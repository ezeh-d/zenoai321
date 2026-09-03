from __future__ import annotations

from pathlib import Path

from reyes_agent.proactive_models import CheckResult, DeliveryState, Importance
from reyes_agent.proactive_store import ProactiveStore


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **payload):
        self.calls.append(payload)
        return {"delivered": True}


def notice(store: ProactiveStore, importance: Importance, subject: str = "agenda"):
    return store.upsert_notice(
        CheckResult.changed("calendar", subject, "changed", f"{subject} changed", importance_hint=importance),
        importance=importance,
    )


def test_quiet_hours_hold_normal_updates_without_losing_them(tmp_path: Path) -> None:
    from reyes_agent.proactive_delivery import PresenceSnapshot, ProactiveDeliveryService

    store = ProactiveStore(tmp_path / "notices.db", clock=lambda: 100.0)
    item = notice(store, Importance.NOTIFY)
    notifier = RecordingNotifier()
    service = ProactiveDeliveryService(
        store, notifier=notifier, presence=lambda: PresenceSnapshot(quiet_hours=True)
    )

    assert service.surface_pending() == []
    held = store.list_notices(state=DeliveryState.HELD)
    assert [entry.id for entry in held] == [item.id]
    assert notifier.calls == []


def test_urgent_update_surfaces_visually_but_never_interrupts_active_voice(tmp_path: Path) -> None:
    from reyes_agent.proactive_delivery import PresenceSnapshot, ProactiveDeliveryService

    store = ProactiveStore(tmp_path / "notices.db", clock=lambda: 100.0)
    item = notice(store, Importance.URGENT)
    notifier = RecordingNotifier()
    service = ProactiveDeliveryService(
        store, notifier=notifier,
        presence=lambda: PresenceSnapshot(quiet_hours=True, voice_active=True),
    )

    surfaced = service.surface_pending()
    assert [entry.id for entry in surfaced] == [item.id]
    assert store.list_notices(state=DeliveryState.SURFACED)[0].id == item.id
    assert notifier.calls == [{"title": item.title, "body": item.summary, "source": "proactive", "priority": "urgent"}]
    assert service.last_decisions[item.id].voice_now is False


def test_focus_held_updates_are_available_as_a_bounded_catch_up(tmp_path: Path) -> None:
    from reyes_agent.proactive_delivery import PresenceSnapshot, ProactiveDeliveryService

    store = ProactiveStore(tmp_path / "notices.db", clock=lambda: 100.0)
    notice(store, Importance.INBOX, "agenda")
    notice(store, Importance.NOTIFY, "mail")
    service = ProactiveDeliveryService(
        store, notifier=RecordingNotifier(), presence=lambda: PresenceSnapshot(focus_mode=True)
    )

    assert service.surface_pending() == []
    catch_up = service.catch_up(limit=3)
    assert catch_up["count"] == 2
    assert catch_up["summary"] == "2 updates while you were focused."
    assert {item["subject"] for item in catch_up["items"]} == {"agenda", "mail"}
