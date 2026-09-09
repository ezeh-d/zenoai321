// Isolated Node test harness for the Emotion Engine derivation logic.
// Stubs the DOM primitives orb.js touches at import/init time so the pure
// derivation logic can be exercised without a browser.
global.document = {
  createElement: () => ({ classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} },
    style: { setProperty(){} }, querySelector: () => makeEl(), appendChild(){}, innerHTML: '' }),
  head: { appendChild(){} },
  body: { appendChild(){} },
  visibilityState: 'visible',
  addEventListener(){},
};
function makeEl() {
  return { getContext: () => ({ clearRect(){}, beginPath(){}, arc(){}, fill(){}, set fillStyle(v){}, set globalAlpha(v){} }),
    style: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} } };
}
global.window = { addEventListener(){}, ZenoSpring: null };
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};
global.performance = { now: () => Date.now() };

const { initOrb } = await import('../reyes_agent/static/orb.js');
const orb = initOrb(null);

const cases = [
  { name: 'tool success -> a positive/confident expression', deltas: { valence: 0.72, confidence: 0.68, energy: 0.6 }, expectOneOf: ['smile', 'happy', 'proud'] },
  { name: 'tool failure -> a concerned expression', deltas: { concern: 0.6, valence: 0.35, urgency: 0.3 }, expectOneOf: ['annoyed', 'worried', 'concerned'] },
  { name: 'high urgency + high concern -> warning', deltas: { urgency: 0.85, concern: 0.7 }, expectOneOf: ['warning'] },
  { name: 'high confidence + amusement -> smug', deltas: { confidence: 0.85, amusement: 0.7 }, expectOneOf: ['smug'] },
  { name: 'high arousal + positive valence -> excited/celebrating', deltas: { arousal: 0.8, valence: 0.75 }, expectOneOf: ['excited', 'celebrating'] },
  { name: 'low energy + low arousal -> sleepy', deltas: { energy: 0.1, arousal: 0.15 }, expectOneOf: ['sleepy'] },
  { name: 'high curiosity, low focus -> curious', deltas: { curiosity: 0.8, focus: 0.2 }, expectOneOf: ['curious'] },
  { name: 'high focus, low arousal -> deep_thinking', deltas: { focus: 0.8, arousal: 0.25 }, expectOneOf: ['deep_thinking'] },
];

let failures = 0;
for (const c of cases) {
  // Reset to neutral baseline first so a previous case's dimensions don't
  // leak into this one (immediate:true skips momentum smoothing).
  orb.setEmotion({ valence: 0.55, arousal: 0.35, confidence: 0.6, curiosity: 0.4, focus: 0.4,
    urgency: 0.1, amusement: 0.2, concern: 0.1, energy: 0.6, social_engagement: 0.5 }, { immediate: true });
  orb.setEmotion(c.deltas, { immediate: true });
  const derived = orb.getState();
  const ok = c.expectOneOf.includes(derived);
  console.log(`${ok ? 'PASS' : 'FAIL'} ${c.name} -> got "${derived}", expected one of [${c.expectOneOf.join(', ')}]`);
  if (!ok) failures++;
}

// Protected-state gate: while "listening" (a real, event-driven state), an
// emotion nudge must NOT silently override it -- voice correctness outranks
// a mood swing.
orb.setState('listening');
orb.setEmotion({ valence: 0.9, energy: 0.9, confidence: 0.9 }, { immediate: true });
const guardOk = orb.getState() === 'listening';
console.log(`${guardOk ? 'PASS' : 'FAIL'} protected state (listening) is not overridden by an emotion nudge`);
if (!guardOk) failures++;

// Once no longer in a protected state, emotion nudges apply normally again.
orb.setState('idle');
orb.setEmotion({ valence: 0.9, energy: 0.9, confidence: 0.9 }, { immediate: true });
const resumesOk = orb.getState() !== 'idle';
console.log(`${resumesOk ? 'PASS' : 'FAIL'} emotion nudges resume once state is no longer protected (got "${orb.getState()}")`);
if (!resumesOk) failures++;

console.log(failures === 0 ? `ALL ${cases.length + 2} CASES PASSED` : `${failures} CASE(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
