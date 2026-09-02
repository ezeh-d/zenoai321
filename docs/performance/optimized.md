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
rendering, browser, network, process-startup, or full-app performance. The
benchmark itself is in-process and does not start or require a ZENO server,
voice device, provider, panel, or browser.

## Bounded live ZENO checks

The local server was available at `http://127.0.0.1:8765` (health HTTP 200).
After one unmeasured cache-warming request, 100 persistent-connection
`/api/health` requests that consumed the complete response measured p50
15.5255 ms, p95 29.1308 ms, p99 54.3276 ms, and maximum 126.7527 ms. The
server then reported `cached: true`, `ONLINE`, and 16 health checks.

An earlier 50-request PowerShell `Invoke-RestMethod` run measured p50 46.0010
ms, p95 188.8227 ms, and p99/maximum 838.6394 ms. That observation combines
a cold health snapshot and PowerShell JSON response conversion, so it is not
attributable to server work alone. The warmed persistent-client measurement is
the reproducible server-boundary result.

Twenty warmed, allow-listed `hello zeno` fast-path turns completed locally
without a provider, tool call, or shared conversation history. Their loopback
HTTP timing was p50 15.6477 ms, p90 34.4081 ms, p95 34.6472 ms, p99/maximum
133.4495 ms. Five initial fast-path turns also created five complete latency
timelines. As designed, those timelines reported zero `model_latency` and
`time_to_first_token` samples because no model was requested; absent is not
recorded as zero.

One bounded streamed provider probe was made only after health reported
providers available. Its complete timeline contained `model_requested` but no
`first_model_token`, and reported total latency 151.0841 s. The live model
router recorded connection failures across the configured fallback attempts
(Gemini, OpenAI, xAI, and local Ollama); no code change can honestly claim to
fix an unavailable provider/network path. The next provider-backed latency
measurement must wait for a successful real model stream, then record the
existing first-token mark rather than synthesizing one.

The next target must be selected from measured evidence:

1. Reinvestigate routing only if greeting p95 exceeds 5 ms or maximum exceeds
   100 ms after warmups.
2. A local server is available and loopback/trace completeness was measured;
   collect a first-token sample only after a provider-backed stream succeeds.
3. Until then, benchmark one deterministic local target from Event Bus, worker
   queue, scheduler, or Workspace panel throughput before changing it.
