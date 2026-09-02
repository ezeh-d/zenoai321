# ZENO Routing Hot-Path Result — 2026-09-02

## Change under test

Normal conversation now remains on the deterministic capability path. The
optional semantic router is consulted only for command-shaped requests and
only if it was already initialized. The change does not load a model, start a
service, or contact an external provider.

## Command

```powershell
& .\.venv\Scripts\python.exe -m reyes_agent.performance_benchmark --router-only --iterations 500 --warmups 5
```

The benchmark clears only capability follow-up context before each route. It
uses `time.perf_counter_ns`, discards five warmups per case, and reports every
measured action failure.

## Result

All 3,500 measured route calls completed successfully; every case reported a
zero failure rate.

| Case | p50 | p95 | p99 | Maximum | Tools exposed |
|---|---:|---:|---:|---:|---:|
| `Hello ZENO, how are you?` | 0.1350 ms | 0.2777 ms | 1.6153 ms | 2.4387 ms | 2 |
| `What time is it?` | 0.1897 ms | 0.5197 ms | 1.8513 ms | 2.6086 ms | 12 |
| `Open Chrome` | 0.1383 ms | 0.3372 ms | 1.4824 ms | 2.5228 ms | 12 |
| `Search YouTube for football highlights` | 0.2215 ms | 0.5730 ms | 2.0762 ms | 3.2979 ms | 12 |
| `Remember that blue is my test colour` | 0.3348 ms | 0.7061 ms | 2.5792 ms | 3.1443 ms | 16 |
| `Look at my screen` | 0.3196 ms | 1.4613 ms | 4.6403 ms | 10.0262 ms | 8 |
| `Fix this Python traceback` | 0.4417 ms | 1.8162 ms | 4.3334 ms | 9.3265 ms | 9 |

The greeting's p95 dropped from 51.7992 ms to 0.2777 ms, and its measured
maximum dropped from 64,891.2985 ms to 2.4387 ms for the respective runs.
This comparison specifically removes the lazy semantic-model initialization
from normal chat; it is not a general claim about every ZENO subsystem.

## Test evidence

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_performance_benchmark.py
# 4 passed in 1.01s

& .\.venv\Scripts\python.exe -m pytest -q tests/test_intent_router.py tests/test_capability_router.py tests/test_fast_intelligence.py tests/test_conversation_state.py
# 105 passed in 8.85s
```

## Limits and next measurement rule

This router benchmark does **not** prove STT, TTS, LLM/provider, UI,
rendering, browser, network, process-startup, or full-app performance. It ran
without a local ZENO server, voice device, provider, panel, or browser.

The next target must be selected from measured evidence:

1. Reinvestigate routing only if greeting p95 exceeds 5 ms or maximum exceeds
   100 ms after warmups.
2. If a local ZENO server is available, measure loopback acknowledgement and
   first-token trace completeness.
3. Otherwise, benchmark one deterministic local target from Event Bus, worker
   queue, scheduler, or Workspace panel throughput before changing it.
