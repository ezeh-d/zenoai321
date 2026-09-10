# Character engine research index (Phase 2)

Real inspection of the actual clones under `_research/character_engine/`
(not GitHub-API metadata this time). Read selectively: READMEs, package
manifests, and the files most relevant to gaze/blink/emotion/state-machine
architecture, per the master prompt's "don't reread everything" instruction.
Use this file and `CHARACTER_IMPLEMENTATION_MAP.md` as the reference from
now on instead of re-opening these repos.

## 1. DesktopPetLive2D (Chi-Yue-Shan, MIT)

- **Stack**: Electron + PixiJS + pixi-live2d-display + Live2D Cubism.
- **Architecture**: `main/` (Electron main: window, LLM calls, diary/memory/
  reminders/tarot features), `renderer/app.js` (drag handling, calls
  `model.focus(x, y)` on `mousemove` to drive Live2D's built-in gaze).
- **Gaze**: delegates entirely to Cubism's internal `CubismTargetPoint`/drag
  manager (`model.focus()`) — no standalone damping algorithm to extract;
  it's baked into the Live2D runtime, not separable from a rigged model.
- **Idle/interaction**: drag-to-move, click-through toggle, chat bubble.
- **License**: MIT. **Verdict**: confirms the "mouse position → focus
  target" pattern ZENO's own `orb.js`/`character.js` already implement via
  a real spring (`spring.js`), just with Cubism's internals doing the
  damping instead of an explicit one. Nothing new to adopt — the pattern
  is already matched or exceeded (ZENO's spring exposes dead-zone-adjacent
  clamping and idle recovery explicitly; Cubism's is opaque).

## 2. buddy (AG9898, MIT)

- **Stack**: Electron (main) + Svelte (renderer) + a Rust CLI bridge for
  WSL hook events. npm-distributed dev tool, not a consumer app.
- **Architecture** (from `docs/ARCHITECTURE.md`): CLI → local HTTP sidecar
  (`127.0.0.1:7777`, token-authenticated) → Electron main (owns the
  transparent/frameless/always-on-top window, `setIgnoreMouseEvents` for
  click-through) → Svelte renderer (drives a **sprite/spritesheet**
  animation state machine from a `pet.json` manifest). Agent lifecycle
  events (Claude Code / Codex hooks) POST to `/state`, which forwards to
  the renderer as a named state change.
- **Pattern worth the name**: a small, explicit **event-name → animation
  state** lookup, config-driven per pet (`pet.json` manifest + spritesheet),
  not a general inference system.
- **License**: MIT. **Verdict**: confirms the manifest-driven asset
  approach the master prompt's Phase 6/7 ask for (`character.json` +
  `assets/characters/zeno/`) is a proven real-world shape — adopt the
  *shape* (manifest + swappable spritesheet) once real art exists; nothing
  to adopt today since ZENO's character is still CSS/DOM shapes, not
  sprites.

## 3. emotion-desktop-pet (Valerie Liang, MIT)

- **Stack**: Python + Tkinter, talks to any OpenAI-compatible model over
  HTTP.
- **Architecture**: `desktop_pet/commands.py`, `config.py`, `launcher.py`;
  `ui/overlay.py` for the transparent Tk overlay window and speech bubble.
- **Pattern already adopted last session**: the model tags its own
  sentences inline (e.g. `[joy]`), the client strips the tag before
  display/speech and uses it to pick the matching expression — a low-risk
  bridge between "LLM decides emotional intent" and "character engine owns
  the animation" without a separate sentiment classifier. **Still not
  implemented in ZENO** (needs a coordinated change to the system prompt +
  the streaming text parser in `index.html`/`mini.html`); still the
  cleanest next step for Phase 28 (conversational intent → expression).
- **License**: MIT.

## 4. avatar (ARPA Hellenic Logical Systems, MIT)

- **Stack**: React + `@pixiv/three-vrm` (VRM 3D avatars), Vite.
- **`src/hooks/useBlink.js`**: real, minimal, tested blink timer —
  `MIN_INTERVAL=2s, MAX_INTERVAL=6s`, a 0.24s sine-eased open/close, driven
  by a per-frame `delta`. **Confirms** (does not improve on) ZENO's own
  orb/character blink cadence (`3000 + Math.random()*5000` ms, ~130ms
  close/open, occasional double-blink) — already in the same range, no
  change needed.
- **Gaze**: no standalone cursor-gaze-damping module found; `lookAt` in
  this repo is camera orbit-control state, not character eye-gaze. Not
  useful for Phase 11 beyond confirming ZENO's existing spring-based eye
  tracking (`spring.js` + `stepEyeSpring`) is already a reasonable-or-better
  approach than what this repo does.
- **License**: MIT. **Rejected as a renderer** (VRM needs a modeled `.vrm`
  file — same reasoning as the earlier research pass).

## 5. pixi-live2d-display (Guan, MIT)

- **Stack**: TypeScript PixiJS plugin wrapping Cubism 2/4 runtimes.
- Confirms `pixi_layer.js`'s existing pattern (lazy-load PixiJS, isolate
  failures, fall back cleanly) is the right shape for a *future* Live2D
  renderer plugin, if/when a rigged model exists. Nothing actionable today.
