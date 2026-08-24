# ZENO Phase 22 — Validation, Load Testing, and Cleanup

Date: 2026-08-04  
Scope: active desktop path from `ROADMAP.md`: `Open REYES.bat` →
`reyes_agent.desktop_app` → `reyes_agent.web`.

## Confirmed fixes applied

1. **Agent restart could leak duplicate workers.** `restart()` replaced an
   agent's stop event before its old thread exited. The old loop could observe
   the replacement event and remain alive. Restart now signals and joins the
   old worker first, preserves real queued tasks, removes only stale stop
   sentinels, and defers a replacement while a task is still running.
2. **Windows child shutdown could lose the final session snapshot.**
   `Popen.terminate()` is a hard process termination on Windows and does not
   reliably run FastAPI shutdown handlers. The desktop owner now makes a
   loopback-only `prepare-shutdown` durability handshake before terminating its
   own child. It cannot affect a server the window did not launch.
3. **Desktop/server logs and parent file handles could grow indefinitely.**
   Desktop logs now rotate at 2 MiB (one backup), and the parent's duplicate
   child stdout/stderr handles are closed immediately after `Popen`.

No feature work or completed roadmap phase was rebuilt.

## Validation results

| Scenario / requirement | Result |
|---|---|
| Cold server startup | Passed repeatedly; native boot shell remains independent of backend readiness. Prior measured backend readiness was 3,521.5 ms. |
| 30 consecutive real voice requests | **30/30 HTTP 200**, each with non-empty Deepgram transcript and agent reply. Mean 3,825.3 ms; median 2,835.0 ms; p95 9,206.0 ms; max 13,917.4 ms. The test was split after 28 calls solely because the test runner has a 120-second command ceiling. |
| Voice responsiveness | During the monitored final voice/TTS batch, 34 `/api/status` probes had zero errors; maximum 34.0 ms. |
| ElevenLabs speech | Real cache-miss `/api/tts` returned 44,347 bytes in 2,386.4 ms. Controlled timeout test passed without worker failure or cache write. |
| Browser automation | 20 real Playwright actions passed in 2,609.4 ms total. Browser close/reopen/read passed. |
| Browser cancellation/recovery | Phase 21 slow-navigation cancellation returned in 40.1 ms; Phase 22 close/reopen passed. |
| Multi-agent delegation | 10 finite tasks completed across 10 persistent specialists; all 13 agents alive and healthy. |
| Agent restart | Live ARIS restart passed. The restart-race regression test proves no duplicate `agent-*` thread remains. |
| Mission execution | 10 test-local durable missions created and updated successfully. |
| Event Bus | 1,000 events published in 11.3 ms, fully flushed/persisted; deliberately slow subscriber capped at 500 entries. |
| Agent Monitor / Situation Room | 20 open/close cycles each; both overlays closed afterward. Exactly 40 immediate panel fetches and no extra interval polls after 4.5 s. |
| Orb renderer cadence | 53 FPS in headless Chromium. This is not a substitute for native WebView2 measurement. |
| Desktop automation | Read-only process inventory returned 10 entries in 1,076.8 ms. Foreground-window API is unavailable in this non-interactive test host. |
| Shutdown during active task | Voice request was interrupted as expected; child port released in 3.8 ms and no server process remained listening. |
| Session restoration | After a real voice turn and controlled desktop shutdown, restart restored 55 messages and reported a clean shutdown. |
| Idle resources | A 15-second post-warm-up process sample measured 0.0% CPU, zero worker/event queue depth, no thread CPU accumulation, 33 threads, and 98.8 MiB RSS. |

## Measurements and interpretation

Phase 21 reduced cold `reyes_agent.web` import from 6,018–9,224 ms / about
110 MiB RSS to 903–1,823 ms / about 60 MiB. Under the fully staged server,
steady idle RSS was about 99 MiB with 33 threads; this includes the real agent
runtime and service stack. An earlier two-point sample rose during staged
warm-up (77.2 → 98.0 MiB), so it is not treated as a memory leak. A subsequent
15-second CPU trace showed no accumulated thread CPU time. A 35-second sample
varied by +2.0 MiB without thread or queue growth; that is insufficient to
classify as a leak.

Worker and event queues were zero at idle. The scheduler had seven bounded,
non-overlapping jobs; none was running during the CPU trace. The apparent
100.8% instantaneous CPU reading from one earlier performance snapshot was not
reproduced by the 15-second process/thread CPU trace and is treated as sampling
noise, not a confirmed idle polling defect.

