// Agent orbs (PixiJS brief #8) -- a GPU visual for the specialists that are
// ACTUALLY active, driven by the bus (AGENT_ACTIVATED / AGENT_THINKING /
// AGENT_COMPLETED). It complements the existing CSS Agent Ring in orb.js and
// reuses its specialist ids; it does not replace it. Only agents involved in a
// task appear -- an idle roster draws nothing (#8, #30).
//
// Off unless config.agentOrbs; lazy pixi; crash-isolated; full cleanup; idles
// its ticker when nothing is animating. Never touches AI logic -- it only reads
// bus events, so the brain never imports a renderer.

import { EVENTS, on } from "./visual_events.js";
import { effectiveConfig } from "./visual_config.js";

// Same specialists the CSS Agent Ring uses (orb.js SPECIALIST_IDS), + hues.
const HUE = {
  aris: 200, tosin: 150, stark: 356, zeal: 40, titan: 20, apex: 280, nova: 306,
  hermes_comm: 190, oracle: 259, atlas: 120, ultron: 0, kate: 330, helios: 47,
};
const KNOWN = new Set(Object.keys(HUE));

let _app = null, _PIXI = null, _container = null;
let _orbs = new Map();     // agent -> { g, label, status, energy, fade, active }
let _unsubs = [];
let _dirty = false;

export function isEnabled() { return !!_app; }
export function activeAgents() { return [..._orbs.keys()].filter((a) => _orbs.get(a).active); }

export async function initAgentOrbs(mountEl, _opts) {
  const cfg = effectiveConfig();
  if (cfg.agentOrbs === false) return { enabled: false, reason: "agentOrbs disabled" };
  if (_app) return { enabled: true, reason: "already initialised" };
  try { _PIXI = await import("./vendor/pixi.min.mjs"); }
  catch (err) { return { enabled: false, reason: "pixi module failed to load", error: String(err) }; }
  try {
    const mount = mountEl || document.body;
    _app = new _PIXI.Application();
    await _app.init({ backgroundAlpha: 0, antialias: true, powerPreference: "low-power", resizeTo: mount });
    _app.canvas.style.cssText = "position:absolute;inset:0;pointer-events:none";
    mount.appendChild(_app.canvas);
    _container = new _PIXI.Container();
    _app.stage.addChild(_container);
    _unsubs.push(on(EVENTS.AGENT_ACTIVATED, (d) => _activate(d && d.agent)));
    _unsubs.push(on(EVENTS.AGENT_THINKING, (d) => _status(d && d.agent, "thinking")));
    _unsubs.push(on(EVENTS.AGENT_COMPLETED, (d) => _complete(d && d.agent)));
    _app.ticker.maxFPS = cfg.fpsLimit === "auto" ? 60 : cfg.fpsLimit;
    _app.ticker.add(_tick);
    return { enabled: true, renderer: _app.renderer.type === 1 ? "webgl" : "other" };
  } catch (err) {
    destroyAgentOrbs();
    return { enabled: false, reason: "agent orbs init failed", error: String(err) };
  }
}

function _norm(a) { return String(a || "").toLowerCase().trim(); }

function _activate(agent) {
  agent = _norm(agent);
  if (!agent || !KNOWN.has(agent) || !_app) return;
  let orb = _orbs.get(agent);
  if (!orb) {
    const g = new _PIXI.Graphics();
    const label = new _PIXI.Text({
      text: agent.replace("_comm", "").toUpperCase(),
      style: { fill: 0xe8eef8, fontSize: 11, fontFamily: "system-ui, sans-serif" },
    });
    label.anchor.set(0.5, 0);
    _container.addChild(g); _container.addChild(label);
    orb = { g, label, status: "active", energy: 0, fade: 0, active: true };
    _orbs.set(agent, orb);
  }
  orb.active = true; orb.fade = 0; orb.status = "active";
  _relayout();
}

