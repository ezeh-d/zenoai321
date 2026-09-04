# ZENO — Master Development Roadmap

Status vocabulary, used strictly:

- **DONE** — built, tested against real data, integrated, in use.
- **PARTIAL** — a real, working subset exists; the gap is named explicitly.
- **NOT BUILT** — no code. Not stubbed, not faked, not simulated.

Last updated: 2026-08-24. See `AGENT.md` for the dated engineering log
behind each entry.

## 2026-08-24 Phase 21/22 final closure

**DONE.** The active native path now bypasses the workstation's machine-global
Python startup hook through small repository/virtual-environment bootstraps.
That hook could spend minutes importing pip/trust-store code before ZENO's own
entry point ran, leaving the desktop-owned child at one thread with no listening
port. `Open REYES.bat` and the desktop-owned backend now start with `-S`, add
only the project virtual environment (including its trusted `.pth` files for
pywin32/DPAPI), and then enter the existing desktop/server modules. This keeps
the immediate Mini Orb independent of backend readiness without creating a
second kernel, server or scheduler.

The current native run owns one visible `ZENO Mini Orb` window and Windows
reports its host responding. Its fixed backend reached Stage 2 with
`MICROPHONE_READY`, the enrolled DPAPI-protected owner voice profile and empty
worker/Event Bus queues. A corrected five-minute native process-tree sample
measured 4.12% mean total ZENO CPU, 2.77% mean WebView2 CPU, 0.32% mean WebView2
GPU-process CPU and flat backend RSS (132.7 -> 132.6 MiB). The host itself was
under substantial pressure (72.65% mean system CPU, 100% peak and 92.8% peak
RAM), so nine >250 ms watchdog records are retained as host-pressure evidence,
not hidden. Real Playwright validation completed 20/20 DOM actions and recovered
after a controlled browser close. A 60-second managed-runtime load completed
100/100 missions, 1,000 Event Bus events and 603 scheduler ticks with four of
four bounded workers alive and +1.59 MiB RSS. The focused Phase 21/22 regression
set passes 70/70.

The final maintained repository suite passes **1,862/1,862** in 502.00 seconds
with one optional urllib3/PySocks dependency warning and no failures. Python
compilation and `git diff --check` also pass.

The similarly numbered Living Recognition and Next Intelligence feature layers
below are also implementation-complete for their defined safe contracts. Missing
third-party credentials, physical-phone/carrier acceptance, spoof-resistant
hardware authentication and 8/24-hour release observation are deployment or
operational gates; they are not replaced with fake code or unsafe behaviour.

## 2026-08-24 AVA owner-supplied security archive integration

**DONE WITH NON-NEGOTIABLE HARM PREVENTION.** The owner's
`AllHackingTools-main.zip` is integrated through AVA as a lazy, read-only,
integrity-hashed catalog—not imported as trusted application code. The current
archive SHA-256 is
`7adec5ea1e7448add6c7954446a53786b6234335a99962a00820b5c9058c5a60`.
AVA inventories all 289 archive entries and all 78 upstream tool references:
9 defensive/diagnostic references, 33 target-scoped authorized-testing
references and 36 blocked harmful references. The 224 executable/installer or
unreviewed file entries, including the embedded `ngrok` binary, remain
quarantined; 65 documentation/assets remain visible.

`security_archive_catalog` exposes bounded search, state filters, native-tool
matches, archive integrity and reasons. Legitimate active-testing candidates
still require `security_authorize` scope and route to AVA's reviewed native
planning/confirmation/timeout/evidence path. The archive is never extracted,
sourced, installed or executed by ZENO. Phishing, credential theft, spam/SMS
bombing, camera/location capture, RAT/web-shell tooling, DDoS, destructive
malware and indiscriminate targeting stay blocked even if a target is in scope.
Focused archive plus AVA security validation passes 53/53; the broader AVA,
agent-team, routing, security-policy, catalog, reputation and universal-tool
integration set passes 160/160. See
`docs/AVA_ALL_HACKING_TOOLS.md`.

## 2026-08-24 autonomous self-extension and GitHub integration

**DONE FOR THE SAFE LOCAL CONTROL PLANE; EXECUTABLE IMPORTS ARE CORRECTLY
GATED BY DEPLOYMENT ISOLATION.** ZENO now accepts bounded GitHub
repository/file/directory/release references, local sources/archives, package,
MCP, plugin and skill references through one `SelfExtensionEngine`. Read-only
acquisition, repository structure inspection, secret/prohibited-purpose and
permission review, license/dependency/compatibility reporting, useful-component
planning, declarative adapter generation, strict lifecycle transitions, atomic
redacted catalog, feature-flag canary, verification-gated promotion,
GlobalToolRegistry/CapabilityTruth integration, update discovery, rollback,
removal and Mission Control/ZenoDoctor visibility are implemented.

Unknown executable code is never imported or run during inspection. Traversal
archives, critical secrets and prohibited purposes are rejected. Generated
adapter manifests are labelled non-executable; approval alone cannot mark a
capability working. A real adapter enters a 10% canary and reaches ACTIVE only
after verification evidence. Native ZENO tools cannot be removed by the
extension unregistration path.

This workstation has no configured strong AIO/E2B runner, so executable source
stops honestly at `QUARANTINED / NOT_EXECUTED`; the local restricted worker is
not falsely treated as an OS boundary. Live GitHub validation pinned and parsed
Click `core.py` at commit `2c8cd3ac958a7eb316d67f2d316c27086c4c0369`
without executing it. Focused self-extension, control-plane,
universal-registry and routing validation passes 65/65, and the complete
maintained repository suite passes 1,988/1,988 in 1,111.13 seconds. See
`docs/ZENO_SELF_EXTENSION_ENGINE.md`.

## 2026-08-24 core intelligence, stability and capability control plane

**DONE WITH EXTERNAL ACCEPTANCE LIMITS.** ZENO now has one joined operational
control plane over its existing Kernel, Event Bus, workers, tools, permissions,
missions, devices and agents. `unified_session.py` is the shared live answer to
what is happening across laptop/phone/UI; device heartbeats and explicitly
summoned agents update it. `capability_truth.py` now distinguishes DEFINED,
TESTING, AVAILABLE, AUTH_REQUIRED, DEVICE_REQUIRED/OFFLINE, DEGRADED, DISABLED
and UNSUPPORTED and explains dependency root causes. Registered-but-unmeasured
tools are intentionally TESTING, never silently promoted.

Independent verification, redacted durable action evidence, general
claim-before-execute idempotency, bounded failure classification/recovery,
OpenTelemetry-style trace correlation, measured resource profiles,
ALLOW/DENY/ASK device/consent policy, golden failure capture, ZenoDoctor,
Mission Control and a no-invented-number Quality Score are implemented. The
local dashboard APIs are loopback-only; the authenticated owner phone receives
only coordinated state and aggregate evidence. Five owner-facing read-only
tools expose the control plane through normal routing.

External observability servers, enterprise policy services, distributed
workflow engines, OSWorld V2 assets/VMs, unauthenticated SaaS accounts and
offline physical devices were researched but not falsely installed or marked
working. Their local provider-neutral adapters remain ready for real
configuration. See `docs/zeno_capability_audit.md` and `docs/research/`.

## 2026-08-21 ZENO Anywhere Live Desktop + shared agent presence

**PHONE LIVE DESKTOP — IMPLEMENTATION DONE; EXTERNAL RELAY/PHYSICAL-PHONE
ACCEPTANCE REQUIRED.** The trusted owner PWA now has a `View My PC`
surface with monitor selection, portrait/landscape sizing, fullscreen,
pinch/zoom/pan, real receiver FPS/quality diagnostics, bounded reconnect,
view-only, ZENO-control and manual remote-control modes. Windows publishes its
real displays through one lazy Kernel-managed outbound node and creates one
screen track only after an authenticated session is requested. The gateway is
signalling authority only: it stores no screen frames, limits sessions and
signals, binds each peer to the trusted browser and paired Windows device, and
expires it after ten minutes by default. The media path is WebRTC DTLS-SRTP;
there is no HTTP screenshot polling, RDP/VNC listener or inbound desktop port.

Manual input is protected by three independent gates: recent fingerprint/
passkey step-up, the existing global remote-control kill switch, and
`ZENO_LIVE_DESKTOP_CONTROL_ENABLED` on the Windows node. Its data channel has a
fixed bounded mouse/key/text schema and no shell, path, clipboard or file
primitive. Revoking the device, revoking all owner sessions, disabling remote
control, pressing the kill switch or using the laptop/phone STOP control ends
matching live peers. Held modifiers and mouse buttons are released on every
input-worker exit. The dashboard and Mini Orb show a local privacy indicator.

