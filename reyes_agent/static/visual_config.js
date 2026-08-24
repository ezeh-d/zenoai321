// Central visual configuration (PixiJS brief #33, #20, #29).
//
// One place for animation settings instead of constants scattered across files.
// Defaults are DELIBERATELY conservative: the Pixi enhancement layer is OFF by
// default because the owner previously rejected a heavy GPU orb. Enable it
// explicitly; performance mode forces everything back down.

const DEFAULTS = Object.freeze({
  animations: true,
  pixi: false, // optional enhancement layer OFF by default
  particles: "off", // off | low | medium | high | auto
  fpsLimit: 60, // 30 | 60 | auto
  glow: true,
  agentOrbs: true,
  audioVisualizer: true,
  reducedMotion: false,
  performanceMode: false,
});

let _cfg = { ...DEFAULTS };

// Respect the OS "reduce motion" setting when present.
try {
  if (typeof window !== "undefined" && window.matchMedia) {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq && mq.matches) { _cfg.reducedMotion = true; _cfg.particles = "off"; }
  }
} catch (_) {}

export function getConfig() { return { ..._cfg }; }

export function setConfig(patch) {
  if (patch && typeof patch === "object") _cfg = { ..._cfg, ...patch };
  return getConfig();
}

// When performance mode is on, force the cheap profile (#20) without losing the
// user's stored preferences — it's an override, computed at read time.
export function effectiveConfig() {
  const c = { ..._cfg };
  if (c.performanceMode || c.reducedMotion) {
    c.pixi = false;
    c.particles = "off";
    c.glow = false;
    c.fpsLimit = 30;
    c.audioVisualizer = c.audioVisualizer && !c.performanceMode;
  }
  return c;
}

export function setPerformanceMode(on) { _cfg.performanceMode = !!on; return effectiveConfig(); }

// How many particles a "quality" level permits — AUTO starts low and the Pixi
// layer's adaptive scaler may lower it further.
export function particleBudget(quality) {
  switch (String(quality || _cfg.particles)) {
    case "high": return 220;
    case "medium": return 120;
    case "low": return 50;
    case "auto": return 60;
    default: return 0; // off
  }
}

export const config = { getConfig, setConfig, effectiveConfig, setPerformanceMode, particleBudget };
try { if (typeof window !== "undefined") window.zenoVisualConfig = config; } catch (_) {}
