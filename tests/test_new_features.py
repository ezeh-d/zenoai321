"""
Tests for REYES's new subsystems. Runs with pytest OR plain python:

    python tests/test_new_features.py

Covers planning, long-term recall, security tooling, and agent routing —
all offline, no LLM or network needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

# make the project importable when run directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_planner_offline_splits_goal():
    from core.planner import Planner
    plan = Planner(llm=None).make_plan("research laptops and then write an email")
    assert len(plan.steps) == 2
    assert plan.steps[0].n == 1 and not plan.steps[0].done


def test_planner_marks_and_completes():
    from core.planner import Planner
    plan = Planner(llm=None).make_plan("do one thing")
    assert plan.next_step() is not None
    for s in list(plan.steps):
        plan.mark(s.n, "ok")
    assert plan.complete and plan.next_step() is None


def test_retrieval_ranks_relevant_first():
    from memory.retrieval import Retriever
    r = Retriever()
    r.add_many([
        "Boss prefers dark roast coffee",
        "The Acme meeting is on Friday",
        "The API key rotates monthly",
    ])
    hits = r.search("when is the acme meeting", k=1)
    assert hits and "Acme" in hits[0][1]


def test_retrieval_empty_is_graceful():
    from memory.retrieval import deep_recall
    assert "Nothing relevant" in deep_recall("anything", notes=[], history=[])


def test_security_passcheck_levels():
    from security.defense import passcheck
    assert "Very weak" in passcheck("password")          # breached
    assert "weak" in passcheck("abc").lower()             # short
    strong = passcheck("Tr0ub4dor&3xtra!!")
    assert ("Strong" in strong) or ("Excellent" in strong)


def test_security_hash_and_ports_and_log(tmp_path=None):
    import tempfile
    from security.defense import hash_file, scan_ports, scan_log
    d = Path(tempfile.mkdtemp())
    f = d / "sample.txt"
    f.write_text("hello reyes")
    assert "sha256(" in hash_file(str(f))
    assert hash_file(str(d / "missing")).startswith("No such file")
    # port scan returns a string and refuses non-local hosts
    assert isinstance(scan_ports(1, 2), str)
    assert "authorization" in scan_ports(host="8.8.8.8").lower()
    # log triage flags a suspicious line
    log = d / "app.log"
    log.write_text("all good\nFailed password for root\nok\n")
    assert "Flagged" in scan_log(str(log))


def test_security_lab_lookup():
    from security.lab import learn
    assert "SQL Injection" in learn("sqli")
    assert "TryHackMe" in learn("labs")


def test_agent_routing():
    from agents.orchestrator import Orchestrator
    o = Orchestrator(llm=None)
    assert o.route("debug my python function") == "coder"
    assert o.route("research the latest news") == "researcher"
    assert o.route("open chrome and click the button") == "operator"
    assert o.route("draft an email to the team") == "writer"


# ---- plain-python runner (no pytest required) ----------------------------
def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  \033[92mPASS\033[0m {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  \033[91mFAIL\033[0m {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
