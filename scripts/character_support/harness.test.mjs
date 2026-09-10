import assert from 'node:assert/strict';
import test from 'node:test';
import { createHarness } from './harness.mjs';

test('clock runs intervals and frames chronologically and honors cancellation', () => {
  const h = createHarness();
  h.install();
  try {
    const seen = [];
    const interval = setInterval(() => seen.push(performance.now()), 10);
    const cancelled = setTimeout(() => seen.push('cancelled'), 5);
    clearTimeout(cancelled);
    requestAnimationFrame(t => seen.push(`frame:${t}`));
    h.advance(25);
    clearInterval(interval);
    h.advance(25);
    assert.deepEqual(seen, [10, 'frame:16', 20]);
    assert.equal(h.counts().timers, 0);
  } finally { h.restore(); }
});

test('clock catches runaway callbacks without hanging a verification process', () => {
  const h = createHarness({ maxCallbacks: 10 });
  h.install();
  try {
    const loop = () => setTimeout(loop, 0);
    loop();
    assert.throws(() => h.advance(1), /callback limit/);
    assert.throws(() => h.advance(-1), /non-negative/);
  } finally { h.restore(); }
});

test('listener accounting deduplicates and releases handlers', () => {
  const h = createHarness();
  let calls = 0;
  const handler = () => calls++;
  h.window.addEventListener('resize', handler);
  h.window.addEventListener('resize', handler);
  assert.equal(h.counts().listeners, 1);
  h.window.dispatchEvent({ type: 'resize' });
  h.window.removeEventListener('resize', handler);
  h.window.dispatchEvent({ type: 'resize' });
  assert.equal(calls, 1);
  assert.equal(h.counts().listeners, 0);
});

test('DOM keeps distinct roots and mutable measured rectangles', () => {
  const h = createHarness();
  const first = h.document.createElement('div');
  const second = h.document.createElement('div');
  first.id = second.id = 'zeno-character';
  h.document.body.appendChild(first);
  h.document.body.appendChild(second);
  first.rect = {left:100, top:200, width:96, height:128};
  assert.equal(h.roots().length, 2);
  assert.equal(first.getBoundingClientRect().left, 100);
  first.remove();
  assert.deepEqual(h.roots(), [second]);
});

test('restores original globals even with outstanding fake timers', () => {
  const keys = ['window', 'document', 'performance', 'setTimeout', 'clearTimeout',
    'setInterval', 'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame'];
  const originals = new Map(keys.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const h = createHarness();
  h.install();
  setTimeout(() => assert.fail('fake timer escaped'), 100);
  setInterval(() => assert.fail('fake interval escaped'), 100);
  requestAnimationFrame(() => assert.fail('fake frame escaped'));
  h.restore();
  for (const [key, descriptor] of originals) {
    assert.deepEqual(Object.getOwnPropertyDescriptor(globalThis, key), descriptor, `${key} descriptor changed`);
  }
  h.restore();
});
