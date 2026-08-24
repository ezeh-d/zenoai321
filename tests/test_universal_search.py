"""Contracts for universal search (local backend + graceful degradation)."""

from __future__ import annotations

from reyes_agent.universal_search import LocalIndex, UniversalSearchService


def _seed(idx):
    idx.index("m1", "Catherine is a Healthcare Assistant at T21 Services", {"kind": "memory"})
    idx.index("m2", "The recruitment report for August is due Friday", {"kind": "task"})
    idx.index("m3", "Open Slack and message the team about the dashboard", {"kind": "command"})
    idx.index("m4", "Temitope Ajayi leads the training programme", {"kind": "staff"})


def test_exact_term_ranks_top():
    idx = LocalIndex(); _seed(idx)
    hits = idx.search("recruitment report")
    assert hits and hits[0].id == "m2"
    assert hits[0].score > 0.8


def test_typo_tolerance():
    idx = LocalIndex(); _seed(idx)
    # 'recuitment' (missing r) still finds the recruitment report.
    hits = idx.search("recuitment")
    assert hits and hits[0].id == "m2"


def test_phrase_bonus_and_metadata_returned():
    idx = LocalIndex(); _seed(idx)
    hits = idx.search("healthcare assistant")
    assert hits[0].id == "m1"
    assert hits[0].metadata.get("kind") == "memory"


def test_no_match_returns_empty():
    idx = LocalIndex(); _seed(idx)
    assert idx.search("quantum chromodynamics zzz") == []


def test_empty_query_returns_empty():
    idx = LocalIndex(); _seed(idx)
    assert idx.search("") == []
    assert idx.search("   ") == []


def test_limit_respected():
    idx = LocalIndex()
    for i in range(20):
        idx.index(f"d{i}", "slack message team dashboard report")
    assert len(idx.search("slack report", limit=5)) == 5


def test_remove_and_clear():
    idx = LocalIndex(); _seed(idx)
    idx.remove("m2")
    assert all(h.id != "m2" for h in idx.search("recruitment report"))
    idx.clear()
    assert len(idx) == 0


def test_index_ignores_blank_id():
    idx = LocalIndex()
    idx.index("", "text")
    assert len(idx) == 0


# --- service picks local when meilisearch is off ----------------------------
def test_service_defaults_to_local(monkeypatch):
    # Flag off by default -> local backend, no server needed.
    svc = UniversalSearchService()
    assert svc.backend_name == "local"
    n = svc.index_many([
        {"id": "a", "text": "open chrome and search T21 Services", "kind": "cmd"},
        {"id": "b", "text": "send Bukola a good morning message"},
        {"id": "", "text": "ignored, no id"},
    ])
    assert n == 2
    hits = svc.search("chrome T21")
    assert hits and hits[0].id == "a"


def test_service_health_shape():
    svc = UniversalSearchService()
    h = svc.health()
    assert h["active_backend"] == "local" and h["local"]["ok"] is True


def test_service_never_raises_on_bad_docs():
    svc = UniversalSearchService()
    svc.index_many([{"nope": 1}, {"id": "x", "text": None}])  # tolerated
    assert isinstance(svc.search("anything"), list)


def test_as_dict_shape():
    idx = LocalIndex(); _seed(idx)
    d = idx.search("slack")[0].as_dict()
    assert set(d) == {"id", "score", "text", "metadata"}