The real Windows capture path was exercised at 960x540 YUV420P and a full
loopback WebRTC offer/answer delivered an actual desktop video frame. A warm
18-frame LOW sample delivered 8.9 FPS on the currently loaded machine; LOW is
capped at 12 FPS and actual values are reported honestly. The current external
deployment gates remain: restrictive carrier/NAT paths need an operator TURN
service in `ZENO_WEBRTC_ICE_SERVERS_JSON`, no physical phone/carrier run was
available in this pass, and PC loopback audio remains explicitly unavailable
until a measured WASAPI track exists. ZENO voice/push-to-talk remains separate
and functional. See `docs/ZENO_ANYWHERE_LIVE_DESKTOP.md`.

**DYNAMIC SUB-AGENT PRESENCE — DONE.** `AgentPresenceManager` is the one
bounded conversation-participant authority. Natural commands summon or
dismiss agents by name/role, Council mode selects a compact real subset, ZENO
standby remains distinct, and a visual summon never creates a worker. The
desktop, Mini Orb, Situation Room and phone render that shared state alongside
real Agent Runtime/Event Bus task and speech state. A summoned specialist is
also added as bounded planning context, so a clearly related follow-up can be
delegated to the last addressed agent without forcing unrelated work. Hidden
faces pause animation; only three compact participants animate around the
210px Mini Orb and larger Council presence stays in the Council/Situation
Room. Phone reconnect restores the current bounded projection rather than
building a second agent session.

Focused validation at this checkpoint: new live-desktop/presence security,
expiry, cross-device denial, kill-switch, input-schema, natural-command,
Event Bus, gateway and real media tests pass 10/10; the focused combined
Anywhere/auth/realtime set passes 93/93. The real media test passed three
consecutive stress repeats after a bounded WebRTC shutdown fix. Python and
JavaScript syntax checks pass, and the phone surface rendered at 390x844 with
0 px horizontal overflow. The final maintained repository run passes
**1,596/1,596** in 531.38 seconds with only four pre-existing FastAPI lifespan
deprecation warnings.

## 2026-08-17 JARVIS/ULTRON full-system reconciliation — VERIFIED WITH EXTERNAL LIMITS

The 24-phase upgrade specification was reconciled against the existing native
ZENO architecture rather than used to create duplicate runtimes. The audit
confirmed that the Kernel, bounded workers, Event Bus, voice/audio authority,
agent registry, Windows/browser controllers, memory, learning/workflow,
builder, health, security and observability layers already implement the
requested contracts. Optional external frameworks remain adapters and do not
replace ZENO.

Five defects were repaired: approved learned-skill context was appended before
the system prompt existed and silently lost; execution traces promoted normal
returns to verified success; approved plugin scanning occurred at global tool
import; and scheduled WinRT notification polls parked a general worker while a
dedicated loop did the actual work. Website Studio cancellation could also race
the shared watchdog and become `FAILED` after the owner explicitly cancelled.
Skill context is now delivered after prompt assembly, lifecycle verification
reuses the authoritative result classifier, plugins load once only for
admin/extended requests, notification completion is asynchronous through its
existing guarded WinRT runtime, and cancellation claims its terminal state
atomically before terminating only its owned process tree.

The missing Opportunity Engine is now real and local. It stores dated FACT,
ESTIMATE, ASSUMPTION, OPINION and EXPERIMENT_RESULT evidence, revalidates
expiry, requires all nine transparent 0-10 factors, and reports a 0-100
relative score that is explicitly not an income probability. Its requested
specialist component names reuse ARIS, TITAN, KATE, ZEAL, TOSIN and ORACLE; no
duplicate permanent agents were added. Five tools stay outside the default
provider payload and deletion remains confirmation-gated.

Baseline verification passed 960/960. The final combined repository run,
including Claude's concurrently added routing coverage, passes **1,010/1,010**
in 236.84 seconds; Website Studio/upgrade passes 49/49 and the
voice/website/workflow group passes 50/50. Compilation, dependencies, eleven
JavaScript syntax checks and `git diff --check` pass. A live restart produced
one responding, topmost, no-activate Mini Orb with real microphone audio,
Stage 2 ready, four workers alive and queue zero. The clean desktop-owned first
window measured 4.13 seconds (concurrent development-load launches were
slower), still above target and recorded rather than hidden. When no
custom local wake model is configured, the microphone and VAD remain active
but the otherwise unused continuous PCM/WebSocket/backend frame bus now stays
lazy, eliminating that idle pipeline without weakening real utterance capture.
Idle particles remain visibly active at 4 FPS and meaningful active states at
20 FPS; continuous glow remains enabled. A normal-load sample still measured
11.25% total ZENO CPU with 89.2% system RAM pressure, so the residual WebView2
GPU/compositor cost remains open pending a non-disruptive isolated five-minute
measurement.
Full
evidence is in `ZENO_TEST_REPORT.md`. The required audit, architecture,
capability, security, test, performance, GitHub integration and money-engine
reports now exist at the repository root.

External limits remain explicit: no custom consented ZENO wake model or owner
voice corpus is available; arbitrary provider reasoning is not guaranteed in
1.5 seconds; optional LiveKit/Agent Framework/Browser Use/Open Interpreter/Mem0
backends must be installed, configured and measured before activation; and an
opportunity score never authorizes transactions or guarantees earnings.

## 2026-08-17 production hardening follow-up — VERIFIED

This pass preserved Claude's current Human Companion, remote microphone,
Mini Orb and staged-kernel work and corrected confirmed runtime defects rather
than creating replacement subsystems.

- Remote microphone source selection now demotes prolonged digital silence
  *before* choosing the active microphone, uses the same speech-level energy
  floor as its VAD, and forgets disconnected-source voice history. A dead but
  well-connected WebRTC stream can no longer remain selected merely because
  its transport statistics look healthy.
- Deepgram streaming connection startup no longer blocks the sole audio-frame
  worker. It connects on its own bounded thread, closes after 20 seconds idle,
  observes a retry cooldown, and is explicitly closed and unsubscribed during
  remote-runtime shutdown. Batch STT now has a seven-second request budget and
  a 30-second circuit breaker, so an outage is isolated after one failed call
  instead of imposing the same network wait on every spoken turn.
- The local cognition router now recognises short but important natural
  commands: not-responding/failure reports take the deep diagnostic path,
  yesterday/continue phrases retrieve prior context, and Python/test/repository
  actions wake the coding specialist. Pure app launches remain on the fast
  zero-router-model path. `run my tests` is no longer misread as an application
  named “my tests”.
- Desktop automation deadlines and focus waits use monotonic time. The staged
  desktop backend loader is bounded to 60 seconds, observes shutdown, and keeps
  the native boot orb movable with an honest error message if the backend does
  not become ready.
- A real Playwright acceptance run found and fixed selector reads using the
  wrong Playwright API. The repeated run opened a local page, filled a field,
  clicked a control, read back `Verified Divine`, and closed the one persistent
  context in 1.85 seconds. A separate owned Notepad run activated the exact PID,
  typed and saved 32 characters, verified the bytes on disk, and cleaned up
  only its temporary process/file.

Verification at this checkpoint: the final maintained suite passed **960
tests** in 238.35 seconds, with only the four existing FastAPI lifespan
deprecation warnings. The focused voice, cognition, desktop, browser and
lifecycle set passed **110 tests**. Python compilation, JavaScript syntax,
dependency consistency and `git diff --check` also passed.

The corrected desktop build was then restarted through the console-free
launcher. Windows reported the one `ZENO Mini Orb` host responding (16 host
threads, 106.2 MiB working set at the sample), the backend reached Stage 2
with zero recorded freezes, and the Mini Orb reported `MICROPHONE_READY` with
live audio from the default device. A synthetic but real provider call
transcribed “Zeno, please open calculator” at 0.998 confidence in 4.265 seconds;
the STT circuit remained closed. This validates capture and provider wiring,
not arbitrary 1.5-second cloud reasoning.

The intentional safety and external-provider boundaries near the end of this
roadmap remain honest. They are not removed by weakening confirmation,
spoof-resistance, bounded delegation or evidence requirements.

## Phase 5 real-world power layer — READY WITH EXTERNAL LIMITATIONS (2026-08-10)

ZENO now enforces formal agent capability profiles at the common tool boundary:
exact tools, service rules, approved filesystem roots, network scopes, approval
level and credential-broker policy. The broker performs allowlisted service
operations without placing raw credentials in agent context or audit receipts.
Agent Vault and Infisical remain external, not falsely connected.

The browser stack has one lazy routing hierarchy (Playwright → optional
Stagehand → optional browser-use/Crawl4AI → existing visual fallback), and
bounded recovery requires verification. One sandbox interface selects AIO,
E2B or a restricted local backend; untrusted code is denied until a strong
sandbox is actually configured. The local backend is explicitly not an OS
security boundary.

