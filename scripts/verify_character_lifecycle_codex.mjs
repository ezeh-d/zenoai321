// Healthy tests plus executable, explicitly unresolved Claude-owned findings.
// Normal: node scripts/verify_character_lifecycle_codex.mjs
// Strict: node scripts/verify_character_lifecycle_codex.mjs --strict
// TODO tests EXECUTE; strict removes TODO status and returns nonzero on defects.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHarness } from './character_support/harness.mjs';
import { initCharacter } from '../reyes_agent/static/character.js';
import { on, clear } from '../reyes_agent/static/visual_events.js';

// Let character.js finish its optional dynamic visual-bus import using the real
// event loop, before temporarily replacing timer globals inside each test.
await new Promise(resolve => setImmediate(resolve));
const strict = process.argv.includes('--strict');
const gap = reason => strict ? {} : { todo: `CLAUDE-OWNED baseline gap: ${reason}` };

function mounted(t) {
  const h = createHarness();
  h.install();
  t.mock.method(Math, 'random', () => 0.5);
  t.after(() => { clear(); h.restore(); });
  const character = initCharacter(null);
  return { h, character, root: h.roots()[0] };
}

test('real pipeline states emit semantic events without losing authoritative state to mood', t => {
  const {character} = mounted(t);
  const seen = [];
  on('zeno:state', detail => seen.push(detail.state));
  for (const state of ['listening','understanding','thinking','acting','waiting','processing','speaking','error','notice','calling_agent','interrupted','boot']) {
    character.setState(state);
    character.setEmotion({valence:1, energy:1, amusement:1}, {immediate:true});
    assert.equal(character.getState(), state);
  }
  assert.deepEqual(seen, ['listening','understanding','thinking','acting','waiting','processing','speaking','error','notice','calling_agent','interrupted','boot']);
});

test('panel-open event points and gazes toward either side using current measured geometry', t => {
  const {h, character, root} = mounted(t);
  root.rect = {left:352, top:236, width:96, height:128}; // center = 400,300
  for (const [x, side, sign] of [[900,'r',1], [-100,'l',-1]]) {
    h.window.dispatchEvent({type:'zeno:panel-opened', detail:{type:'browser', center:{x,y:300}}});
    h.advance(500);
    assert.equal(character.auditMetrics().pointing, side);
    assert.ok(character.auditMetrics().gaze_offset.x * sign > 0.5);
    assert.ok(Math.abs(character.auditMetrics().gaze_offset.y) < 0.01);
  }
});

test('explicit gaze respects bounds, then returns to neutral after hold', t => {
  const {h, character} = mounted(t);
  character.lookAt(1000000, -1000000, {holdMs:1000});
  h.advance(500);
  const offset = character.auditMetrics().gaze_offset;
  assert.ok(offset.x > 0.5 && offset.x <= 4.5);
  assert.ok(offset.y < -0.5 && offset.y >= -3.2);
  h.advance(1000);
  assert.deepEqual(character.auditMetrics().gaze_offset, {x:0,y:0});
});

test('replacing a point cancels its previous expiration callback', t => {
  const {h, character} = mounted(t);
  character.pointAt(1800, 500, {holdMs:1000});
  h.advance(500);
  character.pointAt(0, 500, {holdMs:1000});
  h.advance(501);
  assert.equal(character.auditMetrics().pointing, 'l');
  h.advance(499);
  assert.equal(character.auditMetrics().pointing, null);
});

test('fresh spatial commands recalculate direction after character rectangle changes', t => {
  const {character, root} = mounted(t);
  root.rect = {left:100,top:100,width:96,height:128};
  character.pointAt(500,200);
  assert.equal(character.auditMetrics().pointing, 'r');
  root.rect.left = 800;
  character.pointAt(500,200);
  assert.equal(character.auditMetrics().pointing, 'l');
});

test('disabled cursor gaze remains neutral and stationary dead-zone input causes no drift', t => {
  const {h, character} = mounted(t);
  h.window.dispatchEvent({type:'pointermove', clientX:1800, clientY:900});
  h.advance(500);
  assert.deepEqual(character.auditMetrics().gaze_offset, {x:0,y:0});
  character.setEyeTracking({enabled:true});
  h.window.dispatchEvent({type:'pointermove', clientX:960, clientY:540});
  h.advance(500);
  assert.deepEqual(character.auditMetrics().gaze_offset, {x:0,y:0});
});

