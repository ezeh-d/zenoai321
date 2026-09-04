/*
 * ZENO panel springs — physics + constants extracted from Framer Motion
 * (motiondivision/motion, packages/motion-dom/.../spring.ts). No library is
 * bundled: this is a ~2KB self-contained helper that reproduces Motion's
 * default spring physics so ZENO's mini-panels can move with real springs
 * instead of fixed-duration easing.
 *
 * ADDITIVE + OPT-IN: nothing here runs on its own. Existing panel code is
 * untouched; call springTo()/springCSS() from panel logic when you want it.
 *
 * Motion's exact springDefaults:
 *   stiffness 100 · damping 10 · mass 1 · velocity 0
 *   duration 800ms · bounce 0.3 (dampingRatio = 1 - bounce = 0.7)
 *   restSpeed 2 · restDelta 0.5
 * dampingRatio = damping / (2 * sqrt(stiffness * mass)); the library default
 * (100/10) is dampingRatio 0.5 — deliberately bouncy.
 */
(function (root) {
  "use strict";

  var SPRING_DEFAULTS = {
    stiffness: 100, damping: 10, mass: 1.0, velocity: 0.0,
    restSpeed: 2, restDelta: 0.5, maxDuration: 10000 /* ms */,
  };

  // damping that yields a target dampingRatio for a given stiffness/mass.
  function dampingFor(stiffness, ratio, mass) {
    return ratio * 2 * Math.sqrt(stiffness * (mass || 1));
  }

  // Presets keyed to Motion's dampingRatios so the feel matches the source.
  var PRESETS = {
    bouncy: { stiffness: 100, damping: 10 },                       // ratio 0.5 (Motion default)
    smooth: { stiffness: 100, damping: dampingFor(100, 0.7, 1) },  // ratio 0.7 (bounce 0.3)
    crisp:  { stiffness: 100, damping: dampingFor(100, 1.0, 1) },  // critically damped, no overshoot
    snappy: { stiffness: 300, damping: dampingFor(300, 0.72, 1) }, // fast settle, tiny overshoot
  };

  function opt(o, k) { return (o && o[k] != null) ? o[k] : SPRING_DEFAULTS[k]; }

  /*
   * stepSpring — ONE physics step of a damped spring toward `target`, given
   * the current {x, v}. Pulled out of springTo()'s inner loop so continuous
   * "chase" motion (cursor-following eyes, a HUD lean that tracks live
   * velocity) shares the exact same math as springTo's fire-and-forget
   * animations, instead of a second hand-rolled approximation. `target` may
   * change every call -- unlike springTo, this never "completes"; the caller
   * decides when motion is negligible (e.g. via restSpeed/restDelta on the
   * returned state) and can stop calling it.
   *   state = ZenoSpring.stepSpring(state, target, dt, "smooth");
   *   el.style.transform = `translate3d(${state.x}px,0,0)`;
   */
  function stepSpring(state, target, dt, cfg) {
    var c = (typeof cfg === "string" ? PRESETS[cfg] : cfg) || PRESETS.smooth;
    var stiffness = opt(c, "stiffness"), damping = opt(c, "damping"), mass = opt(c, "mass");
    var x = state ? state.x : 0, v = state ? state.v : 0;
    // Sub-step for stability exactly like springTo, so a dropped/slow frame
    // (large dt) never overshoots into instability.
    var clamped = Math.min(Math.max(dt, 0), 1 / 30);
    var sub = Math.max(1, Math.ceil(clamped / (1 / 240))), h = clamped / sub;
    for (var i = 0; i < sub; i++) {
      var a = (-stiffness * (x - target) - damping * v) / mass;
      v += a * h; x += v * h;
    }
    return { x: x, v: v };
  }

  /*
   * springTo — animate a value from `from` to `to` with a real spring, driven
   * by requestAnimationFrame (semi-implicit Euler, sub-stepped for stability).
   * Returns a cancel function. onUpdate(value, velocity) each frame.
   */
  function springTo(o) {
    o = o || {};
    var to = o.to || 0, x = o.from || 0, v = opt(o, "velocity");
    var stiffness = opt(o, "stiffness"), damping = opt(o, "damping"), mass = opt(o, "mass");
    var restSpeed = opt(o, "restSpeed"), restDelta = opt(o, "restDelta");
    var onUpdate = o.onUpdate, onComplete = o.onComplete;
    var raf = 0, last = null, stopped = false;

    function frame(now) {
      if (stopped) return;
      if (last == null) last = now;
      var dt = Math.min((now - last) / 1000, 1 / 30); // clamp big gaps
      last = now;
      var sub = Math.max(1, Math.ceil(dt / (1 / 240))), h = dt / sub;
      for (var i = 0; i < sub; i++) {
        var a = (-stiffness * (x - to) - damping * v) / mass;
        v += a * h; x += v * h;
      }
      if (Math.abs(v) < restSpeed && Math.abs(x - to) < restDelta) {
        onUpdate && onUpdate(to, 0);
        onComplete && onComplete();
        return;
      }
      onUpdate && onUpdate(x, v);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return function cancel() { stopped = true; if (raf) cancelAnimationFrame(raf); };
  }

  /*
   * springCSS — Motion's trick: sample the spring once and emit a CSS
   * `linear()` easing + duration, so a plain CSS transition (or WAAPI) gets
   * true spring motion, overshoot and all. Falls back to a cubic-bezier
   * string for engines without linear() support.
   *   var s = ZenoSpring.springCSS("smooth");
   *   el.style.transition = "transform " + s.duration + "ms " + s.easing;
   */
  function springCSS(preset, overrides) {
    var base = (typeof preset === "string" ? PRESETS[preset] : preset) || PRESETS.smooth;
    var cfg = Object.assign({}, base, overrides || {});
    var stiffness = opt(cfg, "stiffness"), damping = opt(cfg, "damping"), mass = opt(cfg, "mass");
    var restSpeed = opt(cfg, "restSpeed"), restDelta = opt(cfg, "restDelta");
    // integrate 0 -> 1 to find settle time and sample the normalized curve.
    var x = 0, v = 0, t = 0, h = 1 / 240, points = [], settle = 0;
    while (t < SPRING_DEFAULTS.maxDuration / 1000) {
      var a = (-stiffness * (x - 1) - damping * v) / mass;
      v += a * h; x += v * h; t += h;
      points.push(x);
      if (Math.abs(v) < restSpeed / 100 && Math.abs(x - 1) < restDelta / 100) { settle = t; break; }
    }
    if (!settle) settle = t;
    // down-sample to ~40 stops for a compact linear() string.
    var stops = [], N = Math.min(40, points.length), i;
    for (i = 0; i <= N; i++) {
      var idx = Math.round((i / N) * (points.length - 1));
      stops.push((points[idx]).toFixed(4));
    }
    return {
      duration: Math.round(settle * 1000),
      easing: "linear(" + stops.join(",") + ")",
      bezier: "cubic-bezier(0.22,1,0.36,1)", // no-overshoot fallback
      config: cfg,
    };
  }

  var api = {
    SPRING_DEFAULTS: SPRING_DEFAULTS,
    PRESETS: PRESETS,
    dampingFor: dampingFor,
    stepSpring: stepSpring,
    springTo: springTo,
    springCSS: springCSS,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ZenoSpring = api;
})(typeof window !== "undefined" ? window : this);
