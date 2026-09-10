# ZENO existing architecture (Phase 1 audit, living-character master prompt)

Real inspection of the running codebase, not assumptions. Written before any
new character work this pass so later phases extend rather than duplicate.

## Application startup / shell

- **Backend**: FastAPI app (`reyes_agent/web.py`, ~4700 lines), started via
  `main()` (uvicorn) at the bottom of that file. One process, one agent loop,
  one provider router -- confirmed, nothing duplicated per surface.
- **Native desktop shell**: `reyes_agent/desktop_app.py`, pywebview (NOT
  PyQt/Electron/Tauri). Creates the native "Mini Orb" window FIRST at boot
  (frameless, on_top, 210x210, transparent), then the main dashboard window.
  `tools/zeno_desktop_bootstrap.py` is the launcher REYES.bat uses.
- **Two reachable modes**: the real desktop app (native window, port 8765)
  vs. "ZENO Anywhere" (headless remote-access mode, port 8768, Task
  Scheduler task, no native window). Only the former has an actual on-screen
  character surface -- established earlier this session, confirmed still
  true.
- **Web front ends**: `reyes_agent/static/index.html` (full dashboard),
  `mini.html` (native Mini Orb page), `phone.html`/`mic.html`/`app.html`
  (phone companion, served over `PHONE_COMPANION_PORT`, `remote_access/`).

## Current avatar / character code

- `reyes_agent/static/orb.js`: CSS/DOM sphere avatar, event-driven
  `setState(name)` over a `STATES` table (hue/spin/eyes), cursor eye-tracking
  with a real spring (`spring.js`), particle canvas, blink timer, panel-dock
  transitions.
- `reyes_agent/static/character.js` (this session, latest commit): a 2D
  cartoon replacement for the orb -- same public API (`setState`,
  `setEmotion`, `pulse`, `setDocked`, etc.) plus `walkTo`. Mounted in both
  `index.html` and `mini.html` in place of the orb.
- `reyes_agent/static/character_brain.js` (this session): the STATES table,
  `SPECIALIST_IDS`, and the dimensional Emotion Engine (10 dimensions,
  momentum, per-dimension decay, threshold-derived expression), shared by
  both `orb.js` and `character.js` so neither duplicates the "brain".
