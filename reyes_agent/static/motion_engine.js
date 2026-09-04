/*
 * ZENO virtual motion + personality bridge.
 *
 * Shake/dizziness only ever comes from HUD WINDOW DRAG velocity (mini.html's
 * existing drag handler, extended to dispatch one CustomEvent -- see the
 * bottom of this file), never from ordinary cursor movement across the page.
 * Incidental mouse motion driving "shake" would make the whole HUD twitchy
 * for no reason; a deliberate window-shake is a real, rare, intentional
 * gesture. Cursor position/velocity is tracked separately and used only for
 * the existing eyes' spring target (see orb.js's queueCursorEyes upgrade).
 *
 * PURE CORE below (createMotionState/updateSample/step) has no DOM
 * dependency and no side effects -- it is `require()`-able from Node for
 * tests (see tests/motion_engine.node.js) exactly like spring.js. DOM glue
 * (near the bottom, guarded by `typeof window`) is the only part that
 * touches the page, and it is entirely additive: nothing here replaces an
 * existing listener, element or class.
 */
(function (root) {
  "use strict";

  // ---- tunables --------------------------------------------------------
  var SHAKE_WINDOW_MS = 700;          // reversals older than this don't count
  var SHAKE_REVERSALS_FOR_MAX = 6;    // reversals within the window -> shakeIntensity 1
  var SHAKE_MIN_SPEED = 60;           // px/s below this, a direction flip is jitter, not shake
  var SHAKE_DECAY_PER_S = 1.4;        // shakeIntensity units/s lost once shaking stops
  var DIZZY_GAIN_PER_S = 0.9;         // dizziness units/s gained at shakeIntensity 1
  var DIZZY_DECAY_PER_S = 0.18;       // dizziness units/s lost while settled
  var DIZZY_SETTLE_BELOW = 0.15;      // shakeIntensity below this counts as "settling"
  var VELOCITY_IDLE_MS = 80;          // no fresh sample for this long -> velocity decays toward 0
  var VELOCITY_IDLE_DECAY = 0.85;     // per-frame multiplier while idle
  var REACT_DIZZY_ON = 0.55;          // rising-edge threshold that can trigger a "dizzy" reaction
  var REACT_DIZZY_OFF = 0.12;         // falling-edge threshold that can trigger "recovered"
  var REACT_SHAKE_ON = 0.7;           // rising-edge threshold that can trigger a "shake" reaction

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clamp01(v) { return clamp(v, 0, 1); }

  /** MotionState: position/velocity/acceleration {x,y}; angularVelocity
   *  (scalar, rad/s-ish -- direction-change rate, not a literal rotation);
   *  shakeIntensity/dizziness in [0,1]; orientation is null on desktop, a
   *  {alpha,beta,gamma} snapshot on a phone that granted DeviceOrientation;
   *  lastMovementAt is a Date.now() timestamp, 0 until the first sample. */
  function createMotionState() {
    return {
      position: { x: 0, y: 0 },
      velocity: { x: 0, y: 0 },
      acceleration: { x: 0, y: 0 },
      angularVelocity: 0,
      shakeIntensity: 0,
      dizziness: 0,
      orientation: null,
      lastMovementAt: 0,
      _reversals: [],            // bounded: pruned to SHAKE_WINDOW_MS every step()
      _lastDir: { x: 0, y: 0 },
      _lean: { x: 0, v: 0 },     // spring state for the HUD lean transform
      _wasDizzy: false,          // edge-detection so a reaction fires once per crossing,
      _wasShaking: false,        // not continuously while a threshold stays crossed
    };
  }

  /** One raw position sample (window screenX/screenY while being dragged).
   *  Pure: returns the same `state` object, mutated, for cheap call sites --
   *  callers that need immutability should shallow-copy before calling. */
  function updateSample(state, x, y, now) {
    var dtMs = state.lastMovementAt ? (now - state.lastMovementAt) : 16;
    var dt = Math.max(1, dtMs) / 1000;
    var dx = x - state.position.x, dy = y - state.position.y;
    var vx = dx / dt, vy = dy / dt;
    var ax = (vx - state.velocity.x) / dt, ay = (vy - state.velocity.y) / dt;
    var speed = Math.sqrt(vx * vx + vy * vy);

    if (speed > SHAKE_MIN_SPEED) {
      var dirX = vx / speed, dirY = vy / speed;
      var hadDir = state._lastDir.x !== 0 || state._lastDir.y !== 0;
      var dot = dirX * state._lastDir.x + dirY * state._lastDir.y;
      if (hadDir && dot < -0.2) {
        state._reversals.push(now);
        state.angularVelocity = Math.acos(clamp(dot, -1, 1)) / dt;
      }
      state._lastDir = { x: dirX, y: dirY };
    }
    while (state._reversals.length && now - state._reversals[0] > SHAKE_WINDOW_MS) {
      state._reversals.shift();
    }

    state.position = { x: x, y: y };
    state.velocity = { x: vx, y: vy };
    state.acceleration = { x: ax, y: ay };
    state.lastMovementAt = now;
    return state;
  }

  /** Advance shake decay, dizziness accumulation/decay, velocity idle-decay
   *  and the lean spring by `dt` seconds. Call every animation frame
   *  regardless of whether a new sample arrived this frame -- decay and the
   *  spring both need to keep running while the HUD is still. `spring` is
   *  the ZenoSpring module (stepSpring); passing null skips the lean step
   *  (still fully valid -- lean is cosmetic, not required for the state
   *  machine tests). Returns {state, reaction} where reaction is null or
   *  one of "shake"/"dizzy"/"recovered" -- an EDGE only, never repeated
   *  every frame the threshold stays crossed. */
  function step(state, dt, spring, now) {
    now = now == null ? Date.now() : now;
    dt = clamp(dt, 0, 1 / 15); // a stalled/backgrounded tab must not "catch up" in one jump

    // Reversals must age out purely by TIME, not only when a new sample
    // happens to arrive -- otherwise the HUD going still right after a shake
    // freezes the reversal count and shakeIntensity/dizziness never decay.
    while (state._reversals.length && now - state._reversals[0] > SHAKE_WINDOW_MS) {
      state._reversals.shift();
    }
    var reversalCount = state._reversals.length;
    var targetShake = clamp01(reversalCount / SHAKE_REVERSALS_FOR_MAX);
    if (targetShake > state.shakeIntensity) {
      state.shakeIntensity = targetShake; // a real shake registers instantly, never smoothed away
    } else {
      state.shakeIntensity = Math.max(0, state.shakeIntensity - SHAKE_DECAY_PER_S * dt);
    }

    if (state.shakeIntensity > DIZZY_SETTLE_BELOW) {
      state.dizziness = clamp01(state.dizziness + DIZZY_GAIN_PER_S * state.shakeIntensity * dt);
    } else {
      state.dizziness = Math.max(0, state.dizziness - DIZZY_DECAY_PER_S * dt);
    }

    var idleMs = state.lastMovementAt ? (now - state.lastMovementAt) : Infinity;
    if (idleMs > VELOCITY_IDLE_MS) {
      state.velocity = { x: state.velocity.x * VELOCITY_IDLE_DECAY, y: state.velocity.y * VELOCITY_IDLE_DECAY };
      state.angularVelocity *= VELOCITY_IDLE_DECAY;
    }

    if (spring && spring.stepSpring) {
      var leanTarget = clamp(state.velocity.x / 60, -6, 6);
      state._lean = spring.stepSpring(state._lean, leanTarget, dt, "smooth");
    }

    var reaction = null;
    var isShaking = state.shakeIntensity >= REACT_SHAKE_ON;
    var isDizzy = state.dizziness >= REACT_DIZZY_ON;
    var isRecovered = state.dizziness <= REACT_DIZZY_OFF;
    if (isShaking && !state._wasShaking) {
      reaction = "shake";
    } else if (isDizzy && !state._wasDizzy) {
      reaction = "dizzy";
    } else if (state._wasDizzy && isRecovered) {
      reaction = "recovered";
    }
    state._wasShaking = isShaking;
    state._wasDizzy = state._wasDizzy ? !isRecovered : isDizzy;
    return { state: state, reaction: reaction };
  }

  var core = {
    createMotionState: createMotionState,
    updateSample: updateSample,
    step: step,
    TUNABLES: {
      SHAKE_WINDOW_MS: SHAKE_WINDOW_MS, SHAKE_REVERSALS_FOR_MAX: SHAKE_REVERSALS_FOR_MAX,
      SHAKE_MIN_SPEED: SHAKE_MIN_SPEED, REACT_DIZZY_ON: REACT_DIZZY_ON,
      REACT_DIZZY_OFF: REACT_DIZZY_OFF, REACT_SHAKE_ON: REACT_SHAKE_ON,
    },
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = core;
    return; // Node/test context: DOM glue below is browser-only and must not run.
  }

  // ---- DOM glue (browser only) ------------------------------------------
  // Nothing below runs until start() is called; importing this file alone
  // has zero side effects, same discipline as spring.js.
  function start(opts) {
    opts = opts || {};
    var state = createMotionState();
    var spring = root.ZenoSpring || null;
    var leanEl = typeof opts.leanTarget === "string"
      ? document.querySelector(opts.leanTarget) : opts.leanTarget;
    var reactCooldownMs = 12000; // mirrors ragebait.py's _MOTION_COOLDOWN_S server-side cooldown
    var lastReactAt = 0;
    var raf = 0;

    function isMuted() {
      try { return localStorage.getItem("zeno_reaction_muted") === "1"; }
      catch (_e) { return false; }
    }

    function applyVisuals() {
      if (!leanEl) return;
      // NOT leanEl.style.transform: verified live that orb.js's own
      // stylesheet already owns `transform` on this element (its centering
      // translate) -- an inline write here REPLACES rather than composes
      // with it, and the orb visibly jumps to the top-left corner (measured:
      // its centered bounding rect collapsed to ~0,0). Filter is a property
      // orb.js's CSS never touches, so it is the safe channel for "orb
      // instability" here; a literal rotate() is left for a future target
      // element that actually owns its own transform (opts.leanTarget can
      // still be pointed at one -- see the CSS var fallback below for that
      // case specifically, so this is not dead code for every caller).
      if (leanEl.style.getPropertyValue("--zeno-owns-transform") === "1") {
        var lean = state._lean.x;
        var wobble = state.dizziness > DIZZY_SETTLE_BELOW
          ? (Math.sin(Date.now() / (90 - state.dizziness * 40)) * state.dizziness * 3) : 0;
        leanEl.style.transform = "rotate(" + (lean + wobble).toFixed(2) + "deg)";
      }
      leanEl.classList.toggle("zeno-dizzy", state.dizziness > REACT_DIZZY_ON);
      leanEl.classList.toggle("zeno-shaking", state.shakeIntensity > 0.3);
    }

    function maybeReact(reaction) {
      if (!reaction) return;
      // /api/personality/physical-event forwards to reyes_agent/ragebait.py's
      // on_motion() -- the EXISTING, consent-scoped (owner must have said
      // "ragebait me" first) local reaction state, not a second personality
      // system. It returns an emotion tag, never spoken text: Ragebait's
      // reactions are visual/state, not unprompted TTS, so there is no
      // /api/tts call here (motion_engine.js does not own any voice output).
      // reactRemote:false (the phone companion) skips the request entirely --
      // that endpoint is loopback-only, see remote_access/boundary.py.
      if (opts.reactRemote === false) return;
      var now = Date.now();
      if (now - lastReactAt < reactCooldownMs) return; // client-side mirror of ragebait's own cooldown
      lastReactAt = now;
      fetch("/api/personality/physical-event", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: reaction, dizziness: state.dizziness, shake_intensity: state.shakeIntensity }),
      }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
        if (!data || !data.reacted) return;
        root.dispatchEvent(new CustomEvent("zeno:personality-reaction", {
          detail: { emotion: data.emotion || "", event: reaction },
        }));
      }).catch(function () {});
    }

    var last = null;
    function frame(now) {
      raf = requestAnimationFrame(frame);
      var dt = last == null ? 1 / 60 : (now - last) / 1000;
      last = now;
      var result = step(state, dt, spring, Date.now());
      applyVisuals();
      maybeReact(result.reaction);
    }
    raf = requestAnimationFrame(frame);

    // Window-drag samples: mini.html's own drag handler dispatches this (see
    // the small addition at the bottom of mini.html) -- it already tracks
    // screenX/screenY while dragging, so this is purely an ADDITIONAL
    // listener on an event that did not exist before, never a replacement
    // for how dragging itself works.
    root.addEventListener("zeno:hud-drag", function (e) {
      var d = e.detail || {};
      if (typeof d.screenX === "number" && typeof d.screenY === "number") {
        updateSample(state, d.screenX, d.screenY, Date.now());
      }
    });

    return {
      state: state,
      stop: function () { if (raf) cancelAnimationFrame(raf); },
      setMuted: function (muted) {
        try { localStorage.setItem("zeno_reaction_muted", muted ? "1" : "0"); } catch (_e) {}
      },
    };
  }

  /** Phone companion opt-in: DeviceMotion/DeviceOrientation, permission-gated
   *  (iOS 13+ requires an explicit user-gesture-triggered request). Never
   *  required -- desktop motion (above) works entirely without this, and a
   *  denied/unsupported permission just means orientation stays null. Feeds
   *  the SAME MotionState shape via updateSample-equivalent acceleration
   *  sampling, so a phone and the desktop drive identical downstream logic. */
  function requestPhoneMotionPermission() {
    var DME = root.DeviceMotionEvent;
    if (DME && typeof DME.requestPermission === "function") {
      return DME.requestPermission().then(function (r) { return r === "granted"; }).catch(function () { return false; });
    }
    return Promise.resolve(!!DME); // Android/desktop browsers: no gate, just feature-detect
  }

  function attachPhoneMotion(handle) {
    if (!handle || !handle.state) return false;
    var state = handle.state;
    var supported = false;
    if (root.DeviceOrientationEvent) {
      root.addEventListener("deviceorientation", function (e) {
        state.orientation = { alpha: e.alpha, beta: e.beta, gamma: e.gamma };
      });
      supported = true;
    }
    if (root.DeviceMotionEvent) {
      root.addEventListener("devicemotion", function (e) {
        var acc = e.accelerationIncludingGravity || e.acceleration;
        if (!acc) return;
        var now = Date.now();
        // Phone acceleration -> the same virtual position pipeline: integrate
        // a small virtual displacement so shake detection (built on position
        // SAMPLES) works identically to the desktop's window-drag path,
        // without a second shake algorithm.
        var dtMs = state.lastMovementAt ? (now - state.lastMovementAt) : 16;
        var dt = Math.max(1, dtMs) / 1000;
        var vx = (acc.x || 0) * 40, vy = (acc.y || 0) * 40;
        updateSample(state, state.position.x + vx * dt, state.position.y + vy * dt, now);
      });
      supported = true;
    }
    return supported;
  }

  var api = Object.assign({}, core, {
    start: start,
    requestPhoneMotionPermission: requestPhoneMotionPermission,
    attachPhoneMotion: attachPhoneMotion,
  });
  root.ZenoMotion = api;
})(typeof window !== "undefined" ? window : this);
