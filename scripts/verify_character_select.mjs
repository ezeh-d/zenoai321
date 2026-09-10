// Isolated Node test for character_select.js -- the boot-time choice
// between the 2D character (default, ZENO's primary identity) and the orb
// (demoted to an opt-in compact/fallback mode). Stubs localStorage and the
// same DOM primitives the two renderer modules touch at init time.
function makeClassList() {
  const set = new Set();
  return { add(){}, remove(){}, toggle(){}, contains: () => false };
}
function makeEl() {
  return {
    classList: makeClassList(), style: { setProperty(){} }, innerHTML: "",
    appendChild(){}, addEventListener(){},
    querySelector: () => makeEl(),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 96, height: 128 }),
    getContext: () => ({ clearRect(){}, beginPath(){}, arc(){}, fill(){}, set fillStyle(v){}, set globalAlpha(v){} }),
  };
}
global.document = {
  createElement: () => makeEl(),
  head: { appendChild(){} },
  body: { appendChild(){} },
  visibilityState: "visible",
  addEventListener(){},
};
global.window = { addEventListener(){}, innerWidth: 1920, innerHeight: 1080, ZenoSpring: null };
global.performance = { now: () => Date.now() };
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const { getAvatarMode, setAvatarMode, initZenoAvatar } = await import("../reyes_agent/static/character_select.js");

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " -> " + detail : ""}`);
  if (!ok) failures++;
}

// 1) Default is the 2D character -- the user's explicit standing
// requirement ("by default, ZENO should launch and operate as the 2D
// character"), not the orb.
check("default avatar mode is 'character'", getAvatarMode() === "character");

// 2) initZenoAvatar() in default mode returns a character.js instance --
// verified via walkTo, which only exists on character.js's API, not orb.js's.
const defaultAvatar = initZenoAvatar(null);
check("initZenoAvatar() mounts the 2D character by default", typeof defaultAvatar.walkTo === "function");

// 3) Switching to compact/orb mode is real and persists.
setAvatarMode("orb");
check("setAvatarMode('orb') persists", getAvatarMode() === "orb");
const orbAvatar = initZenoAvatar(null);
check("initZenoAvatar() mounts the orb once compact mode is selected", typeof orbAvatar.walkTo === "undefined");

// 4) Both renderers still share the same core API regardless of mode --
// this is what makes the swap safe (every existing caller keeps working).
const sharedMethods = ["setState", "pulse", "setPerformanceMode", "setActive", "setDocked",
  "dispatchAgent", "setAgentWorking", "setEmotion", "getEmotionState", "getState"];
const bothHaveShared = sharedMethods.every((m) => typeof defaultAvatar[m] === "function" && typeof orbAvatar[m] === "function");
check("both renderers expose the same core API", bothHaveShared);

// 5) Switching back works too.
setAvatarMode("character");
check("setAvatarMode('character') switches back", getAvatarMode() === "character");

console.log(failures === 0 ? "ALL 5 CASES PASSED" : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
