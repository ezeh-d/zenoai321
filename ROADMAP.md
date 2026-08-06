# ZENO — Master Development Roadmap

Status vocabulary, used strictly:

- **DONE** — built, tested against real data, integrated, in use.
- **PARTIAL** — a real, working subset exists; the gap is named explicitly.
- **NOT BUILT** — no code. Not stubbed, not faked, not simulated.

Last updated: 2026-08-04. See `AGENT.md` for the dated engineering log
behind each entry.

---

## Phase 1 — Core Architecture · DONE
Provider-agnostic agent core (`provider.py`, `agent.py`), tool registry
(`tools/__init__.py`, 93 tools), config/env, audit log, confirmation gate,
plugin loader with manifest enforcement.

## Phase 2 — Executive Brain · DONE (one named limit)
**Done:** the staged pipeline (planning → delegating/acting → verifying →
responding) with `on_stage` callbacks, surfaced in the GUI and SSE.
**Model Router** (`model_router.py`): per-task-kind routing chains
configurable in .env, availability detection from real credentials,
health from consecutive-failure counts, automatic fallback around
degraded providers, and **measured** latency recorded from every real
provider call in `provider.py` (never seeded or estimated).
`GET /api/router`. **Named limit, reported by the router itself:** this
install has 2 providers configured, so most routes collapse onto the same
one and routing is close to a no-op until more keys exist. The router says
that in its own `note` field rather than implying richer behaviour.

## Phase 3 — Multi-Agent System · DONE
13 specialists with scoped toolsets, real delegation, and genuine parallel
execution. The long-standing "multi-agent doesn't work" bug was root-caused
on 2026-08-04 to Gemini sending `index=None` on tool-call deltas, which
merged parallel calls into one and corrupted their arguments — fixed in
`provider.py`. No recursive delegation (sub-agents never receive `delegate`).

## Phase 4 — Mission Engine · DONE
`tools/missions.py` — bounded state machine, objectives, progress, log,
GUI panel, ATLAS integration. Campaigns mirror into missions.

## Phase 5 — Living Memory · DONE
`living_memory.py` — file-backed canonical records with immutable version
snapshots, edit/compare/restore, archive/restore/delete/purge, merge and
split (both with previews), and importance/recall tracking. Semantic
search over real embeddings (`tools/rag.py`), plus activity and Event Bus
history. Dream Mode archives near-duplicates reversibly (never purges).
The legacy SQLite `facts` table is imported once for compatibility and is
no longer the authority. Existing memories were preserved throughout.

## Phase 6 — Knowledge Graph · DONE
`knowledge_graph.py` — real entities and edges from the vault:
`[[wikilinks]]`, `#tags`, folder placement, and shared-tag co-occurrence
(capped at 25 notes/tag so a common tag can't produce a quadratic
explosion). Nothing is model-inferred, so every connection traces back to
something the user wrote. Orphans reported rather than hidden. Tools:
`knowledge_graph_stats`, `explore_knowledge`. Verified on the real vault.

## Phase 7 — Browser Intelligence · DONE
`browser_controller.py` + 9 tools. Playwright, persistent profile (logins
survive restarts), OpenCV template-match vision fallback. Verified live.
**Deliberately excluded:** bulk submission helpers — see Campaign Engine,
which does batching with a preview + single approval instead.

## Phase 8 — Desktop Automation · DONE
App control, window/media/volume, clipboard, keyboard/mouse, file
operations, shell commands. Governed by the Permission Engine.

