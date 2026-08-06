// One shared, lightweight animated-face system for every ZENO specialist.
//
// PERFORMANCE CONTRACT (this project has a real history of GUI lag on a
// 2-core machine, so these are hard rules, not aspirations):
//   * Pure CSS. No canvas, no WebGL, no particles, no per-face JS loop.
//     A state change is ONE className write.
//   * Only ACTIVE faces animate. Idle/offline faces are static -- their
//     keyframes are gated behind state classes, so an inactive face costs
//     the compositor nothing.
//   * `stopAll()` clears every animation when the Council closes, and the
//     module is lazy-imported so none of this loads until first opened.
//   * No box-shadow is animated. Glow sits on a static layer, exactly as
//     the main orb was fixed on 2026-08-05 after profiling showed animated
//     box-shadow forcing continuous GPU re-rasterisation.
//
// DISTINCT, NOT DUPLICATED
// Each agent differs by hue AND eye geometry AND accent shape, derived
// from its id -- so agents stay recognisable in greyscale/peripheral
// vision, not only by colour. ZENO itself is deliberately NOT in here: it
// keeps its own orb as the primary identity.

const FACE_STYLES = ["round", "narrow", "wide", "angular", "soft", "slit"];
const ACCENTS = ["ring", "bar", "dots", "arc", "none", "notch"];

let stylesInjected = false;

