// ZENO orb v3 -- a SIMPLE glowing sphere, pure CSS (no WebGL, no
// three.js, no per-pixel shader). v2 was a fullscreen fragment shader
// computing simplex noise every pixel every frame -- tunable (pixel
// ratio, octaves) but never actually cheap, and the underlying approach
// itself is what the user rejected ("not good... high GPU... will make
// it lag"). A radial-gradient circle with a CSS breathing animation
// costs the compositor almost nothing (transform/opacity/filter on one
// small element, GPU-composited) and reads as clean and simple, which is
// exactly what was asked for.
//
// Public API is IDENTICAL to v1/v2 (setState / pulse / setPerformanceMode
// / setActive / dispatchAgent / setAgentWorking / getAgentScreenPositions
// / specialists) so index.html and the Agent Ring (which already talks
// only to this API) need zero changes.

// `eyes` names an expression class; the eyes are pure CSS shapes, so an
// expression costs one class swap, not a render loop. Deliberately subtle
// -- this reads as attentiveness, not a cartoon face.
const STATES = {
  // hue in degrees (CSS hsl), not the old 0..1 fraction -- kept as close
  // as possible to the same color language the ticker/GUI already uses.
  idle:          { hue: 187, spin: 22, eyes: "calm" },
  listening:     { hue: 32,  spin: 16, eyes: "attentive" },
  understanding: { hue: 208, spin: 15, eyes: "attentive" },
  thinking:      { hue: 259, spin: 9,  eyes: "focused" },
  acting:        { hue: 306, spin: 8,  eyes: "focused" },
  waiting:       { hue: 56,  spin: 28, eyes: "scanning" },
  success:       { hue: 137, spin: 20, eyes: "bright" },
  processing:    { hue: 259, spin: 9,  eyes: "focused" },
  speaking:      { hue: 180, spin: 7,  eyes: "calm" },
  error:         { hue: 356, spin: 26, eyes: "concerned" },
  searching:     { hue: 58,  spin: 6,  eyes: "scanning" },
  coding:        { hue: 137, spin: 11, eyes: "focused" },
  creating:      { hue: 306, spin: 8,  eyes: "bright" },
  communicating: { hue: 209, spin: 10, eyes: "calm" },
  learning:      { hue: 47,  spin: 18, eyes: "attentive" },
  reasoning:     { hue: 270, spin: 7,  eyes: "focused" },
  sleeping:      { hue: 210, spin: 40, eyes: "closed" },
};

const SPECIALIST_IDS = ["aris", "tosin", "stark", "zeal", "titan", "apex", "nova", "hermes_comm", "oracle", "atlas", "ultron", "kate", "helios"];

