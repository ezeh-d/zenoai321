# ZENO living desktop character — architecture

Living document for the "ZENO LIVING DESKTOP CHARACTER" work. Covers what
actually exists as of this pass. See the chat history / commit messages
for the full phase-by-phase status; this file documents *how it fits
together*, not a progress log.

## Layering

```
character_brain.js   -- pure, DOM-free: STATES table, dimensional Emotion
                         Engine, idle-nudge decision function. Shared by
                         orb.js and character.js. No rendering, no DOM.

character.js          -- the character's "brain wiring": owns the state
                         machine (setState), emotion API (setEmotion),
                         idle behavior engine, gaze system (cursor +
                         lookAt), point gesture (pointAt), walking
                         (walkTo/setDocked), and the public API every
                         caller (index.html, mini.html) uses. Renderer-
                         agnostic: position is applied as CSS custom
                         properties directly on the shared root element,
                         so any renderer mounted inside it inherits
                         position for free.

character_renderers.js -- the VISUAL BODY only. Today: a built-in CSS/DOM
                         placeholder body (inline in character.js, always
                         available, zero asset dependency) and
                         SpriteStateRenderer (Stage A -- swaps a single
                         <img> per named state). CutoutRenderer (Stage B)
                         and Live2DRenderer are deliberately NOT stubbed
                         yet -- see "Why no stub classes" below.

character_manifest.js -- detects whether real sprite art has been
                         supplied (fetches /static/character_assets/
                         manifest.json). Resolves to null today (no file
                         exists) -- that's what keeps the placeholder body
                         active by default right now.

character_select.js   -- boot-time choice between character.js (default)
                         and orb.js (opt-in compact/fallback mode,
                         persisted via a Settings toggle). Not a live
                         hot-swap -- see its own file comment for why.

orb.js                 -- the original sphere avatar. Untouched, fully
                         intact, used only when compact mode is selected.
```

## Renderer activation (Stage A)

`character.js` always builds its CSS/DOM placeholder body first (this is
what renders today, with zero asset dependency). At the same time it
kicks off `loadCharacterManifest()` — an async fetch for
`/static/character_assets/manifest.json`. Because that file doesn't exist
yet, the fetch always resolves to `null` and nothing else happens: the
placeholder body is what every user sees right now.

**The moment that file (plus the sprite images it points to) is dropped
in, the sprite renderer activates automatically on the next page load —
no code change.** `character.js`'s `setState()` already drives whichever
renderer is active; `pointAt()` already swaps to a `_pointing` sprite if
the manifest supplies one.

### Manifest format

```json
{
  "version": 1,
  "sprites": {
    "neutral": "/static/character_assets/sprites/neutral.png",
    "happy": "/static/character_assets/sprites/happy.png",
    "smug": "/static/character_assets/sprites/smug.png",
    "thinking": "/static/character_assets/sprites/thinking.png",
    "listening": "/static/character_assets/sprites/listening.png",
    "speaking": "/static/character_assets/sprites/speaking.png",
    "surprised": "/static/character_assets/sprites/surprised.png",
    "concerned": "/static/character_assets/sprites/concerned.png",
    "serious": "/static/character_assets/sprites/serious.png",
    "confused": "/static/character_assets/sprites/confused.png",
    "celebrating": "/static/character_assets/sprites/celebrating.png",
    "sleepy": "/static/character_assets/sprites/sleepy.png",
    "_pointing": "/static/character_assets/sprites/pointing.png"
  }
}
```

Every one of `character_brain.js`'s ~50 named states resolves onto one of
these 12 categories via `resolveSpriteCategory()` in
`character_renderers.js` (e.g. `deep_thinking` → `thinking`,
`shocked` → `surprised`). Any state not explicitly mapped, or any
category missing from the manifest, falls back to `neutral` rather than
showing a broken image — verified in
`scripts/verify_character_renderers.mjs`.

### Why no Stage B / Live2D stub classes yet

