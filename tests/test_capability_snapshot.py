"""The live capability snapshot reads ZENO's REAL registry -- no fabrication."""

from __future__ import annotations

from reyes_agent import capability_snapshot as cs


def test_tool_inventory_reflects_real_registry():
    inv = cs.tool_inventory()
    # ZENO registers a large tool set; the snapshot must count the real one.
    assert inv["registered"] > 20
    assert isinstance(inv["names"], list) and inv["registered"] == len(inv["names"])


def test_by_area_marks_connected_areas():
    areas = {a["area"]: a for a in cs.by_area()}
    # Browser and desktop are core, populated capability areas.
    assert areas["browser"]["connected"] is True
    assert areas["desktop"]["connected"] is True
    assert areas["browser"]["tools_connected"] > 0


def test_can_i_known_area_and_tool():
    assert cs.can_i("browser")["connected"] is True
    ans = cs.can_i("open_app")
    assert ans["connected"] is True and ans.get("healthy") in (True, False)


def test_can_i_unknown_is_honestly_no():
    ans = cs.can_i("teleportation_ray")
    assert ans["connected"] is False and "no such tool" in ans["reason"]


def test_can_i_blank():
    assert cs.can_i("")["connected"] is False


def test_what_can_i_do_lists_connected_areas():
    out = cs.what_can_i_do()
    assert out["tool_count"] > 20
    labels = {a["label"] for a in out["connected_areas"]}
    assert "Browser control" in labels or "Desktop control" in labels


def test_system_status_is_honest_rollup():
    st = cs.system_status()
    assert st["tools"] > 20
    assert st["areas_connected"] >= 1 and st["areas_connected"] <= st["areas_total"]
    assert isinstance(st["quarantined"], list)
    assert isinstance(st["proven_active"], list)
    # open_app was seeded as proven-active via capability_truth.
    assert "open_app" in st["proven_active"]
    assert isinstance(st["flags_on"], list)


def test_snapshot_functions_never_raise():
    # Even if called repeatedly / in any order, they return plain data.
    for _ in range(2):
        assert isinstance(cs.tool_inventory(), dict)
        assert isinstance(cs.by_area(), list)
        assert isinstance(cs.system_status(), dict)
