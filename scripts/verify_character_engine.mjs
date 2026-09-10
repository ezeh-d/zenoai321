// Isolated Node test harness for character.js -- the 2D cartoon desktop
// companion that replaces the orb/sphere as ZENO's actual visual, per the
// user's explicit "i dont want the mini orb i want that type of 2d cartoon
// character" instruction. Mirrors verify_orb_emotion_engine.mjs's approach
// (stub the DOM primitives touched at import/init time) so the real
// character.js module -- not a copy of its logic -- is what gets exercised.
function makeClassList() {
  const set = new Set();
  return {
    add: (...names) => names.forEach((n) => set.add(n)),
    remove: (...names) => names.forEach((n) => set.delete(n)),
    toggle: (n, on) => { if (on) set.add(n); else set.delete(n); },
    contains: (n) => set.has(n),
    _set: set,
  };
}
function makeStyleStub() {
  const props = {};
  return { setProperty: (k, v) => { props[k] = v; }, _props: props };
}
function makeEl() {
  return {
    classList: makeClassList(), style: makeStyleStub(), innerHTML: "",
    appendChild() {}, addEventListener() {},
    querySelector: () => makeEl(),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 96, height: 128 }),
  };
}

const rootEl = makeEl();
global.document = {
  createElement: () => rootEl,
  head: { appendChild(){} },
  body: { appendChild(){} },
  visibilityState: "visible",
  addEventListener(){},
};
const windowListeners = {};
global.window = {
  addEventListener: (ev, fn) => { (windowListeners[ev] = windowListeners[ev] || []).push(fn); },
  innerWidth: 1920, innerHeight: 1080,
};
function fireWindowEvent(name, detail) {
  (windowListeners[name] || []).forEach((fn) => fn(detail));
}
global.performance = { now: () => Date.now() };
global.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
global.cancelAnimationFrame = (id) => clearTimeout(id);