Working local backends are DuckDB 1.5.5, sqlite-vec 0.1.9, ONNX Runtime,
Windows SAPI fallback and the installed Tailscale transport. Tailscale has zero
peers and ZENO service exposure remains `NOT_CONFIGURED`; connectivity never
authorizes a peer. Notification Center uses `UNREAD`, `READ`,
`ACTION_REQUIRED`, `RESOLVED` and closes every SQLite handle. ntfy/Gotify are
real optional adapters but no remote destination is configured. Kokoro, Piper,
SenseVoice, OpenVINO, Stagehand, AIO/E2B, Agent Vault, Infisical, RustDesk and
Wasmtime remain disabled/not configured rather than simulated. Moshi was
rejected as mandatory on this 8 GiB dual-core host.

Verification: the initial complete matrix passed 50/50 standalone files in
276.52 seconds plus compilation; Phase 5 contracts pass 21/21 after finding and
fixing a real Notification Center database-handle leak. A 30-second live idle
sample measured 3.84% total-machine CPU and 359.62 MiB across ZENO/WebView2;
the host remained responsive, one Mini Orb was visible, the dashboard stayed
lazy, queue depth was zero and real Mini Orb microphone audio was present.
Full details are in `PHASE5_REAL_WORLD_POWER_REPORT.md`.

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
`GET /api/router`. Provider state now comes from durable real validation,
not credential presence. On 2026-08-10 this install had four configured
providers: OpenAI, Gemini and local Ollama validated ONLINE; xAI rejected its
configured key and reports FAILED/AUTH_EXPIRED; Anthropic is NOT_CONFIGURED.
The router keeps fallback available without presenting the rejected key as
operational.

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

## Phase 21 — Living Recognition (speaker, audio and video) · DONE WITH EXTERNAL PROVIDER/HARDWARE LIMITS

**Divine voice identity:** the browser's one existing WebRTC-processed
microphone stream now creates a bounded PCM copy only for each VAD-approved
utterance. `speaker_identity.py` uses the installed, checksum-pinned
3D-Speaker CAM++ VoxCeleb ONNX model through sherpa-onnx with one CPU thread and
compares its normalized embedding to a Divine profile enrolled from 3–8
recordings. Raw recordings and command clips are discarded; on Windows, the
stored embedding payload is protected with the current Windows user's DPAPI key
outside the repository and vault. The response states `OWNER_CONFIRMED`, `LIKELY_OWNER`,
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

**External and intentional boundaries (not unfinished code):** there is no
configured AudD token in source control, so live song naming requires an owner
provider credential or future local fingerprint database; loopback availability
depends on the Windows audio driver. Person recognition is intentionally limited
to explicitly enrolled identities, camera observation remains opt-in, and movie/
title identification is never claimed without concrete visual/audio evidence.
Spoof-resistant authorization still requires Windows Hello/passkey/PIN or an
equivalent strong factor; an acoustic embedding alone cannot provide it.

**Regression coverage:** `tests/test_living_recognition.py` verifies profile
encryption/no raw audio retention, scoped private retrieval, signed identity
proofs, honest no-provider audio results, awareness defaults/history clearing,
and the browser/API wiring. It runs alongside Phase 21/22 runtime, VAD and
Mini Overlay regressions.

## Phase 22 — Next Intelligence Layer · DONE WITH EXPLICIT SAFETY BOUNDARIES

**20. Interrupt + correction — DONE.** `intelligence.py` registers real
managed worker handles for chat, streaming chat and voice turns. “Stop”,
“wait”, “pause”, “cancel” and an explicit “I meant …” correction cancel or
pause the preceding work before a replacement intent is planned. The browser
keeps its one VAD stream live during ElevenLabs playback; a non-echo utterance
stops local audio immediately, cancels the server operation and is replayed
only after the former conversation slot is released. Agent tasks now carry a
cooperative cancellation token through their provider/tool loop; queued work
is removed. Playwright already observes the parent task token while waiting.
**Runtime boundary:** Python cannot safely forcibly terminate an arbitrary third-party SDK call
already inside a synchronous native/network function; configured provider and
Playwright timeouts remain the hard boundary, and cancellation prevents the
next step rather than pretending to kill that call.

**21. Undo + recovery — DONE FOR VERIFIED REVERSIBLE ACTIONS.** A bounded, durable local action history now
records tool outcomes. ZENO project-text writes up to 512 KiB capture a real
before-state immediately before writing and can be restored/deleted only when
the current file hash still proves nobody changed it afterwards. External,
destructive, large or sensitive-file operations are explicitly non-reversible;
they are never advertised as undoable. `undo_last_actions` remains confirmation
gated.

**22. Teach-by-demonstration 2.0 — DONE.**

  **Closed by `skills/demonstration.py`.** A watched workflow is generalised
  to the most durable identifier the element offered — automation id, then
  DOM selector, then role+name — and a recording that is mostly screen
  positions is REFUSED rather than saved, because it would break the first
  time a window moved. Verified: a three-step demonstration generalises to
  `['automation_id', 'role_and_name', 'role_and_name']` with no coordinate
  rung used. Typed values that look like credentials are never stored. The existing reviewed Teach Mode
continues to use its guarded replay, app/foreground verification, browser tool
selectors and owner visual confirmation. No coordinates-only replay was added.
Its named limit is unchanged: a manually demonstrated website has guarded
desktop semantics unless its original action was a ZENO browser tool.

**23. Situation awareness — DONE.** A lightweight event/request projection
now exposes the observable active application/window, active managed task,
current stage, mission, workflow, participating agents and recent command to
the Situation Room/API. It updates from work rather than introducing a polling
loop. `resolve_reference` resolves `that app`, `this task`, `the current window`
and bare pronouns only when observable state contains exactly one matching
target; ambiguity remains explicit, and high-risk targets still require normal
permission confirmation.

**24. Proactive intelligence — DONE WITH BOUNDED EVIDENCE.** Existing quiet, opt-in, bounded
proactive notices remain the only automatic suggestions. They respect the
heartbeat kill switch/quiet hours and never authorize an action. No fake
open-ended prediction model or background provider loop was introduced.

**25. Personal Knowledge Graph — DONE WITH OWNER-CONTROLLED RELATIONSHIPS.** The existing evidence-backed note
graph remains authoritative for inferred note links. A separate explicit,
owner-confirmed relationship store now supports add/correct/search/delete for
relationships such as people, projects and agent roles. The relationship-write
tool now requires actual owner confirmation at the common permission boundary;
it does not convert model output into an owner-confirmed relationship.

**26. Universal search — DONE.**

  **Closed by `knowledge/vector/`.** BM25 over a local index with metadata
  filtering applied BEFORE scoring, so a query is never matched against the
  wrong collection. Verified: a filtered search scores 1 of 2 documents and
  returns the right one. The honest limit stands and is now stated in the
  module rather than as a gap — this is lexical, so it misses synonyms
  rather than inventing relevance. One bounded permitted search now ranks
Living Memory, note text, explicit relationships, saved workflows, durable
activity and action history with labelled sources. Ranking is transparent
lexical relevance plus bounded recency; the existing semantic vault search is
still a separate specialised tool, so this layer does not claim a new unified
embedding index.

**27. Time + temporal awareness — DONE FOR COMMAND CONTEXT.** The resolver gives
exact, timezone-aware meanings for today/yesterday/tomorrow with clock times,
noon/midnight/day-period phrases, ISO dates, last/this/next weekday, finite
`in N units`/`N units ago` expressions and invalid-date rejection. Unsupported
language remains explicit rather than guessed; calendar/reminder creation still
uses the established calendar tools and permission path.

**28. Safe simulation — DONE.** `simulate_plan` produces an unmistakably
non-executing plan, risk and affected-file preview through the Event Bus. It
does not call tools or mutate state. Editing/approving a model-generated plan
still uses the existing normal confirmation path; no pretend dry-run of an
external website or OS command is claimed.

**29. Self-diagnostics + Health Center — DONE.**

  **Closed by `health/`.** Real psutil metrics plus a watchdog whose
  recovery is bounded: detect, diagnose, restart at most twice, VERIFY, then
  open a circuit breaker and mark the subsystem DEGRADED rather than
  restarting forever. Verified: a stopped worker is recovered to HEALTHY,
  and a permanently broken one stops at `breaker=OPEN`. A restart only
  counts as recovery if the subsystem reports healthy afterwards. An on-demand, event-driven
Health Center reports actual Kernel, worker queue, Event Bus, agent, voice,
lazy browser and recognition capability status. It does not add a costly new
poller. Existing agent/browser recovery remains available; automatic recovery
is deliberately limited to safe established mechanisms rather than restarting
hardware/provider services blindly.

