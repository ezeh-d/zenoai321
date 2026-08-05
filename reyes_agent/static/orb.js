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
      filter: blur(8px);
      transition: background-color .6s ease;
    }
    #orb-simple .orb-particles {
      position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;
    }
    #orb-simple.lite .orb-halo { filter: none; opacity: 0.6; }
    #orb-simple .orb-ring {
      position: absolute; inset: -8px; border-radius: 50%;
      border: 1px solid hsl(var(--orb-hue) 90% 70% / 0.35);
      animation: orb-spin var(--orb-spin, 20s) linear infinite;
    }
    #orb-simple.lite .orb-ring { animation: none; }
    #orb-simple .orb-core {
      position: absolute; inset: 22px; border-radius: 50%;
      background:
        radial-gradient(circle at 34% 28%, hsl(var(--orb-hue) 95% 80%), hsl(var(--orb-hue) 85% 56%) 45%, hsl(var(--orb-hue) 70% 28%) 78%, transparent 100%);
      box-shadow: 0 0 34px hsl(var(--orb-hue) 90% 58% / 0.55), 0 0 80px hsl(var(--orb-hue) 90% 55% / 0.30);
      animation: orb-breathe 3.6s ease-in-out infinite;
      transition: background .6s ease, box-shadow .6s ease;
    }
    #orb-simple .orb-core.energy {
      box-shadow: 0 0 46px hsl(var(--orb-hue) 95% 62% / 0.75), 0 0 110px hsl(var(--orb-hue) 90% 58% / 0.45);
    }
    #orb-simple .orb-core.pulse-burst { animation: orb-breathe 3.6s ease-in-out infinite, orb-pulse-burst .5s ease-out; }
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
  root.innerHTML = `<div class="orb-halo"></div><canvas class="orb-particles" width="220" height="220"></canvas><div class="orb-ring"></div>`
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
  function setEyes(expression) {
    if (expression === currentEyes) return;
    root.classList.remove("eyes-" + currentEyes);
    currentEyes = expression;
    root.classList.add("eyes-" + currentEyes);
  }
  root.classList.add("eyes-calm");

  function setState(name) {
    const s = STATES[name] || STATES.idle;
    currentHue = s.hue;
    root.style.setProperty("--orb-hue", String(currentHue));
    root.style.setProperty("--orb-spin", s.spin + "s");
    setEyes(s.eyes || "calm");
    setParticleCount({ idle: 16, listening: 24, processing: 34, speaking: 28,
      error: 14, searching: 32, coding: 34, creating: 30, communicating: 24,
      learning: 28, reasoning: 34, sleeping: 12 }[name] || 16);
  }

  // One small canvas and a fixed object pool: no particle DOM nodes, no
  // allocations or physics in the draw path, no blur filter.  Idle redraws
  // at 30fps; meaningful active states use 40fps only in this 220px area.
  const particles = Array.from({ length: 40 }, (_v, i) => ({
    phase: (i * 2.399) % (Math.PI * 2), radius: 32 + (i % 7) * 9,
    speed: 0.00022 + (i % 5) * 0.000035, size: 0.8 + (i % 3) * 0.45,
  }));
  let particleCount = 16;
  let particleTimer = null;
  let particleActive = true;
  function drawParticles(now) {
    particleTimer = null;
    if (!particleActive || document.visibilityState !== "visible") return;
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
    particleTimer = setTimeout(() => drawParticles(performance.now()), particleCount > 20 ? 25 : 33);
  }
  function setParticleCount(count) {
    particleCount = Math.max(0, Math.min(particles.length, count));
    if (particleActive && particleTimer === null) drawParticles(performance.now());
  }
  function setParticlesActive(on) {
    particleActive = !!on;
    if (!particleActive) {
      clearTimeout(particleTimer); particleTimer = null;
      particleContext.clearRect(0, 0, 220, 220);
    } else if (particleTimer === null) drawParticles(performance.now());
  }
  drawParticles(performance.now());

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
    else { clearTimeout(blinkTimer); setParticlesActive(false); }
  });

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
  function dispatchAgent(_id) { pulse(); agentEnergy = 1; core.classList.add("energy"); }
  function setAgentWorking(_id, working) {
    agentEnergy = working ? 1 : 0;
    core.classList.toggle("energy", agentEnergy > 0);
  }
  function getAgentScreenPositions() { return []; }

  function setActive(on) {
    root.style.display = on ? "block" : "none";
    // Stop the blink timer when the orb is off -- "off" should mean zero
    // work, which is the whole reason the WebGL orb was replaced.
    if (on) scheduleBlink();
    else clearTimeout(blinkTimer);
    setParticlesActive(on);
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
    blink: () => {
      root.classList.add("blinking");
      setTimeout(() => root.classList.remove("blinking"), 130);
    },
    specialists: SPECIALIST_IDS.slice(),
  };
}
