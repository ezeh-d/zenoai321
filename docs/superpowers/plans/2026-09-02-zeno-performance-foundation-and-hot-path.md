# ZENO Performance Foundation and Conversation Hot-Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a reproducible local performance baseline and remove the measured semantic-model cold stall from ordinary conversation routing.

**Architecture:** Keep the existing capability router, latency store, performance monitor, scheduler, and worker ownership. A developer-only benchmark reports honest latency distributions. The capability router may use semantic classification only when the optional semantic router is already warm; it never initializes a sentence-transformer while handling normal conversation.

**Tech Stack:** Python 3.12, pytest, standard-library time/statistics/json, existing reyes_agent routing and bounded diagnostics.

**Spec:** docs/superpowers/specs/2026-09-02-zeno-performance-stability-design.md

## Global Constraints

- Windows is the target platform; do not use Unix signals or uvloop.
- Preserve the shared dirty worktree; stage only files created or modified by these tasks.
- Do not install or initialize optional profiling, model, provider, browser, voice, or telemetry dependencies solely for benchmarking.
- Do not send messages, invoke destructive tools, launch applications, or call cloud providers in benchmark tests.
- Each distribution reports sample count, p50, p90, p95, p99, maximum, and failure rate; unavailable metrics remain unavailable.
- Do not alter security, authentication, authorization, permission, TLS, owner-trust, or secret-redaction behavior.

---

## File Structure

| File | Responsibility |
|---|---|
| reyes_agent/performance_benchmark.py | Dependency-free summary, repeated runner, safe router benchmark, and JSON CLI. |
| reyes_agent/routing/intent_router.py | Non-initializing ready-only semantic classification API. |
| reyes_agent/routing/capability.py | Ready-only, command-shaped semantic fallback. |
| tests/test_performance_benchmark.py | Benchmark statistics, failures, warmups, route output, and CLI tests. |
| tests/test_intent_router.py | Cold-router and ready-router semantic boundary tests. |
| tests/test_capability_router.py | Existing tool budget and deterministic latency guard. |
| docs/performance/baseline.md | Measured pre-change values and limitations. |
| docs/performance/optimized.md | Exact post-change result and test evidence. |

## Shared Interfaces

~~~python
def summarize(samples_ms: Iterable[float], *, attempts: int, failures: int) -> dict[str, int | float | None]: ...
def run_case(name: str, action: Callable[[], object], *, iterations: int = 200, warmups: int = 5) -> dict[str, object]: ...
def run_router_benchmark(*, iterations: int = 200, warmups: int = 5) -> dict[str, object]: ...

class IntentRouter:
    def is_ready(self) -> bool: ...
    def classify_if_ready(self, message: str) -> IntentMatch | None: ...
~~~

classify_if_ready is a pure readiness-gated query. It must not call _ensure, import sentence_transformers, create a model, or mutate route vectors. classify retains its existing explicit warm/load behavior.

### Task 1: Add the safe benchmark primitive

**Files:**
- Create: reyes_agent/performance_benchmark.py
- Create: tests/test_performance_benchmark.py

**Consumes:** routing.capability.tools_for only inside the route runner; generic cases receive an injected zero-argument action.

**Produces:** Result dictionaries with name, attempts, failures, failure_rate_pct, samples, p50_ms, p90_ms, p95_ms, p99_ms, max_ms, and errors.

- [ ] **Step 1: Write failing summary and runner tests**

~~~python
from reyes_agent.performance_benchmark import run_case, summarize

def test_summary_reports_required_distribution_fields():
    row = summarize([1.0, 2.0, 3.0, 4.0], attempts=5, failures=1)
    assert row == {
        "samples": 4, "attempts": 5, "failures": 1,
        "failure_rate_pct": 20.0, "p50_ms": 3.0, "p90_ms": 4.0,
        "p95_ms": 4.0, "p99_ms": 4.0, "max_ms": 4.0,
    }

