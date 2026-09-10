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
  return { classList: makeClassList(), style: makeStyleStub(), innerHTML: "", appendChild() {}, addEventListener() {} };
}

const rootEl = makeEl();
global.document = {
  createElement: () => rootEl,
  head: { appendChild(){} },
  body: { appendChild(){} },
  visibilityState: "visible",
  addEventListener(){},
};
global.window = { addEventListener(){}, innerWidth: 1920, innerHeight: 1080 };
global.performance = { now: () => Date.now() };

const { initCharacter } = await import("../reyes_agent/static/character.js");
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

console.log(failures === 0 ? "ALL 5 CASES PASSED" : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