- **License**: MIT.

## 6. CubismWebFramework (Live2D Inc.)

- **Stack**: TypeScript, the official Cubism SDK core.
- **`src/effect/cubismeyeblink.ts`**: a proper state machine for blinking
  (`Interval → Closing → Closed → Opening`) with separate configurable
  durations for each phase (default: closing 0.1s, closed 0.05s, opening
  0.15s) and randomized next-blink timing
  (`t + random() * (2*interval - 1)`, default interval 4s). This is a more
  *granular* version of what ZENO's binary blink-class-toggle already does
  (same idea, coarser easing). Worth adopting the phase-state shape (not
  the code) if/when a smoother blink animation is wanted; not urgent since
  the current toggle already reads correctly at this character's size.
- **License**: Live2D's own EULA (`NOASSERTION`), not a normal OSS grant —
  **reference only, never copy code**, consistent with the earlier
  research pass's conclusion.

## 7. CubismWebSamples (Live2D Inc.)

- **`Demo/src/lappmodel.ts`**: sample app wiring `CubismLookUpdater` +
  `_dragManager` to a mouse-drag target — same "focus point, internals
  handle damping" pattern as DesktopPetLive2D above; nothing separable.
- **License**: Live2D EULA. **Rejected as a renderer**, reference only.

## 8. OpenPet (OpenPet contributors, MIT)

- **Stack**: Electron, large multi-package workspace (Control Center + AI
  + plugin system). `docs/agent-awareness-development-design.md` and
  sibling docs describe an agent-awareness plugin architecture (the pet
  reacting to *coding-agent* lifecycle events, similar in spirit to
  `buddy`'s hook bridge).
- **Verdict**: architecturally the heaviest of the nine (full plugin
  system, Control Center UI) — confirms the "electron pet + plugin system"
  shape is a known-viable design, but ZENO already has its own tool/agent
  system and does not need a second plugin runtime. Adopt nothing
  structural; the one relevant idea (external lifecycle events → pet
  reaction) is already covered by ZENO's own `visual_events.js` bus and
  the existing tool/agent event wiring.
- **License**: MIT.

## 9. simple-desktop-pet (Desktop Pet Contributors, license not re-verified
   this pass — treat as reference only)

- **Stack**: Electron, plain JS (no framework), sprite-based dog pet.
- **`renderer/state-machine.js`**: a small, real, **genuinely adoptable**
  pattern — a guarded state-transition function (e.g. `LICKING` not
  allowed during `LYING_DOWN`; `BOUNCING` blocks all transitions until it
  completes) plus an **idle inactivity timer**: after 30s with no
  interaction, auto-transition from `IDLE` to `LYING_DOWN`, reset on any
  new interaction. This is the simplest real version of Phase 16's "human-
  like idle engine" concept.
- **`renderer/interactions.js`**: hit-testing a "head zone" (an ellipse
  proportional to the character's size) to distinguish hover-on-head vs.
  hover-elsewhere, driving a distinct reaction (`LICKING`) only when the
  cursor is over that region. Directly reusable idea for Phase 18 (mouse
  interaction) once the character has real body-part regions.
- **Verdict**: **adopted this pass** — see implementation map. The idle-
  timeout-with-guarded-transitions shape is exactly the missing piece
  between ZENO's existing (reactive) emotion engine and Phase 16's "alive
  while doing nothing" requirement.

## Overall conclusion

No repo offers a gaze-damping or blink algorithm materially better than
what ZENO's `orb.js`/`character.js` already has (both were independently
built to the same real-world parameters these repos use). The two
genuinely new, adoptable ideas found this pass are:

1. **Idle inactivity timer with guarded state transitions**
   (simple-desktop-pet) → implemented this pass as `character.js`'s idle
   behavior engine.
2. **Manifest-driven, swappable art** (buddy's `pet.json` + spritesheet)
   → deferred until real ZENO art exists (Phase 6/7), since there is
   nothing to manifest yet — CSS/DOM placeholder shapes have no asset
   files to describe.

Everything else confirms ZENO's existing approach rather than improving on
it, or is architecturally inapplicable (VRM/Live2D need rigged model files
nobody has yet; Electron would duplicate the existing pywebview shell).