`_research/CHARACTER_REPO_INDEX.md`'s conclusion still holds: a
`CutoutRenderer` needs independently posable parts (head/hair/visor/eyes/
arms/hands/legs as separate transparent layers), and `Live2DRenderer`
needs an actual rigged Cubism/VRM model file. Building either abstraction
before a single real layered asset exists to test it against is
speculative work with nothing to verify against — the stub would be
untestable dead code. `pointAt(x, y)` and `walkTo(x, y)` are already
written as **semantic** calls (not "rotate this specific div" or "swap to
this specific sprite") for exactly this reason: when Stage B assets
exist, only `character_renderers.js` needs a new renderer added to it;
`character.js`'s calls into it don't change.

## Panel spatial awareness

`reyes_agent/static/panels/manager.js`'s `open()` dispatches a one-shot
`zeno:panel-opened` window event carrying the new panel's actual
on-screen center (`{x, y}`) — only for a genuinely new panel, never for a
singleton-reuse/focus/minimize. `character.js` listens for this directly
and reacts with `lookAt(x, y)` (damped eye/gaze offset) and `pointAt(x, y)`
(arm-lift toward that side, or a pointing sprite if the manifest has one)
together, so opening a panel now makes the character visibly notice and
gesture toward it.

This is the full extent of "desktop director"-style coordination that
exists today. A dedicated `DesktopDirector` module (home-zone management,
avoiding panel/character overlap, choosing *where* a new panel should
open relative to the character, coordinating multiple simultaneous
agents) has **not** been built — the current wiring is a direct,
one-event reaction, not a coordinating layer with its own state.

## Boot and standby/wake

- Boot: `index.html`'s init script sets `boot` → (400ms) `waking` →
  (900ms) `idle`. Both states already existed in `character_brain.js`'s
  `STATES` table but were never triggered anywhere before this pass.
- Standby: saying a standby phrase ("ZENO standby", "go to sleep", ...)
  sets the dedicated `standby` state (previously this incorrectly fell
  back to plain `idle`, indistinguishable from normal idle).
- Wake: resuming listening after a real standby period briefly shows
  `waking` (250ms) before settling into `listening`, tracked by a local
  `_wasStandby` flag that only ever gets set by the standby transition
  itself — an ordinary idle→listening turn never triggers it.

## Avatar boot-mode selection

See `character_select.js`. `getAvatarMode()`/`setAvatarMode()` persist a
`reyes_avatar_mode` localStorage key (`'character'` default, `'orb'`
opt-in), read once at page load by `initZenoAvatar()`. A "Compact avatar"
toggle in the dashboard's Settings panel drives this, taking effect on
the next reload (not a live hot-swap — see the file's own comment for
why).

## Testing

Each layer has an isolated Node test (dependency-free, DOM/fetch stubbed
at the top of the file, then the real module is imported and exercised
directly — this repo's established convention, since no JS test
framework is wired in for `static/*.js`):

- `scripts/verify_orb_emotion_engine.mjs` — orb.js, emotion derivation.
- `scripts/verify_character_engine.mjs` — character.js: emotion,
  protected states, idle engine, gaze (dead zone/damping/enable-gating),
  panel look/point reactions.
- `scripts/verify_character_select.mjs` — boot-mode selection.
- `scripts/verify_character_renderers.mjs` — manifest loading (404/error/
  malformed/valid) and the sprite renderer in isolation.
- `scripts/verify_character_sprite_integration.mjs` — end-to-end: a real
  manifest fed to `character.js` actually activates the sprite renderer
  and stays wired through `setState()`.

## What is genuinely not built yet (regardless of art)

- `DesktopDirector` as its own coordinating module (home-zone tracking,
  panel placement decisions, avoiding character/panel overlap, multi-
  agent spatial coordination).
- `ScreenAwareness` (display/work-area/multi-monitor/DPI tracking beyond
  what the existing panel-docking signal already provides).
- Full hand/gesture vocabulary beyond a single left/right point.
- Lip sync (no viseme timing or audio-amplitude analysis wired yet).
- Proactive notification behavior with its own cooldown/importance model.
- Click-through / accurate hit-region overlay behavior.
- Application-window awareness (identifying a real native app's window
  bounds, as opposed to ZENO's own panel system).