## Phase 9 — Voice System · DONE (one browser-reported limit)
**Done:** ElevenLabs TTS; Voice Manager with 13 per-agent profiles; **all
13 agents now have their own distinct voice** (owner supplied 12 ids
2026-08-04 — verified genuinely distinct, not just configured: same
sentence as ULTRON vs APEX produced different byte lengths and MD5s);
disk cache (measured 3.36s → 0.19s on repeats); speech queue; diagnostics;
preview endpoint; **Voice Test panel in Settings** (per-agent preview,
editable voice id saved surgically to .env and applied without restart,
roll call button, diagnose button); **Agent Roll Call** — each specialist
introduces itself in its own voice, played sequentially in the browser
with the mic paused; once-per-session first-activation introductions on
delegation. Persistent listening with standby + self-echo rejection.
**Listening:** one browser-owned `getUserMedia` stream now requests noise
suppression, echo cancellation and auto gain; a real adaptive energy VAD
(rolling noise floor, hysteresis, 700 ms hangover) records only bounded
speech clips from that exact processed stream. Clips are transcribed in
the bounded Deepgram voice worker, so neither the Mini Orb nor dashboard
opens a second Web Speech microphone stream. The UI reads the live track
settings back and reports what the browser actually applied.
**Persistent Mini Orb handoff:** the Mini Orb and lazy dashboard now have a
single explicit microphone-owner handoff. Opening the dashboard releases the
Mini stream; hiding/minimizing it releases its stream and, after a short
release delay, restores the Mini listener automatically. The WebView2
profile remains `%LOCALAPPDATA%\\ZENO\\WebView2\\UserData`, so a saved grant
persists across restart. If WebView2 cannot report saved permissions through
the Permissions API, the Mini Orb performs the normal one-time capture attempt
instead of silently disabling wake-word listening. VAD now genuinely retries
only an unsupported optional `channelCount` constraint; denied/busy device
errors remain visible and are never masked by retries.
**Named browser limit:** energy VAD reduces silence and ordinary background
noise but cannot reliably distinguish the user from a TV or another person
speaking, and audio drivers/WebView2 may decline a requested processing
constraint. Account-side id validation needs an ElevenLabs key with
`voices_read`; this install's key lacks that scope, which affects
validation only, not speech.

## Phase 10 — Vision System · PARTIAL
**Done:** screenshots, webcam capture, screen understanding, OpenCV
template matching, hand-gesture/mouse control (opt-in — it was the cause
of a real performance regression).
**Gap:** no OCR (`pytesseract` not installed).

## Phase 11 — Event Bus · DONE
`event_bus.py` — typed, durable, queryable, bounded fan-out, prefix and
correlation filtering. `notification_bus` forwards into it. Publishing
never raises.

## Phase 12 — GUI · DONE
Voice-first HUD, activity ticker, stage indicator, workspaces (coding,
news, map), Timeline, command palette, focus mode, explainability panel,
missions panel, phone companion page.

**Live Project Activity View (Task 16):** a project write is now observable
from destination selection through real file completion. New projects do not
silently choose a folder: `write_project_file` returns a destination request
and the Activity View offers Desktop, Documents, ZENO Projects, or an explicit
full path. It then shows actual state, active agent when known, tools, files,
errors/warnings, bounded code/HTML preview and completed-step counts over the
Event Bus. It does not expose private reasoning or manufacture a percentage
when no finite plan exists. Existing vault projects remain editable at their
current paths. Selecting a destination in the visible view is an explicit
owner action and continues through the normal conversation/permission path;
it is not an autonomous retry.

## Phase 13 — Orb System · DONE
CSS orb (WebGL removed — it was the lag), 11 states and on-demand
specialist presence with per-agent colour/identity, live activation from real
delegation events, click-through dashboards.

**Council faces and emotional presence (Tasks 13 & 15):** `agent_faces.js`
is one shared CSS face primitive, lazily loaded for Council/Situation/Mini
presentations. Each registered specialist has distinct hue, eye geometry,
accent, name and role. Real lifecycle emits map to waiting, thinking, working,
speaking, success and error. Expression is separately event-backed:
neutral/happy/excited/curious/thinking/confused/surprised/concerned/serious/
skeptical/frustrated/proud/sad/warning/success can react while an agent stays
silent. Silent faces use static poses, CSS transitions and bounded
deterministic blinks; only thinking, working and real audio-speaking states
animate. Closing Council destroys face DOM/timers, and hidden views pause all
animation.

**On-demand specialist presence (Task 14):** ZENO is the only persistent
Mini Orb. Specialist orbs/faces are created only from real `agent.*` Event
Bus lifecycle events: queued → waiting, task/provider → thinking, tool
execution → working, real audio playback → speaking, then success/error
and release. The Mini Orb consumes the same Event Bus feed and shows only
called participants around ZENO; the dashboard keeps no permanent 13-agent
ring. The explicitly opened Council room may show the roster as static faces,
but only real lifecycle/audio activity animates a face. CSS animation is
gated to the active state and is paused while hidden; terminal dashboard
cards fade out and their DOM/timers are released.