def test_runner_excludes_warmups_and_retains_failure_type():
    calls = []
    def action():
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("expected")
    row = run_case("sample", action, iterations=3, warmups=2)
    assert row["attempts"] == 3 and row["failures"] == 1
    assert row["samples"] == 2 and row["errors"] == {"RuntimeError": 1}
~~~

- [ ] **Step 2: Run the new test and verify it fails**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py
~~~

Expected: collection fails because reyes_agent.performance_benchmark is absent.

- [ ] **Step 3: Implement the minimal benchmark module**

~~~python
def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[round((len(ordered) - 1) * fraction)], 4)

def run_case(name, action, *, iterations=200, warmups=5):
    for _ in range(max(0, warmups)):
        try:
            action()
        except Exception:
            pass
    samples, errors = [], {}
    for _ in range(iterations):
        started = time.perf_counter_ns()
        try:
            action()
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
        except Exception as exc:
            errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1
    return {"name": name, **summarize(samples, attempts=iterations,
                                      failures=sum(errors.values())),
            "errors": errors}
~~~

Validate iterations is at least one and warmups is non-negative. Retain no more than ten error type names. Return JSON-serializable values only.

- [ ] **Step 4: Add route coverage**

Define this fixed case tuple:

~~~python
ROUTE_CASES = (
    "Hello ZENO, how are you?", "What time is it?", "Open Chrome",
    "Search YouTube for football highlights", "Remember that blue is my test colour",
    "Look at my screen", "Fix this Python traceback",
)
~~~

For every case, clear only capability follow-up context before calling tools_for. Include tools_exposed from the final successful route. Do not start a server, provider, browser, audio device, or scheduler.

- [ ] **Step 5: Run focused tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

~~~powershell
git add reyes_agent/performance_benchmark.py tests/test_performance_benchmark.py
git commit -m "feat(perf): add reproducible routing benchmark"
~~~

### Task 2: Make semantic fallback ready-only on the conversation hot path

**Files:**
- Modify: reyes_agent/routing/intent_router.py
- Modify: reyes_agent/routing/capability.py
- Modify: tests/test_intent_router.py
- Modify: tests/test_capability_router.py

**Consumes:** IntentRouter._ready, _ensure, and injectable encoder behavior; deterministic capability classification.

**Produces:** IntentRouter.is_ready, IntentRouter.classify_if_ready, and a tools_for path that cannot trigger a semantic model load for normal conversation.

- [ ] **Step 1: Write failing semantic-boundary tests**

~~~python
def test_ready_only_classification_never_initializes_router(monkeypatch):
    router = IntentRouter(_ROUTES, encoder=_bow)
    called = {"ensure": 0}
    monkeypatch.setattr(router, "_ensure",
                        lambda: called.__setitem__("ensure", 1) or True)
    assert router.classify_if_ready("open chrome") is None
    assert called["ensure"] == 0

def test_ordinary_conversation_never_calls_semantic_router(monkeypatch):
    from reyes_agent.routing import capability, intent_router
    calls = {"cold": 0, "ready": 0}
    class ColdRouter:
        def classify(self, _message):
            calls["cold"] += 1
            raise AssertionError("ordinary chat must not initialize semantic routing")
        def classify_if_ready(self, _message):
            calls["ready"] += 1
            raise AssertionError("ordinary chat must not invoke semantic routing")
    monkeypatch.setattr(intent_router, "get_intent_router", lambda: ColdRouter())
    capability.tools_for("Hello ZENO, how are you?")
    assert calls == {"cold": 0, "ready": 0}
~~~

Add a pre-warmed command test with a stub whose classify_if_ready returns IntentMatch("open_app", "desktop", 0.7) for "get calculator going"; assert desktop is included. Retain the existing explicit-regex skip test.

- [ ] **Step 2: Run semantic-boundary tests and verify failure**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_intent_router.py tests/test_capability_router.py
~~~

Expected: failure because classify_if_ready is absent and ordinary chat calls classify.

