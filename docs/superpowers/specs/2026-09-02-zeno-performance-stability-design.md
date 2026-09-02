# ZENO Performance and Stability Engineering Design

**Date:** 2026-09-02  
**Status:** Proposed and approved for spec review  
**Scope:** Native ZENO runtime performance, responsiveness, bounded resource
use, recovery, and evidence-based diagnostics.

## 1. Objective

Make ZENO measurably more responsive and stable without introducing a second
runtime, faking progress, weakening safety controls, or rewriting working
subsystems. Every production change must target a measured bottleneck and
include a repeatable benchmark or regression test.

The program is intentionally staged. The repository contains a mature Python
runtime with existing latency tracing, capability routing, a managed worker
pool, bounded Event Bus queues, a scheduler, recovery watchdogs, resource
governance, and a Universal Workspace. Replacing those systems would create
more risk than it removes. This work strengthens their existing boundaries.

## 2. Baseline Evidence and Constraints

### Current shared worktree

The base checkout is shared and contains unrelated tracked changes to package,
presentation, web, and tool files, plus unrelated untracked research folders.
This work must neither reset, clean, overwrite, stage, nor commit those files.

### Evidence gathered on this machine

The deterministic capability router already prevents the historic full-schema
payload on explicit commands. A 500-sample measurement found these current
tool-exposure counts and p95 router times:

| Request | Tools exposed | p95 router latency |
|---|---:|---:|
| What time is it? | 12 | 0.53 ms |
| Open Chrome | 12 | 0.41 ms |
| Search YouTube for football highlights | 12 | 0.93 ms |
| Remember a fact | 16 | 0.60 ms |
| Look at my screen | 8 | 0.46 ms |
| Fix this Python traceback | 9 | 0.51 ms |

Ordinary conversation is not yet safe on the same path. For `Hello ZENO, how
are you?`, the optional semantic intent fallback produced p50 26.58 ms, p95
51.80 ms, p99 85.97 ms, and a 64.89-second cold maximum. With the fallback
disabled in a separate process, the same request measured p50 0.24 ms and p95
0.49 ms. The cause is confirmed in `routing/capability.py`: a regex miss on a
short conversational request calls `IntentRouter.classify`, which initializes
and runs the sentence-transformer model by default. Explicit command matches
bypass that branch.

The selected existing performance and stability contracts passed: **112 tests
in 103.82 seconds**. No ZENO server was running at `127.0.0.1:8765`, so no
live desktop, provider, microphone, or browser timing is claimed in this
baseline.

### Existing observability to reuse

- `reyes_agent.latency` supplies bounded per-turn milestones, including
  first-token and first-audio timings.
- `reyes_agent.performance_monitor` records bounded latency samples, process
  resource usage, event-loop stalls, and renderer/host incident evidence.
- `reyes_agent.trace_engine` and `observability.tracer` provide correlation
  and redaction boundaries.
- `event_bus`, `worker_pool`, `scheduler`, `resource_governor`,
  `resource_manager`, and `health.watchdog` already own queuing, cancellation,
  admission, cleanup, and finite recovery responsibilities.

## 3. Goals and Non-goals

### Goals

1. Keep normal conversation and deterministic commands off heavyweight model
   initialization paths.
2. Produce repeatable cold and warm measurements with p50, p90, p95, p99,
   maximum, sample count, and failure rate.
3. Measure actual stage boundaries: command acknowledgement, routing,
   dispatch, first model token, first audio, panel state transition, queue
   delay, event-loop stalls, CPU/RAM, and recovery outcomes when each is
   available.
4. Bound background work, stale work, queue growth, resources, and retries so
   that interactive work remains responsive.
5. Exercise sustained load and service-failure behavior without emitting real
   messages, purchases, destructive actions, or browser automation.
6. Report unavailable physical or cloud measurements as unavailable rather
   than inventing a number.

### Non-goals

- No mass async rewrite, new parallel agent runtime, or replacement model
  gateway.
- No security-boundary, authentication, authorization, TLS, permission, or
  owner-trust weakening for speed.
- No automatic installation, model download, provider activation, external
  telemetry, or third-party repository cloning merely for benchmarking.
- No claim that synthetic voice tests prove a physical microphone, speaker,
  provider, or network result.

## 4. Selected Architecture: Evidence-first, Staged Retrofit

Three approaches were considered:

1. **Evidence-first retrofit (selected).** Reuse the current control plane,
   add a reproducible benchmark harness, eliminate proven hot-path blockers,
   and audit each subsequent bottleneck before changing it. This minimizes
   regressions and gives each improvement a comparable before/after result.
2. **New central performance runtime.** Build a universal scheduler, metrics
   pipeline, resource manager, and router. It would duplicate existing
   ownership and substantially increase integration and race-condition risk.
3. **Dependency-first replacement.** Add profiling, async, model, or storage
   libraries up front. This cannot prove a runtime improvement and risks
   startup, package, and Windows compatibility regressions.

The selected design keeps each authority singular and changes a boundary only
when evidence identifies it as the cause.

## 5. Component Design

### 5.1 Performance benchmark and report

Add a developer-only benchmark command and a structured, versioned result
format. It will run deterministic local measurements by default and accept an
explicit loopback-server target for live measurements. Each result identifies
the environment, mode, sample count, result distribution, failures, and
unavailable stages.

The harness will cover:

- Python import/cold-start and warm-start budgets for the relevant runtime
  path;
- capability routing for ordinary conversation, deterministic commands,
  ambiguous paraphrases, and controlled expansion;
- in-process memory lookup and safe tool dispatch fixtures;
- workspace panel state operations and Event Bus publication throughput;
- worker queue delay, cancellation, and bounded retry behavior;
- process CPU, RSS, threads, handles where Windows exposes them, and
  event-loop/renderer stall evidence;
