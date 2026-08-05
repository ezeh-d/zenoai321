# Phase 21 roadmap re-audit

Date: 2026-08-04  
Scope: active desktop path defined by `ROADMAP.md` and `Open REYES.bat`.

## Measured findings before this correction

| Area | Evidence | Finding |
|---|---|---|
| Startup | `desktop_app.py` previously waited for `/api/status` before creating a native window; current launcher creates its boot window first. | The original pre-window blocking cause is removed. Recent logs also show `WinError 10048` port collisions, so an unsuccessful child-server bind must remain visible rather than being mistaken for a slow start. |
| Imports | Cold `reyes_agent.web` import was 6,018-9,224 ms / ~110 MiB before lazy loading and 903-1,823 ms / ~60 MiB after. | Eager agent/provider/tool/STT imports were a measured startup cause; they are now deferred. |
| Voice / AI | The old `async` voice endpoint ran STT and `run_agent()` directly after `await audio.read()`. The current route submits STT and the AI turn to the bounded priority runtime. | This was a real event-loop blocking cause and has been removed from the web UI path. Provider calls have a 90-second configurable SDK/task deadline. |
| Event bus | 1,000 events previously exceeded a 30-second stress window because every publish opened SQLite and recreated schema/index checks. | Batched persistence now makes 250 durable publishes finish under one second and a 1,000-event smoke run pass. |
| Browser automation | Real headless `browser_open('https://example.com')` ran through the worker system: open completed in 7,927.3 ms, then `browser_read()` failed with `Cannot switch to a different thread`. | **Open defect:** `playwright.sync_api` contexts are thread-affine. A general multi-worker pool cannot safely own one persistent context. |
| Polling/threads | Current active package has six intentional thread creation sites: bounded general worker pool, scheduler, event writer, agent workers/supervisor, and serial speech worker. | The prior request-per-chat and per-poll daemon-thread creation has been removed. Remaining workers have fixed ownership/queue roles. |
| Locks/deadlocks | Chat history has one lock and serializes mutable conversation state. The browser context lock did not serialize actual page actions across workers. | Browser calls can race/cross threads; this is corrected below with a dedicated one-worker browser runtime. |

## Root-cause summary

1. The original desktop startup waited synchronously for the server before a
   window existed.
2. Eager imports loaded all provider/tool/voice dependencies before the status
   shell could serve.
3. Voice STT and model work ran in an async request handler on the server event
   loop.
4. Persistent synchronous Playwright objects crossed worker threads; this was
   reproduced by a real browser task and is the remaining direct browser
   automation fault.
5. Event persistence performed expensive SQLite setup/write work synchronously
   for every event.

No completed roadmap phase is rebuilt. The following change is limited to
thread-affinity-safe Playwright execution, browser progress/health reporting,
and its regression verification.

## Correction implemented and verified

- Added `browser_runtime.py`: one reusable, bounded (16 pending) browser
  worker owns the complete synchronous Playwright lifecycle. General agent
  workers may wait on its task handle, but can never call a page/context from a
  different thread.
- `browser_controller.py` now records owner metadata without touching
  Playwright objects from diagnostic threads; accidental cross-thread access
  produces an explicit safe error instead of a greenlet failure.
- Every agent-facing browser tool executes the full operation on this browser
  worker. Navigation/action waits are bounded and capped by the managed task's
  remaining deadline. Cancellation returns control to the caller immediately;
  an in-flight synchronous Playwright action releases once its own configured
  timeout or I/O completion occurs.
- The desktop app now creates the native shell before launching/waiting for its
  child server and reuses a healthy existing server, avoiding the measured
  `WinError 10048` duplicate-port race. A failed owned child reports the log
  location instead of appearing as an indefinite silent start.
- Cache-miss ElevenLabs synthesis, voice previews, and voice diagnosis now run
  through the voice-priority managed worker rather than a synchronous request
  handler.

### Live verification after correction

| Case | Result |
|---|---|
| Cold child-server readiness | `/api/status` ready in 3,521.5 ms; native shell is already created before this wait begins. |
| Real Playwright open/read | Headless Chromium opened `https://example.com` and then read its body through separate general-worker tasks successfully; browser runtime: 1 worker, 0 queue depth, 0 failures. |
| Browser cancellation | A deliberately slow local navigation returned a cancelled outer task in 40.1 ms; the browser context then closed cleanly. |
| Real voice turn | Existing cached MP3 transcribed and produced an agent reply in 20.08 s. During the turn, 31 `/api/status` probes had no errors and a 27.9 ms maximum. |
| Real ElevenLabs route | Cache-miss `/api/tts` returned 32,226 bytes in 7.03 s; 9 concurrent status probes had no errors and a 14.1 ms maximum. |

The tests above prove that work remains outside the request/UI event loop.
They do not substitute for a manual, visible Windows-shell test of WebView2
animation and window dragging on the target desktop.