## Regression protection

`tests/test_phase22_stability.py` now covers:

- duplicate-free agent restart and failed-agent isolation;
- bounded worker growth and cleanup;
- non-blocking Event Bus publication with a slow subscriber;
- desktop startup ownership boundary;
- controlled provider and ElevenLabs failures;
- loopback-only shutdown durability handshake;
- bounded desktop log rotation.

The existing Phase 21 runtime suite still covers priority, cancellation,
retry, scheduler overlap, event batching, browser worker affinity, bounded
history/subscribers, and freeze records.

## Tests run

- `python -m compileall -q reyes_agent tests` — passed.
- `python tests/test_phase22_stability.py` — 9 passed.
- `python tests/test_phase21_runtime.py` — 8 passed.
- `python tests/stress_phase21.py --profile smoke --duration 10` — passed:
  100 missions, 1,000 events, 101 scheduler ticks, 4/4 test workers alive,
  +1.82 MiB RSS in 10 seconds.
- Live HTTP, TTS, browser, dashboard, worker restart, session recovery, and
  controlled shutdown tests summarized above.

## Honest unresolved limits / release gates

- The one-hour idle observation has now been completed and is reported in the
  final addendum below. The longer 8-hour/24-hour profiles remain release gates;
  one hour cannot rule out every slow resource leak.
- Native Windows WebView2 orb FPS, window drag/click responsiveness, and the
  absence of the OS-level “Not Responding” banner require a manual target-PC
  run. Headless Chromium measured 53 FPS only.
- Provider/ElevenLabs failure tests use controlled failing seams. Real requests
  were successful, but a black-holed external network endpoint was not used.
- A cancellation request returns control immediately, while a synchronous
  Playwright/SDK call finishes only at its configured I/O timeout; Python cannot
  safely kill that third-party call mid-frame.

## Final validation addendum — 2026-08-12

This pass revalidated the current, much larger checkout rather than relying on
the August 4 result. It did not rebuild Phase 21 or add a product feature.

### Confirmed defects fixed

1. The recent fast-chat latency path stopped injecting the bounded local
   awareness and anticipation context. That made an ordinary conversation fast
   but context-blind. Fast chat still sends no tool schemas, but again receives
   those cached, provider-free directives.
2. Windows process-health sampling called `psutil.Process.open_files()`. During
   the complete suite, the native Windows handle walker raised an access
   violation while another thread closed a handle. ZENO now uses the cheap
   process handle count for leak trending and does not enumerate file handles.
3. Freeze instrumentation omitted the PID, active operation, current thread,
   worker/event queue depths and system CPU/RAM snapshot. Its worker lookup
   could also create the global pool while diagnosing a stall, and its published
   count was capped at the ten displayed records. Reports are now process
   attributable, cumulative and observational.
4. The opt-in frontend audit referenced `orbitTimer` outside its JavaScript
   closure. Normal rendering continued, but audit reporting stopped with a
   `ReferenceError`. The ring and Agent Space now expose small read-only audit
   states through their existing public controllers.
5. One workflow regression test inherited a fake foreground application from a
   previous test. The production pause-after-step logic was correct; the test
   now establishes its own initial foreground state.
6. Windows notification polling created a fresh asyncio loop for every WinRT
   request. Timed-out WinRT wrappers could retain native handles and development
   mode exposed allocator corruption. Notification polling now uses one owned
   loop thread, shields the native completion from cancellation, prevents
   overlapping requests and releases the owning-loop wrappers during shutdown.
   Sixty real polls held 333 handles at calls 1, 10, 30 and 60.
7. The managed worker history retained 100 completed `TaskHandle` objects. Each
   handle owned Windows synchronization primitives, producing a bounded but
   unnecessary plateau of roughly 300 handles. History now stores only ten
   lightweight redacted failure summaries. A 500-task run stayed at 288 handles
   at tasks 100, 250 and 500, then fell to 268 after shutdown.
8. A conversation-continuity test replaced the shared `time.time` function and
   restored the already-replaced reference, freezing wall-clock time for later
   tests. The test now uses pytest-scoped patching, and job deadlines use
   `time.monotonic()` so wall-clock adjustment cannot hang timeout handling.

### Fresh measured results