function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;
  const style = document.createElement("style");
  style.textContent = `
  .zface {
    position: relative; width: var(--zf-size, 84px); height: var(--zf-size, 84px);
    border-radius: 50%; flex-shrink: 0; cursor: default;
    --zf-s: 78; --zf-l: 46;
    background: radial-gradient(circle at 34% 28%,
      hsl(var(--zf-h) calc(var(--zf-s) * 1%) calc((var(--zf-l) + 28) * 1%)),
      hsl(var(--zf-h) calc(var(--zf-s) * 1%) calc(var(--zf-l) * 1%)) 52%,
      hsl(var(--zf-h) calc(var(--zf-s) * 0.9%) calc((var(--zf-l) - 26) * 1%)) 100%);
    filter: saturate(.45) brightness(.62);
    transition: filter .45s ease, transform .35s ease;
  }
  /* Static glow layer -- never animated (see header note). */
  .zface::before {
    content: ""; position: absolute; inset: -6px; border-radius: 50%;
    box-shadow: 0 0 14px hsl(var(--zf-h) 90% 60% / .0);
    transition: box-shadow .45s ease; pointer-events: none;
  }
  .zface.active { filter: saturate(1.15) brightness(1); }
  .zface.active::before { box-shadow: 0 0 16px hsl(var(--zf-h) 90% 60% / .55); }

  .zf-eyes { position: absolute; inset: 0; display: flex; align-items: center;
             justify-content: center; gap: 22%; }
  .zf-eye {
    width: 13%; height: 20%; border-radius: 50%;
    background: rgba(5, 10, 20, .84);
    box-shadow: inset 0 -12% 18% rgba(255,255,255,.22);
    transition: height .3s cubic-bezier(.3,.8,.3,1), width .3s ease, transform .35s ease;
  }
  .zf-brow { position:absolute; top:29%; width:19%; height:3px; border-radius:999px;
    background:rgba(5,10,20,.55); transition:transform .35s ease, opacity .35s ease; }
  .zf-brow.left { left:22%; } .zf-brow.right { right:22%; }
  /* per-agent eye geometry -- recognisable without colour */
  .zface[data-style="round"]   .zf-eye { height: 21%; width: 14%; }
  .zface[data-style="narrow"]  .zf-eye { height: 12%; width: 16%; border-radius: 40%; }
  .zface[data-style="wide"]    .zf-eye { height: 26%; width: 15%; }
  .zface[data-style="angular"] .zf-eye { height: 15%; width: 15%; border-radius: 22%; }
  .zface[data-style="soft"]    .zf-eye { height: 23%; width: 12%; }
  .zface[data-style="slit"]    .zf-eye { height: 9%;  width: 17%; border-radius: 30%; }

  /* mouth: only visible/animated while speaking */
  .zf-mouth {
    position: absolute; left: 50%; bottom: 24%; transform: translateX(-50%);
    width: 22%; height: 4%; border-radius: 999px;
    background: rgba(5,10,20,.72); opacity: 0; transition: opacity .25s ease;
  }
  .zface.speaking .zf-mouth { opacity: 1; animation: zf-talk .34s ease-in-out infinite; }
  @keyframes zf-talk {
    0%,100% { height: 4%;  width: 20%; }
    50%     { height: 13%; width: 26%; }
  }

  /* accents -- a second non-colour identity cue */
  .zf-accent { position: absolute; inset: 0; pointer-events: none; opacity: .5; }
  .zface[data-accent="ring"]  .zf-accent { border: 1.5px solid hsl(var(--zf-h) 90% 72% / .5); border-radius: 50%; inset: 5%; }
  .zface[data-accent="bar"]   .zf-accent { border-top: 2px solid hsl(var(--zf-h) 90% 72% / .55); inset: 18% 26% auto 26%; }
  .zface[data-accent="arc"]   .zf-accent { border-bottom: 2px solid hsl(var(--zf-h) 90% 72% / .5); border-radius: 50%; inset: 8%; }
  .zface[data-accent="notch"] .zf-accent { border-left: 2px solid hsl(var(--zf-h) 90% 72% / .5); inset: 28% auto 28% 12%; }
  .zface[data-accent="dots"]::after {
    content: ""; position: absolute; top: 12%; left: 50%; transform: translateX(-50%);
    width: 4px; height: 4px; border-radius: 50%; background: hsl(var(--zf-h) 90% 72% / .6);
  }

  /* --- states. Only these classes animate. ------------------------- */
  .zface.thinking .zf-eye { height: 10%; width: 16%; border-radius: 40%; }
  .zface.thinking .zf-eyes { animation: zf-ponder 2.2s ease-in-out infinite; }
  @keyframes zf-ponder { 0%,100% { transform: translateX(-5%); } 50% { transform: translateX(5%); } }

  .zface.listening .zf-eye { height: 27%; width: 14%; }

  .zface.working .zf-eye { height: 13%; width: 15%; border-radius: 35%; }
  .zface.working::before { box-shadow: 0 0 18px hsl(var(--zf-h) 92% 62% / .7); }
  .zface.working .zf-accent { animation: zf-spin 2.4s linear infinite; }
  @keyframes zf-spin { to { transform: rotate(360deg); } }

  /* WAITING is visibly distinct but deliberately static: an agent in a
     managed queue must not consume an animation loop before real work starts. */
  .zface.waiting { filter: saturate(.8) brightness(.85); }
  .zface.waiting::before { box-shadow: 0 0 13px hsl(45 95% 58% / .5); }

  .zface.success { filter: saturate(1.3) brightness(1.1); }
  .zface.success .zf-eye { height: 8%; border-radius: 40% 40% 0 0; }
  .zface.success::before { box-shadow: 0 0 20px hsl(140 85% 55% / .75); }

  .zface.warning::before { box-shadow: 0 0 18px hsl(45 95% 58% / .7); }
  .zface.warning .zf-eye:first-child { transform: rotate(9deg); }
  .zface.warning .zf-eye:last-child  { transform: rotate(-9deg); }

  .zface.error::before { box-shadow: 0 0 20px hsl(0 90% 60% / .8); }
  .zface.error .zf-eye:first-child { transform: rotate(16deg); }
  .zface.error .zf-eye:last-child  { transform: rotate(-16deg); }

  .zface.sleeping { filter: saturate(.25) brightness(.45); }
  .zface.sleeping .zf-eye { height: 2.5%; }
  .zface.blink .zf-eye { height: 2.5%; }

  /* Expressions are static poses plus transitions. A silent summoned agent
     can be visibly attentive without starting a compositor loop. */
  .zface[data-emotion="happy"] .zf-mouth,
  .zface[data-emotion="proud"] .zf-mouth,
  .zface[data-emotion="success"] .zf-mouth { opacity:.78; width:25%; height:7%; border-radius:0 0 999px 999px; }
  .zface[data-emotion="happy"] .zf-brow,
  .zface[data-emotion="proud"] .zf-brow { transform:translateY(-3px); }
  .zface[data-emotion="excited"] .zf-eye { height:29%; width:16%; }
  .zface[data-emotion="excited"] .zf-brow { transform:translateY(-5px); }
  .zface[data-emotion="curious"] .zf-eye:first-child { transform:translate(8%, -4%); }
  .zface[data-emotion="curious"] .zf-eye:last-child { transform:translate(8%, 4%); }
  .zface[data-emotion="curious"] .zf-brow.left { transform:translateY(-5px); }
  .zface[data-emotion="thinking"] .zf-brow.left { transform:rotate(-10deg) translateY(-2px); }
  .zface[data-emotion="confused"] .zf-brow.left { transform:rotate(-18deg) translateY(-4px); }
  .zface[data-emotion="confused"] .zf-brow.right { transform:rotate(8deg); }
  .zface[data-emotion="surprised"] .zf-eye { height:31%; width:16%; }
  .zface[data-emotion="surprised"] .zf-mouth { opacity:.72; width:12%; height:14%; border-radius:50%; }
  .zface[data-emotion="concerned"] .zf-brow.left { transform:rotate(13deg) translateY(-2px); }
  .zface[data-emotion="concerned"] .zf-brow.right { transform:rotate(-13deg) translateY(-2px); }
  .zface[data-emotion="serious"] .zf-eye { height:10%; width:17%; border-radius:35%; }
  .zface[data-emotion="serious"] .zf-brow.left { transform:rotate(9deg); }
  .zface[data-emotion="serious"] .zf-brow.right { transform:rotate(-9deg); }
  .zface[data-emotion="skeptical"] .zf-brow.left { transform:rotate(-17deg) translateY(-4px); }
  .zface[data-emotion="frustrated"] .zf-brow.left { transform:rotate(17deg) translateY(3px); }
  .zface[data-emotion="frustrated"] .zf-brow.right { transform:rotate(-17deg) translateY(3px); }
  .zface[data-emotion="sad"] .zf-eye { height:13%; }
  .zface[data-emotion="sad"] .zf-brow.left { transform:rotate(-12deg); }
  .zface[data-emotion="sad"] .zf-brow.right { transform:rotate(12deg); }
  .zface[data-emotion="warning"]::before { box-shadow:0 0 17px hsl(45 95% 58% / .72); }
  .zface[data-emotion="success"]::before { box-shadow:0 0 18px hsl(140 85% 55% / .68); }
  .zface.look-left .zf-eye, .zface.look-left .zf-brow { transform:translateX(-14%); }
  .zface.look-right .zf-eye, .zface.look-right .zf-brow { transform:translateX(14%); }
  .zface.reaction { transform:scale(1.045) translateY(-2px); }

  @media (prefers-reduced-motion: reduce) {
    .zface .zf-mouth, .zface .zf-eyes, .zface .zf-accent { animation: none !important; }
  }

  /* card chrome used by the Council view */
  .zf-card { display: flex; flex-direction: column; align-items: center; gap: 5px; width: 104px; }
  .zf-name { font: 700 10.5px system-ui, sans-serif; letter-spacing: .06em; color: var(--text); }
  .zf-role { font: 9.5px system-ui, sans-serif; color: var(--text-dim); text-align: center;
             line-height: 1.25; min-height: 22px; }
  .zf-state { font: 9px system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase;
              color: var(--text-dim); }
  .zf-card.is-active .zf-state { color: hsl(var(--zf-h) 90% 70%); }
  `;
  document.head.appendChild(style);
}