- `reyes_agent/static/motion_engine.js`: window-drag shake/dizziness virtual
  motion + lean, consent-gated (`ragebait.py`), filter-channel only (never
  writes `transform` directly -- the avatar's own CSS owns that property).
- `reyes_agent/static/gesture.js`: **not** a character gesture system --
  webcam MediaPipe hand-tracking used to control the *computer* (play/pause,
  volume, mouse pointer). Named collision risk only; unrelated to Phase 13's
  character hand-pose system, which does not exist yet.

## Event architecture (the seam this master prompt calls "CharacterEventBus")

- `reyes_agent/static/visual_events.js` already **is** a real, tested,
  framework-free pub/sub bus (`on`/`off`/`emit`), with a frozen `EVENTS`
  vocabulary (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `EXECUTING`,
  `ERROR`, `SUCCESS`, `STATE`, `AGENT_ACTIVATED/THINKING/COMPLETED`,
  `MISSION_*`, `NOTIFICATION`, `AUDIO_LEVEL`). `orb.js`/`character.js` both
  emit into it one-way today; nothing currently subscribes on the character
  side (it feeds an optional Pixi overlay only). This is the natural home
  for Phase 19's expanded event vocabulary -- extend it, do not build a
  second bus.
- `reyes_agent/static/pixi_layer.js` is the existing renderer-abstraction +
  fallback pattern Phase 5/39 ask for: lazy-loaded, crash-isolated (a
  failure falls back to "no overlay", never kills the interface), fully
  torn down on destroy, driven entirely off the event bus. It is a visual
  *effects* overlay, not the character itself, but the pattern (optional
  renderer, graceful fallback, bus-driven, zero cost when off) is proven
  and should be reused rather than re-invented for a future Live2D renderer.

## Voice pipeline

- Wake word: `reyes_agent/wake/engine.py` (+ `openwakeword_backend.py`),
  `voice/wake.py`, `wake_cli.py`.
- STT: `reyes_agent/voice/stt/manager.py`, `streaming.py`.
- TTS: reached through `/api/tts`; ElevenLabs is one provider among the
  voice stack (not modified this pass; not touched by any character work).
- `reyes_agent/voice/realtime_session.py`, `conversation_coordinator.py`,
  `voice/continuity.py`: turn/session plumbing shared by desktop, mini, and
  phone surfaces -- one voice pipeline, not duplicated per surface.
- `reyes_agent/voice/local_command_router.py`: fast local command paths
  that bypass a full LLM turn (relevant to Phase 20's "react before Claude
  finishes thinking" -- this already exists for *commands*; it does not yet
  drive character reactions).

## Model routing / providers

- `reyes_agent/model_router.py`: `route(kind)` reads
  `MODEL_ROUTE_{CODING,RESEARCH,VISION,OFFLINE,...}` env overrides, one
  router, not touched by character work and must stay that way (Phase 35:
  AI and animation are decoupled).
- `reyes_agent/provider.py`: provider abstraction (Anthropic/Gemini/Ollama).

## Sub-agents / council

- `reyes_agent/agent_teams.py`, `agent_space.py`, `agent_presence.py`,
  `tools/subagents.py`, `agents/identity.py`: the existing multi-specialist
  system (ARIS, TOSIN, STARK, KATE, ULTRON, ZEAL, TITAN, HERMES, NOVA,
  HELIOS, ORACLE, APEX, HUNTER X, ...). `agent_presence.py` already supports
  a summoned specialist owning the conversational turn directly (earlier
  this session). `character_brain.js`'s `SPECIALIST_IDS` list already
  mirrors this roster for face/avatar purposes.

## Panels / Live Canvas equivalent

- `reyes_agent/panels.py` + `static/panels/manager.js`: the panel/workspace
  system. `PanelManager._reportPanelState()` fires a `zeno:panels-state`
  window event the avatar listens to for docking -- this is the existing
  "panel spatial awareness" seam (Phase 25), currently only a
  count/maximized signal, not per-panel bounds.
- `panels.py` also has a Panel Request API (`request_panel`,
  `release_panels_for`, `owner_of`) added earlier this session so agents can
  ask for their own workspace explicitly.
- No dedicated "Live Canvas" module by that exact name was found; the panel
  system + `static/panels/renderers.js` is the closest existing equivalent.

## Notifications / tools / browser & desktop automation

- `reyes_agent/notification_listener.py`, `system_health.py`.
- `reyes_agent/tools/` is large (dozens of tool modules: browser, system,
  android, evidence, universal_catalog, intelligence, teaching_notepad,
  panel_tools, messaging/, subagents, ...). `tools/__init__.py` has the
  existing `classify_tool_result()` failure-prefix vocabulary the avatar's
  `tool_result` emotion reaction already keys off (wired earlier this
  session).
- `browser_controller.py`: browser automation. Desktop control lives under
  `tools/system.py` and related modules.

## Performance / resource governance

- `reyes_agent/resource_governor.py`: the existing resource-pressure
  governor, wired into the dashboard's automatic visual degradation earlier
  this session (`static/index.html`'s `_autoLite`/
  `applyEffectivePerformanceMode()`).
- `/api/performance-features/settings` (GET/POST, `web.py:3407/3415`):
  existing settings endpoint carrying `performance_mode`,
  `cursor_eye_tracking`, `eye_tracking_fps` -- both `index.html` and
  `mini.html` already fetch and apply this. This is most of Phase 40's
  "character settings" requirement already, just not under
  `ZENO_CHARACTER_*` env names; extending this endpoint's schema is lower
  risk than introducing a parallel settings surface.

## Config / environment flags

- `reyes_agent/config.py`: central config; no `ZENO_CHARACTER_*` flags exist
  yet (Phase 40 is genuinely new).

## Tests

- Python: `tests/` (pytest), scoped/targeted runs are the established
  convention in this repo, not a blind full-suite run every pass.
- JS: no test framework is wired into this repo for `static/*.js`. The
  established convention (this session) is a dependency-free Node script
  under `scripts/` that stubs the DOM primitives a module touches at
  import/init time, then imports and exercises the real module directly
  (`scripts/verify_orb_emotion_engine.mjs`,
  `scripts/verify_character_engine.mjs`). New character-engine tests should
  follow this pattern rather than introducing a new JS test runner/
  dependency.

## What this means for later phases

- Phase 4 (core character architecture): the prescribed `src/character/...`
  TypeScript class-hierarchy is a foreign shape for this codebase (no
  bundler/TS build step exists for the frontend; everything under
  `static/` is a plain ES module served as-is). Per the master prompt's own
  instruction ("adapt folder/language conventions... do not force this
  exact structure if another existing structure is better"), the ZENO-native
  equivalent is: keep extending `character.js` + `character_brain.js` as
  focused ES modules under `reyes_agent/static/`, one concern per file,
  wired through the existing `visual_events.js` bus -- not a parallel OOP
  framework.
- Phase 19 (event bus): extend `visual_events.js`'s `EVENTS` vocabulary and
  give the character module real *inbound* subscriptions (it only emits
  today) instead of building a second bus.
- Phase 5/39 (renderer abstraction + fallback): `pixi_layer.js` is the
  proven pattern to imitate for a future Live2D/sprite renderer -- lazy
  load, crash isolation, graceful fallback to the current CSS/DOM renderer.
