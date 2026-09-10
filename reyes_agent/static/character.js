// ZENO's 2D cartoon desktop companion.
//
// The user explicitly does not want the orb/sphere as ZENO's final visual
// ("i dont want the mini orb i want that type of 2d cartoon character that
// is the desktop companion", following an earlier request for something
// that "can walk itself across the screen" with "differnt chracteristics").
// This is an ORIGINAL character -- a small round-headed robot-ish figure --
// not a trace or rename of any existing copyrighted design (see the
// declined "Dexter" request earlier in this project's history).
//
// This is a PLACEHOLDER body: pure CSS/DOM shapes, no image assets, so it
// renders today without blocking on the user's own final art (their own
// instruction: "I WILL SUPPLY FINAL ZENO ART... Use temporary assets/
// placeholders"). When real art exists, only the shape-building block below
// needs to change -- everything else (state, emotion, walking, docking,
// the public API) stays the same, because none of it is orb-specific.
//
// Public API is a superset of orb.js's (setState / pulse / setPerformanceMode
// / setActive / setDocked / dispatchAgent / setAgentWorking /
// getAgentScreenPositions / setEyes / setEyeTracking / blink / auditMetrics
// / specialists / setEmotion / getEmotionState / getState), PLUS walkTo --
// so index.html/mini.html only need their `initOrb` import swapped for
// `initCharacter`; nothing that already calls methods on the returned
// object needs to change.
import { STATES, SPECIALIST_IDS, EMOTION_PROTECTED_STATES, createEmotionEngine, shouldIdleNudge } from "./character_brain.js";