const STATES = new Set(["idle", "listening", "waiting", "thinking", "speaking", "working",
                        "success", "warning", "error", "sleeping"]);
const EMOTIONS = new Set(["neutral", "happy", "excited", "curious", "thinking", "confused",
                          "surprised", "concerned", "serious", "skeptical", "frustrated",
                          "proud", "sad", "warning", "success"]);
// Animated states -- used to decide whether a face costs anything.
const ANIMATED = new Set(["thinking", "speaking", "working"]);

// Hue alone loses real distinctions: STARK (#ef4444) and ULTRON (#b91c1c)
// are both hue 0 but obviously different reds, as are ORACLE/APEX in cyan.
// Carrying saturation and lightness keeps each agent's actual brand colour,
// clamped so no face becomes unreadably dark or blown out.
function hslFromHex(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
  if (!m) return { h: 200, s: 78, l: 46 };
  const r = parseInt(m[1], 16) / 255, g = parseInt(m[2], 16) / 255, b = parseInt(m[3], 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  const l = (max + min) / 2;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = ((h * 60) + 360) % 360;
  }
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  return {
    h: Math.round(h),
    s: Math.round(Math.max(30, Math.min(92, s * 100))),
    l: Math.round(Math.max(34, Math.min(62, l * 100))),
  };
}

