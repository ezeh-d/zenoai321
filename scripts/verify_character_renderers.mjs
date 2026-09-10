// Isolated Node tests for the Stage A sprite-renderer scaffolding:
// character_manifest.js (detects whether real ZENO art has been supplied)
// and character_renderers.js (the actual sprite-swapping renderer), plus
// a real integration check that character.js activates the sprite
// renderer the moment a manifest resolves -- and stays on the CSS/DOM
// placeholder body when it doesn't (today's real state, since no art has
// been supplied yet).
import { resolveSpriteCategory, createSpriteStateRenderer } from "../reyes_agent/static/character_renderers.js";
import { loadCharacterManifest } from "../reyes_agent/static/character_manifest.js";

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " -> " + detail : ""}`);
  if (!ok) failures++;
}

// --- character_manifest.js ------------------------------------------------

// 1) A 404 (the real state today, since no manifest file exists yet) -> null.
const notFoundFetch = async () => ({ ok: false, status: 404 });
check("loadCharacterManifest() returns null on 404 (today's real state)",
  await loadCharacterManifest(notFoundFetch) === null);

// 3) A network error -> null, not a throw (missing assets must not crash ZENO).
const throwingFetch = async () => { throw new Error("network down"); };
check("loadCharacterManifest() returns null on a fetch error, does not throw",
  await loadCharacterManifest(throwingFetch) === null);

// 4) Malformed JSON body (no "sprites" object) -> null, treated as absent.
const malformedFetch = async () => ({ ok: true, json: async () => ({ version: 1 }) });
check("loadCharacterManifest() rejects a manifest with no sprites object",
  await loadCharacterManifest(malformedFetch) === null);

// 5) A real, valid manifest -> returned as-is.
const realManifest = { version: 1, sprites: { neutral: "/x/neutral.png", happy: "/x/happy.png" } };
const validFetch = async () => ({ ok: true, json: async () => realManifest });
const loaded = await loadCharacterManifest(validFetch);
check("loadCharacterManifest() returns a valid manifest unchanged",
  loaded && loaded.sprites && loaded.sprites.neutral === "/x/neutral.png", JSON.stringify(loaded));

// --- character_renderers.js: resolveSpriteCategory -------------------------

check("resolveSpriteCategory maps 'happy' -> 'happy'", resolveSpriteCategory("happy") === "happy");
check("resolveSpriteCategory maps 'deep_thinking' -> 'thinking'", resolveSpriteCategory("deep_thinking") === "thinking");
check("resolveSpriteCategory maps 'shocked' -> 'surprised'", resolveSpriteCategory("shocked") === "surprised");
check("resolveSpriteCategory maps an unknown state -> 'neutral' (graceful fallback)",
  resolveSpriteCategory("some_future_state_not_in_the_table") === "neutral");

// --- character_renderers.js: createSpriteStateRenderer ---------------------

function makeRootStub() {
  const children = [];
  return {
    appendChild: (el) => children.push(el),
    _children: children,
  };
}
function makeImgStub() {
  return { className: "", alt: "", draggable: true, src: "", remove() {} };
}
global.document = { createElement: () => makeImgStub() };

const manifest = {
  sprites: {
    neutral: "/sprites/neutral.png",
    happy: "/sprites/happy.png",
    _pointing: "/sprites/pointing.png",
  },
};
const rootStub = makeRootStub();
const renderer = createSpriteStateRenderer(rootStub, manifest);
renderer.mount();
check("mount() appends exactly one <img> to root", rootStub._children.length === 1);

renderer.setExpression("happy");
check("setExpression('happy') sets the mapped sprite URL", renderer._debugImg().src === "/sprites/happy.png");

renderer.setExpression("idle"); // -> category 'neutral'
check("setExpression('idle') resolves through resolveSpriteCategory to 'neutral'",
  renderer._debugImg().src === "/sprites/neutral.png");

renderer.setExpression("some_future_state_not_in_the_table");
check("setExpression() on an unmapped state falls back to neutral, never a broken src",
  renderer._debugImg().src === "/sprites/neutral.png");

renderer.setExpression("happy");
renderer.setPointing("r", 5000); // long hold so the release timer hasn't fired yet
check("setPointing() swaps to the manifest's pointing sprite when one exists",
  renderer._debugImg().src === "/sprites/pointing.png", renderer._debugImg().src);

// A manifest with NO "_pointing" entry must be a safe no-op, never a
// broken/blank src (Phase 55/56: missing assets must not crash ZENO).
const noPointManifest = { sprites: { neutral: "/sprites/neutral.png" } };
const renderer2 = createSpriteStateRenderer(makeRootStub(), noPointManifest);
renderer2.mount();
renderer2.setExpression("neutral");
const before2 = renderer2._debugImg().src;
renderer2.setPointing("l", 0);
check("setPointing() with no '_pointing' sprite in the manifest is a safe no-op",
  renderer2._debugImg().src === before2, renderer2._debugImg().src);

console.log(failures === 0 ? "ALL CASES PASSED" : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
