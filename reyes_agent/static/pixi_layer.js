// Optional Pixi enhancement layer (PixiJS brief #19, #22, #24, #30, #34, #35).
//
// This does NOT replace the CSS orb (v3, deliberately cheap after the owner
// rejected the heavy WebGL orb). It is a SEPARATE, OFF-by-default overlay that
// paints subtle GPU particle bursts on discrete real events (success, agent
// activation). It:
//   * lazy-loads pixi only when enabled (no cost otherwise);
//   * is crash-isolated -- any failure falls back to "no overlay", never kills
//     the interface or the orb;
//   * cleans up fully (ticker, listeners, textures, canvas) on destroy;
//   * idles its ticker when there is nothing to animate.
//
// It listens to the visual-event bus, so it stays decoupled from AI logic.

import { EVENTS, on } from "./visual_events.js";
import { effectiveConfig, particleBudget } from "./visual_config.js";

let _app = null;
let _PIXI = null;
let _unsubs = [];
let _particles = [];
let _mount = null;
let _running = false;

export function isEnabled() { return !!_app; }

export async function initPixiLayer(mountEl) {
  const cfg = effectiveConfig();
  if (!cfg.pixi) return { enabled: false, reason: "pixi disabled (config/performance mode)" };
  if (_app) return { enabled: true, reason: "already initialised" };
  try {
    _PIXI = await import("./vendor/pixi.min.mjs");
  } catch (err) {
    return { enabled: false, reason: "pixi module failed to load", error: String(err) };
  }
  try {
    _mount = mountEl || document.body;
    _app = new _PIXI.Application();
    await _app.init({
      backgroundAlpha: 0, antialias: false, powerPreference: "low-power",
      resizeTo: _mount === document.body ? window : _mount,
    });
    _app.canvas.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:1";
    _mount.appendChild(_app.canvas);
    _app.ticker.maxFPS = cfg.fpsLimit === "auto" ? 60 : cfg.fpsLimit;
    _app.ticker.add(_tick);
    _wireBus();
    return { enabled: true, renderer: (_app.renderer && _app.renderer.name) || "webgl" };
  } catch (err) {
    // Advanced renderer failed -> tear down and fall back to the CSS orb.
    destroyPixiLayer();
    return { enabled: false, reason: "pixi init failed; using CSS fallback", error: String(err) };
  }
}

function _wireBus() {
  const burst = (color) => () => _spawnBurst(color);
  _unsubs.push(on(EVENTS.SUCCESS, burst(0x35d39a)));
  _unsubs.push(on(EVENTS.AGENT_ACTIVATED, burst(0x4da3ff)));
  _unsubs.push(on(EVENTS.MISSION_COMPLETED, burst(0x7d5cff)));
  _unsubs.push(on(EVENTS.ERROR, burst(0xff5f6d)));
}

function _spawnBurst(color) {
  if (!_app) return;
  const budget = Math.min(particleBudget(), 60);
  if (budget <= 0) return;
  const cx = _app.renderer.width / 2, cy = _app.renderer.height / 2;
  const n = Math.min(budget, 24);
  for (let i = 0; i < n; i++) {
    const g = new _PIXI.Graphics().circle(0, 0, 2 + Math.random() * 2).fill(color);
    g.x = cx; g.y = cy; g.alpha = 1;
    const ang = (Math.PI * 2 * i) / n, spd = 1.5 + Math.random() * 2.5;
    g._vx = Math.cos(ang) * spd; g._vy = Math.sin(ang) * spd; g._life = 1;
    _app.stage.addChild(g); _particles.push(g);
  }
  _running = true;
}

function _tick(ticker) {
  if (!_running || !_app) return;
  const dt = (ticker && ticker.deltaTime) || 1;
  for (let i = _particles.length - 1; i >= 0; i--) {
    const g = _particles[i];
    g.x += g._vx * dt; g.y += g._vy * dt;
    g._life -= 0.02 * dt; g.alpha = Math.max(0, g._life);
    if (g._life <= 0) {
      _app.stage.removeChild(g); g.destroy(); _particles.splice(i, 1);
    }
  }
  if (_particles.length === 0) _running = false; // idle -> stop doing work (#30)
}

export function destroyPixiLayer() {
  for (const u of _unsubs) { try { u(); } catch (_) {} }
  _unsubs = [];
  try { for (const g of _particles) g.destroy(); } catch (_) {}
  _particles = [];
  if (_app) {
    try { _app.ticker.remove(_tick); } catch (_) {}
    try { if (_app.canvas && _app.canvas.parentNode) _app.canvas.parentNode.removeChild(_app.canvas); } catch (_) {}
    try { _app.destroy(true, { children: true, texture: true }); } catch (_) {}
  }
  _app = null; _PIXI = null; _running = false; _mount = null;
}

// Test/diagnostic hook: current live particle count + init state.
export function _debugStats() { return { enabled: !!_app, particles: _particles.length }; }

export const pixiLayer = { initPixiLayer, destroyPixiLayer, isEnabled, _debugStats };
try { if (typeof window !== "undefined") window.zenoPixiLayer = pixiLayer; } catch (_) {}