- [ ] **Step 3: Add IntentRouter ready-only methods**

~~~python
def is_ready(self) -> bool:
    with self._lock:
        return bool(self._ready)

def classify_if_ready(self, message: str) -> IntentMatch | None:
    text = str(message or "").strip()
    if len(text) < 2 or not self.is_ready():
        return None
    return self._classify_loaded(text)
~~~

Extract the existing post-_ensure classification body to _classify_loaded(text). Keep classify as:

~~~python
if len(text) < 2 or not self._ensure():
    return None
return self._classify_loaded(text)
~~~

Do not alter thresholds, routes, model configuration, available(), or route-vector construction.

- [ ] **Step 4: Restrict capability fallback to ready command-shaped routing**

Add this compiled guard near _FOLLOW_UP:

~~~python
_SEMANTIC_COMMAND = re.compile(
    r"\b(?:open|launch|start|play|pause|resume|search|find|look|read|send|"
    r"message|tell|where|check|show|turn|set|go|bring|fire|put|get)\b", re.I)
~~~

Replace the unconditional semantic fallback with:

~~~python
if not capabilities and _SEMANTIC_COMMAND.search(message or ""):
    from reyes_agent.routing.intent_router import get_intent_router
    match = get_intent_router().classify_if_ready(message)
    if match and match.capability in CAPABILITIES:
        capabilities = (match.capability,)
        confidence = "semantic-ready"
        reason = f"{reason or 'no trigger'}; semantic:{match.intent}"
~~~

Keep the surrounding exception guard. Do not call _ensure, available, or a model constructor here. A semantic miss returns existing essentials and keeps enable_tools expansion available.

- [ ] **Step 5: Run regression tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_intent_router.py tests/test_capability_router.py tests/test_fast_intelligence.py tests/test_conversation_state.py
~~~

Expected: PASS, ordinary conversation remains tiny, and deterministic routing remains under the existing 15 ms guard.

- [ ] **Step 6: Run a routing benchmark**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m reyes_agent.performance_benchmark --router-only --iterations 500 --warmups 5
~~~

Expected: JSON for every fixed case. Greeting output has no model-load-sized maximum; unexpected failures appear in errors.

- [ ] **Step 7: Commit**

~~~powershell
git add reyes_agent/routing/intent_router.py reyes_agent/routing/capability.py tests/test_intent_router.py tests/test_capability_router.py
git commit -m "fix(routing): keep semantic model off chat hot path"
~~~

### Task 3: Add CLI coverage and durable benchmark evidence

**Files:**
- Modify: reyes_agent/performance_benchmark.py
- Modify: tests/test_performance_benchmark.py
- Create: docs/performance/baseline.md
- Create: docs/performance/optimized.md

**Consumes:** run_router_benchmark, approved pre-change values, and real post-change CLI output.

**Produces:** python -m reyes_agent.performance_benchmark --router-only plus durable before/after evidence.

- [ ] **Step 1: Write failing CLI tests**

~~~python
def test_main_router_only_writes_one_json_document(monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "run_router_benchmark",
                        lambda **_kwargs: {"suite": "router", "cases": []})
    assert benchmark.main(["--router-only", "--iterations", "7", "--warmups", "0"]) == 0
    assert json.loads(capsys.readouterr().out) == {"suite": "router", "cases": []}

def test_invalid_iteration_count_is_rejected():
    with pytest.raises(ValueError, match="iterations"):
        benchmark.run_case("x", lambda: None, iterations=0)
~~~

- [ ] **Step 2: Run test and verify failure**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py
~~~

Expected: failure because main is absent or does not validate arguments.

- [ ] **Step 3: Implement the JSON-only CLI**

Use argparse with --router-only, --iterations default 200, and --warmups default 5. Reject invalid counts through ValueError in library functions and parser.error in the CLI. Print exactly one JSON document and no progress text.

~~~python
if __name__ == "__main__":
    raise SystemExit(main())
~~~

