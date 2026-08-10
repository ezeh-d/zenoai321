# ZENO — Master Development Roadmap

Status vocabulary, used strictly:

- **DONE** — built, tested against real data, integrated, in use.
- **PARTIAL** — a real, working subset exists; the gap is named explicitly.
- **NOT BUILT** — no code. Not stubbed, not faked, not simulated.

Last updated: 2026-08-10. See `AGENT.md` for the dated engineering log
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
14 specialists with scoped toolsets, real delegation, and genuine parallel
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
**Done:** ElevenLabs TTS; Voice Manager with 14 per-agent profiles; **the
original 13 agents have their own distinct voice** (owner supplied 12 ids
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

## Phase 10 — Vision System · DONE (with named recognition limits)
Screenshots, webcam capture, screen understanding, OpenCV template matching,
hand-gesture/mouse control (opt-in — it was the cause of a real performance
regression), and OCR through the installed Windows OCR engine are integrated.
The older `pytesseract` gap is obsolete; Phase 10b records the actual document
format limits and Phase 21 records the temporal/person-recognition limits.

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

## Phase 14 — Executive Dashboard · DONE
**Done:** **Agent Monitor** (live worker state, heartbeat age, queue
depth, tasks done/failed, success rate, per-agent restart button; polls
only while open), Timeline, missions panel, approvals, notices, system
health, permission status, mini-orb hover card, **Executive Meeting**
(every specialist reports its REAL runtime metrics aloud in its own
voice, then ZENO summarises).
The unified Situation Room composing these runtime views is implemented in
Phase 19; this older gap is therefore closed rather than counted twice.

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

**Website Builder Mode (Phase 1 foundation):** Website requests now enter the
existing Fast/Deep router as `WEBSITE_BUILDER`; actual project work remains in
`build_project`, the managed Task Engine, bounded terminal executor, preview
manager and Live Activity View. Successful web builds register durable local
metadata (name, framework, folder, status and detected pages) in the existing
state database. `website_project` can list these projects, run bounded static
title/description/alt checks, and make an on-project `.zeno/versions`
checkpoint before a redesign. Checkpoints exclude dependencies, build output
and Git data and use configurable source-only limits (default 750 files / 12
MiB; capped limits are reported rather than silently treated as full undo
points). The existing Coding Executor now supplies structured defect
categories plus a five-attempt safe-repair loop; a repair that increases the
measured defect score is rolled back. Website Studio is available from the
dashboard's **Web Studio** panel as well as tools. Its on-demand Visual Check
uses the existing single-owner Playwright runtime to render a managed local
preview at desktop and mobile sizes, save screenshots and report layout
evidence; it does not claim aesthetic success. The preview manager has one
managed record per project (URL, port, PID/thread, owners and start time), so
repeated starts reuse rather than stack servers. No extra server, worker,
Event Bus, agent or memory vault was introduced.

**Website Studio audit repair:** generated website folders are now refused if
they resolve inside the ZENO installation or vault. Restoring a checkpoint is
explicit-confirmation gated, automatically snapshots the current project
first, and only replaces ordinary tracked project files (dependencies, build
output, Git data and checkpoint history are preserved). Test-mode builds no
longer pollute durable Website Studio project memory.

**Whole-system regression audit (2026-08-07):** every repository standalone
test suite passed after a complete sweep of the kernel, workers, agents,
Event Bus, browser runtime, voice/VAD, Mini Orb, Website Studio, workflows,
recognition and dashboard paths. Two confirmed regressions were corrected:
the local Intelligence Router now uses a bounded exact-message cache while
returning fresh diagnostic maps per caller (repeated routing stays below its
1 ms budget), and the browser-owner runtime now waits only until the caller's
actual remaining deadline rather than rounding short deadlines up to a 50 ms
poll interval. External provider limits remain correctly reported rather than
masked: the current Gemini/OpenAI accounts were quota/credit limited during
an offline test path, and provider configuration/credit changes require the
owner rather than a source-code workaround. The installed Ollama model is now
an explicit emergency fallback on this machine: both the modern OpenAI-
compatible gateway and the legacy LiteLLM seam normalize their different
model/base-URL conventions and returned a real `LOCAL_READY` response.

**Peak stability validation (2026-08-07):** each specialist queue is capped at
32 retained tasks (configurable from 1–256), rejects overflow visibly, and
preserves deduplication, cancellation and restart semantics. Provider circuit
breakers now quarantine an authentication-rejected credential until an
explicit reset/restart instead of probing the same bad key every cooldown.
The router reports configured and operational state separately. A native-only
microphone capability prevents an old localhost Chrome tab from becoming a
second always-on listener or overwriting Mini Orb capture evidence; typed web
access remains available. Measured cold startup reached READY in 2.73 seconds.
A five-second live process-tree sample before these final guards measured
4.93% total ZENO CPU, 392.2 MiB aggregate working set and every host/WebView
responding while the machine itself was at 100% CPU and about 92% RAM. The
complete 36-file standalone regression suite passed before the ownership guard;
focused voice, VAD, kernel, router and queue suites passed after it.

**Creator, Mastery and Foodie Intelligence:** `creator_mode.py` and
`foodie_intelligence.py` extend the existing conversation engine, Fast/Deep
router, Event Bus and local state database rather than creating another brain,
memory store, task scheduler or permanent specialist. Creator projects retain
only an explicit project ID, goal, stage, completed stages, verified files,
decisions and open tasks. Mastery coaching tracks owner-supplied practice
evidence and weak areas, never claims an objective score or automatic
promotion. Foodie Mode handles practical recipes, step-by-step cooking,
ingredient scaling and food-safety policy; its optional cooking session stores
only the current agreed steps. It does not retain food preferences separately
from Living Memory, make idle model calls, or claim timers/assets/results that
were not actually created. Existing ZEAL, project, image, vision, research and
timer capabilities are reused only when the request requires them.
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

## Phase 21 — Living Recognition (speaker, audio and video) · PARTIAL, with explicit privacy boundaries

**Divine voice identity:** the browser's one existing WebRTC-processed
microphone stream now creates a bounded PCM copy only for each VAD-approved
utterance. `speaker_identity.py` compares its local spectral acoustic feature
vector to a Divine profile enrolled from 3–8 recordings. Raw recordings and
command clips are discarded; on Windows, the stored feature-vector payload is
protected with the current Windows user's DPAPI key outside the repository and
vault. The response states `OWNER_CONFIRMED`, `LIKELY_OWNER`,
`UNKNOWN_SPEAKER`, `MULTIPLE_SPEAKERS`, `INSUFFICIENT_AUDIO`, or `NO_PROFILE`
instead of quietly equating it with STT confidence. The server signs each
fresh result before a browser voice turn can use it, so an arbitrary web
client cannot post its own `OWNER_CONFIRMED` claim. Unknown voice requests use
a clean non-persistent history and do not receive recalled living-memory facts
or private retrieval tools. A high-risk voice action always remains queued for
desktop confirmation, even on this trusted-local installation.

**Named security limit:** this is local acoustic similarity for
personalisation and privacy posture, **not** spoof-resistant speaker
verification. It intentionally does not claim to implement Windows Hello,
passkeys, PIN validation or liveness detection; those remain the required
second factor for highly sensitive work. Accent and Pidgin are not used as a
speaker feature — the profile compares audio characteristics, while Deepgram
continues to supply an independent speech confidence.

**Audio recognition:** `audio_recognition.py` accepts a finite 4–18 second
sample from an explicit upload, microphone, or Windows WASAPI loopback source.
It uses a local perceptual cache that retains a small fingerprint/result only,
not audio. Provider selection is modular; the integrated AudD adapter is
enabled only when `AUDD_API_TOKEN` is present, runs with a timeout, and names
the provider/source in the result. With no provider or no match, ZENO says so
instead of inventing a title. System and microphone recognition controls are
off by default and visible in the dashboard. Matched metadata/artwork is
shown as a short-lived dashboard/Mini Orb card from the real Event Bus event.

**Video and visual awareness:** `visual_awareness.py` provides visible
Visual Awareness, Microphone Recognition, System Audio Recognition and Rolling
Buffer controls. All default off. When Visual Awareness + Rolling Buffer are
enabled, the shared scheduler takes one compressed screen sample every five
seconds on a background worker and retains at most 12 in-memory frames (no
disk capture, no camera). `understand_video` either analyses one directly
requested screen frame or uses that real buffer for a past-event question;
it applies local OCR to selected frames and at most one vision-model request,
not every frame. System-audio evidence is fused only when the separate visible
system-audio control is on. Unknown people are described rather than
identified; no stranger profile is built. Confidence remains `unknown` when a
model does not expose a calibrated score, while OCR confidence is labelled as
the existing local heuristic.

**Named capability gaps:** there is no local music database or configured
AudD token in source control, so live song naming awaits owner provider
configuration; loopback depends on the Windows audio driver. There is no
person-recognition enrolment/UI beyond Divine's voice profile, no temporal
action classifier, no camera activation by this subsystem, and no automatic
movie/title identification without concrete visual/audio evidence.

**Regression coverage:** `tests/test_living_recognition.py` verifies profile
encryption/no raw audio retention, scoped private retrieval, signed identity
proofs, honest no-provider audio results, awareness defaults/history clearing,
and the browser/API wiring. It runs alongside Phase 21/22 runtime, VAD and
Mini Overlay regressions.

## Phase 22 — Next Intelligence Layer · PARTIAL, with explicit limits

**20. Interrupt + correction — PARTIAL.** `intelligence.py` registers real
managed worker handles for chat, streaming chat and voice turns. “Stop”,
“wait”, “pause”, “cancel” and an explicit “I meant …” correction cancel or
pause the preceding work before a replacement intent is planned. The browser
keeps its one VAD stream live during ElevenLabs playback; a non-echo utterance
stops local audio immediately, cancels the server operation and is replayed
only after the former conversation slot is released. Agent tasks now carry a
cooperative cancellation token through their provider/tool loop; queued work
is removed. Playwright already observes the parent task token while waiting.
**Limit:** Python cannot forcibly terminate an arbitrary third-party SDK call
already inside a synchronous native/network function; configured provider and
Playwright timeouts remain the hard boundary, and cancellation prevents the
next step rather than pretending to kill that call.

**21. Undo + recovery — PARTIAL.** A bounded, durable local action history now
records tool outcomes. ZENO project-text writes up to 512 KiB capture a real
before-state immediately before writing and can be restored/deleted only when
the current file hash still proves nobody changed it afterwards. External,
destructive, large or sensitive-file operations are explicitly non-reversible;
they are never advertised as undoable. `undo_last_actions` remains confirmation
gated.

**22. Teach-by-demonstration 2.0 — PARTIAL.** The existing reviewed Teach Mode
continues to use its guarded replay, app/foreground verification, browser tool
selectors and owner visual confirmation. No coordinates-only replay was added.
Its named limit is unchanged: a manually demonstrated website has guarded
desktop semantics unless its original action was a ZENO browser tool.

**23. Situation awareness — PARTIAL.** A lightweight event/request projection
now exposes the observable active application/window, active managed task,
current stage, mission, workflow, participating agents and recent command to
the Situation Room/API. It updates from work rather than introducing a polling
loop. Ambiguous references are not resolved automatically.

**24. Proactive intelligence — PARTIAL.** Existing quiet, opt-in, bounded
proactive notices remain the only automatic suggestions. They respect the
heartbeat kill switch/quiet hours and never authorize an action. No fake
open-ended prediction model or background provider loop was introduced.

**25. Personal Knowledge Graph — PARTIAL.** The existing evidence-backed note
graph remains authoritative for inferred note links. A separate explicit,
owner-confirmed relationship store now supports add/correct/search/delete for
relationships such as people, projects and agent roles. It does not infer
private relationships from model output.

**26. Universal search — PARTIAL.** One bounded permitted search now ranks
Living Memory, note text, explicit relationships, saved workflows, durable
activity and action history with labelled sources. Ranking is transparent
lexical relevance plus bounded recency; the existing semantic vault search is
still a separate specialised tool, so this layer does not claim a new unified
embedding index.

**27. Time + temporal awareness — PARTIAL.** The new resolver gives exact,
timezone-aware meanings for today/yesterday/tomorrow, last weekday and finite
“N hours from now” expressions. Unsupported natural language remains explicit
rather than guessed; it is not a calendar/reminder parser replacement.

**28. Safe simulation — PARTIAL.** `simulate_plan` produces an unmistakably
non-executing plan, risk and affected-file preview through the Event Bus. It
does not call tools or mutate state. Editing/approving a model-generated plan
still uses the existing normal confirmation path; no pretend dry-run of an
external website or OS command is claimed.

**29. Self-diagnostics + Health Center — PARTIAL.** An on-demand, event-driven
Health Center reports actual Kernel, worker queue, Event Bus, agent, voice,
lazy browser and recognition capability status. It does not add a costly new
poller. Existing agent/browser recovery remains available; automatic recovery
is deliberately limited to safe established mechanisms rather than restarting
hardware/provider services blindly.

**30. Capability awareness / truth — PARTIAL.** `capability_status` provides
AVAILABLE, PARTIAL, NOT CONFIGURED and UNAVAILABLE states with concrete
limitations, including audio recognition and spoof-resistant voice identity.
It prevents this new layer from representing planned/incomplete work as live,
but it is a curated registry rather than a runtime proof for every third-party
provider credential.

**31. True mission pause + resume — PARTIAL.** Missions now preserve observable
goal, plan, completed/pending steps, files, agents, decisions, blockers and
verification in the existing local state database; pauses/completions update
the projection. Workflow replay keeps its own precise resumable checkpoint.
An arbitrary in-flight model/desktop operation cannot be resurrected after a
process crash, so ZENO requires evidence before retrying an unfinished step.

**32. “ZENO, handle it” — PARTIAL.** The existing Executive Brain, dynamic
specialists, Activity View, destination gate, permission engine, verification
recording and on-demand faces are now connected to interruption, situational
context and persisted mission evidence. ZENO can plan/delegate/observe and
show real work, but there is no new autonomous outcome executor that claims it
can resolve every ambiguous goal without asking a consequential question.

**Regression coverage:** `tests/test_next_intelligence.py` verifies managed
cancellation, specialist cancellation, safe reversible project writes and
modified-file refusal, mission-state persistence, temporal explicitness,
relationship correction/deletion, non-executing simulation and the one-stream
browser barge-in wiring. It runs with the existing Phase 21/22, workflow,
voice, Mini Orb, Activity View, agent-presence, confidence and kernel suites.

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

---

## Microphone diagnosis and recovery — IMPLEMENTED AND LIVE-VALIDATED

The earlier large “blocked in Windows or this ZENO profile” banner was an
incorrect frontend collapse of `NotAllowedError`; it did not prove that
Windows privacy was denied. Local diagnosis on 2026-08-06 found Windows user,
machine and desktop-app microphone consent set to `Allow`, Deepgram
configured, and eight recording inputs, with the Realtek Microphone Array as
the default. A direct PortAudio open was rejected by the audio host before
samples were read, so it is recorded as a device-initialization/busy-path
observation, not falsely as a permission denial and not as proof that WebView2
capture failed.

`microphone.py` now reports the stable states
`MIC_PERMISSION_DENIED`, `MIC_PERMISSION_NOT_REQUESTED`,
`WEBVIEW2_PERMISSION_DENIED`, `WINDOWS_PERMISSION_DENIED`,
`NO_MICROPHONE_FOUND`, `MICROPHONE_DISABLED`, `MICROPHONE_BUSY`,
`DEVICE_INITIALIZATION_FAILED`, `AUDIO_CAPTURE_FAILED`, `STT_FAILED`,
`WAKE_WORD_FAILED`, `BACKEND_CONNECTION_FAILED`, and `MICROPHONE_READY`.
The Dashboard and Mini Orb report browser-observed stream open, live RMS
input, capture loss, wake/STT transport failure and selected device to a
small in-memory status endpoint; no audio is stored. The dashboard has
Enable microphone, Test microphone, Refresh devices, a persistent profile
device choice and a live input meter. The Mini Orb uses the same saved device
and remains the sole listener when the dashboard is hidden. Both retain the
one processed VAD stream and make at most two safe recovery attempts after a
track ends.

**Live validation (2026-08-07):** after restart, the persistent WebView2
profile reported `MICROPHONE_READY` with `audio_received=true` from both the
Mini Orb handoff and the dashboard owner. Warm Deepgram samples recognized
"Zeno open Chrome" in 0.54–2.01 seconds (1.40 seconds average across three),
and a real app conversation returned successfully. Energy VAD still has the
named TV/other-speaker limitation in Phase 9; that is not misreported as a
permission failure.

---

## Optional performance features — RE-ENABLED WITH GUARDS

**Dream Mode:** remains enabled through the existing proactive scheduler, but
now has a persisted on/off setting and explicit `DREAM_MODE_IDLE`, `WAITING`,
`RUNNING`, `PAUSED`, `COMPLETE` and `ERROR` states. It waits for ten minutes
of user idle time, a three-hour cooldown and CPU/RAM/worker headroom; it
checks again between local maintenance passes and yields when activity or core
work returns. The previous automatic `reindex_vault` call was the confirmed
performance risk: it can make remote embedding requests for changed notes.
Automatic Dream Mode now only inspects local graph health; manual indexing
remains available through the existing tool.

**Background dashboard updates:** the existing Event Bus remains the primary
source of state changes. The persistent dashboard now has a saved Background
dashboard updates preference: while hidden it performs only a 5-second status
refresh (2 seconds visible), without waking closed Council, Timeline,
Situation Room or Agent Monitor panels. The Mini Orb remains independent of
dashboard visibility, voice handoff and agent runtime.

**Cursor eyes:** the existing CSS eyes now use a shared, saved, capped
cursor-following transform (Auto/15/30 FPS). Pointer events coalesce into one
timer, idle returns once toward neutral, sleeping/hidden/lite states suppress
it, and a five-second existing dashboard load sample reduces it under high
CPU/RAM/worker pressure. This tracks cursor movement inside ZENO's WebView;
no global Windows mouse hook or high-frequency Python/WebView bridge was
added merely for cosmetic animation.

**Regression coverage:** `tests/test_reenabled_performance_features.py`
verifies persistence, resource gating, the no-automatic-embedding Dream path,
the bounded dashboard cadence and cursor-eye wiring.

---

## Multi-level specialist teams and Subspace — PARTIAL

The existing 13 primary specialists now have bounded, on-demand worker-team
definitions (74 workers total), rather than treating APEX as a special
parallel framework. Workers reuse the current specialist provider turn,
scoped tool registry, permission path, cancellation check and Event Bus; no
worker thread, private Event Bus, or recursive worker hierarchy is created.
The hard limits are three workers per specialist task, three tool rounds per
worker, a 120-second worker deadline, and depth `ZENO → primary → worker`.
Workers with missing tools report `UNAVAILABLE`; they are not run or displayed
as operational merely because their role exists.

`/api/hierarchy` supplies the live agent-runtime snapshot and capability
metadata to the on-demand **Agent Subspace** dashboard overlay. It fetches
once when opened and afterwards receives only real `agent.*` Event Bus
messages. The normal view contains ZENO plus genuinely participating
specialists/workers; selecting a participating specialist expands that team's
registered workers and their capability status. Closing the overlay drops its
small in-memory projection, DOM and listeners. Worker terminal events now
truthfully distinguish `success`, `error`, `timed_out`, and `cancelled`; this
corrects the earlier false-success visual state.

**Verified offline:** worker capability containment, parent attribution,
budget/depth limits, Event Bus delivery, provider failure, timeout and owner
cancellation; hierarchy endpoint shape; Python and dashboard/Mini Orb syntax;
existing agent-runtime, voice-handoff, Mini Orb, performance and intelligence
regressions.

**Live-verified 2026-08-06 (running server, real provider):** `/api/hierarchy`
returns 13 primaries / 74 workers, all `AVAILABLE`, HTTP 200 in 19 ms. A real
worker turn (`apex → pixel`, "measure this machine") completed in 23.9 s,
called `system_health`, and returned a measurement grounded in real values
(RAM 7.6/8.4 GB, 90%). `agent.worker_started` was published with
`parent: apex`, which is the field Subspace nests on. `tests/test_agent_teams.py`
(16 assertions) passes.

**Known behaviour, not a defect but worth stating:** commanders often answer
simple questions themselves instead of calling a worker. This is a direct
consequence of the containment rule — a commander holds at least its team's
tools, so for a one-tool question like "why is my FPS low" APEX can call
`system_health` directly and does, returning the correct answer in one model
call instead of two. Measured: ZENO → APEX answered correctly with real
numbers, but `agent.worker_started` did not fire. Workers engage for sub-tasks
that genuinely need their depth. If more eager delegation is wanted, the lever
is the team-roster guidance in `_run_specialist`, not the architecture.

**Still not live-verified:** the Subspace overlay rendering a multi-worker
mission on the running desktop process (the endpoint and event payloads it
consumes are verified; the visual assembly is not), and cancellation
propagating ZENO → primary → worker against a live provider. Manual summon/dismiss controls are intentionally not
added: delegation and cancellation continue through the existing permissioned
mission/agent runtime rather than a dashboard button that could fabricate or
bypass work.

---

## Creative Design + Learning Intelligence â€” PARTIAL, with explicit execution limits

ZEAL remains the one existing Creative Director, now explicitly scoped for
original logo/brand direction, typography, colour, layout, UI/UX critique,
vector-capable project assets and design education. No second creative agent,
image queue, renderer or idle model was created. Complex design-learning paths
and complete identities take the existing DEEP route; small questions such as
kerning remain FAST. The agent receives compact per-turn policies requiring
originality, visual evidence for critique, small-scale/monochrome logo checks,
print constraints and real tool evidence before it calls an asset complete.

`learning_mode` persists only explicit owner learning progress (subject,
level, completed topics, reported difficulty, exercise and next lesson) in the
existing local `state.db`, emits bounded Event Bus updates, and supports both
design curricula and a modest generic path for other hard-to-start skills. It
does not infer learner progress, create a persistent worker, or duplicate
Living Memory. `critique_current_design` stays lazy and calls the existing
screenshot/vision seam only when the owner asks to inspect a visible design.
Existing image generation and project-writing tools remain the sole execution
paths, including real SVG/text assets where appropriate; their save-location,
worker, cancellation and Activity View rules remain unchanged.

**Named limits:** native Figma, Canva, Photoshop, Illustrator, printer and
vector-editor control is not claimed unless a real tool is connected. Visual
critique needs an available screenshot/vision provider; otherwise ZENO reports
that limitation instead of inventing observations. An image generation or
project write is not reported as completed until its existing tool returns a
real result.

**Regression coverage:** `tests/test_design_learning.py` verifies FAST/DEEP
routing, original/evidence-based design policy, local persistent/adaptive
learning progress, generic learning paths, lazy tool registration, ZEAL scope,
and that design/learning remain prompt policy on the existing provider turn.

---

## JARVIS systems integration and situational intelligence -- DONE

JARVIS is the fourteenth registered ZENO specialist, not a second executive
brain or a permanently running renderer. It starts only when ZENO delegates
real work, uses the existing bounded specialist queue, permission engine,
cancellation path, Event Bus and serialized Voice Manager, and reports back to
ZENO. Its three bounded workers are TELEMETRY (measured runtime/context),
CONDUIT (mission state) and FLIGHTDECK (explicit owner-requested interface
operations). All worker tools remain subsets of JARVIS's own scope. The voice
profile uses ZENO's configured voice unless `ELEVENLABS_VOICE_JARVIS` is set to
an original owner-configured voice; no film performance or voice is copied.

Claude's `awareness.py` and `anticipation.py` are integrated into the same
brain as cached prompt context and into JARVIS's audit tools. They add no
sensor, thread, poller or scheduler. Awareness fuses existing foreground-app,
idle, task, battery and local-calendar evidence; anticipation learns only from
the newest bounded executable-name samples and never reads window titles.
Predictions below the evidence threshold remain absent. Two integration bugs
were corrected before acceptance: the calendar query now uses the real
`due_at` column, and the learner keeps the newest 20,000 records instead of the
oldest records forever.

The **JARVIS Systems HUD** is a lazy command-palette view backed by
`/api/situation` and the existing Event Bus. It displays measured runtime,
mission, provider, Event Bus, situational and learned-pattern evidence. It does
not claim fictional hardware. Opening it creates one EventSource and one
two-second measurement timer; closing it closes the source, clears the timer
and removes the DOM. It uses CSS only: no WebGL, canvas, particle loop or
`requestAnimationFrame`. Desktop and 390x844 layouts were rendered and checked
with zero horizontal overflow; closing left zero HUD elements.

**Measured live (2026-08-10):** staged startup reached READY in 2.61 seconds.
A real Gemini turn delegated to JARVIS, called measured system health, returned
CPU/RAM evidence in 47.57 seconds under severe machine pressure, published the
full waiting/thinking/working/success lifecycle, and left the worker healthy
with an empty queue. The post-restart situation endpoint returned 14 agents,
2,889 real activity samples and the new 16.9 KB HUD module. A cold standalone
awareness fusion measured 744.59 ms and anticipation learning 35.15 ms on a
90% RAM machine; both run on a managed background turn, not the GUI thread,
and their combined cached path measured 0.019 ms.

---

## External intelligence foundation — PHASE 2 STEPS 6–10 — READY WITH LIMITATIONS (2026-08-10)

Phase 1 (`f00505c`) was audited before integration. Its LiveKit, Microsoft
Agent Framework, CUA, OmniParser and browser-use seams remain lazy and retain
the existing conventional voice, bounded agent runtime, UI Automation and
Playwright fallbacks. One false-success path in deterministic computer control
was corrected: a queued, blocked or failed tool result is no longer returned
as a successful device action.

**Memory:** `reyes_agent/memory/` now provides one selective memory manager
over canonical Living Memory, a bounded session store and an optional lazy
Mem0 semantic index. Stable preferences, explicitly requested context and
verified project/agent lessons may become durable; secrets, raw large inputs
and temporary status do not. Retrieval happens before planning, is relevance
ranked and bounded, and the Mem0 call has a 1.5-second managed timeout. Legacy
records can be previewed and copied into Mem0 without deleting the originals.
Mem0 is not installed or enabled on this machine, so Living Memory is the
tested live backend.

**Wake word:** `reyes_agent/wake/` implements one deterministic state machine,
energy VAD, cooldown, consecutive-hit filtering and a lazy openWakeWord ONNX
adapter. It consumes 16 kHz PCM from the already-authorized Mini Orb WebView2
stream and never opens a second microphone. The package is installed, but no
trusted custom ZENO model is configured; local ZENO/Hey ZENO/Yo ZENO scoring
therefore reports `MODEL_NOT_CONFIGURED` and the existing VAD-bounded Deepgram
phrase fallback remains active. This is an explicit incomplete deployment
item, not reported as local detection.

**Coding specialist and MCP:** TOSIN owns the optional Open Interpreter exec
adapter. It is workspace-contained, shell-free, permission classified,
time-bounded, output-capped at 1 MiB and never uses auto-run; the executable is
not installed here, so existing confirmed file/command tools remain its live
fallback. MCP 2.0 is now a core dependency. The central bus uses an explicit
allowlist plus trust and capability declarations, copies only named
environment variables, supports `CONNECTED`/`DISCONNECTED`/`DEGRADED`/`FAILED`,
caps concurrency at two and opens finite stdio sessions only on a real call.
A real local MCP 2.0 discovery/call/redaction round trip passes; no production
server is configured or trusted automatically.

**Device/lifecycle/health:** one `local-windows` device adapter wraps the
existing Phase 1 hybrid controller with a per-device foreground lock. Future
device types are interface values only; there is no distributed daemon. One
observable execution trace now covers understand → retrieve → plan → select →
execute → observe → verify → store → respond, with explicit autonomy levels
0–4 and at most two recorded recovery attempts. Capability policy is enforced
for every registered tool, actual monetary actions remain structurally
blocked, and structured `ok=false` results cannot become verification
evidence. `/api/health` is an on-demand truth API with no monitor thread.

**Measured verification:** 26 Phase 2 contract tests pass, including the real
MCP stdio round trip and out-of-order startup completion; the final complete
41-file standalone suite passed in 169.7 seconds. A live Playwright
cycle opened `https://example.com` in 9.64 seconds cold, read the rendered page
in 168 ms and closed the saved context. Staged backend startup changed from
2,612.7 ms to 2,600.9 ms in the final post-change restart. A startup race found
under pressure was fixed: the last-finishing core worker can no longer regress
`ready` back to `executive_ready`. A real Gemini reply completed in 14.77
seconds and its ElevenLabs generation in 5.79 seconds. No new scheduler,
permanent poller, agent worker, browser process or microphone owner is created
by Phase 2 while idle.

**Known limits:** this 8 GiB machine was at 83% system CPU and 89% RAM during
the normal-workload sample. The complete ZENO/WebView2 tree measured 10.08%
CPU, 607.3 MiB and 189 threads over ten seconds; 8.95% was WebView2 and 4.61%
was its GPU process. Those visual costs pre-exist this lazy backend phase and
remain above the desired isolated target. Mem0, Open Interpreter and a custom
ZENO wake model are not deployed. LiveKit, Microsoft Agent Framework,
OmniParser and browser-use are also not installed/enabled; their tested
fallbacks remain active. See `PHASE2_INTEGRATION_REPORT.md` for the complete
architecture, dependency, test and deployment record.

After the live provider/TTS run, system RAM reached 94% and the event-loop
probe recorded delays from 211 ms to 1.31 seconds. A live all-thread capture
found the server main thread idle in Windows IOCP, all four bounded workers
waiting on an empty queue, the scheduler waiting on its condition and no lock,
future, provider or tool held on the event loop. Ten status probes ranged from
36 ms to 16.8 seconds during the same machine-wide paging episode. This is
not claimed fixed or attributed to a Python deadlock; isolated-machine
validation remains required.

### JARVIS verification and limits (continued from the JARVIS section above Phase 2)

**Verification:** all 39 standalone regression files passed in 159.5 seconds;
Python compilation, JavaScript syntax and `git diff --check` passed. This
includes 16 awareness honesty tests, 5 awareness/JARVIS integration tests, 6
HUD/specialist tests, all 14 specialist operational checks and all 77 bounded
worker-team checks.

**Honest limits:** this is an original ZENO armored-systems interface, not
Marvel artwork, dialogue, hardware or an impersonated voice. JARVIS remains
OFFLINE until actually delegated (by design). Its first cold context fusion can
add under one second to a background AI turn on this pressured machine; it
does not block rendering and subsequent cached reads are effectively free.

---

## Phase 3 — Advanced capabilities foundation · READY WITH LIMITATIONS (2026-08-10)

Phase 3 adds one lazy integration catalogue, capability-aware model facade,
OpenAI routing, a contextual policy constitution, local redacted tracing,
explicit episodic-provider privacy, a working temporal fact graph, structured
document chunking, engineering/device/sandbox facades and optional external
service adapters. It reuses the existing kernel, worker pool, scheduler, Event
Bus, provider executor, Living Memory, workflow engine, permissions and single
microphone owner. No second scheduler, provider client, Event Bus or audio
listener was created.

Heavy capabilities are registered as dormant Stage 3 services and default
off. Screenpipe/ActivityWatch capture also requires the independent
`ZENO_EPISODIC_MEMORY_ENABLED` kill switch. The agent loads seven advanced tool
schemas only for relevant document/history/device/sandbox requests; ordinary
turns gain only the compact truthful `phase3_status` entry point.

Verified: 30 Phase 3 contracts, 38 Phase 1 integrations, 26 Phase 2 contracts,
15 Phase 21 and 9 Phase 22 tests pass. A live Gemini turn called the new status
tool and reported the real 5/25 enabled count. Local Ollama returned
`LOCAL_OK`. The restarted app reached staged backend READY in 2.652 s with
four workers, queue zero and no boot error; Mini Orb was the only visible ZENO
window. Isolated Phase 3 import cost 15.26 ms, 112 KiB and no thread.
The final complete repository run passed 42/42 standalone files in 156.1 s.
A validation-discovered `voice.stt` module-shadowing regression was corrected
before that clean run.

The final live worker audit also caught Windows notification WinRT calls
exceeding their managed deadlines and contending with voice transcription.
Those awaits are now two-second bounded, non-overlapping and circuit-backed;
their error log rotates. Six post-restart notification cycles completed with
zero failures, zero timeouts and zero overlaps while all four workers remained
available and the Mini Orb host reported responding.

Honest status: external Screenpipe, ActivityWatch, Graphiti, Docling, Sherpa,
OpenHands, mobile, smart-home, observability-exporter, OPA and n8n deployments
were not present, so adapters are not called production-ready. Host-to-HTTP
startup still measured about 8.3 s and the existing WebView2 tree remains the
dominant process cost under 88% system RAM. Full details are in
`PHASE3_ADVANCED_CAPABILITIES_REPORT.md`.
