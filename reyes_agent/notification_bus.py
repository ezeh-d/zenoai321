"""A tiny in-process pub/sub so a background thread (notification_listener)
can push a live event to whatever browser tab(s) are connected, via SSE.

Deliberately separate from web.py/notification_listener.py rather than
living in either -- web.py imports notification_listener at startup, so
notification_listener importing back from web.py at module level would
be circular. This module has no dependency on either, so both can import
it directly, no deferred-import juggling needed.
"""

from __future__ import annotations

import queue
import threading

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_SUBSCRIBER_MAXSIZE = 100


def subscribe() -> queue.Queue:
    # A disconnected/stalled SSE client must not retain every future desktop
    # notification in RAM. The durable event bus remains the replay source.
    q: queue.Queue = queue.Queue(maxsize=_SUBSCRIBER_MAXSIZE)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(event: dict) -> None:
    # Forward into the durable Event Bus first so live UI pushes also land
    # in the replayable record (Timeline/Activity Stream read from there).
    # Deferred import: event_bus imports config, not this module, so no
    # cycle -- and a failure here must never stop the live push below.
    try:
        from reyes_agent import event_bus

        event_bus.publish(
            f"ui.{event.get('type', 'unknown')}",
            payload=event,
            source="notification_bus",
        )
    except Exception:  # noqa: BLE001
        pass

    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            # Live UI notification is best effort; blocking a background
            # listener or growing the process without bound is not.
            pass