| Scenario | 2026-08-12 result |
|---|---|
| Cold backend readiness | 3,381.1 ms to `/api/performance`, 69.6 MiB RSS, 15 threads and zero startup freezes. The native shell still renders before backend readiness. |
| Repeated command path | 30/30 non-empty local fast-path responses; mean 54.68 ms, median 25.51 ms, p95 291.12 ms, max 301.76 ms. This is command routing, not a new STT corpus. The prior 30/30 real Deepgram result remains the real voice-request evidence. |
| Browser automation | 21/21 real browser actions including close/reopen recovery; 175 concurrent status probes, zero errors, worst 423.5 ms. |
| Multi-agent / missions | 10/10 persistent specialists completed; all agent threads were gone after controlled shutdown. A 60-second load run also completed 100/100 missions, 1,000 events and 600 scheduler ticks with four bounded workers and +1.76 MiB RSS. |
| Agent Monitor / Situation Room | 20 open/close cycles each. Exactly 20 fetches per panel, both overlays closed, and zero panel requests during the following 4.5 seconds. |
| Renderer audit | Six headless Chromium samples posted successfully. Average frame time 16.67–17.06 ms (about 59–60 FPS), worst 83.3 ms, two running animations, four timers and zero frontend messages/s at idle. This is not a native WebView2 claim. |
| Responsive HTTP under machine pressure | 525 status probes in 32 seconds, zero errors, mean 10.3 ms, worst 83.0 ms and zero probes over 250 ms. Machine CPU reached 100% and RAM reached about 90%, so recorded event-loop delays are retained as machine-pressure evidence rather than hidden. |
| One-hour resource observation | After a five-minute warm-up, 121 samples over 3,600.2 seconds measured ZENO RSS 106.0 -> 94.6 MiB (trend -10.43 MiB/hour), CPU mean 2.35% / max 8.0%, threads 18 -> 18 (max 24), and zero worker/event queue depth. Handles were 474 -> 603 with a transient max of 751; a separate five-minute no-sampling drain fell 751 -> 724, so the residual +129 is reported as a monitoring risk, not declared leak-free. The host was heavily constrained: system CPU mean 63.91% / max 98.6%, RAM 80.6% -> 89.0% / max 96.0%, and swap fell 422.5 MiB. `/api/performance` mean was 48.29 ms, max 239.57 ms. |

The current cold readiness is slightly better than the previous 3,521.5 ms
measurement. Relative to the pre-Phase-21 baseline, even full server readiness
is also well below the former 6,018–9,224 ms import time. Those are different
measurement boundaries, so the comparison is directional rather than a claimed
like-for-like speedup.

### Regression and cleanup verification

- Complete maintained suite: **919 passed**, 5 dependency/deprecation warnings,
  0 failures in 250.46 seconds.
- Final focused runtime/Phase 22/conversation/job/website/workflow set:
  **75 passed**, 4 FastAPI deprecation warnings, 0 failures in 51.97 seconds.
- A live 60-poll WinRT notification test and a 500-task handle-retention test
  passed with the stable handle counts recorded above.
- Real shutdown durability handshake saved the session and flushed events before
  each owned test server was terminated; every disposable port was released.

### Remaining limits

- Native WebView2 dragging/clicking and the Windows “Not Responding” banner
  still require observation on the interactive desktop. A temporary native
  `ZENO Mini Orb` window owned one HWND and Windows reported its host process as
  responding, but the automation screenshot helper failed, so visual acceptance
  is not claimed.
- The renderer's 83.3 ms worst frame exceeds both the 16.7 ms 60 FPS and 33.3 ms
  30 FPS budgets. It was isolated rather than sustained; native WebView2 must
  still be watched under the owner's normal workload.
- During system-wide 100% CPU pressure, the event-loop watchdog recorded real
  delays despite the HTTP surface remaining responsive. ZENO cannot guarantee a
  250 ms scheduling budget when the host machine is saturated.
- In the final warmed one-hour run the watchdog recorded 119 delays: mean
  433.6 ms, p95 982.7 ms and max 1,759.5 ms; 90 exceeded 250 ms. Those samples
  coincided with mean 90.5% system CPU and 92.5% RAM, with 84/119 samples at or
  above 90% CPU and 100/119 at or above 90% RAM. This proves host scheduling
  pressure affected the backend loop; it does not prove native WebView2 stayed
  responsive, so the Windows UI acceptance gate remains open.
- The warmed hour ended 129 handles above its measured start, although it fell
  148 handles from the transient peak and a separate drain sample also fell.
  The two confirmed handle-retention bugs are fixed, but an 8-hour/24-hour run
  without periodic HTTP diagnostics is still required before declaring the
  process handle count leak-free.
- The controlled provider and ElevenLabs timeout seams remain deterministic
  regression tests; this pass did not deliberately black-hole a live provider.