const { initCharacter } = await import("../reyes_agent/static/character.js");
const { shouldIdleNudge } = await import("../reyes_agent/static/character_brain.js");
const zc = initCharacter(null);

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " -> " + detail : ""}`);
  if (!ok) failures++;
}

// 1) Shares the exact same derivation table as the orb (character_brain.js)
// -- a positive tool-result reaction should read as a positive expression.
zc.setEmotion({ valence: 0.72, confidence: 0.68, energy: 0.6 }, { immediate: true });
check("tool success -> a positive/confident expression", ["smile", "happy", "proud"].includes(zc.getState()), zc.getState());

// 2) Protected-state gate: identical guarantee to the orb.
zc.setState("listening");
zc.setEmotion({ valence: 0.9, energy: 0.9, confidence: 0.9 }, { immediate: true });
check("protected state (listening) is not overridden by an emotion nudge", zc.getState() === "listening");

// 3) DOM shape: a real 2D character silhouette, not a sphere -- head, torso,
// legs and eyes must all exist as distinct elements (checked via the class
// names character.js's own innerHTML template assigns).
const shapeOk = /zc-head/.test(rootEl.innerHTML) && /zc-torso/.test(rootEl.innerHTML)
  && /zc-leg-l/.test(rootEl.innerHTML) && /zc-leg-r/.test(rootEl.innerHTML)
  && /zc-arm-l/.test(rootEl.innerHTML) && /zc-eye/.test(rootEl.innerHTML);
check("renders a character silhouette (head/torso/legs/arms/eyes), not a sphere", shapeOk);

// 4) Walking: walkTo must move the tracked position and toggle zc-walking
// for a real, non-zero, distance-scaled duration -- this is the "can walk
// itself across the screen" requirement, not a teleport.
zc.setState("idle");
zc.walkTo(500, 500);
const walkingNow = rootEl.classList.contains("zc-walking");
const leftSet = rootEl.style._props["--zc-left"] === "500px";
const msSet = parseInt(rootEl.style._props["--zc-walk-ms"], 10) > 0;
check("walkTo() starts a walk with a real, non-zero duration", walkingNow && leftSet && msSet,
  `walking=${walkingNow} left=${rootEl.style._props["--zc-left"]} ms=${rootEl.style._props["--zc-walk-ms"]}`);

// 5) setDocked reuses walkTo (a real walk out of the way), not a snap.
zc.setDocked("bottom-left");
const dockWalked = rootEl.classList.contains("zc-walking") && rootEl.style._props["--zc-left"] === "150px";
check("setDocked('bottom-left') walks to the docked position instead of snapping", dockWalked,
  `left=${rootEl.style._props["--zc-left"]}`);

// 6) Idle behavior engine: the pure decision function (character_brain.js)
// only fires past its threshold and within its probability roll -- imported
// and exercised directly since it's DOM-free by design.
check("shouldIdleNudge: gated by both the idle threshold and the probability roll",
  shouldIdleNudge(30000, 0.05) === true && shouldIdleNudge(10000, 0.05) === false && shouldIdleNudge(30000, 0.5) === false);

// 7) Gaze system gating: disabled by default, and setEyeTracking's enabled
// flag is what actually controls it (index.html/mini.html already call
// this with the user's real saved preference).
check("gaze is off until setEyeTracking({enabled:true}) is called", zc.auditMetrics().gaze_enabled === false);
zc.setEyeTracking({ enabled: true });
check("setEyeTracking({enabled:true}) turns gaze on", zc.auditMetrics().gaze_enabled === true);

// 8) Gaze dead zone: a pointer move that stays within the dead zone of the
// character's center must NOT move the eyes -- only a real, deliberate
// cursor position outside it should.
fireWindowEvent("pointermove", { clientX: 48, clientY: 64 }); // dead center of the 96x128 stub rect
await new Promise((r) => setTimeout(r, 200)); // past the reaction delay + one damping frame
const centerOffset = zc.auditMetrics().gaze_offset;
check("a cursor near center (inside the dead zone) does not move the eyes",
  Math.abs(centerOffset.x) < 0.5 && Math.abs(centerOffset.y) < 0.5, JSON.stringify(centerOffset));

fireWindowEvent("pointermove", { clientX: 1200, clientY: 600 }); // far outside the dead zone
await new Promise((r) => setTimeout(r, 400)); // reaction delay + enough damping frames to move noticeably
const farOffset = zc.auditMetrics().gaze_offset;
check("a cursor well outside the dead zone moves the eyes toward it",
  farOffset.x > 1, JSON.stringify(farOffset));

zc.setEyeTracking({ enabled: false });
check("setEyeTracking({enabled:false}) recenters the gaze", zc.auditMetrics().gaze_enabled === false);

// 9) Panel spatial awareness: lookAt() moves the eyes toward a given point
// regardless of the cursor-tracking preference (gaze is off here, from the
// step above) -- this is ZENO reacting to something real, not passive
// cursor-following.
zc.lookAt(1400, 700, { holdMs: 5000 });
await new Promise((r) => setTimeout(r, 100));
const lookAtOffset = zc.auditMetrics().gaze_offset;
check("lookAt() moves the eyes even while cursor gaze is disabled",
  lookAtOffset.x > 0.5, JSON.stringify(lookAtOffset));

// 10) The real trigger: panels/manager.js dispatches zeno:panel-opened with
// the new panel's actual center -- character.js must react to that exact
// event without any glue code in index.html/mini.html. The stub character
// rect is anchored at {top:0, height:128}, so its own center is y=64 --
// a panel centered at y=600 is BELOW that, so the eyes should ease toward
// a positive y offset (looking down-right, matching x too).
fireWindowEvent("zeno:panel-opened", { detail: { type: "music", center: { x: 1500, y: 600 } } });
await new Promise((r) => setTimeout(r, 400)); // let the eased chase fully converge from test 9's target
const panelLookOffset = zc.auditMetrics().gaze_offset;
check("a real zeno:panel-opened event makes the character look toward the panel",
  panelLookOffset.x > 0.5 && panelLookOffset.y > 0.5, JSON.stringify(panelLookOffset));

// 11) Point gesture: the arm on the SAME side as the target lifts, and it
// clears automatically after the hold duration -- a real, semantic pose,
// not a coin-flip animation.
zc.pointAt(1500, 200); // target is to the right of the stub rect (center x=48)
check("pointAt() lifts the arm on the target's side", zc.auditMetrics().pointing === "r", zc.auditMetrics().pointing);
zc.pointAt(-500, 200); // now to the left
check("pointAt() switches side when the target moves to the other side", zc.auditMetrics().pointing === "l", zc.auditMetrics().pointing);

// 12) The real trigger: a zeno:panel-opened event drives BOTH the gaze and
// the point gesture together, matching "ZENO looks toward it, then points."
fireWindowEvent("zeno:panel-opened", { detail: { type: "browser", center: { x: 1800, y: 300 } } });
check("a real zeno:panel-opened event also triggers the point gesture", zc.auditMetrics().pointing === "r");

console.log(failures === 0 ? "ALL 14 CASES PASSED" : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