- [ ] **Step 4: Run CLI and benchmark tests**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py
& .\.venv\Scripts\python.exe -m reyes_agent.performance_benchmark --router-only --iterations 500 --warmups 5
~~~

Expected: tests pass and the command emits valid JSON only.

- [ ] **Step 5: Record evidence**

Write docs/performance/baseline.md with the measured pre-change greeting figures: p50 26.58 ms, p95 51.80 ms, p99 85.97 ms, maximum 64.89 s. Include the explicit command results from the design spec and state that no live server, voice device, provider, panel, browser, or full-app startup timing was available.

Write docs/performance/optimized.md with the exact JSON output from Step 4, executed test commands/results, machine limitations, and the explicit statement that this router benchmark does not prove STT, TTS, provider, UI, or network speed.

- [ ] **Step 6: Commit**

~~~powershell
git add reyes_agent/performance_benchmark.py tests/test_performance_benchmark.py docs/performance/baseline.md docs/performance/optimized.md
git commit -m "docs(perf): record routing benchmark evidence"
~~~

### Task 4: Verify the first delivery and select the next measured bottleneck

**Files:**
- Modify: docs/performance/optimized.md

**Consumes:** Benchmark JSON and existing contracts.

**Produces:** A reproducible first delivery and a ranked next investigation rather than speculative queue, voice, UI, or dependency changes.

- [ ] **Step 1: Run the regression matrix**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py tests/test_intent_router.py tests/test_capability_router.py tests/test_fast_intelligence.py tests/test_conversation_state.py tests/test_phase21_runtime.py tests/test_realtime_conversation.py tests/test_resource_leases.py tests/test_workspace_frontend.py tests/test_visual_performance.py
~~~

Expected: PASS. If a test fails, stop and use root-cause investigation before changing another component.

- [ ] **Step 2: Run import, whitespace, and scope checks**

Run:

~~~powershell
& .\.venv\Scripts\python.exe -m compileall -q reyes_agent/performance_benchmark.py reyes_agent/routing
git diff --check HEAD~3..HEAD
git diff --name-only HEAD~3..HEAD
~~~

Expected: compile success, no whitespace errors, and only benchmark/routing/tests/docs paths plus required package files. Do not claim a clean whole worktree because unrelated shared edits exist.

- [ ] **Step 3: Run a bounded no-server health probe**

Run:

~~~powershell
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri 'http://127.0.0.1:8765/api/health' } catch { $_.Exception.GetType().Name }
~~~

Record unavailable if no local server is running. Do not launch a provider, browser, voice, or model merely to change that result.

- [ ] **Step 4: Append the next-investigation decision**

Use this fixed rule:

1. If post-fix greeting p95 exceeds 5 ms or maximum exceeds 100 ms after warmups, investigate routing/import state again.
2. Otherwise, if a live local server is available, measure loopback acknowledgement and first-token trace completeness.
3. Otherwise, benchmark the next deterministic local target from Event Bus, worker queue, scheduler, or Workspace panel throughput before modifying it.

- [ ] **Step 5: Commit**

~~~powershell
git add docs/performance/optimized.md
git commit -m "test(perf): verify routing hot-path delivery"
~~~

## Plan Self-Review

- **Spec coverage:** Tasks 1 and 3 create reproducible distributions and before/after reports. Task 2 fixes the proven model-load regression without replacing the router. Task 4 preserves bounded diagnostics and chooses the next stability/voice/UI investigation only from evidence.
- **Intentional deferrals:** live voice, TTS, browser, provider, app startup, network chaos, dependency research, and long soak require a live resource or a newly measured deterministic target. They remain unavailable, not fabricated.
- **Placeholder scan:** Every task names files, interfaces, test cases, expected failure/pass behavior, commands, and commit contents.
- **Type consistency:** Task 1 defines the benchmark interface consumed by Tasks 2 through 4. Task 2 defines is_ready and classify_if_ready before its only consumer uses them.