let stylesInjected = false;
function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    #zeno-character {
      position: fixed; top: var(--zc-top, 50%); left: var(--zc-left, 50%);
      width: 96px; height: 128px; margin: -64px 0 0 -48px;
      transform: scale(var(--zc-scale, 1)) scaleX(var(--zc-facing, 1));
      z-index: 0; pointer-events: none;
      /* "walk itself across the screen": position moves via top/left with a
         real duration (walkTo below sets --zc-walk-ms per trip -- distance
         at a constant speed, not one fixed time for every trip), not a
         teleport. Docking reuses this same walk, so ZENO visibly steps out
         of the way instead of snapping. */
      transition: top var(--zc-walk-ms, 900ms) linear, left var(--zc-walk-ms, 900ms) linear,
                  transform .35s ease;
    }
    @media (prefers-reduced-motion: reduce) {
      #zeno-character { transition: transform .2s ease; }
    }
    #zeno-character .zc-shadow {
      position: absolute; left: 50%; bottom: 2px; width: 46px; height: 10px;
      margin-left: -23px; border-radius: 50%;
      background: radial-gradient(circle, rgba(0,0,0,.32), transparent 72%);
    }
    #zeno-character .zc-body {
      position: absolute; inset: 0; transition: transform .18s ease;
    }
    /* A gentle idle bob -- alive without a WebGL loop, same "cheap CSS
       only" philosophy as the orb this replaces. */
    #zeno-character.zc-motion:not(.lite) .zc-body { animation: zc-bob 2.6s ease-in-out infinite; }
    #zeno-character.zc-walking .zc-body { animation: zc-walk-bob .5s ease-in-out infinite; }
    @keyframes zc-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
    @keyframes zc-walk-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }

    #zeno-character .zc-torso {
      position: absolute; left: 50%; bottom: 14px; width: 50px; height: 40px;
      margin-left: -25px; border-radius: 22px 22px 18px 18px;
      background: linear-gradient(180deg, hsl(var(--zc-hue) 70% 46%), hsl(var(--zc-hue) 65% 32%));
      box-shadow: inset 0 -6px 10px rgba(0,0,0,.22), inset 0 4px 8px rgba(255,255,255,.14);
      transition: background .6s ease;
    }
    #zeno-character .zc-chest {
      position: absolute; left: 50%; top: 8px; width: 16px; height: 16px; margin-left: -8px;
      border-radius: 50%; background: hsl(var(--zc-hue) 90% 72% / .85);
      box-shadow: 0 0 10px hsl(var(--zc-hue) 90% 65% / .8);
    }
    #zeno-character.energy-on .zc-chest { box-shadow: 0 0 16px hsl(var(--zc-hue) 95% 68% / .95); }

    #zeno-character .zc-arm { position: absolute; top: 18px; width: 9px; height: 26px; border-radius: 6px;
      background: hsl(var(--zc-hue) 55% 40%); transform-origin: top center; transition: transform .3s ease; }
    #zeno-character .zc-arm-l { left: 6px; }
    #zeno-character .zc-arm-r { right: 6px; }
    #zeno-character.zc-walking .zc-arm-l { animation: zc-swing-l .5s ease-in-out infinite; }
    #zeno-character.zc-walking .zc-arm-r { animation: zc-swing-r .5s ease-in-out infinite; }
    @keyframes zc-swing-l { 0%, 100% { transform: rotate(-16deg); } 50% { transform: rotate(16deg); } }
    @keyframes zc-swing-r { 0%, 100% { transform: rotate(16deg); } 50% { transform: rotate(-16deg); } }

    #zeno-character .zc-leg { position: absolute; bottom: 0; width: 11px; height: 18px; border-radius: 5px;
      background: hsl(var(--zc-hue) 40% 28%); transform-origin: top center; transition: transform .3s ease; }
    #zeno-character .zc-leg-l { left: 50%; margin-left: -13px; }
    #zeno-character .zc-leg-r { left: 50%; margin-left: 2px; }
    #zeno-character.zc-walking .zc-leg-l { animation: zc-step-l .5s ease-in-out infinite; }
    #zeno-character.zc-walking .zc-leg-r { animation: zc-step-r .5s ease-in-out infinite; }
    @keyframes zc-step-l { 0%, 100% { transform: rotate(18deg); } 50% { transform: rotate(-18deg); } }
    @keyframes zc-step-r { 0%, 100% { transform: rotate(-18deg); } 50% { transform: rotate(18deg); } }
    @media (prefers-reduced-motion: reduce) {
      #zeno-character .zc-arm, #zeno-character .zc-leg, #zeno-character .zc-body { animation: none !important; }
    }

    #zeno-character .zc-head {
      position: absolute; left: 50%; bottom: 50px; width: 56px; height: 52px; margin-left: -28px;
      border-radius: 50%;
      background: radial-gradient(circle at 34% 28%, hsl(var(--zc-hue) 85% 80%), hsl(var(--zc-hue) 75% 58%) 55%, hsl(var(--zc-hue) 60% 34%) 100%);
      box-shadow: inset 0 -6px 10px rgba(0,0,0,.2), inset 0 5px 8px rgba(255,255,255,.2);
      transition: background .6s ease;
    }
    #zeno-character .zc-antenna { position: absolute; left: 50%; bottom: 100px; width: 3px; height: 14px;
      margin-left: -1.5px; background: hsl(var(--zc-hue) 40% 45%); border-radius: 2px; }
    #zeno-character .zc-antenna-tip { position: absolute; left: 50%; bottom: 112px; width: 8px; height: 8px;
      margin-left: -4px; border-radius: 50%; background: hsl(var(--zc-hue) 95% 70%);
      box-shadow: 0 0 8px hsl(var(--zc-hue) 95% 65% / .85); transition: background .6s ease; }
    #zeno-character.zc-motion:not(.lite) .zc-antenna-tip { animation: zc-antenna-pulse 2.2s ease-in-out infinite; }
    @keyframes zc-antenna-pulse { 0%, 100% { opacity: .7; } 50% { opacity: 1; } }

    /* --- expressive eyes: identical vocabulary to the orb (eyes-calm /
       eyes-attentive / ... ), so setState/setEyes need zero character-
       specific branching -- same class names, scoped to this element. */
    #zeno-character .zc-eyes { position: absolute; left: 50%; bottom: 66px; width: 34px; height: 16px;
      margin-left: -17px; display: flex; align-items: center; justify-content: space-between;
      pointer-events: none; transition: transform .5s ease; }
    #zeno-character .zc-eye { width: 30%; height: 70%; border-radius: 50%;
      background: rgba(8, 14, 26, 0.88);
      box-shadow: inset 0 -10% 16% rgba(255,255,255,0.3), 0 0 6px hsl(var(--zc-hue) 90% 70% / 0.5);
      transition: height .32s cubic-bezier(.3,.8,.3,1), width .32s ease,
                  transform .4s ease, opacity .3s ease, border-radius .3s ease; }
    #zeno-character.blinking .zc-eye { height: 8%; }
    #zeno-character.eyes-calm .zc-eye       { height: 62%; }
    #zeno-character.eyes-attentive .zc-eye  { height: 78%; width: 34%; }
    #zeno-character.eyes-focused .zc-eye    { height: 38%; width: 36%; border-radius: 40%; }
    #zeno-character.eyes-scanning .zc-eye   { height: 50%; animation: zc-scan 1.5s ease-in-out infinite; }
    #zeno-character.eyes-bright .zc-eye     { height: 76%; box-shadow: inset 0 -10% 16% rgba(255,255,255,.4), 0 0 10px hsl(var(--zc-hue) 95% 75% / .85); }
    #zeno-character.eyes-concerned .zc-eye:first-child { transform: rotate(11deg); }
    #zeno-character.eyes-concerned .zc-eye:last-child  { transform: rotate(-11deg); }
    #zeno-character.eyes-closed .zc-eye     { height: 8%; opacity: .75; }
    @keyframes zc-scan { 0%, 100% { transform: translateX(-22%); } 50% { transform: translateX(22%); } }
    @media (prefers-reduced-motion: reduce) {
      #zeno-character .zc-eye { animation: none !important; }
    }
    #zeno-character.zc-pulse .zc-body { animation: zc-pulse-burst .5s ease-out; }
    #zeno-character.zc-motion:not(.lite).zc-pulse .zc-body { animation: zc-bob 2.6s ease-in-out infinite, zc-pulse-burst .5s ease-out; }
    @keyframes zc-pulse-burst { 0% { filter: brightness(1); } 30% { filter: brightness(1.5); } 100% { filter: brightness(1); } }
  `;
  document.head.appendChild(style);
}

// Bridge onto the same shared visual-event bus the orb uses, so any
// existing listener (a Pixi overlay, a HUD) reacts identically regardless
// of which renderer is actually mounted. One-way report, never a dependency.
let _visualBus = null;
try { import("./visual_events.js").then((m) => { _visualBus = m; }).catch(() => {}); } catch (_) {}
const _STATE_EVENT = {
  listening: "zeno:listening", understanding: "zeno:thinking", thinking: "zeno:thinking",
  reasoning: "zeno:thinking", processing: "zeno:thinking", acting: "zeno:executing",
  coding: "zeno:executing", speaking: "zeno:speaking", success: "zeno:success",
  error: "zeno:error", idle: "zeno:idle",
};
function _emitVisual(ev, detail) { try { _visualBus && _visualBus.emit(ev, detail); } catch (_) {} }

export function initCharacter(canvas) {
  injectStyles();
  if (canvas) canvas.style.display = "none";

  const root = document.createElement("div");
  root.id = "zeno-character";
  root.innerHTML = `<div class="zc-shadow"></div><div class="zc-body">`
    + `<div class="zc-leg zc-leg-l"></div><div class="zc-leg zc-leg-r"></div>`
    + `<div class="zc-torso"><div class="zc-chest"></div></div>`
    + `<div class="zc-arm zc-arm-l"></div><div class="zc-arm zc-arm-r"></div>`
    + `<div class="zc-antenna"></div><div class="zc-antenna-tip"></div>`
    + `<div class="zc-head"></div>`
    + `<div class="zc-eyes"><div class="zc-eye"></div><div class="zc-eye"></div></div>`
    + `</div>`;
  (canvas && canvas.parentNode ? canvas.parentNode : document.body).appendChild(root);

  let currentHue = STATES.idle.hue;
  root.style.setProperty("--zc-hue", String(currentHue));

  let currentEyes = "calm";
  let currentState = "idle";
  root.classList.add("zc-idle");
  function setEyes(expression) {
    if (expression === currentEyes) return;
    root.classList.remove("eyes-" + currentEyes);
    currentEyes = expression;
    root.classList.add("eyes-" + currentEyes);
  }
  root.classList.add("eyes-calm");

  function setState(name) {
    const s = STATES[name] || STATES.idle;
    const nextState = STATES[name] ? name : "idle";
    root.classList.remove("zc-" + currentState);
    currentState = nextState;
    root.classList.add("zc-" + currentState);
    root.classList.toggle("zc-motion", currentState !== "idle" && currentState !== "waiting");
    _emitVisual("zeno:state", { state: currentState });
    const _ve = _STATE_EVENT[currentState];
    if (_ve) _emitVisual(_ve, { state: currentState });
    currentHue = s.hue;
    root.style.setProperty("--zc-hue", String(currentHue));
    setEyes(s.eyes || "calm");
    // Idle behavior engine (Phase 16): any REAL state change resets the
    // idle clock -- only genuine, sustained idleness (not a real event
    // ZENO just reacted to) should ever produce an idle attention blip.
    if (nextState !== "idle") idleSinceMs = _now();
  }

  // Same dimensional Emotion Engine the orb uses (character_brain.js) --
  // derived expressions only ever call setState, and never override a
  // real, event-driven pipeline state (EMOTION_PROTECTED_STATES).
  const emotionEngine = createEmotionEngine((expression) => {
    if (!EMOTION_PROTECTED_STATES.has(currentState)) setState(expression);
  });
  let emotionTickTimer = setInterval(() => {
    if (document.visibilityState === "visible") emotionEngine.tickDecay(performance.now());
  }, 2500);

  // Idle behavior engine (Phase 16, see character_brain.js's
  // shouldIdleNudge -- adapted from simple-desktop-pet's idle-inactivity-
  // timer). Runs on the SAME 2.5s cadence as emotion decay above (one
  // timer tier, not a second animation clock): while genuinely idle for a
  // while, occasionally nudge curiosity/social_engagement up a little so
  // the existing Emotion Engine can naturally derive a brief "glance
  // around" mood -- then its own decay pulls it back. setState() resets
  // idleSinceMs the moment anything real happens, so this can never fire
  // mid-task or fight a real event-driven expression.
  const _now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  let idleSinceMs = _now();
  let idleTickTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    if (currentState !== "idle") return;
    if (shouldIdleNudge(_now() - idleSinceMs, Math.random())) {
      emotionEngine.apply({ curiosity: 0.55, social_engagement: 0.5 });
    }
  }, 2500);

  // Blink on a random human-ish cadence -- identical rhythm to the orb.
  let blinkTimer = null;
  function scheduleBlink() {
    clearTimeout(blinkTimer);
    blinkTimer = setTimeout(() => {
      if (currentEyes !== "closed" && document.visibilityState === "visible") {
        root.classList.add("blinking");
        setTimeout(() => root.classList.remove("blinking"), 130);
        if (Math.random() < 0.22) {
          setTimeout(() => {
            root.classList.add("blinking");
            setTimeout(() => root.classList.remove("blinking"), 110);
          }, 240);
        }
      }
      scheduleBlink();
    }, 3000 + Math.random() * 5000);
  }
  scheduleBlink();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") scheduleBlink();
    else { clearTimeout(blinkTimer); blinkTimer = null; }
  });

  function pulse() {
    root.classList.remove("zc-pulse");
    void root.offsetWidth; // force reflow so a repeat pulse restarts the animation
    root.classList.add("zc-pulse");
    setTimeout(() => root.classList.remove("zc-pulse"), 550);
  }

  function setPerformanceMode(lite) {
    root.classList.toggle("lite", !!lite);
  }

  // "Can walk itself across the screen" (the user's explicit ask). Moves to
  // an absolute viewport position with real leg/arm animation for the
  // duration of the trip, not a teleport -- duration scales with distance
  // so a short hop and a cross-screen walk both look like walking, not a
  // fixed-speed slide.
  let walkTimer = null;
  let posLeft = window.innerWidth / 2, posTop = window.innerHeight / 2;
  root.style.setProperty("--zc-left", posLeft + "px");
  root.style.setProperty("--zc-top", posTop + "px");
  function walkTo(x, y, { speed = 140 } = {}) {
    const dx = x - posLeft, dy = y - posTop;
    const dist = Math.hypot(dx, dy);
    if (dist < 2) return;
    if (dx < -2) root.style.setProperty("--zc-facing", "-1");
    else if (dx > 2) root.style.setProperty("--zc-facing", "1");
    const ms = Math.max(220, Math.min(6000, (dist / speed) * 1000));
    root.style.setProperty("--zc-walk-ms", ms + "ms");
    posLeft = x; posTop = y;
    root.style.setProperty("--zc-left", posLeft + "px");
    root.style.setProperty("--zc-top", posTop + "px");
    root.classList.add("zc-walking");
    clearTimeout(walkTimer);
    walkTimer = setTimeout(() => root.classList.remove("zc-walking"), ms);
  }

  // Move out from behind an open panel -- now a genuine walk instead of a
  // snap, satisfying both the earlier "must move out of the way" work and
  // the new "can walk itself across the screen" ask with one mechanism.
  let currentDock = "center";
  function setDocked(mode) {
    const next = mode === "bottom-left" || mode === "bottom-right" ? mode : "center";
    if (next === currentDock) return;
    currentDock = next;
    const margin = 150, bottom = window.innerHeight - 90;
    if (next === "bottom-left") walkTo(margin, bottom);
    else if (next === "bottom-right") walkTo(window.innerWidth - margin, bottom);
    else walkTo(window.innerWidth / 2, window.innerHeight / 2);
  }
  window.addEventListener("zeno:panels-state", (event) => {
    const detail = (event && event.detail) || {};
    if (!detail.count) { setDocked("center"); return; }
    setDocked(detail.hasMaximized ? "bottom-right" : "bottom-left");
  });
  window.addEventListener("resize", () => {
    // Re-anchor without an animated walk on a plain window resize -- this
    // isn't ZENO deciding to move, it's the canvas changing under it.
    if (currentDock === "center") { posLeft = window.innerWidth / 2; posTop = window.innerHeight / 2; }
    else if (currentDock === "bottom-left") { posLeft = 150; posTop = window.innerHeight - 90; }
    else { posLeft = window.innerWidth - 150; posTop = window.innerHeight - 90; }
    root.style.setProperty("--zc-walk-ms", "0ms");
    root.style.setProperty("--zc-left", posLeft + "px");
    root.style.setProperty("--zc-top", posTop + "px");
  });

  let agentEnergy = 0;
  function dispatchAgent(_id) {
    pulse(); agentEnergy = 1; root.classList.add("energy-on");
    _emitVisual("agent:activated", { id: _id });
  }
  function setAgentWorking(_id, working) {
    agentEnergy = working ? 1 : 0;
    root.classList.toggle("energy-on", agentEnergy > 0);
    _emitVisual(working ? "agent:thinking" : "agent:completed", { id: _id });
  }
  function getAgentScreenPositions() { return []; }

  function setActive(on) {
    root.style.display = on ? "block" : "none";
    if (on) scheduleBlink();
    else clearTimeout(blinkTimer);
    if (!on) setGazeTarget(0, 0);
  }

  // === Gaze system (living-character master prompt Phase 11) ===
  // Research (_research/CHARACTER_REPO_INDEX.md #1, #7) found no reference
  // repo's cursor-gaze is separable from an opaque rigged-model runtime, so
  // this is a real, from-scratch implementation for this character rather
  // than a port -- but it targets the SAME properties Phase 11 calls out
  // explicitly: damping (eased chase, never an instant snap), a dead zone
  // (tiny cursor jitter near center is ignored), a reaction delay ("notices
  // after a slight delay", not a robotic lock-on), a maximum offset (eyes
  // cannot rotate past a small, readable range), and a return to neutral
  // once the cursor stops moving. Off by default; index.html/mini.html
  // already call setEyeTracking with the user's real saved preference, so
  // this only ever runs when actually enabled.
  const eyesLayer = root.querySelector(".zc-eyes");
  const GAZE_DEAD_ZONE_PX = 40;
  const GAZE_REACT_DELAY_MS = 120;
  const GAZE_NEUTRAL_AFTER_MS = 1400;
  const GAZE_MAX_X = 4.5, GAZE_MAX_Y = 3.2;
  let gazeEnabled = false;
  let gazeTargetX = 0, gazeTargetY = 0, gazeCurX = 0, gazeCurY = 0;
  let gazeRaf = null, gazeDebounceTimer = null, gazeNeutralTimer = null, pendingPointer = null;
  function writeGaze(x, y) {
    gazeCurX = x; gazeCurY = y;
    if (eyesLayer) eyesLayer.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
  }
  function stepGaze() {
    gazeRaf = null;
    const dx = gazeTargetX - gazeCurX, dy = gazeTargetY - gazeCurY;
    if (Math.abs(dx) < 0.08 && Math.abs(dy) < 0.08) { writeGaze(gazeTargetX, gazeTargetY); return; }
    // Eased chase, not a snap -- this IS the damping (same idea as the
    // orb's real spring, simplified: a fixed-rate lerp is enough motion
    // for a ~4px eye offset and needs no extra script dependency).
    writeGaze(gazeCurX + dx * 0.18, gazeCurY + dy * 0.18);
    gazeRaf = requestAnimationFrame(stepGaze);
  }
  function setGazeTarget(x, y) {
    gazeTargetX = x; gazeTargetY = y;
    if (gazeRaf === null) gazeRaf = requestAnimationFrame(stepGaze);
  }
  function applyGaze() {
    if (!pendingPointer) return;
    const p = pendingPointer; pendingPointer = null;
    if (!gazeEnabled || currentEyes === "closed") return;
    const rect = root.getBoundingClientRect ? root.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    const dx = p.x - cx, dy = p.y - cy;
    if (Math.hypot(dx, dy) < GAZE_DEAD_ZONE_PX) { setGazeTarget(0, 0); return; }
    const nx = Math.max(-1, Math.min(1, dx / 400));
    const ny = Math.max(-1, Math.min(1, dy / 400));
    setGazeTarget(nx * GAZE_MAX_X, ny * GAZE_MAX_Y);
  }
  function onPointerMove(e) {
    if (!gazeEnabled || currentEyes === "closed") return;
    pendingPointer = { x: e.clientX, y: e.clientY };
    clearTimeout(gazeDebounceTimer);
    gazeDebounceTimer = setTimeout(applyGaze, GAZE_REACT_DELAY_MS);
    clearTimeout(gazeNeutralTimer);
    gazeNeutralTimer = setTimeout(() => setGazeTarget(0, 0), GAZE_NEUTRAL_AFTER_MS);
  }
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  function setEyeTracking(options = {}) {
    gazeEnabled = !!(options && options.enabled);
    if (!gazeEnabled) {
      clearTimeout(gazeDebounceTimer); gazeDebounceTimer = null;
      clearTimeout(gazeNeutralTimer); gazeNeutralTimer = null;
      pendingPointer = null;
      setGazeTarget(0, 0);
    }
  }

  // Panel spatial awareness ("ZENO should look toward panels" / Phase 25):
  // a deliberate, event-driven glance toward a real screen point, reusing
  // the SAME damped gaze mechanism above rather than a second system --
  // and unlike cursor-tracking, this fires regardless of the user's eye-
  // tracking preference, since it's ZENO reacting to something that just
  // happened, not passive cursor-following.
  function lookAt(x, y, { holdMs = 1800 } = {}) {
    const rect = root.getBoundingClientRect ? root.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    const dx = x - cx, dy = y - cy;
    const nx = Math.max(-1, Math.min(1, dx / 400));
    const ny = Math.max(-1, Math.min(1, dy / 400));
    setGazeTarget(nx * GAZE_MAX_X, ny * GAZE_MAX_Y);
    clearTimeout(gazeNeutralTimer);
    gazeNeutralTimer = setTimeout(() => setGazeTarget(0, 0), holdMs);
  }
  window.addEventListener("zeno:panel-opened", (event) => {
    const center = event && event.detail && event.detail.center;
    if (center && typeof center.x === "number" && typeof center.y === "number") lookAt(center.x, center.y);
  });

  return {
    setState,
    pulse,
    setPerformanceMode,
    setActive,
    setDocked,
    walkTo,
    dispatchAgent,
    setAgentWorking,
    getAgentScreenPositions,
    setEyes,
    setEyeTracking,
    lookAt,
    blink: () => {
      root.classList.add("blinking");
      setTimeout(() => root.classList.remove("blinking"), 130);
    },
    auditMetrics: () => ({ blink_timer: blinkTimer !== null, emotion_ticker: emotionTickTimer !== null,
      idle_ticker: idleTickTimer !== null, gaze_enabled: gazeEnabled,
      gaze_offset: { x: gazeCurX, y: gazeCurY },
      walking: root.classList.contains("zc-walking") }),
    specialists: SPECIALIST_IDS.slice(),
    setEmotion: (deltas, opts) => emotionEngine.apply(deltas || {}, opts || {}),
    getEmotionState: () => emotionEngine.snapshot(),
    getState: () => currentState,
  };
}
