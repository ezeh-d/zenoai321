# ZENO Phase 21 Performance Audit

Audit date: 2026-08-04  
Status: pre-change baseline (written before implementation changes)

## Scope and method

The launchers and import graph show that the active desktop product is
`Open REYES.bat` -> `pythonw -m reyes_agent.desktop_app` ->
`python -m reyes_agent.web`. The older root PySide application and the
`REYES (4)` / `gui old` trees are retained copies, not part of that startup
path. They were included in the static inventory but are not candidates for
runtime refactoring in this phase because changing inactive copies would add
risk without improving the product.

The audit covered:

- 63 Python files / 11,062 lines in the active package and tests.
- 231 Python files / 37,851 lines across the repository after excluding the
  virtual environment and bytecode.
- The active HTML/JavaScript polling, animation, SSE, and fetch paths.
- Cold imports in clean Python 3.12 processes, process RSS/thread count after
  import, import-time tracing, and static searches for blocking I/O, loops,
  threads, polling, subprocesses, SQLite access, and network calls.

## Measured baseline

| Measurement | Before Phase 21 |
|---|---:|
| Cold `import reyes_agent.web`, sample 1 | 9,223.7 ms |
| Cold `import reyes_agent.web`, sample 2 | 6,018.2 ms |
| Cold `import reyes_agent.web`, sample 3 | 6,892.1 ms |
| RSS immediately after web import | 110.3-110.7 MiB |
| OS threads immediately after web import | 11 |
| OpenAI SDK cumulative import cost in trace | ~2,150 ms |
| Provider module cumulative import cost in trace | ~4,716 ms |
| Whole web module cumulative import cost in trace | ~6,604 ms |
| Explicit `threading.Thread(...)` sites in active package | 13 |
| Indefinite `while True` loops in active package | 13 |
| Explicit `time.sleep(...)` sites in active package | 19 |
| Synchronous `requests` call sites in active package | 9 |
| SQLite connection sites in active package | 15 |
| Frontend repeating intervals | 9 |
| Frontend fetch call sites | 37 |

The import benchmark alone exceeds the requested total startup target. The
desktop window is created only *after* the server readiness wait, so current
time-to-first-window is necessarily worse than this baseline.

## Findings

### P0 - desktop startup is deliberately blocked before first render

`reyes_agent/desktop_app.py` starts the server and then calls
`_wait_for_server()` before `webview.create_window()`. That polling loop may
sleep for up to 30 seconds. During that entire period Windows has no ZENO
window to paint, which directly explains the frozen/not-responding launch
experience. The window must be created immediately and display a local,
lightweight boot document that switches to the server when health is ready.

### P0 - the web server eagerly imports every heavy subsystem

`reyes_agent/web.py` imports background services, the agent, both cloud SDKs,
the STT stack, and the complete tool registry at module import time.
`reyes_agent/tools/__init__.py` then imports every built-in tool and scans user
plugins for registration side effects. This pulls provider, browser, vision,
email, investment, knowledge, voice, and automation code into RAM before the
status endpoint can answer. Import tracing attributes about 4.7 seconds to the
provider path alone. These imports must be deferred to first use and heavy
plugin/tool registration must run away from the UI/event-loop path.

### P0 - blocking AI and speech work can occupy the server event loop

`voice_turn()` is declared `async`, but after reading the upload it runs
synchronous transcription and the full synchronous agent pipeline directly.
Unlike ordinary synchronous FastAPI handlers, this work is not automatically
offloaded to Starlette's thread pool. A long STT/provider/tool call can prevent
status, animation-supporting APIs, approvals, and other requests from being
served. All STT, AI, browser, OCR, indexing, plugin scanning, and desktop work
must execute through a bounded background runtime.

### P0 - request threads are unbounded and not cancellable

Each `/api/chat/stream` call creates a new daemon thread and an unbounded
`queue.Queue`. If several requests arrive while the global history lock is
held, those threads accumulate waiting for the lock. A disconnected SSE client
does not cancel the model call. Parallel delegation also creates a fresh
`ThreadPoolExecutor` per tool round. The active package has 13 raw thread
creation sites in total. ZENO needs one reusable, bounded, priority-aware worker
pool with task handles, cooperative cancellation, deadlines, retry policy,
progress events, queue backpressure, and observable metrics.

### P1 - startup starts all background systems at once

The FastAPI startup callback boots 13 specialist worker threads, restores the
session, starts session snapshots, model warmup, heartbeat, notification
polling, activity monitoring, Gmail polling, and proactive/dream checks before
startup completes. Several services each own another permanent polling thread.
The basic UI/status route should become ready first. Background services should
be scheduled in stages after readiness and share a scheduler/worker pool where
their semantics permit it.

### P1 - conversation and live-notification memory can grow without bound

The web `_history` list is never trimmed, even though provider requests use a
window and session recovery already restores only a tail. Over a long voice or
chat session, unused history remains resident. `notification_bus.subscribe()`
also creates an unbounded queue per tab; a stalled consumer can retain every
future notification until disconnect cleanup runs. Histories need a bounded
active window with archival, and all subscriber queues need a maximum size and
drop/coalesce behavior.

