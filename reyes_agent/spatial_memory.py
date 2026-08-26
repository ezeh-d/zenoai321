"""ZENO Spatial Memory -- a clean service layer over eMEM's SpatioTemporalMemory.

WHY A SERVICE LAYER
-------------------
eMEM is coordinate-based (x, y, z); ZENO's owner speaks in named places ("the
office desk", "the hallway"). This service is the adapter between the two: it
maps a named location to STABLE coordinates (so every mention of "office desk"
clusters at the same point and spatial queries work), stores the human-readable
place/zone/entity in metadata, and exposes ZENO-shaped operations. It leaves
ZENO's existing memory system completely untouched -- this is an ADDITIONAL,
spatial layer.

RESILIENCE
----------
eMEM is optional. If it cannot be imported or initialised, every method returns
a structured ``{"ok": False, "error": ...}`` and ZENO keeps running. Persistence
lives in ZENO's own data dir (``%LOCALAPPDATA%/ZENO/spatial``), never inside the
eMEM git checkout. Verified against the installed eMEM 0.3.0 source -- no invented
APIs.

SECURITY
--------
This only records observations the owner explicitly gives it or that authorised
ZENO sources feed in. It performs no covert person tracking and initiates no
sensing on its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config

_HOME = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "spatial"
_DB = _HOME / "spatial.db"
_LOCMAP = _HOME / "locations.json"

# Bounded plane so hash-derived coordinates stay in a sane range (metres).
_PLANE = 100.0


class _LocationMap:
    """Named place -> stable (x, y, z). Deterministic via SHA-256 so the same
    place always resolves to the same point across processes/restarts; an
    explicit coordinate the owner supplies is remembered and wins."""

    def __init__(self, path: Path = _LOCMAP) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._map: dict[str, list[float]] = self._load()

    def _load(self) -> dict[str, list[float]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._map, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            pass

    @staticmethod
    def _key(location: str, zone: str) -> str:
        return f"{zone.strip().casefold()}/{location.strip().casefold()}".strip("/")

    def coords_for(self, location: str, zone: str = "",
                   explicit: tuple[float, float, float] | None = None) -> tuple[float, float, float]:
        key = self._key(location, zone) or "unknown"
        with self._lock:
            if explicit is not None:
                self._map[key] = [float(explicit[0]), float(explicit[1]), float(explicit[2])]
                self._save()
                return tuple(self._map[key])  # type: ignore[return-value]
            if key in self._map:
                return tuple(self._map[key])  # type: ignore[return-value]
            digest = hashlib.sha256(key.encode("utf-8")).digest()
            x = (int.from_bytes(digest[0:4], "big") / 2**32) * _PLANE
            y = (int.from_bytes(digest[4:8], "big") / 2**32) * _PLANE
            self._map[key] = [round(x, 3), round(y, 3), 0.0]
            self._save()
            return tuple(self._map[key])  # type: ignore[return-value]


class SpatialMemoryService:
    def __init__(self, db_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path else _DB
        self._locmap = _LocationMap(self._db_path.parent / "locations.json")
        self._mem: Any = None
        self._available: bool | None = None
        self._error = ""

    # -- lifecycle -------------------------------------------------------
    def _ensure(self) -> bool:
        if self._mem is not None:
            return True
        try:
            from emem import SpatioTemporalMemory

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._mem = SpatioTemporalMemory(db_path=str(self._db_path))
            self._available = True
            return True
        except Exception as exc:  # noqa: BLE001 -- optional dependency
            self._available = False
            self._error = f"{type(exc).__name__}: {exc}"[:200]
            return False

    def available(self) -> bool:
        with self._lock:
            return self._ensure()

    def status(self) -> dict[str, Any]:
        with self._lock:
            ok = self._ensure()
            return {"available": ok, "backend": "eMEM SpatioTemporalMemory" if ok else None,
                    "db_path": str(self._db_path), "error": "" if ok else self._error}

    def close(self) -> None:
        with self._lock:
            if self._mem is not None:
                try:
                    self._mem.save()
                    self._mem.close()
                except Exception:  # noqa: BLE001
                    pass
                self._mem = None

    def _unavailable(self) -> dict[str, Any]:
        return {"ok": False, "error": f"Spatial memory is not available ({self._error or 'eMEM not initialised'}). "
                                      "ZENO continues normally; spatial recall is offline."}

    # -- writes ----------------------------------------------------------
    def store_event(self, entity: str = "", location: str = "", *, zone: str = "",
                    source: str = "user", confidence: float = 1.0,
                    event_type: str = "observation", description: str = "",
                    coordinates: tuple[float, float, float] | None = None,
                    metadata: dict[str, Any] | None = None,
                    remember_entity: bool = True) -> dict[str, Any]:
        with self._lock:
            if not self._ensure():
                return self._unavailable()
            try:
                x, y, z = self._locmap.coords_for(location or (entity or "unknown"), zone, coordinates)
                text = description.strip() or (
                    f"{entity} {event_type} at {location}".strip() if location else
                    f"{entity} {event_type}".strip()) or event_type
                meta = {"entity": entity, "location": location, "zone": zone,
                        "event_type": event_type, **(metadata or {})}
                conf = max(0.0, min(1.0, float(confidence)))
                oid = self._mem.add(text, x=x, y=y, z=z, source_type=str(source or "user"),
                                    confidence=conf, metadata=meta)
                if remember_entity and entity:
                    self._mem.add_entity(entity, x=x, y=y, z=z,
                                         entity_type=str(meta.get("entity_type", "object")),
                                         confidence=conf, metadata=meta)
                self._mem.save()
                return {"ok": True, "id": oid, "entity": entity, "location": location,
                        "zone": zone, "coordinates": [x, y, z], "text": text}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"store failed: {type(exc).__name__}: {exc}"[:200]}

    def update_location(self, entity: str, to_location: str, *, from_location: str = "",
                        zone: str = "", source: str = "user", confidence: float = 1.0) -> dict[str, Any]:
        desc = (f"{entity} moved from {from_location} to {to_location}" if from_location
                else f"{entity} moved to {to_location}")
        return self.store_event(entity=entity, location=to_location, zone=zone, source=source,
                                confidence=confidence, event_type="moved", description=desc,
                                metadata={"from_location": from_location})

    # -- reads -----------------------------------------------------------
    def _q(self, fn_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            if not self._ensure():
                return self._unavailable()
            try:
                result = getattr(self._mem, fn_name)(*args, **kwargs)
                return {"ok": True, "result": str(result)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{fn_name} failed: {type(exc).__name__}: {exc}"[:200]}

    def where_is(self, entity: str) -> dict[str, Any]:
        entity = str(entity or "").strip()
        if not entity:
            return {"ok": False, "error": "name the object to locate."}
        return self._q("locate", entity)

    def recall(self, query: str) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "provide something to recall."}
        return self._q("recall", query)

    def room_state(self, zone: str = "") -> dict[str, Any]:
        # The current known objects. eMEM's entity list does not carry the zone
        # label in its text, so we return all known entities and note the zone
        # rather than silently dropping matches (honest over precise).
        res = self._q("entity_query")
        if res.get("ok") and zone:
            res["note"] = f"All currently-known objects (zone '{zone}' not filtered at source)."
        return res

    def events_at(self, location: str, zone: str = "", radius: float = 5.0) -> dict[str, Any]:
        with self._lock:
            if not self._ensure():
                return self._unavailable()
            try:
                x, y, _ = self._locmap.coords_for(location, zone)
                return {"ok": True, "result": str(self._mem.spatial_query(x=x, y=y, radius=radius))}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"location query failed: {type(exc).__name__}"[:120]}

    def events_when(self, **kwargs: Any) -> dict[str, Any]:
        return self._q("temporal_query", **kwargs)

    def recent(self, limit: int = 10) -> dict[str, Any]:
        # Uses temporal_query, which reads the PERSISTED store (survives restart),
        # not the session-only working buffer that get_recent exposes.
        with self._lock:
            if not self._ensure():
                return self._unavailable()
            try:
                n = max(1, int(limit)) if limit else 10
                return {"ok": True, "result": str(self._mem.temporal_query(order="newest", n_results=n))}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"recent failed: {type(exc).__name__}: {exc}"[:200]}

    def session_buffer(self, limit: int = 10) -> dict[str, Any]:
        """The current SESSION's unflushed observations (working memory only --
        empty after a restart). Structured; complements the durable recent()."""
        with self._lock:
            if not self._ensure():
                return self._unavailable()
            try:
                nodes = self._mem.get_recent(int(limit) if limit else None)
                events = []
                for node in nodes:
                    coords = getattr(node, "coordinates", None)
                    events.append({
                        "text": getattr(node, "text", ""),
                        "when": time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(getattr(node, "timestamp", 0.0))),
                        "source": getattr(node, "source_type", ""),
                        "confidence": getattr(node, "confidence", None),
                        "coordinates": [float(coords[0]), float(coords[1]), float(coords[2])]
                                       if coords is not None else None,
                        "metadata": getattr(node, "metadata", {}) or {},
                    })
                return {"ok": True, "count": len(events), "events": events}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"session buffer failed: {type(exc).__name__}"[:120]}


_instance: SpatialMemoryService | None = None
_instance_lock = threading.Lock()


def get_spatial_memory() -> SpatialMemoryService:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SpatialMemoryService()
        return _instance


def reset_for_tests(db_path: Path | None = None) -> SpatialMemoryService:
    global _instance
    with _instance_lock:
        _instance = SpatialMemoryService(db_path)
        return _instance
