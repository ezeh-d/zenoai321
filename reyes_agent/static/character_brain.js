// Shared "character brain" -- the state vocabulary and dimensional Emotion
// Engine used by BOTH renderers of ZENO's presence: orb.js (the existing
// glowing-sphere avatar, still used wherever nothing else has opted in yet)
// and character.js (the 2D cartoon companion the user actually wants as the
// desktop companion -- see the "keep going... i dont want the mini orb i
// want that type of 2d cartoon character" instruction).
//
// This file used to be duplicated inline in orb.js. Splitting it out is not
// a rewrite of that logic -- every constant and function below is verbatim
// what orb.js already had -- it just gives character.js the same real,
// already-tested emotion brain instead of a second copy of it.

export const SPECIALIST_IDS = ["aris", "tosin", "stark", "zeal", "titan", "apex", "nova", "hermes_comm", "oracle", "atlas", "ultron", "kate", "helios"];

// `hue` (CSS hsl degrees) and `eyes` (an expression class name) are shared
// across renderers; `spin` is orb-specific (ring rotation seconds) and is
// simply ignored by a renderer that has no spinning ring.
export const STATES = {
  idle:          { hue: 187, spin: 22, eyes: "calm" },
  listening:     { hue: 32,  spin: 16, eyes: "attentive" },
  understanding: { hue: 208, spin: 15, eyes: "attentive" },
  thinking:      { hue: 259, spin: 9,  eyes: "focused" },
  acting:        { hue: 306, spin: 8,  eyes: "focused" },
  waiting:       { hue: 56,  spin: 28, eyes: "scanning" },
  success:       { hue: 137, spin: 20, eyes: "bright" },
  processing:    { hue: 259, spin: 9,  eyes: "focused" },
  speaking:      { hue: 180, spin: 7,  eyes: "calm" },
  error:         { hue: 356, spin: 26, eyes: "concerned" },
  searching:     { hue: 58,  spin: 6,  eyes: "scanning" },
  coding:        { hue: 137, spin: 11, eyes: "focused" },
  creating:      { hue: 306, spin: 8,  eyes: "bright" },
  communicating: { hue: 209, spin: 10, eyes: "calm" },
  learning:      { hue: 47,  spin: 18, eyes: "attentive" },
  reasoning:     { hue: 270, spin: 7,  eyes: "focused" },
  sleeping:      { hue: 210, spin: 40, eyes: "closed" },
  notice:        { hue: 32,  spin: 10, eyes: "attentive" },
  happy:         { hue: 120, spin: 14, eyes: "bright" },
  amused:        { hue: 45,  spin: 10, eyes: "bright" },
  curious:       { hue: 190, spin: 13, eyes: "attentive" },
  focused:       { hue: 259, spin: 14, eyes: "focused" },
  serious:       { hue: 220, spin: 24, eyes: "focused" },
  concerned:     { hue: 15,  spin: 20, eyes: "concerned" },
  surprised:     { hue: 320, spin: 5,  eyes: "bright" },
  warning:       { hue: 40,  spin: 18, eyes: "concerned" },
  interrupted:   { hue: 356, spin: 5,  eyes: "concerned" },
  calling_agent: { hue: 270, spin: 8,  eyes: "scanning" },
  moving:        { hue: 187, spin: 4,  eyes: "calm" },
  standby:       { hue: 200, spin: 45, eyes: "calm" },
  boot:          { hue: 187, spin: 3,  eyes: "closed" },
  smile:         { hue: 130, spin: 16, eyes: "bright" },
  laugh:         { hue: 50,  spin: 6,  eyes: "bright" },
  smug:          { hue: 280, spin: 12, eyes: "focused" },
  proud:         { hue: 45,  spin: 12, eyes: "bright" },
  excited:       { hue: 330, spin: 4,  eyes: "bright" },
  shocked:       { hue: 300, spin: 2,  eyes: "bright" },
  confused:      { hue: 270, spin: 12, eyes: "scanning" },
  deep_thinking: { hue: 259, spin: 20, eyes: "focused" },
  whispering:    { hue: 190, spin: 10, eyes: "calm" },
  worried:       { hue: 20,  spin: 22, eyes: "concerned" },
  annoyed:       { hue: 15,  spin: 14, eyes: "concerned" },
  angry:         { hue: 5,   spin: 8,  eyes: "concerned" },
  suspicious:    { hue: 265, spin: 16, eyes: "scanning" },
  embarrassed:   { hue: 340, spin: 18, eyes: "attentive" },
  bored:         { hue: 210, spin: 34, eyes: "calm" },
  sleepy:        { hue: 215, spin: 30, eyes: "calm" },
  waking:        { hue: 187, spin: 6,  eyes: "attentive" },
  celebrating:   { hue: 100, spin: 3,  eyes: "bright" },
};