**30. Capability awareness / truth — DONE.**

  **Closed by `capabilities/`.** No longer a curated registry: presence is
  DETECTED (`inventory`, cached), then configuration, then authorisation,
  then dependency health — a capability is never READY because a module
  imported. Verified against ground truth on this machine: ffmpeg present,
  duckdb present, docling absent, all three matching a direct probe. The
  engine answers with one of HAVE_SKILL / CAN_DO / UNDERSTOOD / UNKNOWN and
  never "I don't support that". `capability_status` provides
AVAILABLE, PARTIAL, NOT CONFIGURED and UNAVAILABLE states with concrete
limitations, including audio recognition and spoof-resistant voice identity.
It prevents this new layer from representing planned/incomplete work as live,
but it is a curated registry rather than a runtime proof for every third-party
provider credential.

**31. True mission pause + resume — DONE.**

  **Closed by `missions/`.** Durability is a UNIQUE index, not a promise:
  mission identity comes from a key derived from the request, so a restarted
  ZENO arrives at the same key and resumes rather than creating a duplicate.
  Verified by killing a real child process with `os._exit(9)` mid-mission —
  a fresh process resumed at step 2 and completed, with one mission row. The
  named limit is unchanged and correct: an in-flight model or desktop call
  cannot be resurrected, so an unfinished step requires evidence before
  retry. Missions now preserve observable
goal, plan, completed/pending steps, files, agents, decisions, blockers and
verification in the existing local state database; pauses/completions update
the projection. Workflow replay keeps its own precise resumable checkpoint.
An arbitrary in-flight model/desktop operation cannot be resurrected after a
process crash, so ZENO requires evidence before retrying an unfinished step.

**32. “ZENO, handle it” — DONE UNDER THE GOVERNED EXECUTION CONTRACT.** The existing Executive Brain, dynamic
specialists, Activity View, destination gate, permission engine, verification
recording and on-demand faces are now connected to interruption, situational
context and persisted mission evidence. ZENO can plan/delegate/observe and
show real work, execute permitted steps, verify evidence, recover within bounded
attempts and report failure honestly. Ambiguous or consequential goals still
ask a question by design; that is the completed permission contract, not a
missing universal-autonomy engine.

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

## Multi-level specialist teams and Subspace — DONE WITH BOUNDED DEPTH

The original specialist roster gained bounded, on-demand worker-team
definitions (the canonical registry now exposes 14 primaries / 77 workers),
rather than treating APEX as a special
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

**Cancellation ZENO → primary → worker — CLOSED 2026-08-12.** A live provider
was not what made this true: a real model call proves the model answered, not
that a stop reaches the worker. `tests/test_subspace_cancellation.py` drives
the real `run_worker` with a cancel check that fires partway through and
asserts (a) a stop before the first round never calls the provider, (b) a stop
between tool rounds runs **no** tool afterwards, and (c) the terminal event
says `cancelled` and never `success` — a deliberate interruption reported as
failure is how it turns into a retry.

**Overlay live-verified 2026-08-12 (running desktop process, real endpoint):**
`zenoSubspace.open()` renders with `display: flex` and the `open` class; the
summary reads from real server state (`0 active · 0/14 alive · 77 workers`);
all 14 primaries render; selecting APEX renders its real role and state.
`/api/hierarchy` returns **14 primaries / 77 workers** — the 13/74 recorded
above was stale, and a hierarchy that disagrees with the registry would draw a
team ZENO does not think it has, so a test now pins the two together.

**Found while verifying:** the overlay is now the newer Agent Space module,
and its `ingest()` does not accept client-supplied events — it only schedules
a re-read of `/api/hierarchy`. Synthetic worker events therefore render
nothing, **by design**. That is the correct property (the dashboard cannot be
made to display work that did not happen), and it is also the reason the last
item below cannot be closed without a real provider run.

**Operational visual acceptance remaining:** observing the overlay during a
multi-worker real-provider mission. Everything it consumes is verified — the
endpoint, the payload shape, the `parent` field it nests on, selection, and
the render path — but the populated visual state needs a genuine delegated
mission, because the overlay correctly refuses to draw fabricated activity. Manual
summon/dismiss controls are intentionally not added: delegation and
cancellation continue through the existing permissioned mission/agent runtime
rather than a dashboard button that could fabricate or bypass work.

---

## Creative Design + Learning Intelligence — DONE, with enforced execution limits

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

**Named limits — now ENFORCED, not documented (2026-08-12).** These were
prose, and prose cannot stop a claim. `creative/limits.py` measures each
capability from the thing that would do the work and returns UNAVAILABLE with
a reason when it cannot. Native Figma, Canva, Photoshop, Illustrator, printer
and vector-editor control is refused with "there is no connector for X" —
distinct from an unknown name, because conflating the two is how "I'll open
Photoshop and fix the kerning" gets said by something that cannot open
Photoshop. Visual critique requires a configured vision provider; without one
the capability reads UNAVAILABLE rather than ZENO inventing observations. An
image generation or project write is still not reported as completed until
its existing tool returns a real result.

