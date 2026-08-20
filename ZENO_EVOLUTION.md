# ZENO Evolution Report

Date: 2026-08-20
Baseline: `fefc6eb`
Codex branch: `codex/zeno-evolution`

## Current Health

| Area | Evidence-backed state |
|---|---|
| Stability | Existing bounded workers, staged kernel, agent supervisor and circuit breakers are real. The full maintained Python suite passes 1,474 tests with one optional-backend skip. |
| Performance | A cold test-process import of `reyes_agent.web` registered 191 routes in 2,786.32 ms at 67.86 MiB RSS and 8 threads. The native shell starts independently, but gateway cold readiness remains worth profiling. |
| Voice | openWakeWord, Silero-style VAD seams, faster-whisper, sherpa-onnx and provider TTS fallbacks already exist. This pass deliberately did not replace them. |
| Agents | Fifteen primary specialists are registered lazily. One Council meeting is capped at four advisors; this pass makes that cap process-wide. |
| Memory | Local memory, Mem0 fallback seams, privacy policy and bounded retrieval exist. Forty-five direct SQLite connection sites remain an architectural consolidation risk, not a proven incident. |
| Automation | Managed Playwright/browser recovery and deterministic Windows seams already exist. No competing automation framework was added. |
| UI | Staged desktop startup and event-driven UI paths already exist. This pass did not touch Claude's presentation/UI work. |
| Security | The research crawler now validates all resolved IPv4/IPv6 addresses, blocks credentials/non-web ports, refuses redirects and closes bounded streams. |
| Maintainability | 505 Python modules / 76,639 lines are under test. There are 760 broad `except Exception` sites; many are deliberate isolation boundaries, but the volume makes silent-degradation audits an ongoing priority. |

## Current Ten Biggest Weaknesses

1. **Research SSRF validation — hardened here.** Prefix matching accepted
   `172.16/12`, `100.64/10` and integer-loopback DNS answers.
2. **Crawler redirect/stream safety — fixed here.** Requests followed redirects,
   early-capped streamed responses were not explicitly closed, and the final
   chunk could exceed the stated cap by 64 KiB.
3. **Provider first-use race — fixed here.** Thirty-two concurrent callers
   created 32 SDK clients and connection pools.
4. **Council thread multiplication — fixed here.** Ten concurrent four-advisor
   meetings created 37 provider worker threads.
5. **Piper configuration split — fixed here.** The documented voice router
   variable was `ZENO_PIPER_MODEL`, while direct TTS read `PIPER_MODEL`; owner
   configuration could silently select different models.
6. **Cold web registration cost — remaining.** Measured at 2.79 seconds and
   67.86 MiB in a clean test process. It is outside first native render but
   still delays backend readiness.
7. **Dependency reproducibility — remaining.** Twenty-seven of 30 runtime
   requirement lines are ranges rather than exact pins; native Windows/audio
   packages make an unreviewed lock-file conversion risky.
8. **SQLite ownership is fragmented — remaining risk.** Forty-five connection
   call sites raise migration, busy-timeout and WAL-consistency costs. No data
   corruption was observed, so a rewrite is not justified in this pass.
9. **Exception-policy consistency — remaining audit.** 760 broad catch sites
   include valid fault-isolation boundaries and some silent fallbacks. They
   need subsystem-by-subsystem review, not mass replacement.
10. **FastAPI lifecycle deprecation — remaining.** The maintained suite emits
   four warnings from `web.py`'s `on_event` startup/shutdown hooks.

## GitHub Discoveries

Scores are impact-to-risk for this Windows ZENO checkout, not popularity.

