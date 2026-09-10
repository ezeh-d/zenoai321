// Renderer implementations for the character's VISUAL BODY only.
//
// character.js owns the "brain" -- state machine, dimensional Emotion
// Engine, gaze damping, idle behavior, and walk/dock positioning (applied
// as CSS custom properties directly on the shared #zeno-character root,
// so it is renderer-agnostic by construction). A renderer's only job is
// to draw the character's current appearance inside that root and react
// to a small, stable set of calls -- swapping which renderer is mounted
// must never touch character.js's already-tested brain logic.
//
// Renderer contract (documented, not enforced by a base class -- there is
// only ever one concrete renderer alongside the built-in CSS/DOM
// placeholder body, so a formal interface would be ceremony):
//   mount()                     -- insert this renderer's DOM into root
//   setExpression(stateName)    -- show the visual for this named state
//   setPointing(side, holdMs)   -- 'l' | 'r', auto-releases after holdMs
//   destroy()
//
// Today only SpriteStateRenderer (Stage A: flat, per-expression images)
// exists here. CutoutRenderer (Stage B: independently posable layers --
// head/hair/visor/eyes/arms/hands/legs) and Live2DRenderer are
// deliberately NOT stubbed with dead code -- per the research this
// project already did (_research/CHARACTER_REPO_INDEX.md), building that
// abstraction before a single real layered asset exists to test it
// against is speculative work with nothing to verify. The renderer
// hierarchy this file is meant to grow into is documented in
// docs/ZENO_LIVING_DESKTOP_CHARACTER.md.

// Maps every named state (character_brain.js's STATES) onto one of the 13
// sprite categories the supplied ZENO expression sheet actually has
// (neutral, happy, smug, thinking, listening, speaking, surprised,
// concerned, serious, confused, celebrating, sleepy, plus a "_pointing"
// pose used only by setPointing). This is a real design decision, not a
// placeholder table -- but it is deliberately approximate where the sheet
// doesn't have a 1:1 match (e.g. "angry" reads as "concerned", not a
// separate rage sprite that doesn't exist yet). Anything not listed here
// resolves to "neutral".
const SPRITE_CATEGORY_BY_STATE = {
  idle: "neutral", standby: "neutral", boot: "neutral", notice: "neutral",
  curious: "neutral", moving: "neutral", calling_agent: "neutral", waiting: "neutral",
  embarrassed: "neutral",

  happy: "happy", smile: "happy", amused: "happy", laugh: "happy",
  excited: "happy", proud: "happy", celebrating: "celebrating",

  smug: "smug", suspicious: "smug",

  thinking: "thinking", understanding: "thinking", reasoning: "thinking",
  deep_thinking: "thinking", processing: "thinking", acting: "thinking",
  coding: "thinking", creating: "thinking", searching: "thinking",
  learning: "thinking", focused: "thinking",

  listening: "listening",
  speaking: "speaking", communicating: "speaking", whispering: "speaking",

  surprised: "surprised", shocked: "surprised",

  concerned: "concerned", worried: "concerned", warning: "concerned",
  interrupted: "concerned", error: "concerned", angry: "concerned", annoyed: "concerned",

  serious: "serious",

  confused: "confused",

  success: "celebrating",

  sleepy: "sleepy", sleeping: "sleepy", bored: "sleepy", waking: "sleepy",
};

export function resolveSpriteCategory(stateName) {
  return SPRITE_CATEGORY_BY_STATE[stateName] || "neutral";
}

// Stage A renderer. Swaps a single <img>'s src per named state, with a
// graceful per-category fallback (an unmapped/missing category quietly
// falls back to "neutral" rather than showing a broken image or crashing
// -- Phase 55/56's "missing assets must not crash ZENO" requirement,
// satisfied for real here, not just documented).
export function createSpriteStateRenderer(root, manifest) {
  const sprites = (manifest && manifest.sprites) || {};
  let img = null;
  let pointTimer = null;

  function mount() {
    img = document.createElement("img");
    img.className = "zc-sprite";
    img.alt = "ZENO";
    img.draggable = false;
    root.appendChild(img);
  }

  function urlFor(category) {
    return sprites[category] || sprites.neutral || null;
  }

  function setExpression(stateName) {
    if (!img) return;
    const category = resolveSpriteCategory(stateName);
    const url = urlFor(category);
    if (url) img.src = url;
  }

  function setPointing(side, holdMs = 1600) {
    if (!img) return;
    const url = sprites._pointing;
    if (!url) return; // no pointing sprite supplied -- stay on the current expression
    const previousSrc = img.src;
    img.src = url;
    clearTimeout(pointTimer);
    pointTimer = setTimeout(() => { if (img) img.src = previousSrc; }, holdMs);
  }

  function destroy() {
    clearTimeout(pointTimer);
    if (img && img.remove) img.remove();
    img = null;
  }

  return { mount, setExpression, setPointing, destroy, _debugImg: () => img };
}