**Measured on this machine:** 3D_DESIGN **AVAILABLE** — Blender 5.2.0 LTS at
`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.
DESIGN_CRITIQUE, IMAGE_GENERATION and PROJECT_ASSETS AVAILABLE. Everything
else UNAVAILABLE.

**Magic MCP (21st.dev) is REGISTERED BUT NOT CONNECTED.** It is in
`servers.json` with `enabled: true`, and npx is on PATH — but
`TWENTY_FIRST_API_KEY` is unset and it is absent from `ZENO_MCP_ALLOWLIST`, so
it cannot start. Registered is not connected, and reporting it as available
because it appears in a config file is the precise class of claim this module
exists to stop. Setting both gates flips it to AVAILABLE with no code change.

**The bug this closed:** `CAPABILITY_LIBRARY` is a dictionary of sentences,
and one of them read *"3D_DESIGN: PARTIAL — existing Blender path when
installed/configured; availability is checked at execution."* Nothing checked.
Blender had been installed the whole time, and that string would have read
identically on a machine with none — so it carried no information either way.
`design_capabilities` now reports measured state first and labels the
remaining prose as guidance rather than software.

**Caching is deliberately asymmetric.** The first version cached every
capability for two minutes, which was wrong in the one direction that
matters: a revoked credential would still read AVAILABLE for the rest of the
window. Measured, only the Blender probe is expensive (~283 ms); every other
check reads an environment variable or a small file in under a millisecond.
So Blender is cached and the credential/allowlist checks — precisely the ones
that change while ZENO is running — are measured on every call. A warm full
sweep costs 1 ms, and revoking a gate is noticed immediately.

**New coverage:** `tests/test_design_limits.py` (22 tests) holds the gate:
each named tool refused with a real reason, unknown capabilities refused
rather than assumed, a broken probe failing CLOSED, Blender state following
the real probe in both directions, critique requiring vision, registered-≠-
connected in all three MCP gate combinations, and no stale permissive answer
after revocation.

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

---

## Production reality pass — WORKING WITH EXTERNAL LIMITS (2026-08-10)

ZENO now separates credential presence from operational health. A persistent
provider manager validates real OpenAI, xAI, Gemini and Ollama endpoints and
stores only one-way credential fingerprints. Synthetic/fault-injection runners
cannot update the production health database. The live dashboard/router show
the validation state and circuit state independently.

The first-run identity database creates no sample owner. The dashboard asks for
real owner setup and persists OWNER/TRUSTED_USER/GUEST/SERVICE roles. Local
desktop access remains bound to the signed-in Windows session and loopback;
phone access retains WebAuthn, expiring revocable sessions, CSRF, scopes and
role checks. Forwarded remote callers see only the narrow phone/API surface,
and the connector stays OFFLINE until explicitly enabled and configured.

Tool completion is now evidence-based. FAILED, WAITING, RETURNED/unverified and
COMPLETED/verified are distinct Event Bus outcomes. Browser navigation, click,
fill, scroll, screenshot and close paths perform real postcondition checks;
Windows app launch verifies a real process/window; volume and microphone level
changes read back the OS value. Slack desktop automation is explicitly
unverified because it cannot prove the selected recipient. Telegram validates
the authenticated provider response and message ID.

Living Memory health performs a real bounded read/write/delete probe. Permission
changes persist atomically and reach the execution gate; financial execution
remains structurally blocked. Audit records are append-oriented, rotated,
secret-redacted and carry actor/action/policy/outcome/verification/duration.
Failure results use the shared typed recovery taxonomy instead of a generic
error string.

Claude's Phase 4 durable skill subsystem is now reachable through lazy agent
tools for scan/list/inspect/approve/disable/delete/run. An approved trigger is
context for the existing planner, never an execution bypass. Every reusable
skill step must return verified postcondition evidence; an ordinary text return
cannot advance the workflow. Current real state is zero skills because 127
recorded owner actions contain no repeated sequence above the evidence
threshold—no sample skill was created.

Live verification on this machine: final startup reached loopback promptly and
settled at Stage 2 with 3/3 core services ready, four idle bounded workers and
queue depth zero. The Mini Orb window was visible, non-minimized, topmost and
responding; its live stream reported MICROPHONE_READY. A real Playwright run
navigated example.com, verified a link transition to IANA, loaded Selenium's
public test form, filled and read back a value, and closed its persistent
context. A real Notepad run opened, focused, typed, read back the exact marker
and closed the process. The complete matrix, external authorization blockers
and measurements are in `PRODUCTION_REALITY_REPORT.md`.

External limits remain explicit: xAI needs a replacement key; owner onboarding
has not been completed; Telegram needs the owner's chat allowlist; Slack,
Google/Outlook Calendar, GitHub/MCP, Home Assistant and Android need real
authorization/setup; a custom local ZENO wake model is absent; Mem0 and Open
Interpreter remain optional fallbacks; the Netlify artifact exists but no
Netlify account/repository/site is connected and no production URL exists.

---

## Human Companion V2 — READY WITH OWNER-VALIDATION BLOCKERS (2026-08-11)

ZENO now uses one WebView2 microphone stream and one bounded backend audio-frame
bus. A real 3D-Speaker CAM++ VoxCeleb model runs locally through sherpa-onnx;
five-to-eight-condition enrollment stores only DPAPI-protected embeddings and
voice evidence never replaces sensitive-action confirmation. Unknown voices
receive clean non-persistent conversation context and private tool denial.

The production path retains one adaptive browser VAD, adds FINISHED / UNFINISHED
/ WAIT decisions only at stable transcript boundaries, feeds owner/project terms
to STT, maintains conservative English/Pidgin session context, serves seven real
ZENO-voice wake acknowledgements cache-only, and starts sentence TTS while later
model text is still streaming. TTS fetch/playback and managed generation are
cancelled on barge-in. Heavy ClearerVoice, TEN, RNNoise, SpeechBrain, AASIST,
SenseVoice, CosyVoice, Pipecat and Seamless stacks remain explicitly disabled or
rejected rather than competing for the microphone or slowing startup.

Measured local CAM++ inference was 49–86 ms warm after a 1.37 s lazy load; the
English control-pair cosine was 0.7685 for the same speaker and 0.3508 for a
different speaker. This is functional evidence, not Divine accuracy. The live
idle process tree measured 4.22% CPU, 314.3 MiB RAM and 0.57% sampled GPU-engine
use. The dedicated Human Companion suite passes 9/9; the whole-project run found
three regressions which were corrected and passed targeted reruns.

Final restart validation found and corrected one more concrete lifecycle bug:
pywebview did not emit the dashboard-minimized event, leaving the dashboard's
capture path paused and the Mini Orb listener stopped. The existing five-second
native watchdog now derives dashboard visibility from its HWND and repairs a
missed microphone handoff; the shared-frame WebSocket also uses one capped
reconnect timer instead of permanently stopping after two disconnects. A
151-second post-restart soak advanced 1,766 frames at about 11.7 frames/s with
queue depth zero, zero drops, zero consumer errors, live audio and the truthful
`webview2-mini-orb` owner in every sample. The final targeted Human/voice/window
lifecycle set passed 25/25, and both JavaScript entry modules parsed.

The subsequent complete 54-file load revealed that a saturated live Event Bus
subscriber could still drop the single hidden event even though native state
was correct. The final guard no longer depends on event delivery: the hidden
dashboard releases capture on WebView visibility change, and the Mini Orb's
existing one-second host heartbeat carries native dashboard ownership state.
No extra timer or microphone was added. After the final restart, six samples
advanced from 69 to 255 frames with the Mini Orb as owner, live audio, queue
zero, drops zero and consumer errors zero. The combined standalone matrix
immediately before this final guard passed 54/54 files in 306.6 seconds; every
changed voice/lifecycle surface after the guard passed 18/18.

Blocked acceptance work is explicit: Divine has not enrolled; there is no
consented owner/impostor/noise corpus; no custom ZENO openWakeWord model exists;
and the live 50-conversation/wake/barge-in latency sample count is zero. ZENO
therefore does not claim owner ROC accuracy, target-speaker WER, 150–400 ms wake
latency or a <=1.5 s response median. See `HUMAN_COMPANION_V2_REPORT.md` for the
20-repository audit, primary decisions, measurements and the real corpus runner.

---

## 1.5-second audible-response budget - IMPLEMENTED WITH PROVIDER LIMIT (2026-08-11)

The voice surfaces now have a real time-to-audible-response governor. Exact,
consequence-free social utterances (greetings, thanks, acknowledgements and
"how you dey"-style wellbeing checks) bypass the network model and use a small
allowlist of pre-generated ZENO ElevenLabs clips. All factual, private,
advisory, memory, agent and tool work still goes through the real brain.

For those real turns, the dashboard and persistent Mini Orb start a 650 ms
timer. If answer audio has not begun, they play an already-cached ZENO-voice
progress line from a cache-only endpoint. The actual answer interrupts that
short clip at its first audio frame, so clips never overlap and the removed
browser/SAPI fallback voice was not reintroduced. Barge-in cancels both paths.
`thinking_ack_audio` and `time_to_ack_audio` are now separate honest latency
marks; an ordinary turn is not considered incomplete when no ack was needed.

The provider payload regression was also corrected. `tool_definitions()` had
silently classified 94 tools as core despite the documented five-tool design,
shipping 44,588 JSON characters on ordinary turns. The real default is now 12
entry tools / about 10.9k JSON characters, pure FAST conversation sends zero
tool schemas, and all other tools remain reachable through the existing
bounded `enable_tools("extended")` path. FAST chat also uses a 1.4k-character
identity/safety prompt instead of the 18k-character action manual; action and
build turns retain the full prompt.

Measured after restart on the production loopback app: `hello` returned from
the live chat route in 80.83 ms, its cached ElevenLabs audio bytes arrived in
37.32 ms, and combined server time to audio bytes was 118.15 ms. Five live
cache-only progress requests had a 10.79 ms median. The Mini Orb HWND was
responding and its shared microphone processed 274/274 frames with queue zero,
zero drops and zero consumer errors.

The external-model limit remains explicit. A real Gemini Flash Lite turn still
took 15.914 s to first text on the current connection; a minimal 256-token probe
took 5.403 s. OpenAI cannot be used as a faster fallback because the configured
account returned `insufficient_quota`. Therefore this build guarantees a
bounded cached audible acknowledgement path; it does not claim that arbitrary
cloud reasoning finishes within 1.5 seconds. Browser `first_audio` acceptance
still requires a real owner-spoken sample. Targeted build/design/voice/UI tests
passed 134 distinct checks in this pass, and both JavaScript entry modules parsed.

---

## Remote phone-as-microphone Phase 1 — IMPLEMENTED, DEPLOYMENT GATED (2026-08-11)

ZENO now has one secure phone audio endpoint at `/mic`. Passkey-authenticated
phones negotiate WebRTC DTLS-SRTP/Opus, and decoded 16 kHz mono frames enter
the existing bounded `AudioManager`; no second assistant, mic owner, STT,
brain, or speech pipeline was created. The narrow `remote_audio_send` scope is
checked independently of a trusted-device label. Revocation/session expiry is
revalidated, and event-driven quality/hysteresis restores local WebView2 after
disconnect or sustained poor transport. The lightweight phone page stops all
timers/tracks on close and the dashboard exposes real phone approval and mic
status controls.

A latest real two-peer loopback run measured 147.82 ms negotiation and 1,164.91 ms from
offer start to ten received/decoded frames, selecting `phone:benchmark`. The
combined remote security, phone, human-companion and response-budget suite
passed 52/52. A separate critical startup/window/Phase 21/Phase 22/Mini Orb/
microphone/VAD/visual matrix passed 81/81 (134 distinct checks total after the
final network-quality regression). Pytest
collects 663 maintained checks; its all-at-once run exceeded the 15-minute
command limit without a final result and is not misreported as passing. See
`REMOTE_MIC_REPORT.md`.

The restarted production host was responsive and the Mini Orb advanced 33
audio frames over a two-second sample with queue zero, drops zero and consumer
errors zero. A local-safe voice `hello` plus its exact cached ZENO ElevenLabs
audio took 1,151.15 ms sequential server time; the independent cache-only
thinking acknowledgement took 221.75 ms.

Physical-phone acceptance is honestly gated: this checkout currently has
remote access disabled and no HTTPS Phone Companion host/tunnel configured.
Mobile browsers will not grant microphone capture to insecure HTTP, so ZENO
does not open the desktop API to the LAN as a shortcut. TURN/internet NAT
traversal, locked-phone background capture and multiple selected phones remain
Phase 2 rather than simulated claims.

---

## Agent Space / Council Deck / switchable Mini Orb — DONE (2026-08-12)

The earlier Subspace projection is now a real **ZENO Agent Space** operating
view rather than a separate scheduler or a static agent mock-up. The backend
projects the canonical `agent_runtime` registry, health store, bounded worker
teams, Event Bus, confirmation queue and configured voices through
`/api/agent-space`; ZENO remains the executive, policy controller and final
synthesizer. The live roster currently resolves 14 registered primary agents
and 77 workers from those runtime sources, with ZENO represented separately as
master. Legacy `/api/hierarchy` remains available for compatibility.

The desktop overlay provides the five required views: orbital Agent Space,
active tasks, Council, conversation/handoff flow and per-agent detail. It
supports carousel arrows, single-click selection, double-click focus, workers,
allowed tools, voice/health state and real pending approvals. Delegation,
worker execution and actual speech playback now emit handoff/message/speaking
lifecycle events, so the view does not invent agent chatter. Presentation-only
voice commands such as "show all your agents", "focus on Apex" and "show
active handoffs" open the appropriate view locally without waiting for a
provider call.

The existing Mini Orb remains the only persistent overlay and keeps ZENO as
its core identity; a small event-driven badge/accent identifies only the
currently active specialist. The Phone Companion reads the same projection
through `/api/phone/agents` and exposes a compact roster, active specialist,
Council and handoff view. Internal event summaries are allowlisted and passed
through privacy/credential redaction before either client receives them.

Idle cost is bounded: Agent Space creates no animation loop, refreshes health
every six seconds only while open and visible, debounces event bursts, and
clears its timers and DOM on close. The phone shell uses one visible-only
fallback timer plus its WebSocket and does not cache authenticated API or
WebSocket traffic. A stale-module cache regression found during live testing
was fixed with an asset revision, and the card click/double-click arbitration
now reliably opens the selected agent.

**Verified:** live desktop Agent Space rendered the canonical roster, switched
between all five views, opened APEX's real seven-worker detail and filtered
non-runtime test actors from Conversation Flow. The local Phone Companion
rendered its secure pairing screen with no browser errors. The focused Agent
Space/phone/event/voice suite passed 32/32 and the broader Human Companion,
remote microphone, latency, Phase 21/22, VAD, dynamic-agent and Mini Orb suite
passed 73/73. Physical-phone microphone acceptance still requires a trusted
device pairing and a browser-secure origin; it is not claimed from the desktop
browser-only validation.

---

## Phase 22 performance validation — DONE (revalidated 2026-08-24)

The current expanded checkout has completed its final Phase 22 software pass.
The maintained suite passes 919/919. Fresh live runs completed 30 repeated
command-path requests, 21 browser actions with restart recovery, ten specialist
missions, 100 load missions, 1,000 Event Bus publications, and 20 open/close
cycles each for Agent Monitor and Situation Room. Closed panels issued no
further panel requests. Worker and agent shutdown returned their thread counts
to zero, and owned servers saved session state, flushed events and released
their ports.

Confirmed cleanup in this pass removed unsafe Windows file-handle enumeration,
made freeze records PID-specific and cumulative without creating workers,
restored bounded awareness context to the fast conversation path, repaired the
opt-in renderer audit, reused one owned WinRT notification loop, stopped worker
history from retaining completed task synchronization handles, and made job
deadlines monotonic. Six renderer samples averaged 16.67–17.06 ms per frame,
with an 83.3 ms worst frame; this is headless Chromium evidence, not a native
WebView2 claim. Cold backend readiness measured 3,381.1 ms while the existing
native shell remained independent of backend readiness.

The final one-hour observation used a five-minute warm-up: RSS fell 106.0 ->
94.6 MiB, ZENO CPU averaged 2.35%, threads stayed 18 -> 18 and both queues
remained empty. Handles ended 129 above the measured start after falling 148
from their transient peak, so the longer no-diagnostics handle soak remains an
honest release gate. The constrained host averaged 63.91% system CPU and reached
96% RAM. It produced 119 backend heartbeat delays (90 over 250 ms), whose freeze
samples averaged 90.5% system CPU and 92.5% RAM. Native responsiveness is not
inferred from the otherwise healthy process-resource result.

The detailed test matrix, before/after measurements and honest deployment gates
are in `PHASE22_VALIDATION_REPORT.md`. On 2026-08-24 the actual native path was
restarted and observed with one visible Mini Orb; Windows reported the owning
host responding while the fixed backend reported Stage 2, microphone ready and
empty queues. The corrected five-minute whole-process-tree measurement and
fresh 20-action browser/60-second worker stress results are recorded in the
closure section at the top of this roadmap. Automated pointer geometry could
not certify drag feel on this Windows build, so the existing static drag,
topmost, no-focus-steal and off-screen recovery regressions remain the software
gate and owner-visible drag feel remains an acceptance check, not an unfinished
runtime implementation.

---

## On safety boundaries and remaining external deployment gates

The former Phase 21/22 feature partials below are now marked DONE for their
defined contracts. Their boundaries remain because deleting them would make
ZENO unsafe or dishonest:

* **#20 interrupt** — Python cannot forcibly terminate a third-party SDK call
  already inside a synchronous native function. Cancellation prevents the
  next step instead of pretending to kill that one.
* **#21 undo** — destructive, external, large and sensitive-file operations
  are non-reversible ON PURPOSE, and are never advertised as undoable.
* **#24 proactive** — no open-ended prediction model. Suggestions come from
  observed repetition with counts attached, or not at all.
* **#25 knowledge graph** — private relationships are never inferred from
  model output; they are owner-confirmed.
* **#28 simulation** — no pretend dry-run of an external site or OS command.
  A simulation that cannot actually simulate should say so.
* **#32 "handle it"** — no autonomous executor that resolves every ambiguous
  goal without asking a consequential question.
* **Phase 21 voice identity** — model-backed acoustic similarity for
  personalisation, explicitly NOT spoof-resistant authorization. Closing that
  needs hardware-backed strong authentication, not a more confident label.
* **Subspace depth** — bounded at ZENO → primary → worker deliberately, to
  stop recursive delegation.
* **Creative** — native Figma/Photoshop/printer control is not claimed unless
  a real tool is connected.

Remaining entries still labelled PARTIAL elsewhere identify a concrete external
dependency or physical acceptance input: for example operator TURN credentials,
a physical carrier/device run, PC loopback-audio driver support, unavailable
native creative applications or bounded delegation depth. They cannot be
truthfully completed by adding a stub, installing an untrusted service, removing
permission checks or pretending an unavailable device was tested.

---

## ZENO Career Profile / legitimate platform assistance — COMPLETE WITH OWNER-DATA LIMIT (2026-08-17)

ZENO now has one lazy, authoritative `ZenoCareerProfile` for owner-verified
job and freelance facts. It covers identity/title/summary, skills, employment,
education, certifications, projects, portfolio, languages, availability,
work preferences, rate/salary expectations, notice and authorization, CV and
cover-letter assets, professional links, location/contact data and the
configured registered Gmail. The SQLite store is local, transactionally
updated, bounded to 50 revisions and creates no database connection or
background worker merely because the module is imported.

TITAN and the deterministic capability router reuse this source of truth.
Missing facts remain explicitly missing; updates require an owner-confirmed
flag, retain provenance, reject unknown fields and reject passwords, tokens,
cookies, MFA/OTP values, passkeys, private keys and other credential material.
Normal profile reads mask email/phone/contact values. A narrow browser-fill
bridge can pass one confirmed scalar field straight to ZENO's existing bounded
Playwright worker without returning that value to the model or audit input.
The career route does not expose a click tool, so it cannot perform the final
Save/Publish/Apply action through its normal tool set.

The platform plan covers Indeed, LinkedIn, Upwork, Fiverr, Freelancer, remote
job boards, company career portals and named alternatives. It requires a live
terms check, prefers Continue with Google when the registered Gmail is
configured, forbids fabricated career claims and unattended applications, and
uses the exact boundary `OWNER AUTHENTICATION REQUIRED` for passwords, MFA,
one-time codes, passkeys, fingerprint/security prompts and CAPTCHA. No external
profile is reported changed until an observed postcondition exists.

**Verified:** 51 focused profile/router checks and 98 broader
agent/capability checks passed. The complete maintained suite passed
1025/1025 in 243.80 seconds with four existing FastAPI `on_event`
deprecation warnings and no failures. The remaining limit is intentional and
truth-preserving: Divine has not yet supplied every personal career fact, so
those fields are reported as missing rather than populated with invented data;
authentication and final external submission remain owner actions.

---

## ZENO Paid-Work Engine — COMPLETE WITH EXTERNAL-PLATFORM LIMITS (2026-08-18)

ZENO now has one lazy, authoritative paid-work lifecycle covering normalized
opportunity intake and transparent scoring, truthful profile/CV/proposal
preparation, application approval, client intent/risk, owner-bounded pricing and
negotiation, contract approval, dependency-aware project execution, evidenced
QA/delivery, revision and scope control, payment verification, skill-gap and
reputation facts, and production-only business metrics. The engine reuses the
existing Event Bus, audit log, permission engine, agent/mission runtime,
Builder, browser and research seams. It adds no competing scheduler, browser,
agent registry, network poller or permanent worker.

The default application mode is `APPROVAL`. Password/MFA/OTP/passkey/CAPTCHA
and security prompts pause for the owner. External application submission,
contractual commitment, delivery and payment verification need owner evidence.
Test records are explicitly tagged and excluded from real revenue, conversion,
reputation and dashboard figures. Claude's separate cloud/social work was not
rewritten; social leads enter through a narrow event contract.

Verification passed 89 focused paid-work/profile/router tests, 81 adjacent
agent/capability/project/mission tests and the complete 1,096-test ZENO suite.
The configured full dry run passed every stage with zero external actions and
left the complete production metrics object unchanged. Detailed evidence is in
`ZENO_CAREER_ENGINE_REPORT.md` and the nine companion business reports.

The remaining limits are deliberate and honest: live discovery uses existing
browser/research evidence rather than claiming unrestricted job-board APIs;
built-in platform adapters default to owner submission; unknown career facts
remain missing; project records delegate real creation to existing Builder/tool
execution; payment tracking never moves money. These boundaries prevent fake
applications, fake clients, fake delivery and fake revenue.

---

## ZENO Anywhere Phone Web Companion — SECURE MEDIA UPGRADE COMPLETE WITH WEB LIMITS (2026-08-20)

The current phone PWA now adds explicit, owner-initiated camera capture, a
bounded file picker, one-shot geolocation, a permission dashboard and one
lightweight draggable in-app ZENO mini-orb. Camera and location are permitted
only for the `/app` shell; every other gateway route keeps them denied. The
camera never starts automatically, geolocation is not watched, selected files
are not given filesystem access and the orb creates no JavaScript animation
loop. Its position persists locally and is clamped back on-screen after a
viewport or orientation change.

Phone attachments use a short-lived AES-256-GCM SQLite channel instead of
putting bytes, paths or secrets into command JSON. Input is bound to the
verified browser device, the selected Windows device and one command ID;
content type and file signatures are checked, active/macro Office content is
rejected, storage and archive expansion are bounded, and plaintext bytes and
filenames are cryptographically released after terminal processing. The
desktop connector performs real image/document analysis on the existing
bounded worker pool, keeps its heartbeat alive, uses a read-only agent scope
and removes its extraction temp file. An unavailable analyzer reports failure
instead of simulated success.

The existing desktop Settings pairing authority is reused rather than
duplicated. It presents a temporary QR containing a high-entropy one-time
token plus a six-digit manual fallback; only hashes are stored, codes expire,
one new offer cancels the prior unconsumed offer and consumption is atomic.
The newer Anywhere owner session, passkey/device approval and Claude's
owner-configured unlock phrase remain the login authority. Unlock phrases are
now bounded, require at least two words, use atomic attempt accounting and
cannot report a browser trusted if the durable approval update failed.

The PWA consumes authenticated Server-Sent Events for nonblocking device/task
state updates and retains bounded polling as a compatibility fallback. Its
existing standards-based Web Push service delivers completion, approval and
security notifications when VAPID is configured and the browser grants
permission; sensitive task content is not placed on the lock screen.
WebAuthn/passkey, session/device revocation, CSRF, strict origins, rate limits
and server-side provider secrets remain in the existing Anywhere architecture.

**Verified:** the new encrypted attachment and unlock suites pass, including
wrong-device/command isolation, expiry/capacity, content spoofing, macro
rejection, upload-to-desktop lifecycle, temp cleanup, read-only execution and
gateway policy boundaries. The broader Anywhere/security regression suite also
passes. Mobile browser QA at 390×844 and 320×600 confirmed portrait layout,
drag persistence, off-screen recovery and no console errors.

**Intentional web limits:** a PWA cannot draw over other Android apps, run an
unrestricted always-on background microphone/camera, bypass Family Link or
Android permission prompts, or guarantee autoplay. A native Android companion
would be required for a system overlay/foreground service and native
notification-channel controls; browser Web Push delivery remains subject to
Android/Chrome background policy. Continuous camera/video understanding,
generic audio/video file analysis and physical-phone camera/passkey acceptance
are not claimed by this increment; authenticated SSE/Web Push and the explicit
camera/document path are the implemented, tested surface.

---

## ZENO Native Android Overlay Companion — IMPLEMENTED WITH OS SAFETY LIMITS (2026-08-21)

ZENO Anywhere now has one optional native Android companion layered on the
existing PWA and DeviceLink authority. The PWA remains the complete phone UI;
the native application supplies only the system overlay and the small set of
basic phone controls a browser cannot provide. Its draggable mini-orb uses an
owner-granted `TYPE_APPLICATION_OVERLAY`, a visible foreground-service
notification, stored/clamped position and a single low-frequency health and
command loop. It does not animate continuously, steal focus or create a second
dashboard.

Pairing is initiated only from a trusted PWA browser. The QR carries an HTTPS
gateway origin and short-lived high-entropy credential; a six-digit manual
fallback is also available. Offers expire in five minutes, only hashes are
stored, one new offer invalidates its predecessor, consumption is atomic and
the permanent device credential is returned once and encrypted with Android
Keystore. Android devices remain pending until owner approval and receive only
the `android_control` DeviceLink scope.

The action surface is deliberately exact: Back, Home, Recents, notifications,
quick settings, scroll up/down and open a normal launchable app. Arbitrary taps,
typing, coordinates, gestures, purchases, sends, deletion, settings/permission
changes, installers, shell commands and credentials are rejected independently
by the cloud/device schema and the native app. Agent tools require confirmation;
successful execution is reported only after real device evidence returns.

**Verification:** 26 Python pairing/policy/API/DeviceLink tests cover single-use
and expiry behavior, scope and platform isolation, disallowed action families,
real claim/acknowledge/complete evidence and owner approval. Three native JUnit
tests exercise the duplicate on-device allowlist. The Kotlin project targets
API 35 and its Gradle 8.9 test/build produced a valid v2-signed debug APK. The
complete maintained ZENO suite passed 1,577/1,577. Physical-phone install,
pairing, overlay permission and per-game acceptance remain owner/device tests.

**Intentional limits:** Android, Family Link and individual apps remain the
permission authority. Lock, permission, payment, DRM and other secure screens
may suppress overlays; some games prohibit overlays or Accessibility services.
ZENO does not bypass those controls and does not claim autonomous gameplay or
unrestricted phone control.

---

## Universal Tool Catalog — STABLE SUPPORTED ADAPTER PASS COMPLETE (2026-08-21)

The 148-section Universal Tool Master Catalog was audited against the current
ZENO architecture. The catalog was treated as its author intended: a selective
capability specification, not permission to clone every repository or install
competing frameworks. ZENO now exposes 299 registered tools through one
lazy registry while sending only 12 core schemas to the provider, and already
has the Kernel, bounded task runtime, Event Bus, permission/verification
layers, device manager, workflows, agents, MCP allowlist, memory and health
architecture required by the catalog.

The confirmed lightweight gaps are now real adapters: pywinauto for native
Windows UIA and bounded native readers for PDF, DOCX, XLSX and PPTX. They are
lazy and create no startup worker or polling loop. The installer now has real
argument parsing, never upgrades compatible packages without explicit consent,
supports a dry run and a supported `--catalog-safe` group, and always checks
dependency consistency. The Windows doctor no longer crashes under CP1252 and
reports the real adapter state.

Live checks launched Playwright Chromium and verified a rendered DOM, queried
the actual Windows UIA desktop, executed ffmpeg and Ollama, and generated then
reread genuine PDF/Word/Excel/PowerPoint files. Dependency consistency passed.
The final complete maintained ZENO suite passed 1,750/1,750 in 569.20 seconds
with deprecation warnings treated as errors. The desktop web shell now uses the
supported FastAPI lifespan API. Load testing also hardened two Windows process
edges: read-only MCP discovery receives one bounded retry while effectful calls
are never replayed, and trusted local sandbox execution remains bounded at 45
seconds. LAN tests no longer treat stale addresses on down adapters as trusted
local routes.
The exact mapping, versions, tests and stability exclusions are documented in
`ZENO_UNIVERSAL_TOOL_CATALOG_REPORT.md`.

The final 2026-08-24 pass added the missing catalog-wide contract without
creating a second executor. All 299 executable tools now have normalized,
versioned metadata, schema validation, permission/device health, managed
timeouts, cancellation and selection through `GlobalToolRegistry`, while real
execution still reaches the existing gated `run_tool` path. The complete 148
catalog sections and 57 provider candidates are exposed through lazy read-only
admin tools, loopback-only APIs and a Tool Library dashboard panel. The panel
fetches only while open, cancels stale searches, does not poll and releases its
rows on close. A cold complete tool import measured 950.6 ms, 17.38 MiB and no
thread growth; catalog status took 69.8 ms and registry health 164.8 ms.

Heavy duplicate stacks (Docling/Torch where native readers suffice, extra
vector databases, competing orchestration frameworks, Tesseract alongside
working Windows OCR, arbitrary GitHub repositories and untrusted MCP servers)
remain deliberately uninstalled or feature-flagged. Account tools such as
Gmail, calendar, GitHub and Home Assistant remain unavailable until the owner
selects and authorizes an account; ZENO does not confuse package presence with
permission or working capability.

---

## Smart Autonomy Policy — COMPLETE (2026-08-26)

ZENO now makes one centralized decision at the existing tool boundary instead
of treating every effectful tool as a reason to ask twice. `ActionPolicy`
classifies the exact requested action and expiring owner/turn context as
`EXECUTE`, `CLARIFY`, `COUNCIL_APPROVAL`, `HIGH_IMPACT_CONFIRMATION`, or
`DENY`. Thinking, analysis, ordinary app/browser/file/development operations,
normal specialist delegation and an exact authenticated send command execute
without duplicate approval. Drafting never sends. A formal full-Council call,
ambiguous targets, financial effects, destructive/irreversible operations,
security-critical changes and unauthenticated remote actions retain their
appropriate gates.

The policy is shared by local text, verified voice, paired-phone commands,
background work and bridge sources through an expiring `ContextVar` turn scope.
Authorization is fingerprinted to the exact tool arguments and cannot authorize
later content, a different recipient, or an open-ended conversation. Existing
permission/capability blocks, privacy restrictions and the confirmation UI were
preserved rather than bypassed. Normal coding inspection/edit/test cycles and
bounded safe recovery no longer stop for routine confirmation.

The implementation is committed as `6b73c11` (`feat: centralize ZENO smart
autonomy policy`). Focused policy, messaging, Council, coding, desktop and
permission tests pass as part of the complete maintained suite described below.

---

## Native ZENO Charm Engine — COMPLETE WITH PROVIDER LIMITS (2026-08-26)

One native, lazy Charm Engine now supplies context-aware conversation coaching
without embedding the cloned applications as competing assistants. The three
repositories under `integrations/` were inspected: Rizzbot contributed design
ideas around structured modes, bounded feedback and `WAIT`/`MATCH`/`PULL_BACK`/
`ABORT`; rizz-ai contributed context-first local analysis; RizzMa contributed
bounded recent context, staged failure isolation and cache limits. They have no
usable repository license files, so no source was copied and none of their
React, Flask, Firebase, Supabase, LangChain, macOS, microphone, model-client or
342-package application stacks was installed. ZENO added no dependency.

The native subsystem supports Natural, Smooth, Sweet, Flirty, Playful, Funny,
Witty, Romantic, Confident, Gentleman, Cheeky, Deep, Serious and Pidgin Smooth.
Its deterministic analyzer measures reciprocity, momentum, engagement, dry
replies, unanswered streaks, tone, refusal and discomfort. Explicit stop or
unsafe escalation evidence blocks generation before any provider call. A single
bounded call through ZENO's existing provider/router generates up to five
contextual drafts; the local critic then scores naturalness, relevance,
confidence, warmth, humor, flirt level, pressure, desperation, cringe and
repetition and selects the strongest eligible candidate instead of trusting
generation order.

`charm_reply`, `charm_analyze`, `charm_set_mode`, `charm_status`,
`charm_feedback` and `charm_coach` use the existing tool registry, brain,
memory, Event Bus and voice path. Reply, opener, compliment, humor,
storytelling, recovery, after-send, simulator and voice-coach features share the
same engine. Callback/"Your Voice" feedback is bounded and process-local;
durable retrieval accepts only privacy-filtered normal ZENO communication
preferences. No private transcript is automatically written to long-term or
eMEM spatial memory. Charm starts no server, microphone, provider client,
database, polling loop, worker or frontend.

Draft and coaching tools contain no transport path and never send a message.
An explicit later owner command may use the normal messaging tool under Smart
Autonomy, scoped to that exact recipient/content. Rejection, discomfort,
coercion, harassment, deceptive impersonation and automated mass messaging are
not supported.

Charm and spatial schemas are now selected on demand by the deterministic
capability router. This repaired a measured regression where the default model
payload reached 27 schemas; ordinary turns are back at the enforced maximum of
12 while both capabilities remain available on their matching turns.

**Verification:** 93 focused Charm tests and 32 focused Smart Autonomy tests
pass after independent code review. The final affected-scope verification
(Charm, Autonomy, voice-response-budget, Website Studio routing and Defense
Mode compatibility coverage) passes **159/159** against the latest shared
branch. The earlier stable complete maintained ZENO suite
passed **2,124/2,124** in 678.39 seconds on 2026-08-26. A later whole-suite run
was deliberately not reported as final evidence because concurrent migration
and defense-mode commits changed the checkout while it was executing.
Compilation and repository checks are recorded in the delivery commit.

**Honest limits:** live social outcome quality depends on the configured ZENO
model provider, network and supplied conversation context; automated tests use
injected provider responses and exercise real parsing/failure isolation without
spending a live API call. A provider outage returns an explicit error and no
canned fake reply. Feedback is bounded to the current process unless the owner
explicitly saves a non-sensitive communication preference through normal ZENO
memory. The full suite reports two non-failing third-party warnings: optional
urllib3 SOCKS support is absent, and the separately edited eMEM integration uses
an embedding compatibility method scheduled for rename.

---

## SIWES supervision experience and student-led story mode — COMPLETE (2026-08-27)

Defense/Presentation Mode now carries one structured, visitor-safe account of
Divine's SIWES supervision experience. Engr. Bello is identified respectfully
as the SIWES invigilator/supervisor; the stored facts say only that Divine
expected to meet him, circumstances prevented the visit from going as planned,
and the situation later worked out. No incident details are stored or inferred.
If a panel member asks what happened, the deterministic response hands the
question to Divine instead of asking a model to invent a story or assign blame.

The existing topic-based presentation flow now offers brief optional comments
for placement, challenges and supervision. Each payload explicitly keeps
Divine as the main presenter, forbids reading slides verbatim and never advances
the presentation automatically. The supervision boundary is shared by the live
visitor briefing, prepared visitor profile and offline SIWES evidence pack.
Presentation routing recognises `Engr Bello`, `Engr. Bello`, invigilator and
supervision phrasing, lazily loads the real `visit_topic` tool, and preserves
the ordinary zero-tool fast path for unrelated conversation.

**Verification:** the new behavior completed a red-green TDD cycle. The final
visitor, evidence-pack, Defense Mode, guest conversation, capability-routing,
provider-payload and Charm-routing regression set passes **162/162**. Python
compilation and repository checks are recorded in the delivery commit. One
pre-existing non-failing eMEM API-rename warning remains.

---

## Ragebait / Provocation Banter Mode — COMPLETE (2026-09-04)

ZENO now has a local, consent-scoped Ragebait state machine for playful
owner-to-ZENO banter. Intensity is bounded from 0 to 5, recent lines are held
only in a bounded in-process history, and Ragebait resets off at restart.
Explicit stop language and serious/sensitive context disable it before any
response directive is generated. Ragebait never changes permissions,
confirmation, tool routing, outbound messaging, or third-party communication.

Battle state, intensity, and local motion reactions publish compact
`ragebait.*` events through the existing Event Bus. The existing panel system
opens a non-persistent, draggable Ragebait Battle view only on a real battle
event and removes it when the battle completes or the mode is disabled. It has
no polling loop, timer, new worker, microphone, or continuous animation.

**Verification:** the Ragebait, humour, Charm, live-panel, proactive-panel and
Phase 22 stability regression suite passes **150/150 in 13.96 seconds**.
Python compilation and whitespace checks pass. The separate manual validation
still required is to open, drag, minimize, restore, and close the battle panel
on the target Windows WebView host during a real owner-started battle.