function applyColor(el, hex) {
  const { h, s, l } = hslFromHex(hex);
  el.style.setProperty("--zf-h", String(h));
  el.style.setProperty("--zf-s", String(s));
  el.style.setProperty("--zf-l", String(l));
}

function hashIndex(id, len) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % len;
}

const faces = new Map();   // agentId -> { el, card, state, emotion, blinkTimer, reactionTimer }

/** Build (or return) one agent's face. Cheap: static DOM + CSS vars. */
export function createFace(agentId, cfg = {}, opts = {}) {
  injectStyles();
  if (faces.has(agentId)) return faces.get(agentId).card;

  const card = document.createElement("div");
  card.className = "zf-card";
  const el = document.createElement("div");
  el.className = "zface";
  el.dataset.agent = agentId;
  el.dataset.style = FACE_STYLES[hashIndex(agentId, FACE_STYLES.length)];
  el.dataset.accent = ACCENTS[hashIndex(agentId + "a", ACCENTS.length)];
  applyColor(el, cfg.color);
  if (opts.size) el.style.setProperty("--zf-size", opts.size + "px");
  el.innerHTML = `<div class="zf-accent"></div>`
    + `<div class="zf-brow left"></div><div class="zf-brow right"></div>`
    + `<div class="zf-eyes"><div class="zf-eye"></div><div class="zf-eye"></div></div>`
    + `<div class="zf-mouth"></div>`;
  el.title = `${cfg.name || agentId} — ${cfg.role || ""}`;

  const name = document.createElement("div");
  name.className = "zf-name";
  name.textContent = cfg.name || agentId.toUpperCase();
  const role = document.createElement("div");
  role.className = "zf-role";
  role.textContent = cfg.role || "";
  const state = document.createElement("div");
  state.className = "zf-state";
  state.textContent = "idle";

  card.append(el, name, role, state);
  applyColor(card, cfg.color);   // .zf-state label uses the same hue
  const face = { el, card, state: "idle", emotion: "neutral", stateEl: state,
                blinkTimer: null, reactionTimer: null };
  faces.set(agentId, face);
  el.dataset.emotion = "neutral";
  scheduleBlink(agentId);
  return card;
}

