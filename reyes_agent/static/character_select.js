// Which avatar renderer ZENO boots into.
//
// The user has been explicit twice now: the 2D cartoon character (not the
// orb/sphere) is ZENO's PRIMARY identity, launched by default. The orb is
// kept -- nothing was deleted -- but demoted to an opt-in compact/fallback
// mode for low-resource situations, exactly as asked ("If it already
// exists: keep it only as optional fallback mode / compact mode /
// performance mode if needed. But by default, ZENO should launch and
// operate as the 2D character.").
//
// Deliberately a BOOT-TIME choice, not a live mid-conversation hot-swap:
// the two renderers are different DOM structures with different internal
// timers, and swapping the actual renderer out from under a user who might
// be mid-conversation is a much riskier, more jarring change than what was
// asked for. The EXISTING setPerformanceMode(lite) on both renderers
// already handles the "reduce animation cost under real resource pressure"
// case live (index.html's _autoLite / resource_governor.py wiring) --
// this module only decides which renderer to mount in the first place.
import { initCharacter } from "./character.js";
import { initOrb } from "./orb.js";

const STORAGE_KEY = "reyes_avatar_mode"; // 'character' (default) | 'orb'

export function getAvatarMode() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "orb" ? "orb" : "character";
  } catch (_e) { return "character"; }
}

export function setAvatarMode(mode) {
  try { localStorage.setItem(STORAGE_KEY, mode === "orb" ? "orb" : "character"); } catch (_e) {}
}

// Mounts whichever renderer is selected and returns it directly -- same
// public API either way (character.js's is a superset of orb.js's), so
// every existing caller (`orb.setState(...)`, `orb.setEmotion(...)`, etc.)
// keeps working unchanged regardless of which mode is active.
export function initZenoAvatar(canvas) {
  return getAvatarMode() === "orb" ? initOrb(canvas) : initCharacter(canvas);
}
