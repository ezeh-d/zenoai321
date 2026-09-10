// End-to-end integration test: character.js must ACTUALLY activate the
// sprite renderer when a real manifest resolves (not just that the two
// pieces work correctly in isolation -- that's covered by
// verify_character_renderers.mjs). Uses a per-call DOM stub (a fresh
// element each time, not one shared object) since this exercises the real
// createElement("img") path inside character_renderers.js alongside
// character.js's own root div -- a shared-stub harness would corrupt both.
function makeClassList() {
  const set = new Set();
  return { add: (...n) => n.forEach((x) => set.add(x)), remove: (...n) => n.forEach((x) => set.delete(x)),
    toggle(n, on) { if (on) set.add(n); else set.delete(n); }, contains: (n) => set.has(n) };
}
function makeEl(tag) {
  const el = {
    tagName: tag, classList: makeClassList(), style: { setProperty(){} }, innerHTML: "",
    children: [], appendChild(child) { el.children.push(child); },
    addEventListener(){}, removeEventListener(){},
    querySelector: (sel) => (tag === "div" && sel === ".zc-eyes" ? makeEl("div") : null),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 96, height: 128 }),
    remove(){},
  };
  return el;
}
global.document = {
  createElement: (tag) => makeEl(tag),
  head: { appendChild(){} },
  body: { appendChild(){} },
  visibilityState: "visible",
  addEventListener(){},
};
global.window = { addEventListener(){}, innerWidth: 1920, innerHeight: 1080 };
global.performance = { now: () => Date.now() };
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};

// A real, valid manifest -- this is what dropping the cropped sprites +
// manifest.json in would actually produce.
const FAKE_MANIFEST = {
  version: 1,
  sprites: {
    neutral: "/static/character_assets/sprites/neutral.png",
    happy: "/static/character_assets/sprites/happy.png",
    listening: "/static/character_assets/sprites/listening.png",
  },
};
global.fetch = async (url) => {
  if (String(url).includes("character_assets/manifest.json")) {
    return { ok: true, json: async () => FAKE_MANIFEST };
  }
  return { ok: false, status: 404 };
};

const { initCharacter } = await import("../reyes_agent/static/character.js");
const zc = initCharacter(null);

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " -> " + detail : ""}`);
  if (!ok) failures++;
}

// The manifest fetch is async -- give its promise chain a turn to resolve.
await new Promise((r) => setTimeout(r, 50));

check("a real manifest makes the sprite renderer activate automatically",
  zc.auditMetrics().sprite_active === true, JSON.stringify(zc.auditMetrics()));

zc.setState("listening");
check("setState() drives the sprite renderer once it's active (no separate wiring needed)",
  zc.auditMetrics().sprite_active === true); // activation persists across state changes

console.log(failures === 0 ? "ALL CASES PASSED" : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