- optional loopback API acknowledgement and streamed first-token checks;
- optional live voice and TTS marks only when real devices and configured
  providers produce them.

Results will feed `docs/performance/baseline.md` and
`docs/performance/optimized.md`. A metric unavailable on this machine remains
explicitly labelled unavailable; it is never substituted with an estimate.

### 5.2 Capability-routing hot path

`routing.capability.tools_for` will remain deterministic and bounded. The
semantic intent router remains optional, but it must not initialize a sentence
transformer or execute embedding inference on normal conversation.

The router will expose a non-initializing readiness check. On a regex miss,
the capability path may consult semantic routing only when that resource is
already warmed and the message is a plausible command/ambiguity candidate.
Otherwise it returns the existing tiny essential tool set immediately. A
controlled mid-turn `enable_tools` expansion remains the correctness fallback
for a missed capability. The semantic model may be warmed through existing
low-priority scheduling only when explicitly enabled and only after
interactive work is idle; it is never loaded at startup merely because the
package is installed.

This preserves paraphrase support without making greetings, ordinary chat, or
the first request pay a model-load tax.

### 5.3 Trace completeness and diagnostics

The benchmark will audit the existing `latency` marks rather than create a
parallel telemetry stream. It will identify missing boundary marks for each
tested turn and record stage timing only when both endpoints are observed.

The existing diagnostics surfaces will be extended only if a single compact
performance summary cannot already be served. The user-facing default remains
quiet. Detailed traces, queue depths, recovery history, and resource samples
appear only through developer/performance diagnostics and the existing System
or Workspace panels.

### 5.4 Background work, queues, and recovery

The audit examines the current `worker_pool`, `scheduler`, `event_bus`,
`resource_governor`, and watchdog contracts. It will look specifically for:

- interactive work queued behind background jobs;
- queues or subscriber feeds that do not coalesce/drop stale telemetry;
- unbounded retention of task, timer, listener, audio, browser, or retry
  objects;
- synchronous work on an async request loop;
- restart/retry loops that do not respect the existing circuit-breaker or
  cancellation state;
- resource cleanup that initializes optional subsystems while diagnosing a
  failure.

Any corrective change keeps existing priorities and service boundaries. Heavy
work moves to existing managed workers only when profiling shows it blocks the
main/UI/async path. Locks are not held across network, provider, TTS, browser,
or subprocess waits.

### 5.5 Voice, UI, and live-service measurement

Voice and UI improvements are a measured follow-on, not assumptions made from
source inspection. The existing trace timeline provides the intended stages:
endpoint detection, STT final, intent/context, model request/first token,
sentence readiness, TTS request/first audio, and response completion.

The implementation will first prove trace coverage through deterministic
tests. A configured local loopback test server may then establish actual API
acknowledgement and streaming behavior. Physical microphone, wake-word,
speaker, cloud STT/TTS, GPU, browser, and provider latency require their
respective real resource to be available; the benchmark records an explicit
skip reason otherwise.

Hidden/minimized Workspace panels remain projections: they may reduce visual
refresh work, but never cancel the underlying user task. The Mini Orb retains
its existing lightweight behavior.

## 6. Failure Handling and Safety

- Every benchmark has bounded timeouts and reports a failure reason.
- Benchmark fixtures use safe, local, read-only or test-double operations;
  soak testing does not send communications or open external applications.
- Semantic routing failure falls back to the deterministic route; it cannot
  block or fail a chat turn.
- Provider/network failures preserve local commands and report their degraded
  state through the current health model. They do not trigger a global restart.
- Diagnostic data remains bounded and redacted. No API key, token, password,
  full conversation, or raw private log is added to a report.

## 7. Testing and Acceptance Criteria

### Automated contracts

- Add a regression proving that the cold semantic model is never initialized
  by an ordinary conversational request.
- Add benchmark-format tests for complete statistics, skip reasons, and
  reproducibility.
- Retain the existing capability-router budget and <15 ms deterministic
  routing contract for explicit commands.
- Retain conversation-state, latency, worker, Event Bus, resource, health,
  Workspace, voice wiring, and relevant UI contracts.
- Add targeted load/soak tests with bounded counts and report process/resource
  trends rather than treating a single sample as a leak conclusion.

### Completion criteria

1. The greeting cold-stall regression is eliminated with before/after
   evidence.
2. Each implemented change has a benchmark comparison and no relevant
   regression failure.
3. The report distinguishes local measurements, live measurements, and
   unavailable hardware/provider measurements.
4. The system remains responsive when background jobs, recovery work, and
   event publication are active.
5. No unrelated shared-worktree file is modified by this effort.

## 8. Phased Delivery Order

1. Build benchmark/report infrastructure and freeze the current baseline.
2. Fix the confirmed capability-routing hot-path regression with test-driven
   development and compare results.
3. Audit and address the next measured queue, event-loop, resource, or
   initialization bottleneck.
4. Run loopback/live diagnostics where resources are present; improve only
   measured voice/UI/service delays.
5. Run bounded load, recovery, and soak scenarios; fix any confirmed
   regression one root cause at a time.
6. Publish the final performance report, exact commands, tests, limitations,
   and files changed.

## 9. Dependency Research Policy

`py-spy`, Scalene, `psutil`, `aiohttp`, `aiofiles`, `orjson`, `msgspec`,
`faster-whisper`, `whisper.cpp`, LiteLLM, OpenTelemetry, `uv`, and Ruff are
research candidates only. Before any use, the implementation will document
maintenance, Windows support, license, integration cost, existing capability
overlap, and the specific measured bottleneck it addresses. No dependency is
installed or enabled unless it wins that evaluation and has a narrowly scoped
test plan.