### P1 - browser recovery is incomplete

The Playwright controller correctly uses lazy loading and one persistent
profile, and most navigation/click calls have explicit timeouts. However, a
crashed browser/context stays cached, there is no health snapshot, no retry that
rebuilds a failed context, no cancellation seam, and no idle resource release.
Browser work is synchronous; safety currently depends on which caller happens
to invoke it. Execution must be routed through the background runtime and the
controller must invalidate/recreate broken contexts.

### P1 - agent lifecycle is partially implemented but over-provisioned

Agent workers correctly block on queues while idle and report real heartbeats,
which avoids busy waiting. However all 13 are created during startup, every
idle worker wakes every two seconds, and the requested explicit sleep/wake
states are absent. Boot must move to a post-readiness stage. Workers should
support sleep/wake/standby without consuming CPU, waking automatically when
work arrives.

### P1 - observability cannot prove the success criteria

The UI can calculate FPS in developer mode and exposes cheap CPU/RAM readings,
while agent and event subsystems have useful local metrics. There is no unified
profiler for worker queue, thread count, subsystem latency, event rate, browser
health, or memory trend. There is also no >200 ms event-loop/UI freeze detector
that records stacks and resources. Without those measurements the 8/24-hour
stability criteria cannot be verified.

### P2 - event persistence performs synchronous SQLite work per event

The durable event bus is bounded for subscribers and prunes stored rows, which
are good existing safeguards. Each publish still opens SQLite and writes
synchronously on the calling thread. Tool completion and agent state events can
therefore add disk latency to foreground work, and bursts can contend on the
shared database. Phase 21 should preserve durability while preventing event
fan-out from blocking; batched asynchronous persistence is the preferred
follow-up after higher-risk freeze causes are removed.

### P2 - polling is individually modest but fragmented

Heartbeat, activity, warmup, proactive checks, email, notification listening,
session recovery, and the frontend each maintain independent timers/loops. Most
sleep for sensible intervals, so none alone explains the freezes, but the
fragmentation increases threads, wakeups, duplicate lifecycle code, and makes
shutdown/testing unreliable. A shared scheduler consolidates the server-side
periodic jobs; frontend polling should pause when the document is hidden and
avoid overlapping fetches.

### Circular dependencies and duplicate architecture

The active agent/tool graph depends on deferred imports and registration side
effects (`agent` -> `tools` -> top-level heartbeat/activity modules, with some
paths importing the agent later). It currently imports successfully but is
fragile and prevents selective loading. The repository also contains several
older app copies. They are a maintenance risk, but removing them is outside
this compatibility-focused phase.

## Change plan and benchmark gates

1. Render the native window immediately and move server readiness polling into
   the boot page.
2. Make the web shell import lightweight and stage nonessential startup work.
3. Add a bounded managed worker pool and scheduler; migrate chat, voice,
   heartbeat fan-out, campaigns, and periodic services where safe.
4. Bound/archive conversation history and bound live event queues.
5. Add browser health/recovery, explicit agent sleep/wake states, unified
   performance snapshots, latency recording, and freeze logs.
6. Add fast stress tests for queue pressure, cancellation, retry, event bursts,
   history bounds, scheduler stability, and resource trends. Long soak tests
   will be parameterized so 8-hour and 24-hour runs can be executed without
   making the normal test suite take a day.
7. Re-run cold-import, memory/thread, queue/event throughput, and focused test
   benchmarks. A change is retained only when behavior stays compatible and
   the relevant metric improves or adds a missing safety bound.

## Explicit limits of this audit

An 8-hour and 24-hour soak cannot be completed inside a single interactive
change session. This phase will provide the automated soak harness and run its
short validation mode; the full-duration acceptance run remains an operational
release gate. GPU usage is platform/driver dependent and must report
"unavailable" when no supported local telemetry provider exists rather than
inventing a value.

## Implemented Phase 21 changes

### Startup and lazy loading

- The desktop launcher now creates a native ZENO boot window immediately. Its
  server readiness probe runs through pywebview's background callback and only
  replaces the boot document with the panel after `/api/status` answers; the
  window no longer waits synchronously before it exists.
- `reyes_agent.web` now imports only the lightweight HTTP shell at process
  start. Agent, provider SDKs, the tool registry, plugins, and STT are loaded
  by the background task that actually needs them.
- Server startup starts only the managed runtime/scheduler and an event-loop
  probe. Session restore, agent workers, polling services, warmup, and idle
  cleanup are staged after the HTTP shell is available.

### Bounded execution and lifecycle management

- Added `worker_pool.py`: reusable bounded priority workers with queue
  backpressure, cooperative cancellation, deadlines, retry/backoff, progress,
  error isolation, and live metrics. Voice work has the highest priority,
  followed by live executive turns, missions, agents, and maintenance.
- Added `scheduler.py`: one non-overlapping periodic scheduler replaces the
  heartbeat, activity, warmup, proactive, email, notification, session, and
  resource polling loops.
