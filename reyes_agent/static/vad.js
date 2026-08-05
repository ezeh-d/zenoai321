// ZENO voice front-end: real noise suppression / echo cancellation, and a
// real energy-based Voice Activity Detector.
//
// WHAT IS ACTUALLY REAL HERE, AND WHAT IS NOT
// -------------------------------------------
// REAL:
//   * Noise suppression, echo cancellation and auto gain are applied by the
//     browser's own audio pipeline (the same WebRTC processing chain used
//     for calls) by requesting them as getUserMedia constraints. We then
//     read `track.getSettings()` back and report what the browser ACTUALLY
//     enabled -- asking for a constraint is not the same as getting it, and
//     `capabilities()` shows the applied values, not the requested ones.
//   * The VAD is a genuine adaptive-threshold energy detector: RMS from an
//     AnalyserNode, a rolling noise-floor estimate that tracks the room,
//     hysteresis (separate open/close thresholds) and a hangover timer so
//     normal pauses between words don't count as end-of-speech.
//
// LIMITS, SAID PLAINLY:
//   * This stream is the one ZENO records and sends to its server-side STT
//     provider. There is no second, hidden Web Speech microphone capture,
//     so these settings and this VAD govern the real command path.
//   * It is energy-based, not a neural VAD. It will not reliably separate
//     speech from a TV playing speech. Silero-style ONNX VAD is the upgrade
//     path and plugs into the same interface.
//
// PERFORMANCE
//   Polls at 20Hz with a 256-bin analyser and no allocation in the loop.
//   Stops entirely when the page is hidden. This machine has 2 cores and a
//   history of GUI lag, so nothing here runs per-frame.

const POLL_MS = 50;              // 20Hz -- plenty for speech onset/offset
const FFT_SIZE = 256;
const NOISE_ADAPT_UP = 0.0005;   // noise floor rises slowly (room got louder)
const NOISE_ADAPT_DOWN = 0.02;   // and falls quickly (a burst ended)
const OPEN_FACTOR = 2.2;         // speech starts: RMS above floor * this
const CLOSE_FACTOR = 1.4;        // speech ends: hysteresis, lower bar
const MIN_FLOOR = 0.0035;        // never trust a floor below sensor noise
const HANGOVER_MS = 700;         // pauses shorter than this stay "speaking"

let ctx = null;
let stream = null;
let analyser = null;
let buffer = null;
let timer = null;

let noiseFloor = 0.01;
let speaking = false;
let lastVoiceAt = 0;
let currentRms = 0;
let appliedSettings = null;
let startError = "";
let visibilityListenerAttached = false;

const listeners = { start: [], end: [] };

function emit(kind) {
  for (const fn of listeners[kind]) {
    try { fn(); } catch (e) { /* a listener must not break detection */ }
  }
}

/** Open the microphone with the browser's own noise/echo/AGC processing. */
export async function start() {
  if (stream) return capabilities();
  startError = "";
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // These are the real WebRTC audio-processing switches.
        noiseSuppression: true,
        echoCancellation: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
  } catch (err) {
    startError = (err && err.name) ? err.name : String(err);
    return capabilities();
  }

  const track = stream.getAudioTracks()[0];
  // Report what the browser ACTUALLY applied, not what we asked for.
  appliedSettings = track && track.getSettings ? track.getSettings() : null;

  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  ctx = new AudioCtx();
  const source = ctx.createMediaStreamSource(stream);
  analyser = ctx.createAnalyser();
  analyser.fftSize = FFT_SIZE;
  analyser.smoothingTimeConstant = 0.4;
  source.connect(analyser);
  // Deliberately NOT connected to ctx.destination -- routing the mic to the
  // speakers would create the very feedback echo cancellation exists to fix.
  buffer = new Uint8Array(analyser.fftSize);

  resume();
  if (!visibilityListenerAttached) {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") resume(); else pause();
    });
    visibilityListenerAttached = true;
  }
  return capabilities();
}

function pause() {
  if (timer !== null) { clearInterval(timer); timer = null; }
  if (speaking) { speaking = false; emit("end"); }
}

function resume() {
  if (timer !== null || !analyser) return;
  if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
  timer = setInterval(tick, POLL_MS);
}

function tick() {
  analyser.getByteTimeDomainData(buffer);
  // RMS around the 128 midpoint; no allocation, fixed-size loop.
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) {
    const v = (buffer[i] - 128) / 128;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / buffer.length);
  currentRms = rms;

  // Adapt the noise floor only while NOT speaking, so a long sentence can't
  // drag the floor up and deafen the detector mid-utterance.
  if (!speaking) {
    const rate = rms > noiseFloor ? NOISE_ADAPT_UP : NOISE_ADAPT_DOWN;
    noiseFloor += (rms - noiseFloor) * rate;
    if (noiseFloor < MIN_FLOOR) noiseFloor = MIN_FLOOR;
  }

  const now = performance.now();
  const openAt = Math.max(noiseFloor * OPEN_FACTOR, MIN_FLOOR * OPEN_FACTOR);
  const closeAt = Math.max(noiseFloor * CLOSE_FACTOR, MIN_FLOOR * CLOSE_FACTOR);

  if (!speaking && rms > openAt) {
    speaking = true;
    lastVoiceAt = now;
    emit("start");
  } else if (speaking) {
    if (rms > closeAt) {
      lastVoiceAt = now;          // still talking (hysteresis band)
    } else if (now - lastVoiceAt > HANGOVER_MS) {
      speaking = false;           // real end of utterance, not a word gap
      emit("end");
    }
  }
}

export function isSpeaking() { return speaking; }

export function onSpeechStart(fn) {
  listeners.start.push(fn);
  return () => { listeners.start = listeners.start.filter((item) => item !== fn); };
}

export function onSpeechEnd(fn) {
  listeners.end.push(fn);
  return () => { listeners.end = listeners.end.filter((item) => item !== fn); };
}

/** The processed, single-owner stream used for recording/transcription. */
export function mediaStream() { return stream; }

/** Pause detection while ZENO speaks, preventing speaker echo as a command. */
export function pauseDetection() { pause(); }

/** Resume a live stream after ZENO has finished speaking. */
export function resumeDetection() { resume(); }

export function stop() {
  pause();
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  if (ctx) { ctx.close().catch(() => {}); ctx = null; }
  analyser = null;
  appliedSettings = null;
  currentRms = 0;
  noiseFloor = 0.01;
}

/** Honest report: what the browser actually applied, and what is measured. */
export function capabilities() {
  const s = appliedSettings || {};
  return {
    running: timer !== null,
    error: startError || null,
    // Applied values read back from the live track -- not our request.
    noise_suppression: s.noiseSuppression === true,
    echo_cancellation: s.echoCancellation === true,
    auto_gain_control: s.autoGainControl === true,
    sample_rate: s.sampleRate || null,
    vad: {
      engine: "energy-adaptive",
      implemented: true,
      speaking: speaking,
      rms: Number(currentRms.toFixed(4)),
      noise_floor: Number(noiseFloor.toFixed(4)),
      open_threshold: Number((noiseFloor * OPEN_FACTOR).toFixed(4)),
      poll_hz: Math.round(1000 / POLL_MS),
      note: "Energy + adaptive floor + hysteresis + hangover. Not a neural "
          + "VAD: it cannot reliably tell a person from a TV playing speech.",
    },
    limitation: "Energy VAD reduces silence and ordinary background noise; "
              + "it is not a neural speech classifier and cannot reliably "
              + "reject another person or a TV playing speech.",
  };
}
