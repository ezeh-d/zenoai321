# ZENO Living Character — Research (Phase 0)

Real research against the repos named in the brief, via GitHub's public API (metadata/license) and README fetches (architecture). No code was copied from any of them — patterns only, adapted to ZENO's actual stack.

## Repos checked

| Repo | Stack | License | Verdict |
|---|---|---|---|
| `valerieliang/desktop-pet` | Python, Tk, HTTP to any OpenAI-compatible model | MIT | **Adopt a pattern** (see below) |
| `AG9898/buddy` | TypeScript, Electron, Svelte, HTTP sidecar | MIT | **Adopt a pattern** (see below) |
| `dengyie/OpenPet` | Electron, JS, manifest-based plugin system | MIT | Adopt plugin-security posture only (not character-relevant) |
| `TonyNa-code/desktop-pet` | JS, cross-platform, character packs, TTS | MIT | Confirms "character pack" config-driven asset pattern; no unique architecture found beyond what's below |
| `ARPAHLS/avatar` | JavaScript, VRM lipsync to local/AI audio | MIT | VRM/3D-avatar — rejected, see below |
| `guansss/pixi-live2d-display` | TypeScript, PixiJS plugin for Live2D | MIT (1.5k stars) | Rejected, see below |
| `Live2D/CubismWebFramework` | TypeScript, official Live2D SDK | Live2D's own EULA (`NOASSERTION`, not a normal OSS license) | Rejected, see below |
| `Live2D/CubismWebSamples` | Live2D sample harness | Live2D's own EULA | Rejected, see below |
| `Yanchen-J/DesktopPetLive2D` | JS, 0 stars, no description | `NOASSERTION` | Rejected — unmaintained, unclear license, same Live2D dependency as above |

## What was rejected, and why

- **Every Live2D path** (`CubismWebFramework`, `CubismWebSamples`, `pixi-live2d-display`, `DesktopPetLive2D`): Live2D isn't a normal open-source render target — it needs an actual **rigged Cubism model file** (`.moc3` + textures + physics config), produced in Live2D's own paid Cubism Editor by an artist who rigs the character for real-time deformation. The user has explicitly said final art is still to come and to use temporary assets now; there is no rigged model to render, and building the abstraction for one before any exists is speculative work with nothing to test against. Live2D's own SDK license (`NOASSERTION`, its own EULA) also isn't a plain MIT grant — commercial use has separate terms. This matches what I already found in the earlier companion-prompt pass this session: heavy 3D/rigged-avatar rendering is the wrong default until there's real art and a measured need.
- **ARPAHLS/avatar (VRM)**: same shape of problem — VRM is a full 3D humanoid avatar format needing a modeled `.vrm` file, not a 2D sprite/CSS character.
- **Electron-based ones** (`AG9898/buddy`, `dengyie/OpenPet`): useful for their *event/state patterns* (below), but ZENO already has a working transparent-overlay shell (pywebview, `desktop_app.py`) — adding Electron would be a second, competing GUI runtime for the exact capability ZENO already has, which the brief's own MISSION explicitly forbids ("do not rebuild ZENO from scratch... integrate into current architecture").

## What was adopted

1. **From `valerieliang/desktop-pet`**: the model tags its own sentences inline (e.g. `[joy]`), the client strips the tag before display/speech and uses it to pick the matching expression. This is a genuinely useful, low-risk bridge between "LLM decides the emotional intent" and "character engine owns the animation" (exactly the brief's own §14 principle) without building a separate sentiment-classifier. **Not implemented this pass** (it needs a coordinated change to `agent.py`'s system prompt and the text-streaming parser in both `index.html` and `mini.html`) — flagged as the clear next step.
2. **From `AG9898/buddy`**: a *small, explicit lookup table* from lifecycle event → animation name (`UserPromptSubmit → jumping`, `PostToolUse → idle`, etc.), not a general-purpose inference system. This is exactly the shape `orb.js`'s existing `_STATE_EVENT` map and `setState()` already use — confirms ZENO's current architecture is already the right shape for this, it just needed the vocabulary and a real dimensional layer on top, which is what this pass adds.
3. **Config-driven emotion/asset naming** (`avatar.emotion_map` in desktop-pet, "character packs" in TonyNa-code/desktop-pet): matches the brief's own §23 asset-manifest idea. Deferred until real art exists — right now `orb.js` has no image assets to manifest (it's pure CSS/SVG), so a JSON manifest would describe nothing real yet.

## Conclusion driving Phase 1

Extend the **existing** `orb.js` state machine with a real dimensional emotion model (§2) and emotion decay/momentum (§15), rather than building a parallel `src/character/` framework. `orb.js` already has: an event-driven `setState()`, a `_STATE_EVENT` bridge to an external bus, per-state hue/spin/eyes (cheap CSS, no new render cost), and (as of this session) 31 named states. What was missing was the *dimensional* layer the brief asks for — the mapping from continuous internal state (valence/arousal/confidence/curiosity/focus/urgency/amusement/concern/energy/social_engagement) to a discrete expression, with momentum so ZENO doesn't snap between emotions like a slot machine. That's Phase 1, implemented this pass.

Deferred to a later pass (real, not yet built): inline emotion-tag stripping from LLM output (adopted pattern above), micro-expressions (blink/eyebrow/glance library), gaze/cursor personality, lip-sync from TTS audio amplitude, gesture system, per-agent distinct animation personality, walking motion, and the sprite/Live2D renderer abstraction (moot until real art exists to abstract over).
