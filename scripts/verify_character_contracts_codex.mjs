// Run: node --test scripts/verify_character_contracts_codex.mjs
// Real DOM-free modules; no provider, network, renderer or model is mocked.
import test from 'node:test';
import assert from 'node:assert/strict';
import { on, emit, clear, listenerCount } from '../reyes_agent/static/visual_events.js';
import { createEmotionEngine, deriveExpression, shouldIdleNudge } from '../reyes_agent/static/character_brain.js';

test('event bus isolates a failing renderer and still delivers to siblings', t => {
  t.after(() => clear());
  t.mock.method(console, 'warn', () => {});
  const seen = [];
  on('probe', () => { throw new Error('renderer failed'); });
  on('probe', value => seen.push(value.state));
  assert.equal(emit('probe', {state:'listening'}), 1);
  assert.deepEqual(seen, ['listening']);
});

test('duplicate subscription and repeated unsubscribe do not multiply delivery', t => {
  t.after(() => clear());
  const seen = [], handler = value => seen.push(value);
  const off = on('probe', handler);
  on('probe', handler);
  emit('probe', 1);
  off(); off();
  emit('probe', 2);
  assert.deepEqual(seen, [1]);
  assert.equal(listenerCount('probe'), 0);
});

test('subscription changes during delivery affect the next emission, not the snapshot', t => {
  t.after(() => clear());
  const seen = [];
  let removeSecond;
  on('probe', () => { seen.push('first'); removeSecond(); on('probe', third); });
  const third = () => seen.push('third');
  removeSecond = on('probe', () => seen.push('second'));
  emit('probe'); emit('probe');
  assert.deepEqual(seen, ['first', 'second', 'first', 'third']);
});

test('clearing one event leaves unrelated renderer channels usable', t => {
  t.after(() => clear());
  const seen = [];
  on('first', () => seen.push('first'));
  on('second', () => seen.push('second'));
  clear('first'); emit('first'); emit('second');
  assert.deepEqual(seen, ['second']);
});

test('1,000 mount/event/unmount subscriptions return to baseline', t => {
  t.after(() => clear());
  let delivered = 0;
  for (let i = 0; i < 1000; i++) {
    const off = on('probe', () => delivered++);
    emit('probe'); off(); off();
    assert.equal(listenerCount('probe'), 0);
  }
  assert.equal(delivered, 1000);
});

test('invalid subscriptions are inert rather than breaking valid listeners', t => {
  t.after(() => clear());
  const off = on('probe', null);
  off();
  assert.equal(emit('probe'), 0);
  assert.equal(listenerCount('probe'), 0);
});

test('emotion inputs clamp valid numeric extremes while nudges retain momentum', () => {
  const engine = createEmotionEngine(() => {});
  engine.apply({valence:2, energy:-1}, {immediate:true});
  assert.equal(engine.snapshot().valence, 1);
  assert.equal(engine.snapshot().energy, 0);
  engine.apply({energy:1});
  assert.equal(engine.snapshot().energy, 0.6);
});

test('caller snapshots and derived callbacks cannot mutate the engine state', () => {
  const engine = createEmotionEngine((_, snapshot) => { snapshot.energy = -50; });
  engine.apply({energy:0.9}, {immediate:true});
  const snapshot = engine.snapshot();
  snapshot.energy = 99;
  assert.equal(engine.snapshot().energy, 0.9);
});

test('long background gap decays by capped elapsed time, not the whole gap', () => {
  const engine = createEmotionEngine(() => {});
  engine.apply({energy:1}, {immediate:true});
  engine.tickDecay(1000);
  assert.equal(engine.snapshot().energy, 1);
  engine.tickDecay(61000);
  // Hand calculation: 1 + (0.6 - 1) * (0.02 * 2 * 4) = 0.936.
  assert.ok(Math.abs(engine.snapshot().energy - 0.936) < 1e-12);
});

test('repeated forward-time decay stays finite and converges toward baseline', () => {
  const engine = createEmotionEngine(() => {});
  engine.apply({energy:1, concern:1, valence:0}, {immediate:true});
  for (let i = 0; i <= 1000; i++) engine.tickDecay(i * 2500);
  const state = engine.snapshot();
  for (const value of Object.values(state)) assert.ok(Number.isFinite(value) && value >= 0 && value <= 1);
  assert.ok(Math.abs(state.energy - 0.6) < 1e-9);
  assert.ok(Math.abs(state.concern - 0.1) < 1e-9);
  assert.ok(Math.abs(state.valence - 0.55) < 1e-9);
});

test('urgent concern outranks positive moods when selecting an expression', () => {
  assert.equal(deriveExpression({urgency:0.9, concern:0.8, valence:0.9,
    confidence:0.9, amusement:0.9, arousal:0.9, energy:0.9, social_engagement:0.9}), 'warning');
});

test('idle nudge requires both elapsed inactivity and a qualifying random sample', () => {
  for (const [elapsed, roll, expected] of [[24999,0,false], [25000,0.119,true], [25000,0.12,false], [60000,0.8,false]]) {
    assert.equal(shouldIdleNudge(elapsed, roll), expected);
  }
});
