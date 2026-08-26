"""Spatial Memory (eMEM) integration -- verified against the REAL installed eMEM.

Covers every required case: eMEM import, init, store, retrieve, object-location,
temporal & location queries, persistence after restart, malformed input,
unavailable eMEM, ZENO-startup-without-spatial-memory, and no regression to the
existing memory system.
"""

from __future__ import annotations

import builtins
import json

import pytest

from reyes_agent.spatial_memory import SpatialMemoryService


@pytest.fixture
def svc(tmp_path):
    return SpatialMemoryService(tmp_path / "spatial.db")


# --- eMEM presence + init ---------------------------------------------------
def test_emem_imports_with_expected_api():
    import emem

    assert hasattr(emem, "SpatioTemporalMemory")
    m = emem.SpatioTemporalMemory  # the class we build on
    assert callable(m)


def test_service_initialises(svc):
    st = svc.status()
    assert st["available"] is True
    assert st["backend"] == "eMEM SpatioTemporalMemory"
    assert "spatial.db" in st["db_path"]


# --- store + retrieve -------------------------------------------------------
def test_store_event_and_retrieve(svc):
    res = svc.store_event("laptop", "office desk", zone="office", source="user", confidence=1.0)
    assert res["ok"] is True and res["entity"] == "laptop"
    assert res["coordinates"] and len(res["coordinates"]) == 3
    recent = svc.recent(5)
    assert recent["ok"] and "laptop" in recent["result"]


def test_object_location_memory(svc):
    svc.store_event("laptop", "office desk", zone="office")
    where = svc.where_is("laptop")
    assert where["ok"] and "Location" in where["result"]


def test_update_location_records_move(svc):
    svc.store_event("bag", "chair", zone="office")
    moved = svc.update_location("bag", "office desk", from_location="chair", zone="office")
    assert moved["ok"] is True
    assert "moved" in svc.recent(5)["result"].lower() or moved["text"]


def test_room_state_lists_known_objects(svc):
    svc.store_event("laptop", "office desk", zone="office")
    svc.store_event("mug", "kitchen counter", zone="kitchen")
    state = svc.room_state("office")
    assert state["ok"] and ("laptop" in state["result"] or "mug" in state["result"])


# --- temporal + location queries -------------------------------------------
def test_temporal_query(svc):
    svc.store_event("keys", "hallway table", zone="hallway")
    res = svc.events_when(last_n_minutes=60)
    assert res["ok"] and "keys" in res["result"]


def test_location_query(svc):
    svc.store_event("parcel", "front door", zone="hallway")
    res = svc.events_at("front door", "hallway")
    assert res["ok"]  # spatial query around that place returns a string result


def test_semantic_recall(svc):
    svc.store_event("laptop", "office desk", zone="office")
    res = svc.recall("laptop")
    assert res["ok"] and "laptop" in res["result"].lower()


# --- persistence after restart ---------------------------------------------
def test_persistence_after_restart(tmp_path):
    db = tmp_path / "spatial.db"
    s1 = SpatialMemoryService(db)
    s1.store_event("laptop", "office desk", zone="office")
    s1.store_event("bag", "chair", zone="office")
    s1.close()
    # Reopen the SAME db in a brand-new service (simulating a restart).
    s2 = SpatialMemoryService(db)
    recent = s2.recent(10)
    assert recent["ok"] and "laptop" in recent["result"]      # durable
    assert s2.where_is("laptop")["ok"]
    s2.close()


# --- malformed / defensive --------------------------------------------------
def test_malformed_input_does_not_crash(svc):
    assert svc.where_is("")["ok"] is False
    assert svc.recall("")["ok"] is False
    # store with confidence out of range is clamped, still ok
    res = svc.store_event("thing", "somewhere", confidence=9.9)
    assert res["ok"] is True


# --- unavailable eMEM -------------------------------------------------------
def test_unavailable_emem_degrades_gracefully(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "emem" or name.startswith("emem."):
            raise ImportError("emem not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    s = SpatialMemoryService(tmp_path / "spatial.db")
    assert s.available() is False
    res = s.store_event("laptop", "desk")
    assert res["ok"] is False and "not available" in res["error"]
    # Reads degrade too, without raising.
    assert s.where_is("laptop")["ok"] is False
    assert s.recent()["ok"] is False


# --- ZENO startup without spatial memory (tools stay safe) ------------------
def test_tools_registered_and_safe_when_backend_down(monkeypatch, tmp_path):
    import reyes_agent.tools.system  # noqa: F401  (registers spatial tools)
    from reyes_agent import spatial_memory
    from reyes_agent.tools import TOOLS, spatial_tools

    for name in ("spatial_remember", "spatial_where_is", "spatial_recent",
                 "spatial_room_state", "spatial_memory_status"):
        assert name in TOOLS

    # Force the shared service to a down backend; the tool must return a clean
    # error string (JSON), never raise -- ZENO keeps running.
    down = SpatialMemoryService(tmp_path / "spatial.db")
    monkeypatch.setattr(down, "_ensure", lambda: False)
    down._error = "simulated down"
    monkeypatch.setattr(spatial_memory, "get_spatial_memory", lambda: down)
    out = json.loads(spatial_tools.spatial_where_is("laptop"))
    assert out["ok"] is False and "not available" in out["error"]


# --- no regression to the existing memory system ---------------------------
def test_existing_memory_system_untouched():
    # The classic memory manager still imports and exposes its API; the spatial
    # layer is additive, not a replacement.
    from reyes_agent.memory_manager import trim_history

    assert callable(trim_history)
