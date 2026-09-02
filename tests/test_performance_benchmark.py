"""Contracts for ZENO's dependency-free local performance benchmark."""

from reyes_agent.performance_benchmark import run_case, run_router_benchmark, summarize


def test_summary_reports_required_distribution_fields():
    """A malformed summary must not be usable as performance evidence."""
    row = summarize([1.0, 2.0, 3.0, 4.0], attempts=5, failures=1)

    assert row == {
        "samples": 4,
        "attempts": 5,
        "failures": 1,
        "failure_rate_pct": 20.0,
        "p50_ms": 3.0,
        "p90_ms": 4.0,
        "p95_ms": 4.0,
        "p99_ms": 4.0,
        "max_ms": 4.0,
    }


def test_runner_excludes_warmups_and_retains_failure_type():
    """Warmup calls and failures must not disappear from recorded evidence."""
    calls = []

    def action():
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("expected")

    row = run_case("sample", action, iterations=3, warmups=2)

    assert row["name"] == "sample"
    assert row["attempts"] == 3
    assert row["failures"] == 1
    assert row["samples"] == 2
    assert row["errors"] == {"RuntimeError": 1}


def test_router_benchmark_reports_each_fixed_route_without_starting_a_server(monkeypatch):
    """The local routing suite must remain a bounded, in-process benchmark."""
    from reyes_agent.routing import capability

    class Route:
        tools = ("enable_tools", "delegate", "get_datetime")
        exposed = 3

    monkeypatch.setattr(capability, "clear_context", lambda: None)
    monkeypatch.setattr(capability, "tools_for", lambda _message: Route())

    result = run_router_benchmark(iterations=1, warmups=0)

    assert result["suite"] == "router"
    assert [row["name"] for row in result["cases"]] == [
        "Hello ZENO, how are you?",
        "What time is it?",
        "Open Chrome",
        "Search YouTube for football highlights",
        "Remember that blue is my test colour",
        "Look at my screen",
        "Fix this Python traceback",
    ]
    assert {row["tools_exposed"] for row in result["cases"]} == {3}
