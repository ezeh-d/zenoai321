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

## Phase 5 — Living Memory · PARTIAL
**Done:** vault notes, semantic search over real embeddings
(`tools/rag.py`), memory facts, activity history, Event Bus history.
**Gap:** no memory versioning, no merge/split/archive UI.

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

## Phase 13 — Orb System · DONE
CSS orb (WebGL removed — it was the lag), 11 states, 13-agent ring with
per-agent colour/icon, live activation from real delegation events,
click-through dashboards.

## Phase 14 — Executive Dashboard · PARTIAL
**Done:** **Agent Monitor** (live worker state, heartbeat age, queue
depth, tasks done/failed, success rate, per-agent restart button; polls
only while open), Timeline, missions panel, approvals, notices, system
health, permission status, mini-orb hover card, **Executive Meeting**
(every specialist reports its REAL runtime metrics aloud in its own
voice, then ZENO summarises).
**Gap:** no single unified "home screen"/Situation Room composing them
into one view.

## Phase 15 — Dream Mode · PARTIAL
**Done:** idle detection, reindexing on idle, proactive nudges.
**Gap:** no day-summary generation or agenda preparation.

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
approval, audit logging. **Named limit:** approved plugins are not
sandboxed — the gate controls whether code loads, not what it does after.

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
