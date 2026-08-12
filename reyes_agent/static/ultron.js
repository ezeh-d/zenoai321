/* ULTRON — ZENO's serious-mode HUD.
 *
 * WHAT THIS IS NOT: a second application, a second agent list, or a second
 * source of truth. It is a skin over the SAME dashboard, and every value it
 * shows is fetched from the backend. The page cannot put itself into serious
 * mode; it asks /api/mode what the mode IS and renders that. A HUD that could
 * decide its own mode would happily show a crimson tactical display over an
 * assistant behaving perfectly normally, which is a lie about the system it
 * is supposed to be displaying.
 *
 * NO FABRICATED TELEMETRY. Every panel renders "N/A" or "NO ACTIVE MISSION"
 * when the backend has nothing. A HUD that invents 72% progress to look busy
 * is worse than an empty one, because an empty panel is information and an
 * invented number is noise that a supervisor might ask about.
 *
 * PERFORMANCE IS A FEATURE HERE. The owner's project is judged on how smooth
 * ZENO feels, and a GUI that costs frames costs the thing being demonstrated.
 * So: one canvas, one rAF loop, no particle fields, no shaders. The loop
 * stops entirely when the tab is hidden or the mode is off -- an idle HUD
 * should cost nothing at all.
 */
(() => {
  'use strict';

  const RED = '#FF3038', CYAN = '#00CFFF', DIM = '#5A6070';
  const POLL_MS = 1200;              // state; events arrive on the bus
  let mode = 'NORMAL', raf = 0, poll = 0, quality = 'MEDIUM';
  let runtime = {}, events = [], booted = 0;

  /* ---- quality: measured, not guessed ------------------------------- */
  function pickQuality() {
    const want = (window.ZENO_ULTRON_QUALITY || 'AUTO').toUpperCase();
    if (want !== 'AUTO') return want;
    const cores = navigator.hardwareConcurrency || 2;
    const mem = navigator.deviceMemory || 4;
    if (cores <= 2 || mem <= 2) return 'LOW';
    if (cores >= 8 && mem >= 8) return 'HIGH';
    return 'MEDIUM';
  }

  /* ---- the core ------------------------------------------------------ */
  function drawCore(ctx, w, h, t, state, level) {
    const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.34;
    ctx.clearRect(0, 0, w, h);

    // State drives the motion. Nothing here is decorative-only: if the rings
    // are counter-rotating, ZENO is actually thinking.
    const speed = { IDLE: 0.10, LISTENING: 0.22, THINKING: 0.55,
                    SPEAKING: 0.34, ERROR: 0.8 }[state] ?? 0.14;
    const glow  = { IDLE: 0.35, LISTENING: 0.7, THINKING: 0.6,
                    SPEAKING: 0.55 + level * 0.45, ERROR: 0.9 }[state] ?? 0.4;

    // outer targeting ring
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * speed);
    ctx.strokeStyle = RED;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1.5;
    for (let i = 0; i < 8; i++) {
      ctx.beginPath();
      ctx.arc(0, 0, r, (i / 8) * Math.PI * 2, (i / 8) * Math.PI * 2 + 0.55);
      ctx.stroke();
    }
    ctx.restore();

    // inner ring, counter-rotating while thinking
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-t * speed * 1.6);
    ctx.strokeStyle = state === 'THINKING' ? CYAN : RED;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.72, 0, Math.PI * 1.5);
    ctx.stroke();
    ctx.restore();

    // radial ticks -- cheap, and they read as instrumentation
    if (level >= 0 && quality !== 'LOW') {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.strokeStyle = DIM;
      ctx.globalAlpha = 0.55;
      const ticks = quality === 'HIGH' ? 48 : 24;
      for (let i = 0; i < ticks; i++) {
        const a = (i / ticks) * Math.PI * 2;
        const inner = r * 1.06, outer = r * (i % 6 === 0 ? 1.16 : 1.10);
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * inner, Math.sin(a) * inner);
        ctx.lineTo(Math.cos(a) * outer, Math.sin(a) * outer);
        ctx.stroke();
      }
      ctx.restore();
    }

    // the eye
    const pulse = 1 + Math.sin(t * 2.2) * 0.05;
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 0.5 * pulse);
    grad.addColorStop(0, `rgba(255,255,255,${0.75 * glow})`);
    grad.addColorStop(0.35, `rgba(255,48,56,${0.85 * glow})`);
    grad.addColorStop(1, 'rgba(255,48,56,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 0.5 * pulse, 0, Math.PI * 2);
    ctx.fill();

    // scanning sweep while verifying
    if (state === 'VERIFYING') {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(t * 2.2);
      ctx.strokeStyle = CYAN;
      ctx.globalAlpha = 0.6;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(r * 0.95, 0);
      ctx.stroke();
      ctx.restore();
    }
  }

  /* One frame, regardless of visibility. Used when the mode turns on and on
     becoming visible again: without it, activating Ultron while the window is
     backgrounded leaves a blank canvas until the first animation tick, and
     the owner switches to the tab to find nothing there. */
  function renderFrame() {
    const canvas = document.getElementById('ultron-core');
    if (!canvas) return false;
    drawCore(canvas.getContext('2d'), canvas.width, canvas.height,
             (performance.now() - booted) / 1000,
             String(runtime.activity_state || 'IDLE').toUpperCase(),
             Number(runtime.audio_level || 0));
    return true;
  }

  function loop() {
    const canvas = document.getElementById('ultron-core');
    if (!canvas || mode !== 'ULTRON' || document.hidden) { raf = 0; return; }
    const ctx = canvas.getContext('2d');
    const t = (performance.now() - booted) / 1000;
    const level = Number(runtime.audio_level || 0);
    drawCore(ctx, canvas.width, canvas.height,
             t, String(runtime.activity_state || 'IDLE').toUpperCase(), level);
    // LOW quality halves the frame rate rather than dropping the visual.
    raf = quality === 'LOW'
      ? setTimeout(() => requestAnimationFrame(loop), 33)
      : requestAnimationFrame(loop);
  }

  /* ---- panels -------------------------------------------------------- */
  const esc = s => String(s ?? '').replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function renderMission() {
    const box = document.getElementById('ultron-mission');
    if (!box) return;
    const task = runtime.current_task;
    if (!task) {
      // Honest emptiness. An invented mission is worse than none.
      box.innerHTML = '<div class="u-empty">NO ACTIVE MISSION</div>';
      return;
    }
    const rows = [
      ['MISSION', task], ['OWNER', runtime.master || 'ZENO'],
      ['MODE', runtime.mode], ['AGENT', runtime.active_agent],
      ['SUB-AGENT', runtime.active_sub_agent], ['WORKER', runtime.active_worker],
      ['TOOL', runtime.current_tool], ['STATE', runtime.activity_state],
      ['ELAPSED', runtime.elapsed_s ? runtime.elapsed_s + 's' : ''],
    ].filter(([, v]) => v);
    box.innerHTML = rows.map(([k, v]) =>
      `<div class="u-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
  }

  function renderEvents() {
    const box = document.getElementById('ultron-events');
    if (!box) return;
    if (!events.length) {
      box.innerHTML = '<div class="u-empty">NO EVENTS YET</div>';
      return;
    }
    box.innerHTML = events.slice(-14).reverse().map(e =>
      `<div class="u-evt"><span>${esc(e.at)}</span>${esc(e.type)}</div>`).join('');
  }

  /* ---- state: fetched, never assumed --------------------------------- */
  async function refresh() {
    try {
      const data = await (await fetch('/api/mode')).json();
      const was = mode;
      mode = data.mode || 'NORMAL';
      runtime = data.runtime || {};
      if (mode !== was) applyMode(mode);
      if (mode === 'ULTRON') { renderMission(); renderEvents(); }
    } catch { /* a failed poll must not break the page */ }
  }

  function applyMode(next) {
    document.documentElement.classList.toggle('ultron', next === 'ULTRON');
    const hud = document.getElementById('ultron-hud');
    if (hud) hud.classList.toggle('hide', next !== 'ULTRON');
    if (next === 'ULTRON') {
      booted = performance.now();
      quality = pickQuality();
      const canvas = document.getElementById('ultron-core');
      if (canvas && !canvas.width) { canvas.width = 340; canvas.height = 340; }
      renderFrame();                       // never leave the HUD blank
      if (!raf) requestAnimationFrame(loop);
    } else if (raf) {
      cancelAnimationFrame(raf); clearTimeout(raf); raf = 0;
    }
  }

  function onEvent(type, payload) {
    if (!type) return;
    if (type === 'assistant.mode_changed') { refresh(); return; }
    if (mode !== 'ULTRON') return;
    const interesting = /^(agent|remote_mic|voice|conversation|tool|task)\./.test(type);
    if (!interesting) return;
    events.push({ at: new Date().toLocaleTimeString(), type: type.toUpperCase(),
                  payload });
    if (events.length > 60) events = events.slice(-40);
    renderEvents();
  }

  // Stop everything when the tab is hidden. An idle HUD should cost nothing.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { if (raf) { cancelAnimationFrame(raf); raf = 0; } }
    else if (mode === 'ULTRON' && !raf) { renderFrame(); requestAnimationFrame(loop); }
  });

  window.zenoUltron = {
    refresh, onEvent, renderFrame,
    mode: () => mode,
    state: () => ({ mode, quality, runtime, events: events.length }),
    async set(next) {
      // Asks the BACKEND. The page never flips its own mode.
      await fetch('/api/mode', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: next }) });
      return refresh();
    },
  };

  refresh();
  poll = setInterval(refresh, POLL_MS);
})();