- Streaming and non-streaming chat, voice STT/AI, API heartbeat calls,
  heartbeat fan-out, campaigns, and parallel agent delegation now use the
  managed runtime rather than creating request-specific threads/executors.
- Agent workers support true blocking sleep/wake while retaining live thread
  identity. Idle workers are slept by the resource sweep and wake on submit.
- Conversation history is capped at 120 active messages (configurable) and
  archives older full turns. Notification and speech queues are bounded.

### Browser, event, memory, and freeze safeguards

- The persistent Playwright context has a default deadline, crash invalidation,
  health reporting, and idle release while preserving the on-disk profile.
- The event bus now uses a bounded single writer and batched SQLite commits;
  publish/fan-out no longer performs schema/index setup and disk I/O on the
  foreground caller. Event persistence queue pressure is observable.
- Added a unified performance snapshot: process/system CPU, RAM/RSS, thread
  count, worker queue, scheduler jobs, agent state, event rate/backlog,
  browser health, latency percentiles, memory trend, and honest GPU
  availability.
- Added a server event-loop probe plus a lightweight visible-WebView watchdog.
  Stalls over 200 ms write timestamp, duration, CPU/RSS, thread stacks,
  subsystem/source, and available renderer details to a size-rotated JSONL
  freeze log. The existing developer overlay now displays the measured
  profiler values without altering the normal UI.

## Post-change validation

| Measurement | Before | After |
|---|---:|---:|
| Cold `import reyes_agent.web` | 6,018-9,224 ms | 903-1,823 ms |
| Median cold web import | 6,892 ms | 1,184 ms |
| RSS immediately after web import | 110.3-110.7 MiB | 59.8-60.1 MiB |
| Heavy agent/provider/tools/STT loaded at web import | Yes | No |
| Raw thread creation sites in active package | 13 | 6 bounded/persistent runtime roles |
| 250-event durable publish regression | Not practical (per-event SQLite setup) | passes in <1 second |
| 100 missions + 1,000 events smoke soak | Not available | passes; 4/4 workers alive; 60-message history cap; +1.79 MiB RSS in 2 s |

The native window’s first render is now independent of HTTP readiness, which
removes the original 30-second pre-window wait. An isolated HTTP readiness
smoke sample was variable on this workstation (3.34 s and 4.99 s), so this
report does **not** claim the backend itself has met the hard <3 s target yet.
It is an environment/release gate to remeasure on the packaged desktop build;
the user-visible window remains immediate while the server initializes.

Completed offline validation:

- `python -m compileall -q reyes_agent tests`
- `python tests/test_phase21_runtime.py` — 7 passed (priority, retry,
  cancellation, scheduling, bounded history/notifications, event batching,
  freeze records)
- `python tests/stress_phase21.py --profile smoke --duration 2` — 100
  simulated missions and 1,000 durable events passed
- Existing direct tests: `tests/test_memory.py` and `tests/test_new_features.py`
  passed; the latter emitted pre-existing model-provider quota/fallback logs
  despite its assertions passing.

Release-soak commands (offline, no external provider/browser calls):

```powershell
.venv\Scripts\python.exe tests\stress_phase21.py --profile 8h
.venv\Scripts\python.exe tests\stress_phase21.py --profile 24h
```

The soak harness explicitly reports browser automation as skipped unless it is
run against a controlled local Playwright target. That browser integration run
is still required for full acceptance; no synthetic browser success is claimed.

## Follow-up: real browser, voice, and desktop verification

The controlled Playwright requirement was subsequently completed. A real
headless Chromium run exposed a concrete remaining failure: a persistent
`playwright.sync_api` context was opened on one general worker, then read on a
different worker, failing with `Cannot switch to a different thread`. This was
corrected by adding a single-worker, bounded browser runtime. All browser page
operations now run on its owning worker; diagnostics only read controller
metadata and never touch the sync API object cross-thread.

| Measurement | Result after final correction |
|---|---:|
| Child server `/api/status` readiness | 3,521.5 ms |
| Real Chromium `browser_open` + separate-worker `browser_read` | Passed; 1 browser worker, 0 backlog/failures |
| Slow browser navigation cancellation returned to caller | 40.1 ms |
| Real cached-audio STT + agent response | 20.08 s; 31 status probes, max 27.9 ms, zero errors |
| Real cache-miss ElevenLabs `/api/tts` | 7.03 s / 32,226 bytes; 9 status probes, max 14.1 ms, zero errors |
| Current short smoke soak | 100/100 missions, 1,000 events, 22 scheduler ticks, 4/4 workers, +1.76 MiB RSS in 2 s |

The native desktop boot shell is created before server launch/readiness polling
and reuses a healthy existing backend, eliminating the observed duplicate-port
startup race (`WinError 10048`). Backend readiness remains above the earlier
3-second release target on this machine; it is no longer on the visible UI
startup path. Full 8-hour/24-hour soaks and a manual target-machine check of
WebView2 orb animation/window movement remain release gates.