## Phase 14 — Executive Dashboard · PARTIAL
**Done:** **Agent Monitor** (live worker state, heartbeat age, queue
depth, tasks done/failed, success rate, per-agent restart button; polls
only while open), Timeline, missions panel, approvals, notices, system
health, permission status, mini-orb hover card, **Executive Meeting**
(every specialist reports its REAL runtime metrics aloud in its own
voice, then ZENO summarises).
**Gap:** no single unified "home screen"/Situation Room composing them
into one view.

## Phase 15 — Dream Mode · DONE
`dream_mode.py` — five idle passes: knowledge upkeep (reindex + orphan
report), memory de-duplication (archives near-duplicates reversibly),
daily summary written from recorded activity, stalled-work detection, and
tomorrow's agenda. **Zero cloud AI usage by design** — every pass is
local SQL/set/string work, so the summary's figures are counts of real
rows rather than model prose. Re-checks idle between passes, so the user
returning stops the run. Verified: 5/5 passes in 0.6s, real summary note
written.

## Phase 16 — Digital DNA · DONE
`digital_dna` computes the working-pattern profile from the REAL
`activity_log` (most-used apps, peak hours, average active time per day)
plus what ZENO has actually been used for, from the event record. Below
60 recorded active minutes it refuses to describe a pattern and says how
much data it has — verified: with 0 samples it declines rather than
inventing a profile. `simulate_mission` estimates from the user's own
completed missions, measured agent durations and real campaign outcomes,
and states "no honest basis for an estimate" when no comparable history
exists — also verified on empty data.

## Phase 17 — Research Lab · DONE
`research_lab` creates a real mission, runs research on ARIS's live
worker, writes a real report into the vault, and advances the mission.
Every artefact it reports exists on disk.

## Phase 18 — Plugin System · DONE
Manifest-declared permissions, capability validation, per-version user
approval, audit logging, **and run-time enforcement** (`plugin_sandbox.py`).
Plugins execute with restricted builtins: guarded `open()` (writes need
`filesystem_write`, outside reads need `filesystem_read`), guarded
`__import__` (network/subprocess/desktop-automation modules each need
their capability), `eval`/`exec`/`compile` removed, and only
`reyes_agent.tools` reachable — behind a proxy that exposes `register`
only. Credentials and the permission engine are never importable at any
level. Every attempt is audited.

Verified 8/8 against real plugin files, including two bugs the tests
caught in the first implementation: `from reyes_agent import config`
bypassed the name check and **printed a live API key**, and attribute
traversal could reach the same object even with the import blocked. Both
closed, then re-verified; a normal plugin can still register tools.

**Named limit, unchanged in substance:** this is a same-process
capability guard, not a security boundary. It stops casual/accidental
over-reach and makes attempts visible; a determined hostile plugin can
still escape it. True isolation needs a separate OS-sandboxed process,
which is NOT implemented.

## Phase 10b — OCR / Document Intelligence · DONE (with named gaps)
`ocr.py` + `tools/ocr_tools.py`. Uses the OCR engine built into Windows
via `winsdk` (already a dependency) — Tesseract was rejected on evidence:
neither `pytesseract` nor its native binary is installed, so wiring it
would have shipped a module that imports and then fails. Screen-region and
full-screen OCR, image OCR, and direct reads for text/markdown/csv/code.
Temporary screen captures are deleted after reading. Confidence is a
labelled heuristic (word-shape/length/volume), never presented as an
engine score. Verified: 617 words read off the live screen at 0.97.
**Gaps, reported by the tool rather than hidden:** PDF/DOCX/XLSX/PPTX need
libraries that are not installed and say so explicitly instead of
returning empty text.

## Phase 19 — Command Center · DONE
**Situation Room** (`GET /api/situation` + full GUI): six live panels —
Agent Runtime, System, Missions, Model Router, Event Bus, Session &
Policy — composed from subsystems that already report observed state.
Unknown values render as a dash rather than a plausible number. Polls
only while open. Verified live: 6 cards, real agent/RAM/event figures,
zero console errors. Reachable from the command palette, alongside the
Agent Monitor and Timeline.

## Phase 20 — Optimization & Production Readiness · ONGOING
Done: WebGL removed; webcam inference made opt-in; dev loop stops when
off; transform-based ring; voice caching; background threads for campaigns
and agent work.

