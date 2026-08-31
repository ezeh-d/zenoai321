"""Universal Learning Engine, Phase 1: study a document, ask grounded questions
with citations, recall, forget, persistence -- and honest failure.

A deterministic bag-of-words embedder is injected so these run fast without the
real sentence-transformer.
"""

from __future__ import annotations

import numpy as np
import pytest

from reyes_agent.study.engine import StudyEngine


def _bow(texts, dim=256):
    import re
    out = []
    for t in texts:
        v = np.zeros(dim, dtype=float)
        for w in re.findall(r"[a-z0-9]+", str(t).lower()):
            v[sum(ord(c) for c in w) % dim] += 1.0
        out.append(v)
    return out


@pytest.fixture()
def engine(tmp_path):
    return StudyEngine(embed=_bow, docs_dir=tmp_path / "docs",
                       catalog_path=tmp_path / "catalog.json")


def _doc(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


# --- studying ---------------------------------------------------------------
def test_study_a_text_file(tmp_path, engine):
    f = _doc(tmp_path, "notes.txt",
             "Voltage is electric potential difference. "
             "Current is the flow of charge. Resistance opposes current.")
    r = engine.study(str(f))
    assert r["ok"] and r["chunks"] >= 1 and r["embedded"] is True
    assert engine.catalog()["count"] == 1


def test_study_missing_file_is_honest(engine):
    r = engine.study("/no/such/file.pdf")
    assert r["ok"] is False and "readable file" in r["error"]


def test_study_empty_file_reports_nothing_studyable(tmp_path, engine):
    f = _doc(tmp_path, "empty.txt", "   ")
    r = engine.study(str(f))
    assert r["ok"] is False and "studyable" in r["error"]


# --- grounded retrieval + citations -----------------------------------------
def test_ask_returns_grounded_passage_with_a_citation(tmp_path, engine):
    f = _doc(tmp_path, "physics.txt",
             "Ohm's law states voltage equals current times resistance. "
             "Capacitors store energy in an electric field.")
    engine.study(str(f))
    r = engine.ask("what is ohm's law about voltage")
    assert r["ok"] and r["grounded"] is True
    top = r["passages"][0]
    assert "voltage" in top["text"].lower()
    assert top["citation"]["source"] == "physics.txt"
    assert top["citation"]["confidence"] in ("high", "medium", "low", "weak")


def test_ask_can_restrict_to_one_source(tmp_path, engine):
    a = _doc(tmp_path, "a.txt", "Fourier transforms convert time to frequency.")
    b = _doc(tmp_path, "b.txt", "Newton's laws describe motion and force.")
    engine.study(str(a)); engine.study(str(b))
    r = engine.ask("frequency", source=str(a))
    assert r["ok"] and r["grounded"]
    assert all(p["citation"]["source"] == "a.txt" for p in r["passages"])


def test_ask_is_honest_when_nothing_is_relevant(tmp_path, engine):
    f = _doc(tmp_path, "cooking.txt", "Boil pasta for eight minutes with salt.")
    engine.study(str(f))
    r = engine.ask("quantum chromodynamics gluon confinement lattice")
    assert r["ok"] and r["grounded"] is False and r["passages"] == []


def test_ask_before_studying_anything_is_honest(engine):
    r = engine.ask("anything")
    assert r["ok"] is False and "nothing has been studied" in r["error"]


# --- persistence across a restart -------------------------------------------
def test_study_persists_across_a_fresh_engine(tmp_path):
    f = _doc(tmp_path, "persist.txt", "The mitochondria is the powerhouse of the cell.")
    StudyEngine(embed=_bow, docs_dir=tmp_path / "docs",
                catalog_path=tmp_path / "catalog.json").study(str(f))
    # a brand-new engine over the same store still answers
    fresh = StudyEngine(embed=_bow, docs_dir=tmp_path / "docs",
                        catalog_path=tmp_path / "catalog.json")
    r = fresh.ask("what is the powerhouse of the cell")
    assert r["ok"] and r["grounded"] and "mitochondria" in r["passages"][0]["text"].lower()


# --- forget -----------------------------------------------------------------
def test_forget_removes_from_the_store(tmp_path, engine):
    f = _doc(tmp_path, "temp.txt", "Ephemeral study content about turbines.")
    engine.study(str(f))
    assert engine.catalog()["count"] == 1
    out = engine.forget(str(f))
    assert out["ok"] and out["found"]
    assert engine.catalog()["count"] == 0


# --- degradation: no embeddings -> keyword overlap, still grounded ----------
def test_degrades_to_keyword_search_without_embeddings(tmp_path):
    eng = StudyEngine(embed=lambda texts: None,     # embeddings unavailable
                      docs_dir=tmp_path / "docs", catalog_path=tmp_path / "catalog.json")
    f = _doc(tmp_path, "k.txt", "Photosynthesis converts sunlight into chemical energy.")
    r = eng.study(str(f))
    assert r["ok"] and r["embedded"] is False
    ans = eng.ask("photosynthesis energy")
    assert ans["ok"] and ans["grounded"] and ans["semantic"] is False


# --- tools registered -------------------------------------------------------
def test_study_tools_registered_and_routable():
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    from reyes_agent.routing.capability import CAPABILITIES
    for name in ("study_document", "study_ask", "study_status", "study_forget"):
        assert name in TOOLS
    assert "study_document" in CAPABILITIES["files"]