// States driven directly by real, authoritative pipeline events -- the
// Emotion Engine's derived expression must NEVER silently override one of
// these mid-turn. Voice/task correctness always outranks a mood swing.
export const EMOTION_PROTECTED_STATES = new Set([
  "listening", "understanding", "thinking", "acting", "waiting", "processing",
  "speaking", "error", "notice", "calling_agent", "interrupted", "boot",
]);

export const EMOTION_DIMENSIONS = ["valence", "arousal", "confidence", "curiosity",
  "focus", "urgency", "amusement", "concern", "energy", "social_engagement"];
export const EMOTION_BASELINE = { valence: 0.55, arousal: 0.35, confidence: 0.6, curiosity: 0.4,
  focus: 0.4, urgency: 0.1, amusement: 0.2, concern: 0.1, energy: 0.6, social_engagement: 0.5 };
export const EMOTION_DECAY_PER_S = { valence: 0.03, arousal: 0.06, confidence: 0.015, curiosity: 0.05,
  focus: 0.03, urgency: 0.12, amusement: 0.08, concern: 0.09, energy: 0.02, social_engagement: 0.04 };
export const clamp01 = (v) => Math.max(0, Math.min(1, v));

export function deriveExpression(s) {
  // Ordered most-specific-first; first match wins. Thresholds are
  // deliberately not razor-thin -- real emotional state rarely sits exactly
  // on a boundary, and flapping between two adjacent expressions every tick
  // would look broken, not alive.
  if (s.urgency > 0.7 && s.concern > 0.55) return "warning";
  if (s.concern > 0.65 && s.arousal > 0.55) return "angry";
  if (s.concern > 0.55 && s.valence < 0.35) return "worried";
  if (s.concern > 0.4 && s.arousal < 0.45) return "annoyed";
  if (s.confidence > 0.7 && s.amusement > 0.55) return "smug";
  if (s.arousal > 0.75 && s.valence > 0.65 && s.social_engagement > 0.5) return "celebrating";
  if (s.arousal > 0.7 && s.valence > 0.6) return "excited";
  if (s.arousal > 0.75 && s.valence < 0.45) return "shocked";
  if (s.arousal > 0.55 && s.valence > 0.5 && s.confidence < 0.4) return "surprised";
  if (s.amusement > 0.7 && s.arousal > 0.5) return "laugh";
  if (s.amusement > 0.5 && s.valence > 0.55) return "amused";
  if (s.confidence > 0.65 && s.valence > 0.6 && s.social_engagement > 0.5) return "proud";
  if (s.valence > 0.7 && s.energy > 0.5) return "happy";
  if (s.valence > 0.6 && s.energy > 0.35) return "smile";
  if (s.curiosity > 0.65 && s.focus < 0.55) return "curious";
  if (s.curiosity > 0.5 && s.confidence < 0.4) return "confused";
  if (s.curiosity > 0.45 && s.concern > 0.35) return "suspicious";
  if (s.focus > 0.7 && s.arousal < 0.4) return "deep_thinking";
  if (s.focus > 0.55) return "focused";
  if (s.valence < 0.4 && s.social_engagement < 0.35) return "embarrassed";
  if (s.energy < 0.25 && s.arousal < 0.3) return "sleepy";
  if (s.energy < 0.35 && s.social_engagement < 0.3 && s.curiosity < 0.3) return "bored";
  if (s.arousal < 0.3 && s.energy < 0.4) return "serious";
  return "idle";
}

export function createEmotionEngine(onDerived) {
  const state = { ...EMOTION_BASELINE };
  let lastTickMs = null;

  function apply(deltas, { immediate = false } = {}) {
    for (const key of EMOTION_DIMENSIONS) {
      if (!(key in deltas)) continue;
      const target = clamp01(deltas[key]);
      // Nudge toward target rather than snapping -- this IS the momentum:
      // one strongly-worded event moves the needle, it does not teleport
      // ZENO from bored to ecstatic in one frame.
      state[key] = immediate ? target : state[key] + (target - state[key]) * 0.6;
    }
    onDerived(deriveExpression(state), { ...state });
  }

  function tickDecay(nowMs) {
    if (lastTickMs === null) { lastTickMs = nowMs; return; }
    // Clamp elapsed time -- a hidden/backgrounded tab must not "catch up"
    // in one enormous jump the moment it becomes visible again.
    const dt = Math.min(2, (nowMs - lastTickMs) / 1000);
    lastTickMs = nowMs;
    let changed = false;
    for (const key of EMOTION_DIMENSIONS) {
      const before = state[key];
      state[key] = before + (EMOTION_BASELINE[key] - before) * Math.min(1, EMOTION_DECAY_PER_S[key] * dt * 4);
      if (Math.abs(state[key] - before) > 0.002) changed = true;
    }
    if (changed) onDerived(deriveExpression(state), { ...state });
  }

  return { apply, tickDecay, snapshot: () => ({ ...state }) };
}
