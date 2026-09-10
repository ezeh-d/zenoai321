# ZENO Character Support Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this bounded support pass. Steps use checkbox syntax for tracking.

**Goal:** Give Claude isolated, executable character regressions and evidence without changing his runtime.

**Architecture:** Run the committed, real ES modules with a deterministic test-only clock and minimal DOM surface. Keep healthy contracts separate from explicitly labelled known-gap probes; strict mode makes those probes fail normally. No second character runtime or renderer.

**Tech Stack:** Existing Node.js >=20, node:test, node:assert/strict; no dependencies or package-file changes.

**Spec:** User-approved ownership proposal in this task; handoff records the durable scope.

## Global Constraints

- Claude owns production runtime, brain, renderer, desktop, boot, panels and artwork.
- Codex owns only new support scripts and documentation listed below.
- visual_events.js and semantic character methods are read-only shared interfaces.
- Start at committed fb38214; do not copy Claude's uncommitted renderer work.
- Never merge into Claude's branch. Leave small commits for his review.
- No unrelated security, network, surveillance, assistant backend or tool changes.
- Simulated clocks/DOM do not prove real desktop FPS, CPU, RAM or hit testing.

## Task 1: Deterministic lifecycle harness

**Files:** Create `scripts/character_support/harness.mjs`, `scripts/character_support/harness.test.mjs`.

**Interfaces:** `createHarness()` returns `{ advance(ms), counts(), window, document, install(), restore(), roots() }`. `install/restore` temporarily replace timer/DOM globals and restore original descriptors. `counts()` reports timers by type, callbacks and event listeners. Element rectangles can be changed via `rect` without pretending to implement browser layout.

- [ ] Write tests first: timer cancellation, chronological interval/rAF execution, runaway guard, listener deduplication/removal, element identity and global restoration.

```js
const h = createHarness();
h.install();
const calls = [];
const id = setInterval(() => calls.push(performance.now()), 10);
h.advance(25);
clearInterval(id);
h.advance(25);
assert.deepEqual(calls, [10, 20]);
h.restore();
```

- [ ] Run `node --test scripts/character_support/harness.test.mjs`; observe missing helper failure.
- [ ] Implement only the test environment: ordered cancellable timers, bounded clock advancement, listener sets, owned element tree, CSS property bag, global restoration. No character behavior in helper.
- [ ] Rerun self-tests; commit helper and this plan after verification.

## Task 2: Real-module contracts and reproducible findings

**Files:** Create `scripts/verify_character_contracts_codex.mjs`, `scripts/verify_character_lifecycle_codex.mjs`.

**Consumes:** Real `visual_events.js`, `character_brain.js`, `character.js`; helper above.

- [ ] Add event tests for failure isolation, snapshot delivery, repeated unsubscribe, and 1,000 subscribe/emit/unsubscribe cycles. Example independent outcome:

```js
const seen = [];
const off = on('probe', detail => seen.push(detail.state));
emit('probe', {state:'listening'}); off(); off();
emit('probe', {state:'speaking'});
assert.deepEqual(seen, ['listening']);
assert.equal(listenerCount('probe'), 0);
```

- [ ] Add emotion tests for bounded finite valid inputs, snapshot isolation, capped elapsed-time decay, and idle threshold/probability gates; protect authoritative states in actual character integration.
- [ ] Add geometry/gesture tests: left/right panel open, bounds of gaze offset, current rectangle coordinates, hold replacement/expiry and 1,000 point operations without growing timers/listeners.
- [ ] Add desired-behavior probes for inactive work, visibility reactivation, continuous cursor gaze and repeat-init teardown. Each real defect remains an explicit TODO with reason in normal runs; `--strict` removes TODO status. No tests for invented panel-move events: record missing contract for Claude instead.

```js
test('cursor gaze updates before continuous movement ends', knownGapOptions, () => {
  const {character, h} = mountedCharacter();
  character.setEyeTracking({enabled:true});
  for (let i = 0; i < 60; i++) {
    h.window.dispatchEvent({type:'pointermove', clientX:1500, clientY:600});
    h.advance(16);
  }
  assert.ok(character.auditMetrics().gaze_offset.x > 0.5);
});
```

- [ ] Run normal and strict suites. Trace failures to source and document expected/actual/root cause/minimal change for Claude. Do not change production to obtain green.
- [ ] Record synthetic counts/timing, not invented live performance metrics; commit tests separately.

## Task 3: Research gaps and handoff

**Files:** Create `docs/agent_handoffs/CODEX_CHARACTER_HANDOFF.md`.

- [ ] Audit only gaps in existing research, with a read-only independent research agent. Verify uncertain license evidence locally without copying assets.
- [ ] Record ownership, findings, exact commands/outcomes, baseline commit, synthetic limits and ready commits. Asset pipeline is deferred because Claude is now actively adding assets/renderers.
- [ ] Run both existing character scripts, new suites, relevant existing orb/event verification, and `git diff --check`.
- [ ] Request independent read-only test review; fix only support-file defects.
- [ ] Commit final handoff; verify production diff remains empty against fb38214 and leave branch unmerged.

## Plan self-review

The three approved workstreams are covered. Asset tooling is deliberately deferred to avoid newly active Claude artwork files. Dynamic panel move/close contracts remain integration findings rather than fictional event tests. The test helper is not production lifecycle cleanup, and TODO probes are not passing product requirements.
