# Feature → reference repo → ZENO implementation location (Phase 48)

Kept up to date as later phases land, so research is not re-read each pass.

| Feature | Reference repo(s) | Reference file | ZENO implementation |
|---|---|---|---|
| Dimensional emotion model + decay | (independent; matches Phase 9/10's own spec directly) | — | `reyes_agent/static/character_brain.js` (`EMOTION_*`, `createEmotionEngine`) |
| Blink cadence (2-7s random, sine ease) | avatar (`useBlink.js`), CubismWebFramework (`cubismeyeblink.ts`) | `avatar/avatar/src/hooks/useBlink.js`; `CubismWebFramework/src/effect/cubismeyeblink.ts` | `reyes_agent/static/character.js` `scheduleBlink()` (already matches; confirmed, not changed) |
| Cursor gaze / focus damping | DesktopPetLive2D, CubismWebSamples (both delegate to opaque Cubism internals) | `DesktopPetLive2D/renderer/app.js`, `CubismWebSamples/.../lappmodel.ts` | `reyes_agent/static/orb.js` `stepEyeSpring`/`spring.js` (already equal-or-better; character.js's own gaze system added this pass, see below) |
| Idle inactivity timer + guarded transitions | simple-desktop-pet | `simple-desktop-pet/renderer/state-machine.js` | `reyes_agent/static/character.js` `_createIdleEngine` (new this pass) |
| Head-zone hover hit-testing | simple-desktop-pet | `simple-desktop-pet/renderer/interactions.js` | not yet implemented (Phase 18, deferred) |
| Event-name → animation lookup | buddy | `buddy/docs/ARCHITECTURE.md` (HTTP `/state` → renderer state) | already matched by `orb.js`/`character.js`'s `setState(name)` + `visual_events.js` bus |
| Manifest-driven swappable art | buddy | `pet.json` + spritesheet | deferred — no real art assets exist yet to manifest (Phase 6/7) |
| Inline emotion-tag stripping (`[joy]` in LLM text) | emotion-desktop-pet | `emotion-desktop-pet/desktop_pet/commands.py` | not yet implemented (needs `agent.py` system-prompt change + streaming parser change in `index.html`/`mini.html`) |
| Renderer abstraction + crash-isolated fallback | pixi-live2d-display (pattern only) | — | `reyes_agent/static/pixi_layer.js` already implements this pattern for the effects overlay; same shape to reuse for a future sprite/Live2D character renderer |
| VRM/Live2D rigged-model rendering | avatar, CubismWebFramework/Samples, pixi-live2d-display, DesktopPetLive2D | — | **rejected** — no rigged model file exists; revisit only once real art + a Cubism/VRM rig exists |