## Final native closure addendum — 2026-08-24

### Newly confirmed startup root cause and fix

The desktop-owned backend could remain at one thread with approximately 4.5 MiB
RSS and never bind its fixed port. The stall occurred before ZENO application
code: this workstation's machine-global Python `sitecustomize` imports pip and
trust-store infrastructure during interpreter startup, and under current memory
pressure that path could park `pythonw` for minutes. The normal desktop launcher
and its owned backend now start through small `-S` bootstraps. Those bootstraps
add only the repository virtual environment through `site.addsitedir`, preserving
the venv's pywin32 `.pth` setup needed by DPAPI while excluding the global hook.

This is a startup-path correction, not another scheduler or application runtime.
The existing `reyes_agent.desktop_app` and `reyes_agent.web` entry points remain
authoritative. After restart, one visible `ZENO Mini Orb` window was present and
Windows reported its owning host process responding. The fixed backend reached
kernel Stage 2, reported `MICROPHONE_READY`, loaded the enrolled DPAPI-protected
owner voice profile with its 3D-Speaker CAM++/sherpa-onnx backend READY, and had
zero worker/Event Bus queue depth.

### Corrected five-minute native A/B evidence

The first attempted sample used the validator's old default port (8768), which
belonged to another development backend and did not include the native WebView2
tree. It is intentionally excluded from acceptance. Repeating the full interval
against the desktop's fixed origin at `http://127.0.0.1:8765` produced:

| Metric | Correct native result |
|---|---:|
| Duration / samples | 300.4 s / 133 |
| Whole ZENO CPU | 4.12% mean, 9.45% max |
| WebView2 CPU | 2.77% mean |
| WebView2 GPU-process CPU | 0.32% mean |
| Backend RSS | 132.7 -> 132.6 MiB (flat) |
| Whole ZENO RSS | 385.0 -> 406.7 MiB |
| Backend threads | 18 -> 17 (19 max) |
| Whole-tree threads | 179 -> 164 (180 max) |
| Backend handles | 535 -> 530 (543 max) |
| Whole-tree handles | 4,456 -> 4,398 |
| Worker / Event Bus queues | 0 / 0 |
| UI heartbeat delay | 77.18 ms mean, 569.2 ms max |
| Watchdog records during interval | 9 |
| System CPU | 72.65% mean, 100% max |
| System RAM | 74.1% -> 92.2% (92.8% max) |
| Swap change | -234.5 MiB |

The approximately 5–8% isolated target is met even though a truly isolated run
could not be performed without closing the active development/ChatGPT host. The
remaining heartbeat outliers occurred while the two-core/8 GiB machine reached
100% CPU and more than 92% RAM. This confirms machine-wide pressure remains the
dominant residual scheduling risk; it does not excuse blocking ZENO code, which
remains covered by the worker, Event Bus and browser timeout regressions.

### Fresh acceptance tests

- Focused Phase 21/22, recognition, visual-performance, Mini Orb and kernel
  regressions: **70/70 passed**.
- Complete current maintained repository suite: **1,862/1,862 passed** in
  502.00 seconds with one optional urllib3/PySocks warning and no failures.
- Real Playwright: **20/20 verified DOM actions** in 4,932.6 ms, followed by a
  controlled context close and successful safe restart.
- Managed-runtime load: **100/100 missions**, **1,000 Event Bus events**, 603
  scheduler ticks, four of four workers alive, bounded 60-message history and
  **+1.59 MiB RSS** over 60 seconds.
- Native window: exactly one visible `ZENO Mini Orb`; Win32 reported
  `hung=false`, `topmost=true`, `no_activate=true`, `minimized=false`, a valid
  monitor and the owning process `Responding=True`. The dashboard remained lazy
  rather than creating a second renderer during the five-minute measurement.

### Remaining operational gates, not unfinished Phase 21/22 code

- Automated pointer geometry could not certify native drag feel because the
  available Windows screenshot/input helper rejected this WebView2 surface.
  Static topmost/no-activate/drag/off-screen-recovery tests pass, and the native
  host/window was directly observed responding. Owner-visible drag feel remains
  an acceptance check.
- Eight-hour and 24-hour no-diagnostics soaks remain release observations. The
  existing one-hour soak plus this five-minute whole-tree run found no backend
  RSS/thread/handle growth, but no shorter test can prove a 24-hour result.
- External provider black-hole behaviour remains covered with deterministic
  timeout seams; deliberately disrupting the owner's real provider account is
  not required for software completion.