/** Set an agent's visual state. One className write; no loop. */
export function setState(agentId, state) {
  const f = faces.get(agentId);
  if (!f || !STATES.has(state) || f.state === state) return;
  f.el.classList.remove(f.state);
  f.state = state;
  f.el.classList.add(state);
  const active = state !== "idle" && state !== "sleeping";
  f.el.classList.toggle("active", active);
  f.card.classList.toggle("is-active", active);
  f.stateEl.textContent = state;

  // Blink only while awake and not currently using a state animation.
  clearTimeout(f.blinkTimer);
  f.blinkTimer = null;
  if (isBlinkEligible(state)) scheduleBlink(agentId);
}

function isBlinkEligible(state) {
  return state !== "sleeping" && !ANIMATED.has(state);
}

function blinkDelay(agentId) {
  // Stable per-agent cadence instead of a decorative randomizer.
  return 4700 + hashIndex(agentId + "blink", 7) * 530;
}

function scheduleBlink(agentId) {
  const f = faces.get(agentId);
  if (!f) return;
  f.blinkTimer = setTimeout(() => {
    if (document.visibilityState === "visible" && isBlinkEligible(f.state)) {
      f.el.classList.add("blink");
      setTimeout(() => f.el.classList.remove("blink"), 130);
    }
    if (isBlinkEligible(f.state)) scheduleBlink(agentId);
  }, blinkDelay(agentId));
}

/** Change a silent agent's expression without granting it speech. */
export function setEmotion(agentId, emotion = "neutral", { react = true } = {}) {
  const f = faces.get(agentId);
  const value = EMOTIONS.has(emotion) ? emotion : "neutral";
  if (!f || (f.emotion === value && !react)) return;
  f.emotion = value;
  f.el.dataset.emotion = value;
  if (!react) return;
  clearTimeout(f.reactionTimer);
  f.el.classList.add("reaction");
  f.reactionTimer = setTimeout(() => f.el.classList.remove("reaction"), 520);
}

/** Turn a silent agent toward the agent currently speaking. */
export function setAttention(agentId, targetAgent = "") {
  const f = faces.get(agentId);
  if (!f) return;
  f.el.classList.remove("look-left", "look-right");
  if (!targetAgent || targetAgent === agentId || !faces.has(targetAgent)) return;
  const ids = [...faces.keys()];
  f.el.classList.add(ids.indexOf(targetAgent) > ids.indexOf(agentId) ? "look-right" : "look-left");
}

export function speak(agentId, on) {
  setState(agentId, on ? "speaking" : "idle");
}

/** True when at least one face is in an animating state -- lets callers
 *  assert the performance contract rather than trust it. */
export function animatingCount() {
  let n = 0;
  for (const f of faces.values()) if (ANIMATED.has(f.state)) n++;
  return n;
}

export function known() { return [...faces.keys()]; }

/** Stop everything. Called when the Council closes. */
export function stopAll() {
  for (const [id, f] of faces) {
    clearTimeout(f.blinkTimer);
    clearTimeout(f.reactionTimer);
    f.blinkTimer = null;
    f.el.classList.remove(f.state, "active", "blink");
    f.el.classList.add("idle");
    f.state = "idle";
    f.stateEl.textContent = "idle";
    f.card.classList.remove("is-active");
    void id;
  }
}

/** Re-arm idle blinking after `stopAll()` (Council reopened, or the window
 *  became visible again). `setState` short-circuits when the state is
 *  unchanged, so blinking has to be restarted explicitly. */
export function resumeBlinks() {
  for (const [id, f] of faces) {
    if (isBlinkEligible(f.state) && !f.blinkTimer) scheduleBlink(id);
  }
}

export function destroyAll() {
  stopAll();
  for (const f of faces.values()) f.card.remove();
  faces.clear();
}

/** Remove one dismissed face and release its timer/DOM reference. */
export function destroyFace(agentId) {
  const f = faces.get(agentId);
  if (!f) return;
  clearTimeout(f.blinkTimer);
  clearTimeout(f.reactionTimer);
  f.card.remove();
  faces.delete(agentId);
}
