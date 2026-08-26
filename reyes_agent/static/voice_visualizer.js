// Voice / audio visualizer (PixiJS brief #5, #6).
//
// A lightweight GPU equalizer driven by the REAL normalised audio level that the
// mic (while listening) or the TTS output (while speaking) emits on the bus as
// EVENTS.AUDIO_LEVEL. The visualizer only READS that level -- it never touches
// microphone or audio processing, keeping capture off the render path.
//
// Off unless config.audioVisualizer is true (and forced off in performance /
// reduced-motion mode). Lazy pixi load, crash-isolated, cleans up fully, and
// idles its ticker when there is no audio. Exposes fps() for measurement.

import { EVENTS, on } from "./visual_events.js";
import { effectiveConfig } from "./visual_config.js";

let _app = null;
let _PIXI = null;
let _bars = [];
let _unsubs = [];
let _level = 0;      // smoothed
let _target = 0;     // latest reported level
let _active = false;
let _fps = { frames: 0, last: 0, value: 0 };

export function isEnabled() { return !!_app; }
export function fps() { return _fps.value; }

export async function initVoiceVisualizer(mountEl, opts) {
  const bars = (opts && opts.bars) || 28;
  const cfg = effectiveConfig();
  if (!cfg.audioVisualizer) return { enabled: false, reason: "audioVisualizer disabled" };
  if (_app) return { enabled: true, reason: "already initialised" };
  try { _PIXI = await import("./vendor/pixi.min.mjs"); }
  catch (err) { return { enabled: false, reason: "pixi module failed to load", error: String(err) }; }
  try {
    const mount = mountEl || document.body;
    _app = new _PIXI.Application();
    await _app.init({ backgroundAlpha: 0, antialias: false, powerPreference: "low-power", resizeTo: mount });
    _app.canvas.style.cssText = "position:absolute;inset:0;pointer-events:none";
    mount.appendChild(_app.canvas);
    const W = _app.renderer.width, bw = W / bars;
    for (let i = 0; i < bars; i++) {
      const g = new _PIXI.Graphics(); g.x = i * bw; _bars.push(g); _app.stage.addChild(g);
    }
    _fps = { frames: 0, last: performance.now(), value: 0 };
    _unsubs.push(on(EVENTS.AUDIO_LEVEL, (d) => {
      _target = Math.max(0, Math.min(1, (d && typeof d.level === "number") ? d.level : 0));
      if (_target > 0.001) _active = true;
    }));
    _app.ticker.maxFPS = cfg.fpsLimit === "auto" ? 60 : cfg.fpsLimit;
    _app.ticker.add(_tick);
    return { enabled: true, renderer: (_app.renderer && _app.renderer.name) || "webgl" };
  } catch (err) {
    destroyVoiceVisualizer();
    return { enabled: false, reason: "voice visualizer init failed", error: String(err) };
  }
}

function _tick(ticker) {
  if (!_app) return;
  // Ease toward the reported level; when audio stops, decay to rest and idle.
  _level += (_target - _level) * 0.3;
  const now = performance.now();
  _fps.frames++;
  if (now - _fps.last >= 1000) { _fps.value = _fps.frames; _fps.frames = 0; _fps.last = now; }

  if (!_active && _level < 0.01) return; // idle: nothing to draw (#30)
  const W = _app.renderer.width, H = _app.renderer.height, n = _bars.length, bw = W / n;
  const t = (ticker && ticker.lastTime) || now;
  for (let i = 0; i < n; i++) {
    const g = _bars[i];
    const dist = Math.abs(i - (n - 1) / 2) / (n / 2);           // 0 centre .. 1 edge
    const wave = 0.55 + 0.45 * Math.sin(i * 0.7 + t / 120);
    const h = Math.max(2, H * _level * (1 - dist * 0.55) * wave);
    g.clear();
    g.roundRect(2, (H - h) / 2, Math.max(1, bw - 4), h, 3).fill({ color: 0x4da3ff, alpha: 0.9 });
  }
  if (_target < 0.001 && _level < 0.01) _active = false;
}

export function destroyVoiceVisualizer() {
  for (const u of _unsubs) { try { u(); } catch (_) {} }
  _unsubs = [];
  try { for (const g of _bars) g.destroy(); } catch (_) {}
  _bars = [];
  if (_app) {
    try { _app.ticker.remove(_tick); } catch (_) {}
    try { if (_app.canvas && _app.canvas.parentNode) _app.canvas.parentNode.removeChild(_app.canvas); } catch (_) {}
    try { _app.destroy(true, { children: true, texture: true }); } catch (_) {}
  }
  _app = null; _PIXI = null; _level = 0; _target = 0; _active = false;
}

// Exposed for honest render-cost measurement (timed synchronous renders).
export function _debugApp() { return _app; }
export const voiceVisualizer = { initVoiceVisualizer, destroyVoiceVisualizer, isEnabled, fps };
try { if (typeof window !== "undefined") window.zenoVoiceVisualizer = voiceVisualizer; } catch (_) {}