let stylesInjected = false;
function injectStyles() {
  if (stylesInjected) return;
  stylesInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    #orb-simple {
      position: fixed; top: 50%; left: 50%; width: 220px; height: 220px;
      transform: translate(-50%, -50%); z-index: 0; pointer-events: none;
    }
    #orb-simple .orb-halo {
      position: absolute; inset: -34px; border-radius: 50%;
      background: radial-gradient(circle, hsl(var(--orb-hue) 90% 60% / 0.28), transparent 70%);
      /* No blur filter: a radial gradient to transparent is already soft,
         and filter:blur forces an offscreen raster pass every time this
         layer is invalidated. Same look, no per-frame filter cost. */
      transition: background .6s ease;
    }
    #orb-simple .orb-particles {
      position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;
    }
    #orb-simple.lite .orb-halo { filter: none; opacity: 0.6; }
    #orb-simple .orb-ring {
      position: absolute; inset: -8px; border-radius: 50%;
      border: 1px solid hsl(var(--orb-hue) 90% 70% / 0.35);
      /* The idle companion is visible all day.  Keep its glow and particles
         alive, but do not continuously composite a decorative ring until
         ZENO is actually doing work. */
      animation: none;
    }
    #orb-simple.orb-motion:not(.lite) .orb-ring { animation: orb-spin var(--orb-spin, 20s) linear infinite; }
    /* The glow lives on its OWN static layer, separate from the element
       that breathes. box-shadow is PAINTED, not composited: when it sat on
       .orb-core, every frame of the scale animation forced the compositor
       to re-rasterize an 80px-blur shadow. Measured 2026-08-05 as sustained
       GPU-process load at idle in WebView2. Split like this the shadow is
       rasterized once and merely composited, and the glow looks identical. */
    #orb-simple .orb-glow {
      position: absolute; inset: 22px; border-radius: 50%;
      box-shadow: 0 0 30px hsl(var(--orb-hue) 90% 58% / 0.52), 0 0 64px hsl(var(--orb-hue) 90% 55% / 0.24);
      transition: box-shadow .6s ease;
      pointer-events: none;
    }
    #orb-simple.energy-on .orb-glow {
      box-shadow: 0 0 46px hsl(var(--orb-hue) 95% 62% / 0.75), 0 0 110px hsl(var(--orb-hue) 90% 58% / 0.45);
    }
    #orb-simple .orb-core {
      position: absolute; inset: 22px; border-radius: 50%;
      background:
        radial-gradient(circle at 34% 28%, hsl(var(--orb-hue) 95% 80%), hsl(var(--orb-hue) 85% 56%) 45%, hsl(var(--orb-hue) 70% 28%) 78%, transparent 100%);
      animation: none;
      /* Own compositing layer so the breathe animation is a GPU transform
         rather than a repaint of the gradient beneath it. */
      will-change: transform;
      transition: background .6s ease;
    }
    #orb-simple.orb-motion:not(.lite) .orb-core { animation: orb-breathe 3.6s ease-in-out infinite; }
    #orb-simple .orb-core.pulse-burst { animation: orb-pulse-burst .5s ease-out; }
    #orb-simple.orb-motion:not(.lite) .orb-core.pulse-burst { animation: orb-breathe 3.6s ease-in-out infinite, orb-pulse-burst .5s ease-out; }
    @keyframes orb-breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.045); } }

    /* --- expressive eyes -------------------------------------------
       Two CSS shapes inside the core. An expression is ONE class swap
       on the container -- no render loop, no per-frame JS, so this adds
       nothing to the frame budget the orb rewrite bought back. Blinks
       are a short class toggle on a random timer, not an animation
       running constantly. */
    #orb-simple .orb-eyes {
      position: absolute; inset: 0; display: flex; align-items: center;
      justify-content: center; gap: 22%; pointer-events: none;
      transition: transform .5s ease;
    }
    #orb-simple .orb-eye {
      width: 13%; height: 22%; border-radius: 50%;
      background: rgba(6, 12, 24, 0.82);
      box-shadow: inset 0 -12% 18% rgba(255,255,255,0.25),
                  0 0 8px hsl(var(--orb-hue) 90% 70% / 0.5);
      transition: height .32s cubic-bezier(.3,.8,.3,1), width .32s ease,
                  transform .4s ease, opacity .3s ease, border-radius .3s ease;
    }
    /* blink: collapse height only -- cheapest possible, and it reads right */
    #orb-simple.blinking .orb-eye { height: 2.5%; }

    /* expressions */
    #orb-simple.eyes-calm .orb-eye       { height: 20%; }
    #orb-simple.eyes-attentive .orb-eye  { height: 27%; width: 14%; }
    #orb-simple.eyes-focused .orb-eye    { height: 11%; width: 15%; border-radius: 40%; }
    #orb-simple.eyes-scanning .orb-eye   { height: 16%; animation: orb-scan 1.5s ease-in-out infinite; }
    #orb-simple.eyes-bright .orb-eye     { height: 26%; box-shadow: inset 0 -12% 18% rgba(255,255,255,.4), 0 0 14px hsl(var(--orb-hue) 95% 75% / .85); }
    #orb-simple.eyes-concerned .orb-eye:first-child { transform: rotate(11deg); }
    #orb-simple.eyes-concerned .orb-eye:last-child  { transform: rotate(-11deg); }
    #orb-simple.eyes-closed .orb-eye     { height: 2.5%; opacity: .75; }
    /* Only the searching state animates the eyes, and only while it lasts. */
    @keyframes orb-scan {
      0%, 100% { transform: translateX(-14%); }
      50%      { transform: translateX(14%); }
    }
    @media (prefers-reduced-motion: reduce) {
      #orb-simple .orb-eye { animation: none !important; }
    }
    @keyframes orb-spin { to { transform: rotate(360deg); } }
    @keyframes orb-pulse-burst { 0% { filter: brightness(1); } 30% { filter: brightness(1.55); } 100% { filter: brightness(1); } }
    @media (prefers-reduced-motion: reduce) {
      #orb-simple .orb-core, #orb-simple .orb-ring { animation: none; }
    }
  `;
  document.head.appendChild(style);
}

export function initOrb(canvas) {
  injectStyles();
  // The canvas element stays in the DOM (index.html references it) but
  // renders nothing now -- hidden, zero cost.
  if (canvas) canvas.style.display = "none";

  const root = document.createElement("div");
  root.id = "orb-simple";
  root.innerHTML = `<div class="orb-halo"></div><canvas class="orb-particles" width="220" height="220"></canvas><div class="orb-ring"></div><div class="orb-glow"></div>`
    + `<div class="orb-core"><div class="orb-eyes">`
    + `<div class="orb-eye"></div><div class="orb-eye"></div></div></div>`;
  (canvas && canvas.parentNode ? canvas.parentNode : document.body).appendChild(root);
  const core = root.querySelector(".orb-core");
  const particleCanvas = root.querySelector(".orb-particles");
  const particleContext = particleCanvas.getContext("2d", { alpha: true });

  let currentHue = STATES.idle.hue;
  root.style.setProperty("--orb-hue", String(currentHue));
  root.style.setProperty("--orb-spin", STATES.idle.spin + "s");

  let currentEyes = "calm";
  let currentState = "idle";
  root.classList.add("orb-idle");
  function setEyes(expression) {
    if (expression === currentEyes) return;
    root.classList.remove("eyes-" + currentEyes);
    currentEyes = expression;
    root.classList.add("eyes-" + currentEyes);
    if (currentEyes === "closed") setEyeOffset(0, 0);
  }
  root.classList.add("eyes-calm");

  function setState(name) {
    const s = STATES[name] || STATES.idle;
    const nextState = STATES[name] ? name : "idle";
    root.classList.remove("orb-" + currentState);
    currentState = nextState;
    root.classList.add("orb-" + currentState);
    // Idle and waiting are deliberately low-motion states.  Their static
    // glow plus low-rate particles keep ZENO visibly present without a
    // permanent compositor workload in the Windows overlay.
    root.classList.toggle("orb-motion", currentState !== "idle" && currentState !== "waiting");
    currentHue = s.hue;
    root.style.setProperty("--orb-hue", String(currentHue));
    root.style.setProperty("--orb-spin", s.spin + "s");
    setEyes(s.eyes || "calm");
    setParticleCount({ idle: 12, listening: 22, understanding: 24, thinking: 30,
      acting: 32, waiting: 12, success: 18, processing: 30, speaking: 24,
      error: 12, searching: 28, coding: 30, creating: 26, communicating: 22,
      learning: 24, reasoning: 30, sleeping: 10 }[name] || 14);
  }

  // One small canvas and a fixed object pool: no particle DOM nodes, no
  // allocations or physics in the draw path, no blur filter.  Idle redraws
  // at 8fps; meaningful active states use 20fps only in this 220px area.
  const particles = Array.from({ length: 40 }, (_v, i) => ({
    phase: (i * 2.399) % (Math.PI * 2), radius: 32 + (i % 7) * 9,
    speed: 0.00022 + (i % 5) * 0.000035, size: 0.8 + (i % 3) * 0.45,
  }));
  let particleCount = 12;
  let particleTimer = null;      // rAF handle (kept as the audit's liveness flag)
  let particleActive = true;
  let lastParticleDraw = 0;
  // Driven by requestAnimationFrame, NOT setTimeout. This is the fix for
  // WebView2 lag while minimised (2026-08-05): `visibilitychange` does not
  // reliably fire for a minimised WebView2 desktop window the way it does
  // for a background browser tab, so a setTimeout loop kept repainting this
  // canvas at 30-40fps behind a hidden window. rAF is issued by the
  // compositor, so it stops on its own the moment nothing is being
  // composited -- minimised, occluded or hidden -- and resumes instantly.
  // The frame-rate cap below is preserved, so the visual result is
  // unchanged; only the wasted off-screen work goes away.
  function drawParticles(now) {
    particleTimer = null;
    if (!particleActive || document.visibilityState !== "visible") return;
    // The always-visible Mini Orb does not need 30/40fps canvas work.  An
    // 8fps idle drift remains visibly alive; active work gets 20fps while
    // still staying well below the 60fps compositor budget.
    lastParticleDraw = now;
    particleContext.clearRect(0, 0, 220, 220);
    particleContext.fillStyle = `hsl(${currentHue} 92% 78%)`;
    for (let i = 0; i < particleCount; i++) {
      const p = particles[i];
      const angle = p.phase + now * p.speed;
      const x = 110 + Math.cos(angle) * p.radius;
      const y = 110 + Math.sin(angle * 1.17) * p.radius;
      particleContext.globalAlpha = 0.22 + (i % 4) * 0.12;
      particleContext.beginPath();
      particleContext.arc(x, y, p.size, 0, Math.PI * 2);
      particleContext.fill();
    }
    particleContext.globalAlpha = 1;
    scheduleParticleFrame();
  }
  // setTimeout picks the CADENCE (8/20fps -- particles don't need 60), then
  // one rAF aligns the actual draw to vsync. The rAF is what makes this
  // self-suspending: a minimised WebView2 window is never composited, so the
  // frame callback never fires and no canvas work happens. Scheduling the
  // draw directly on rAF would instead wake 60x/sec just to skip most frames.
  function scheduleParticleFrame() {
    if (!particleActive) { particleTimer = null; return; }
    const gap = particleCount > 20 ? 50 : 125;
    particleTimer = setTimeout(() => {
      particleTimer = requestAnimationFrame(drawParticles);
    }, gap);
  }
  function startParticles() {
    if (!particleActive) return;
    // ALWAYS clear first rather than bailing when a handle exists. When the
    // window is hidden the loop parks on a requestAnimationFrame that the
    // compositor never fires, so the handle stays non-null for ever; a
    // "already running" early-return then left particles permanently dead
    // after the first minimise. Caught in testing 2026-08-05.
    stopParticleLoop();
    scheduleParticleFrame();
  }
  function stopParticleLoop() {
    if (particleTimer === null) return;
    // The handle is either a timeout id or a rAF id depending on which half
    // of the cycle we're in; clearing both is cheap and unambiguous.
    clearTimeout(particleTimer);
    cancelAnimationFrame(particleTimer);
    particleTimer = null;
  }
  function setParticleCount(count) {
    particleCount = Math.max(0, Math.min(particles.length, count));
    startParticles();
  }
  function setParticlesActive(on) {
    particleActive = !!on;
    if (!particleActive) {
      stopParticleLoop();
      particleContext.clearRect(0, 0, 220, 220);
    } else startParticles();
  }
  startParticles();

  // Blink on a random human-ish cadence (3-8s). setTimeout, not rAF: this
  // is two class toggles a few times a minute, so it costs nothing at rest
  // and stops entirely when the orb is switched off or the tab is hidden.
  let blinkTimer = null;
  function scheduleBlink() {
    clearTimeout(blinkTimer);
    blinkTimer = setTimeout(() => {
      // Don't blink while the eyes are already closed (sleeping) or
      // deliberately narrowed mid-thought -- it reads as a glitch.
      if (currentEyes !== "closed" && document.visibilityState === "visible") {
        root.classList.add("blinking");
        setTimeout(() => root.classList.remove("blinking"), 130);
        // Occasional double blink -- small thing, but it's what stops it
        // looking metronomic.
        if (Math.random() < 0.22) {
          setTimeout(() => {
            root.classList.add("blinking");
            setTimeout(() => root.classList.remove("blinking"), 110);
          }, 240);
        }
      }
      scheduleBlink();
    }, 3000 + Math.random() * 5000);
  }
  scheduleBlink();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") { scheduleBlink(); setParticlesActive(true); }
    else {
      // Blink still needs an explicit stop: setTimeout keeps firing behind a
      // hidden window, unlike the rAF-driven particle loop which the
      // compositor suspends on its own.
      clearTimeout(blinkTimer); blinkTimer = null;
      setParticlesActive(false);
    }
  });

  // Cursor eyes intentionally have no permanent animation loop. Pointer
  // events merely coalesce into one capped compositor transform, then one
  // delayed neutral return. That is smoother than direct DOM writes yet does
  // no work while the cursor is still, the orb is hidden, sleeping or the
  // performance profile says the machine is under pressure.
  const eyesLayer = root.querySelector(".orb-eyes");
  let eyeTrackingEnabled = false;
  let eyeTrackingFps = "auto";
  let eyePerformanceMode = "auto";
  let eyeUpdateTimer = null;
  let eyeNeutralTimer = null;
  let pendingPointer = null;
  let lastEyeX = 0, lastEyeY = 0;
  function effectiveEyeFps() {
    if (eyeTrackingFps === "15" || eyeTrackingFps === "30") return Number(eyeTrackingFps);
    return eyePerformanceMode === "low_power" || root.classList.contains("lite") ? 15 : 30;
  }
  function eyesMayTrack() {
    return eyeTrackingEnabled && root.style.display !== "none"
      && document.visibilityState === "visible" && currentEyes !== "closed";
  }
  function setEyeOffset(x, y) {
    if (!eyesLayer) return;
    // Less than a quarter pixel is invisible, so avoid a compositor update.
    if (Math.abs(x - lastEyeX) < 0.25 && Math.abs(y - lastEyeY) < 0.25) return;
    lastEyeX = x; lastEyeY = y;
    eyesLayer.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`;
  }
  function applyCursorEyes() {
    eyeUpdateTimer = null;
    if (!eyesMayTrack() || !pendingPointer) return;
    const point = pendingPointer;
    pendingPointer = null;
    const cx = window.innerWidth / 2, cy = window.innerHeight / 2;
    const x = Math.max(-1, Math.min(1, (point.x - cx) / Math.max(1, cx))) * 3.4;
    const y = Math.max(-1, Math.min(1, (point.y - cy) / Math.max(1, cy))) * 2.4;
    setEyeOffset(x, y);
  }
  function queueCursorEyes(event) {
    if (!eyesMayTrack()) return;
    pendingPointer = { x: event.clientX, y: event.clientY };
    if (eyeUpdateTimer === null) {
      eyeUpdateTimer = setTimeout(applyCursorEyes, Math.round(1000 / effectiveEyeFps()));
    }
    clearTimeout(eyeNeutralTimer);
    eyeNeutralTimer = setTimeout(() => { pendingPointer = null; setEyeOffset(0, 0); }, 850);
  }
  window.addEventListener("pointermove", queueCursorEyes, { passive: true });
  function setEyeTracking(options = {}) {
    eyeTrackingEnabled = !!options.enabled;
    eyeTrackingFps = String(options.fps || "auto");
    eyePerformanceMode = String(options.performanceMode || "auto");
    if (!eyesMayTrack()) {
      clearTimeout(eyeUpdateTimer); eyeUpdateTimer = null;
      clearTimeout(eyeNeutralTimer); eyeNeutralTimer = null;
      pendingPointer = null; setEyeOffset(0, 0);
    }
  }

  function pulse() {
    core.classList.remove("pulse-burst");
    // Force reflow so re-adding the class restarts the animation even if
    // called twice in quick succession.
    void core.offsetWidth;
    core.classList.add("pulse-burst");
    setTimeout(() => core.classList.remove("pulse-burst"), 550);
  }

  function setPerformanceMode(lite) {
    root.classList.toggle("lite", !!lite);
  }

  let agentEnergy = 0;
  // Energy now toggles on the ROOT so the static .orb-glow layer changes,
  // not the breathing core -- keeps the glow off the animated element.
  function dispatchAgent(_id) { pulse(); agentEnergy = 1; root.classList.add("energy-on"); }
  function setAgentWorking(_id, working) {
    agentEnergy = working ? 1 : 0;
    root.classList.toggle("energy-on", agentEnergy > 0);
  }
  function getAgentScreenPositions() { return []; }

  function setActive(on) {
    root.style.display = on ? "block" : "none";
    // Stop the blink timer when the orb is off -- "off" should mean zero
    // work, which is the whole reason the WebGL orb was replaced.
    if (on) scheduleBlink();
    else clearTimeout(blinkTimer);
    setParticlesActive(on);
    if (!on) setEyeOffset(0, 0);
  }

  return {
    setState,
    pulse,
    setPerformanceMode,
    setActive,
    dispatchAgent,
    setAgentWorking,
    getAgentScreenPositions,
    setEyes,                      // manual override, e.g. sleeping/dream mode
    setEyeTracking,
    blink: () => {
      root.classList.add("blinking");
      setTimeout(() => root.classList.remove("blinking"), 130);
    },
    auditMetrics: () => ({ particle_loop: particleTimer !== null, blink_timer: blinkTimer !== null,
      eye_tracking_timer: eyeUpdateTimer !== null }),
    specialists: SPECIALIST_IDS.slice(),
  };
}
