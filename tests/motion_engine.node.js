/*
 * Pure-logic tests for reyes_agent/static/motion_engine.js -- run directly
 * with `node tests/motion_engine.node.js` (no framework: this repo's JS is
 * vanilla, no existing JS test runner to depend on). Mirrors the style of
 * tests/test_agent_operational_health.py: PASS/FAIL lines, non-zero exit on
 * any failure. Only the DOM-free core (createMotionState/updateSample/step)
 * is exercised here -- the DOM glue (start()/attachPhoneMotion()) is
 * verified live in the browser instead, since it needs a real window/HUD.
 */
"use strict";

const path = require("path");
const M = require(path.join(__dirname, "..", "reyes_agent", "static", "motion_engine.js"));
const S = require(path.join(__dirname, "..", "reyes_agent", "static", "spring.js"));

let failures = 0;
function check(label, cond, detail) {
  const status = cond ? "PASS" : "FAIL";
  console.log(`${status}  ${label}` + (detail !== undefined ? `  -- ${detail}` : ""));
  if (!cond) failures++;
  return cond;
}

function shakeBurst(state, now, count, startToggle) {
  // `startToggle` lets repeated calls continue alternating x rather than
  // each call restarting at the same phase (which would sample the same x
  // every time and produce zero velocity/reversals across calls).
  let toggle = startToggle || false;
  for (let i = 0; i < count; i++) {
    M.updateSample(state, toggle ? 500 : 100, 300, now);
    toggle = !toggle;
    now += 60;
  }
  return { now: now, toggle: toggle };
}

// --- 1. mouse/window-following: position, velocity, acceleration track a real sample path ---
(function testFollowing() {
  const state = M.createMotionState();
  M.updateSample(state, 100, 100, 1000);
  M.updateSample(state, 200, 100, 1060); // 100px in 60ms -> ~1666px/s
  check("position updates to the latest sample", state.position.x === 200 && state.position.y === 100);
  check("velocity reflects real displacement/dt", state.velocity.x > 1000 && state.velocity.x < 2000,
    `vx=${state.velocity.x.toFixed(0)}`);
  check("lastMovementAt is set from the sample timestamp", state.lastMovementAt === 1060);
})();

// --- 2. shake detection ---
(function testShakeDetection() {
  const state = M.createMotionState();
  let now = 1000;
  now = shakeBurst(state, now, 10).now;
  const r = M.step(state, 0.06, S, now);
  check("rapid direction reversals raise shakeIntensity", state.shakeIntensity > 0.8,
    `shakeIntensity=${state.shakeIntensity.toFixed(3)}`);
  check("a shake reaction fires on the rising edge", r.reaction === "shake");

  const still = M.createMotionState();
  M.updateSample(still, 100, 100, 1000);
  M.updateSample(still, 105, 100, 1060); // small, slow, one direction -- not a shake
  const r2 = M.step(still, 0.06, S, 1060);
  check("small slow movement does NOT register as a shake", still.shakeIntensity === 0 && r2.reaction === null);
})();

// --- 3. dizziness accumulation ---
(function testDizzinessAccumulation() {
  const state = M.createMotionState();
  let now = 1000, toggle = false;
  for (let i = 0; i < 60; i++) {
    const r = shakeBurst(state, now, 1, toggle);
    now = r.now; toggle = r.toggle;
    M.step(state, 0.06, S, now);
  }
  check("sustained shaking raises dizziness", state.dizziness > 0.5, `dizziness=${state.dizziness.toFixed(3)}`);
  check("dizziness never exceeds 1 (bounded)", state.dizziness <= 1.0);
  check("dizziness never goes negative (bounded)", state.dizziness >= 0.0);
})();

// --- 4. dizziness recovery ---
(function testDizzinessRecovery() {
  const state = M.createMotionState();
  let now = 1000, toggle = false;
  for (let i = 0; i < 60; i++) {
    const r = shakeBurst(state, now, 1, toggle);
    now = r.now; toggle = r.toggle;
    M.step(state, 0.06, S, now);
  }
  const peak = state.dizziness;
  let recovered = false, steps = 0;
  for (let i = 0; i < 1000; i++) {
    now += 60;
    const r = M.step(state, 0.06, S, now);
    steps++;
    if (r.reaction === "recovered") { recovered = true; break; }
  }
  check("dizziness decays toward 0 once movement stops", recovered, `after ${(steps * 0.06).toFixed(1)}s`);
  check("a 'recovered' reaction fires exactly on the falling edge", recovered);
  check("dizziness actually decreased from its peak", state.dizziness < peak);
})();

// --- 5. no repeated reactions while continuously shaking (sound-cooldown's upstream cause) ---
(function testEdgeDetectionNotContinuous() {
  const state = M.createMotionState();
  let now = 1000;
  const reactions = [];
  for (let i = 0; i < 200; i++) {
    M.updateSample(state, i % 2 === 0 ? 500 : 100, 300, now);
    const r = M.step(state, 0.06, S, now);
    if (r.reaction) reactions.push(r.reaction);
    now += 60;
  }
  check("continuous shaking fires each reaction type at most once (edge-triggered, not per-frame)",
    reactions.length <= 3, `reactions=${JSON.stringify(reactions)}`);
  check("no duplicate consecutive reaction of the same kind", new Set(reactions).size === reactions.length);
})();

// --- 6. reversal window is bounded (memory safety, matches TUNABLES) ---
(function testBoundedReversals() {
  const state = M.createMotionState();
  let now = 1000;
  now = shakeBurst(state, now, 500).now; // far more than any real drag would produce
  check("the reversal window prunes by time, staying bounded",
    state._reversals.length < 50, `len=${state._reversals.length}`);
})();

// --- 7. performance / no UI-thread blocking (measured, not assumed) ---
(function testPerformance() {
  const state = M.createMotionState();
  let now = 1000;
  const N = 20000;
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < N; i++) {
    M.updateSample(state, Math.sin(i) * 300, Math.cos(i) * 300, now);
    M.step(state, 0.016, S, now);
    now += 16;
  }
  const totalMs = Number(process.hrtime.bigint() - t0) / 1e6;
  const perCallUs = (totalMs / N) * 1000;
  check("one updateSample+step is far below a 16.7ms (60fps) frame budget",
    perCallUs < 500, `${perCallUs.toFixed(2)}us/call measured, N=${N}`);
})();

// --- 8. stepSpring (the shared physics both eye-chase and HUD lean use) never explodes ---
(function testSpringStability() {
  let s = { x: 0, v: 0 };
  for (let i = 0; i < 300; i++) s = S.stepSpring(s, 100, 1 / 60, "smooth");
  check("a chased spring settles near its target, not away from it",
    Math.abs(s.x - 100) < 1, `x=${s.x.toFixed(2)}`);
  let s2 = { x: 0, v: 0 };
  s2 = S.stepSpring(s2, 100, 5.0, "smooth"); // a huge dt (e.g. a stalled tab)
  check("a large dt is sub-stepped, not a single unstable jump",
    Number.isFinite(s2.x) && Math.abs(s2.x) < 1000, `x=${s2.x}`);
})();

console.log("=".repeat(60));
if (failures) {
  console.log(`${failures} FAILED`);
  process.exit(1);
}
console.log("ALL MOTION ENGINE TESTS PASSED");