| Rank | Repository | Purpose / license | Score | ZENO relevance and risk | Decision |
|---:|---|---|---:|---|---|
| 1 | [OWASP/CheatSheetSeries](https://github.com/OWASP/CheatSheetSeries) | Security patterns, CC-BY-SA-4.0 | 9.8 | Directly exposed crawler gaps; guidance says validate resolved addresses and disable redirects. | **Integrated pattern**, no copied implementation. |
| 2 | [benfred/py-spy](https://github.com/benfred/py-spy) | Low-overhead sampling profiler, MIT | 9.3 | Windows-capable and out-of-process; ideal for the next real host freeze. | Recommend as optional diagnostic, not runtime dependency. |
| 3 | [microsoft/playwright-python](https://github.com/microsoft/playwright-python) | Browser automation, Apache-2.0 | 9.1 | Already the authoritative browser base; current release remains active. | Keep and test; do not add another browser runtime. |
| 4 | [giampaolo/psutil](https://github.com/giampaolo/psutil) | Process metrics, BSD-3-Clause | 9.0 | Already powers Windows CPU/RAM/thread evidence. | Keep existing integration. |
| 5 | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | Portable VAD, MIT | 8.9 | Strong local VAD and ONNX support; already represented in ZENO's voice seams. | Keep; benchmark real owner audio before tuning. |
| 6 | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Offline speech suite, Apache-2.0 | 8.8 | Windows/offline STT, VAD, TTS and speaker tools; already integrated lazily. | Keep existing seam. |
| 7 | [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) | Local wake word, Apache-2.0 | 8.7 | Correct low-idle architecture and ONNX support on Windows. | Keep existing single listener. |
| 8 | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Optimized Whisper, MIT | 8.7 | Existing local STT fallback; model size/CPU remain the cost. | Keep lazy, never preload. |
| 9 | [gaogaotiantian/viztracer](https://github.com/gaogaotiantian/viztracer) | Cross-platform timeline tracer, Apache-2.0 | 8.2 | Excellent experiment tool for thread/async timelines; higher overhead than sampling. | Defer to an opt-in diagnostic experiment. |
| 10 | [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) | Standard traces/metrics, Apache-2.0 | 8.0 | Mature, but ZENO already has a redacted local tracer and does not need always-on export. | Defer until a concrete exporter is selected. |
| 11 | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Official MCP SDK, MIT | 8.0 | Already used. Recent security advisories make version review and origin/auth tests more valuable than more servers. | Keep one SDK; track supported release/security fixes. |
| 12 | [mem0ai/mem0](https://github.com/mem0ai/mem0) | Agent memory, Apache-2.0 | 7.9 | Existing optional backend and legacy fallback match ZENO's needs. It adds model/vector costs if overused. | Keep optional; no duplicate memory store. |
| 13 | [microsoft/UFO](https://github.com/microsoft/UFO) | Windows/device-agent patterns, MIT | 7.8 | Host→app-agent and UIA/API hybrid patterns are relevant, but importing the framework would duplicate ZENO's device runtime. | Study patterns only. |
| 14 | [jd/tenacity](https://github.com/jd/tenacity) | Retry library, Apache-2.0 | 7.7 | Mature bounded retry primitives, but ZENO already has provider, worker and breaker retry policies. Defaults can retry forever if misused. | Reject runtime addition; retain explicit native bounds. |
| 15 | [danielfm/pybreaker](https://github.com/danielfm/pybreaker) | Thread-safe circuit breaker, BSD-3-Clause | 7.6 | Good design reference; duplicative of model and watchdog breakers. | Reject dependency; compare semantics in tests. |
| 16 | [ijl/orjson](https://github.com/ijl/orjson) | Fast JSON, MPL-2.0/Apache-2.0/MIT | 7.3 | Could help event/dashboard serialization, but no measured JSON bottleneck exists. Bytes-return API adds migration risk. | Benchmark before considering. |
| 17 | [astral-sh/uv](https://github.com/astral-sh/uv) | Fast dependency tooling, Apache-2.0/MIT | 7.2 | Useful for reproducible developer installs; converting Windows native/audio dependencies needs a dedicated compatibility pass. | Defer to packaging work. |
| 18 | [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | Typed agent framework, MIT | 6.8 | Strong eval/durable patterns, but would compete with ZENO's kernel, provider seam, tools and approvals. | Reject framework integration; borrow testing ideas only. |
| 19 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Durable graph agents, MIT | 6.3 | Capable but creates a second orchestration/state runtime and migration burden. | Reject for current architecture. |
| 20 | [Rikorose/DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) | Neural noise suppression; model/license audit required | 5.9 | Quality potential, but heavier inference, older activity and unclear asset licensing are poor fits for limited Windows hardware without an A/B corpus. | Defer/reject until measured offline. |

## Experiments

The raw, deterministic reproductions live in
`experiments/zeno_evolution/README.md` and
`tests/test_evolution_hardening.py`.

### 1. Safe public fetch boundary

Before: private `172.16/12`, carrier-grade NAT and integer-loopback targets
were accepted. Redirects followed automatically.
After: every A/AAAA result must be globally routable, mixed answers fail,
credentials and non-web ports fail, redirects fail, robots fetches do not
redirect, streams/sessions close deterministically, and byte caps are exact.

### 2. Provider client single-flight

Before: 32 simultaneous first calls created 32 SDK clients in 51.82 ms.
After: one shared client was created in 36.99 ms. No provider/network request
was made during the benchmark.

### 3. Process-wide Council bulkhead

Before: ten simultaneous four-advisor meetings created 37 provider workers and
finished the synthetic burst in 183.31 ms.
After: the same burst used four workers and took 530.61 ms. Normal meetings
still run four advisors in parallel. The longer overload latency is intentional:
work queues instead of launching forty provider calls and exhausting CPU/socket
budgets.

## Improvements Integrated

- robust resolved-address and URL validation for research (all DNS answers
  must be public; DNS rebinding remains a residual transport-level risk);
- redirect refusal for page and robots requests;
- exact response limits and deterministic response/session cleanup;
- thread-safe SDK module/client lazy initialization;
- one lazy reusable four-worker Council executor;
- Council executor cleanup in the authoritative kernel shutdown path;
- one authoritative `ZENO_PIPER_MODEL` setting with legacy fallback;
- complete environment-variable documentation with blank secret fields only;
- eight focused regression tests and durable benchmark notes;
- no new runtime dependency.

## Benchmarks

| Measurement | Before | After |
|---|---:|---:|
| Provider factories under 32 first callers | 32 | 1 |
| Distinct provider clients | 32 | 1 |
| Provider initialization wall time | 51.82 ms | 36.99 ms |
| Council provider workers under 10 callers | 37 | 4 |
| Synthetic Council overload wall time | 183.31 ms | 530.61 ms |
| Previously accepted private target classes | 4 tested | 0 |
| New runtime packages | — | 0 |

## Rejected Ideas

- **Replacing ZENO with PydanticAI/LangGraph/UFO:** duplicates the executive,
  scheduler, state, approvals and tools; migration risk exceeds benefit.
- **Adding Tenacity/PyBreaker/pyresilience:** ZENO already has bounded retry and
  circuit-breaker semantics. Another policy layer would make attempts harder to
  reason about.
- **Always-on OpenTelemetry/VizTracer:** adds CPU/data movement before a real
  exporter or incident question exists. Use opt-in diagnostics.
- **Memray:** excellent profiler, but its maintainers explicitly do not support
  Windows; it is unsuitable for this host.
- **DeepFilterNet/Piper replacement:** neural quality alone does not justify
  CPU, model and licensing costs. Existing lazy voice fallbacks stay intact.
- **orjson without a benchmark:** ZENO has no measured JSON serialization hot
  spot; changing return types throughout the API would be churn.

## Recommended Next Work

1. Capture one real unresponsive host with `py-spy dump/record`, correlate it
   with ZENO's heartbeat incident, and fix only the measured stack.
2. Profile the 2.79-second web import by module and move route groups that are
   genuinely optional behind lazy registration without changing API behavior.
3. Convert FastAPI startup/shutdown to a lifespan handler and verify all cleanup
   hooks exactly once.
4. Audit broad exception handlers one subsystem at a time, starting with
   provider, browser and voice boundaries; require an event/log for degraded
   behavior.
5. Create a reviewed Windows dependency lock strategy, preserving optional
   native/audio markers rather than blindly pinning the current machine.
6. Standardize SQLite connection configuration and migrations only after a
   contention/consistency test identifies real divergence.

## Final Verification

| Check | Result |
|---|---|
| Full maintained Python suite | **1,474 passed, 1 skipped**, 4 existing FastAPI deprecation warnings, 389.23 s |
| Focused live-config design/voice/hardening suite | **53 passed, 1 skipped** |
| Earlier focused evolution/architecture suite | **108 passed** |
| Environment contract | **274 documented / 197 read / 0 missing** |
| Python package integrity | `pip check`: **no broken requirements** |
| Python compilation | `compileall`: **passed** |
| ZENO Anywhere web | build plus static build tests: **passed** |
| Git whitespace validation | `git diff --check`: **passed** (line-ending notices only) |

The skipped test requires an optional local/provider backend. No live model or
browser claim is inferred from it. The remaining warnings are the known
FastAPI `on_event` migration listed above.

### Honest residual limits

- Public-address validation happens immediately before the HTTP client opens
  the connection, but the client resolves the hostname again. A hostile domain
  capable of DNS rebinding is therefore a residual risk until the transport
  pins the validated IP while retaining TLS hostname verification.
- The full run used the owner's ignored `.env` and ignored live MCP registry;
  neither was copied, printed or staged.
- No real provider call, owner microphone recording, or long-duration Windows
  GUI soak was performed by this evolution pass. Those require explicit live
  interaction and should not be simulated.