test('1,000 point replacements keep timer/listener counts bounded and expire', t => {
  const {h, character} = mounted(t);
  const before = h.counts();
  for (let i = 0; i < 1000; i++) character.pointAt(i % 2 ? 1800 : 0, 500);
  const during = h.counts();
  assert.equal(during.timers, before.timers + 1);
  assert.equal(during.listeners, before.listeners);
  h.advance(1600);
  assert.equal(character.auditMetrics().pointing, null);
  assert.equal(h.counts().timers, before.timers);
  t.diagnostic(JSON.stringify({operations:1000,before,during,after:h.counts()}));
});

test('cursor gaze updates before continuous pointer movement ends', gap('trailing debounce starves continuous gaze'), t => {
  const {h, character} = mounted(t);
  character.setEyeTracking({enabled:true});
  for (let i = 0; i < 60; i++) {
    h.window.dispatchEvent({type:'pointermove', clientX:1500+i, clientY:600});
    h.advance(16);
  }
  const during = character.auditMetrics().gaze_offset.x;
  h.advance(500);
  t.diagnostic(JSON.stringify({events:60,during,afterPause:character.auditMetrics().gaze_offset.x}));
  assert.ok(during > 0.5, `gaze stayed at ${during} during 960ms of movement`);
});

test('inactive character pauses emotion updates while its document stays visible', gap('setActive(false) does not gate emotion timer'), t => {
  const {h, character} = mounted(t);
  character.setEmotion({energy:1}, {immediate:true});
  character.setActive(false);
  const before = character.getEmotionState();
  h.advance(5000);
  t.diagnostic(JSON.stringify({beforeEnergy:before.energy,afterEnergy:character.getEmotionState().energy,counts:h.counts()}));
  assert.deepEqual(character.getEmotionState(), before);
});

test('document visibility cannot restart blink while character is inactive', gap('visibility handler ignores active state'), t => {
  const {h, character} = mounted(t);
  character.setActive(false);
  h.advance(500); // let neutral gaze settle
  h.document.visibilityState = 'hidden';
  h.document.dispatchEvent({type:'visibilitychange'});
  const before = h.counts().timeout;
  h.document.visibilityState = 'visible';
  h.document.dispatchEvent({type:'visibilitychange'});
  assert.equal(h.counts().timeout, before, 'visibility scheduled hidden character blink');
});

test('inactive character ignores cursor work after gaze has settled', gap('pointer handler ignores active state'), t => {
  const {h, character} = mounted(t);
  character.setEyeTracking({enabled:true});
  character.setActive(false);
  h.advance(500);
  h.window.dispatchEvent({type:'pointermove',clientX:1800,clientY:900});
  h.advance(500);
  assert.deepEqual(character.auditMetrics().gaze_offset, {x:0,y:0});
});

test('runtime teardown releases owned timers, listeners and DOM across replacements', gap('no disposal API on committed runtime'), t => {
  const {h, character, root} = mounted(t);
  // Capability gap first: do not disguise removing a DOM node as real disposal.
  const dispose = character.dispose || character.destroy;
  if (typeof dispose !== 'function') {
    root.remove();
    for (let i = 0; i < 24; i++) { initCharacter(null); h.roots().at(-1).remove(); }
    t.diagnostic(JSON.stringify({simulatedReplacements:25,removedDOMRoots:h.roots().length,retained:h.counts()}));
    assert.fail('No runtime disposal method; removing DOM leaves timers/listeners registered');
  }
  dispose.call(character);
  assert.equal(h.counts().timers, 0);
  assert.equal(h.counts().listeners, 0);
  assert.equal(h.roots().length, 0);
  for (let i = 0; i < 25; i++) {
    const next = initCharacter(null);
    (next.dispose || next.destroy).call(next);
  }
  assert.equal(h.counts().timers, 0);
  assert.equal(h.counts().listeners, 0);
  assert.equal(h.roots().length, 0);
});
