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

- A true one-hour idle sample and the existing 8-hour/24-hour soak profiles
  were not run in this interactive session. They remain release gates; short
  samples cannot prove the one-hour RAM result or rule out slow leaks.
- Native Windows WebView2 orb FPS, window drag/click responsiveness, and the
  absence of the OS-level “Not Responding” banner require a manual target-PC
  run. Headless Chromium measured 53 FPS only.
- Provider/ElevenLabs failure tests use controlled failing seams. Real requests
  were successful, but a black-holed external network endpoint was not used.
- A cancellation request returns control immediately, while a synchronous
  Playwright/SDK call finishes only at its configured I/O timeout; Python cannot
  safely kill that third-party call mid-frame.