**Owner-taught workflow replay:** explicit Teach Mode records a bounded,
reviewable sequence of application changes, pointer actions, safe navigation
hotkeys, and ZENO browser-tool events. The owner must review and name a
workflow before it is saved. Replays use the existing managed workers,
permission engine, browser runtime, Event Bus, and Mini Orb state rather than
parallel runtimes. Typed text, clipboard contents, passwords, cookies, and
URL query strings are never stored; replay stops for those inputs. Manual
desktop clicks are normalized and foreground-app guarded, so an unexpected
window produces a resumable prompt rather than a blind click. **Named limit:**
manually demonstrated websites replay as guarded desktop actions; only actions
originally run through ZENO's browser tools retain Playwright-level selectors.

**Mini Orb overlay reliability:** the Mini Orb is now its own lightweight,
frameless native topmost window. The dashboard is created lazily only when
opened and can be minimized or hidden without navigating, resizing, or
destroying the overlay. The overlay persists its native position, accepts
negative/multi-monitor coordinates, repairs stale/off-screen coordinates to a
working area, and has one five-second no-activate health check for hidden or
minimized windows. The health path uses `SetWindowPos(HWND_TOPMOST,
SWP_NOACTIVATE)` rather than focus-stealing `show()`. Verified live on
2026-08-06: startup, Chrome foreground, File Explorer launch, dashboard
minimize, and a forced off-screen recovery all left the 210x210 orb visible
and responsive. VS Code was not installed on this PC, so that one requested
live application check is unavailable here.

**Idle runtime cost:** the dashboard no longer starts a full WebView at boot,
and the 13 specialists are registered at startup but each supervised worker
starts only when delegated. Duplicate in-flight specialist work shares one
result. The normal Mini Orb heartbeat is one bridge call per second (not four)
and its state uses the existing small particle pool. Its idle state now keeps
the requested continuous glow and 12 visible particles, but draws them at
8fps with no continuous core/ring compositor animation; active work raises
only the particle cadence to 20fps. On the restarted live application,
after staging settled, a 20-second idle sample recorded 8.28% total ZENO CPU,
4.22% WebView2 CPU, 521.7 MiB working set and 155 threads; the Mini Orb window
remained responsive. A short warm-up sample was substantially higher, so this
is not a substitute for the outstanding five-minute isolated A/B measurement.
The bounded 20-second stress run completed 40 missions and 1,000 events with
all four workers alive, 60 retained history entries, and 1.66 MB RSS growth.

**Confidence and verification:** `confidence.py` combines only real supplied
speech, intent, entity, visual, plan, and verification signals; unknown means
unknown, never a made-up score. Risk is derived from the existing Permission
Engine. High-risk action with missing/weak confidence goes through the normal
confirmation gate. Deepgram confidence is retained when its response actually
supplies it. Workflow replay verifies foreground app and browser-runtime
evidence where possible; a coordinate-based desktop workflow pauses for the
owner's final visual confirmation instead of claiming completion. **Gap:**
current providers do not expose calibrated intent/entity confidence, and
manual desktop replay cannot infer semantic success without an explicit
application postcondition or owner confirmation.

**Biggest win, and it was not the GUI.** After three GUI-side fixes the
user still reported lag, so it was measured: 93 tools → 5.35s/turn vs 5
tools → 1.50s. Tool COUNT dominated latency; every turn shipped ~13,900
tokens (10,480 of it tool schemas). Fixed with lazy tool groups — core 54
tools by default (43% payload cut), deeper groups loaded on demand via
`enable_tools`. Measured 2.92s → 2.05s with the multi-second spikes gone.
**~1.5s is the Gemini round-trip floor**; no local work goes below it.

Watching: startup time has grown with the import graph (~0.8s for
reyes_agent.tools; the larger `site` cost is pip/truststore in this
environment, not ZENO).

---

## Future milestones — interfaces only, no placeholder code

| Module | Extension point |
|---|---|
| Knowledge Galaxy | `event_bus.history()` + `rag` embeddings |
| Digital Twin | `system_health` + `activity_monitor` + Event Bus |
| Marketplace | plugin manifest + `permissions.may_load_plugin` |
| Multi-device Sync | phone companion API + Event Bus correlation ids |

These are named as future work in the code. None has stub functions
pretending to work.

---

## Installation policy (THIS machine only)

`INSTALLATION_PROFILE=trusted_local` — full local desktop trust, granted
by the owner 2026-08-04. The shipped default for any other installation is
`cautious`. Outward-facing actions (email, social posting) remain
confirm-gated and configurable. `financial` is BLOCKED in every profile
with no enabling flag: ZENO has no tool that moves money, and the
Investment Engine stops at a validated order ticket by design.
