"""Spatial Memory tools -- ZENO's structured interface to eMEM.

Structured tools, not sentence matching: the model fills fields (entity,
location, zone, source, confidence, time window) and these call the
SpatialMemoryService, which adapts to eMEM. Every tool degrades to a clear
error string if spatial memory is unavailable -- ZENO keeps running.

Covers the requested capabilities: store a spatial event, remember/update an
object's location, query last-known location, by location, by time, by meaning,
recent events, and the current known state of a room.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


def _svc():
    from reyes_agent.spatial_memory import get_spatial_memory

    return get_spatial_memory()


@register(
    name="spatial_remember",
    description="Save WHERE an object is into ZENO's PERSISTENT spatial memory -- "
                "e.g. 'my laptop is on the office desk'. ALWAYS call this to "
                "actually store an object's location (it survives restarts and can "
                "be queried later); simply replying 'noted' does NOT persist it. "
                "Records object, location, zone, source and confidence. Use "
                "spatial_move when an object CHANGES location.",
    input_schema={"type": "object", "properties": {
        "entity": {"type": "string", "description": "The object/thing, e.g. 'laptop', 'bag'."},
        "location": {"type": "string", "description": "Where it is, e.g. 'office desk', 'kitchen counter'."},
        "zone": {"type": "string", "description": "Room/zone, e.g. 'office', 'hallway'. Optional."},
        "source": {"type": "string", "description": "Who/what reported it: 'user', 'camera', 'sensor'. Default 'user'."},
        "confidence": {"type": "number", "description": "0..1 confidence. Default 1.0."},
        "description": {"type": "string", "description": "Optional free-text description of the event."},
    }, "required": ["entity", "location"]},
)
def spatial_remember(entity: str, location: str, zone: str = "", source: str = "user",
                     confidence: float = 1.0, description: str = "") -> str:
    return json.dumps(_svc().store_event(
        entity=entity, location=location, zone=zone, source=source,
        confidence=confidence, description=description), default=str)


@register(
    name="spatial_move",
    description="Record that an object MOVED from one place to another -- e.g. "
                "'the bag moved from the chair to the desk'. Updates its "
                "last-known location.",
    input_schema={"type": "object", "properties": {
        "entity": {"type": "string"},
        "to_location": {"type": "string", "description": "The new location."},
        "from_location": {"type": "string", "description": "The previous location. Optional."},
        "zone": {"type": "string"},
        "source": {"type": "string"},
    }, "required": ["entity", "to_location"]},
)
def spatial_move(entity: str, to_location: str, from_location: str = "",
                 zone: str = "", source: str = "user") -> str:
    return json.dumps(_svc().update_location(
        entity, to_location, from_location=from_location, zone=zone, source=source), default=str)


@register(
    name="spatial_where_is",
    description="Look up an object's LAST-KNOWN location from ZENO's STORED spatial "
                "memory -- wherever it was last recorded (the owner told ZENO, or a "
                "sensor did). ALWAYS call this when asked where something is or "
                "'where did you last see X'. It queries remembered data, so never "
                "say you lack a camera -- check the memory first.",
    input_schema={"type": "object", "properties": {
        "entity": {"type": "string", "description": "The object to locate."},
    }, "required": ["entity"]},
)
def spatial_where_is(entity: str) -> str:
    return json.dumps(_svc().where_is(entity), default=str)


@register(
    name="spatial_room_state",
    description="What objects are CURRENTLY known to be in a room/zone -- e.g. "
                "'what objects are known to be in the office?'. Returns the "
                "currently-tracked objects.",
    input_schema={"type": "object", "properties": {
        "zone": {"type": "string", "description": "Room/zone name. Optional; omit for all known objects."},
    }, "required": []},
)
def spatial_room_state(zone: str = "") -> str:
    return json.dumps(_svc().room_state(zone), default=str)


@register(
    name="spatial_recent",
    description="Show RECENT spatial events (persisted, newest first) -- e.g. "
                "'show recent spatial events', 'what changed in this room?'.",
    input_schema={"type": "object", "properties": {
        "limit": {"type": "integer", "description": "How many events (default 10)."},
    }, "required": []},
)
def spatial_recent(limit: int = 10) -> str:
    return json.dumps(_svc().recent(limit), default=str)


@register(
    name="spatial_events_at",
    description="What events happened at a LOCATION -- e.g. 'what happened near "
                "the front door?'. Queries spatial events around that place.",
    input_schema={"type": "object", "properties": {
        "location": {"type": "string"},
        "zone": {"type": "string"},
    }, "required": ["location"]},
)
def spatial_events_at(location: str, zone: str = "") -> str:
    return json.dumps(_svc().events_at(location, zone), default=str)


@register(
    name="spatial_events_when",
    description="What spatial events happened in a TIME window -- e.g. 'what "
                "happened in the hallway last night?' (use last_n_minutes or a "
                "time range). Newest first.",
    input_schema={"type": "object", "properties": {
        "last_n_minutes": {"type": "number", "description": "Look back this many minutes."},
        "time_after": {"type": "string", "description": "ISO time lower bound. Optional."},
        "time_before": {"type": "string", "description": "ISO time upper bound. Optional."},
        "limit": {"type": "integer", "description": "Max events (default 10)."},
    }, "required": []},
)
def spatial_events_when(last_n_minutes: float = 0.0, time_after: str = "",
                        time_before: str = "", limit: int = 10) -> str:
    kwargs: dict = {"n_results": max(1, int(limit)) if limit else 10, "order": "newest"}
    if last_n_minutes:
        kwargs["last_n_minutes"] = float(last_n_minutes)
    if time_after:
        kwargs["time_after"] = time_after
    if time_before:
        kwargs["time_before"] = time_before
    return json.dumps(_svc().events_when(**kwargs), default=str)


@register(
    name="spatial_recall",
    description="Recall spatial memories by MEANING -- a free-text query over "
                "what ZENO has observed spatially, e.g. 'anything about my keys?'.",
    input_schema={"type": "object", "properties": {
        "query": {"type": "string"},
    }, "required": ["query"]},
)
def spatial_recall(query: str) -> str:
    return json.dumps(_svc().recall(query), default=str)


@register(
    name="spatial_memory_status",
    description="Whether ZENO's Spatial Memory (eMEM) backend is available, and "
                "where it stores data. Use to diagnose spatial recall.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def spatial_memory_status() -> str:
    return json.dumps(_svc().status(), default=str)