function _status(agent, status) {
  const orb = _orbs.get(_norm(agent));
  if (orb) { orb.status = status; if (status === "thinking") orb.energy = 1; }
}

function _complete(agent) {
  const orb = _orbs.get(_norm(agent));
  if (orb) { orb.status = "done"; orb.fade = 0.0001; }   // begins fading out
}

function _relayout() {
  if (!_app) return;
  const shown = [..._orbs.entries()].filter(([, o]) => o.active);
  const W = _app.renderer.width, H = _app.renderer.height;
  const n = shown.length, gap = Math.min(120, W / (n + 1));
  shown.forEach(([, o], i) => {
    o.x = W / 2 + (i - (n - 1) / 2) * gap;
    o.y = H / 2;
  });
  _dirty = true;
}

function _tick(ticker) {
  if (!_app) return;
  const dt = (ticker && ticker.deltaMS) || 16;
  let animating = false;
  for (const [agent, o] of [..._orbs.entries()]) {
    // energy decays; thinking keeps it topped up (pulse); fading removes.
    if (o.status === "thinking") { o.energy = Math.min(1, o.energy + 0.02); animating = true; }
    else o.energy = Math.max(0, o.energy - 0.01);
    if (o.fade > 0) { o.fade += dt / 900; animating = true; if (o.fade >= 1) { _remove(agent); continue; } }
    const hue = HUE[agent] ?? 200;
    const r = 16 + 6 * o.energy;
    const alpha = o.fade > 0 ? Math.max(0, 1 - o.fade) : 1;
    o.g.clear();
    o.g.circle(o.x || 0, o.y || 0, r).fill({ color: _hsl(hue, 0.7, 0.55), alpha: 0.85 * alpha });
    o.g.circle(o.x || 0, o.y || 0, r + 4 + 4 * o.energy).stroke({ color: _hsl(hue, 0.8, 0.65), alpha: 0.5 * alpha, width: 2 });
    if (o.label) { o.label.x = o.x || 0; o.label.y = (o.y || 0) + r + 8; o.label.alpha = alpha; }
    if (o.energy > 0.01) animating = true;
  }
  if (!animating && !_dirty) return;   // idle
  _dirty = false;
}

function _remove(agent) {
  const o = _orbs.get(agent);
  if (!o) return;
  try { o.g.destroy(); if (o.label) o.label.destroy(); } catch (_) {}
  _orbs.delete(agent);
  _relayout();
}

export function destroyAgentOrbs() {
  for (const u of _unsubs) { try { u(); } catch (_) {} }
  _unsubs = [];
  for (const [, o] of _orbs) { try { o.g.destroy(); if (o.label) o.label.destroy(); } catch (_) {} }
  _orbs = new Map();
  if (_app) {
    try { _app.ticker.remove(_tick); } catch (_) {}
    try { if (_app.canvas && _app.canvas.parentNode) _app.canvas.parentNode.removeChild(_app.canvas); } catch (_) {}
    try { _app.destroy(true, { children: true, texture: true }); } catch (_) {}
  }
  _app = null; _PIXI = null; _container = null;
}

function _hsl(h, s, l) {
  // minimal hsl->rgb int for Pixi fills
  s = s; l = l; const a = s * Math.min(l, 1 - l);
  const f = (n) => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1))); };
  return (Math.round(f(0) * 255) << 16) | (Math.round(f(8) * 255) << 8) | Math.round(f(4) * 255);
}

// Expose the internal app for honest render-cost measurement in harnesses.
export function _debugApp() { return _app; }
// Advance one tick with a synthetic delta -- lets a headless harness verify the
// ticker-driven fade/remove logic without depending on the pane's rAF loop.
export function _debugTick(deltaMS) { _tick({ deltaMS: deltaMS || 16 }); }
export const agentOrbs = { initAgentOrbs, destroyAgentOrbs, isEnabled, activeAgents };
try { if (typeof window !== "undefined") window.zenoAgentOrbs = agentOrbs; } catch (_) {}
