// ZENO phone touch-mouse. Turns the phone into a trackpad for the laptop's OS
// cursor via the authenticated /api/remote/* endpoints. Mouse ONLY -- there is
// no keyboard path here by design.
//
// Activates only on a phone-sized/touch client (or ?view=phone). It reuses the
// phone's existing authenticated session (cookie), so the pointer endpoints
// stay owner-only. Control mode defaults to PANEL (watch + tap panels); the
// user explicitly switches to MOUSE to drive the OS cursor; the laptop can cut
// it instantly with the desktop emergency stop.

const isPhone = () =>
  new URLSearchParams(location.search).get("view") === "phone" ||
  (("ontouchstart" in window) && Math.min(screen.width, screen.height) <= 820);

const SENS = 1.6;                 // trackpad sensitivity
const MOVE_MS = 40;               // coalesce moves to ~25/s on the wire

async function api(path, body) {
  try {
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin", body: JSON.stringify(body || {}),
    });
    return await r.json().catch(() => ({ ok: r.ok }));
  } catch (_e) { return { ok: false, detail: "offline" }; }
}

export function initPhoneMouse() {
  if (!isPhone()) return;
  const style = document.createElement("style");
  style.textContent = `
    #zp-phone{position:fixed;left:0;right:0;bottom:0;z-index:9500;
      font-family:system-ui,Segoe UI,sans-serif;color:#dff6ff;
      background:linear-gradient(180deg,rgba(6,18,26,.5),rgba(4,12,20,.98));
      border-top:1px solid rgba(64,196,255,.35);padding:8px 10px 14px;
      backdrop-filter:blur(6px);}
    #zp-phone .row{display:flex;gap:8px;align-items:center;margin-bottom:8px;font-size:12px;}
    #zp-phone .dot{width:8px;height:8px;border-radius:50%;background:#39d98a;}
    #zp-phone .dot.off{background:#ff6b6b;}
    #zp-phone .modes{display:flex;gap:6px;margin-left:auto;}
    #zp-phone button{background:rgba(64,196,255,.1);border:1px solid rgba(64,196,255,.3);
      color:#dff6ff;border-radius:8px;padding:5px 10px;font-size:12px;}
    #zp-phone button.on{background:#40c4ff;color:#04121c;font-weight:600;}
    #zp-phone .pad{height:34vh;border:1px dashed rgba(64,196,255,.35);border-radius:12px;
      background:rgba(64,196,255,.04);display:flex;align-items:center;justify-content:center;
      color:rgba(223,246,255,.4);font-size:13px;touch-action:none;user-select:none;}
    #zp-phone .estop{background:rgba(255,107,107,.15);border-color:rgba(255,107,107,.5);color:#ffb3b3;}`;
  document.head.appendChild(style);

  const el = document.createElement("div");
  el.id = "zp-phone";
  el.innerHTML = `
    <div class="row">
      <span class="dot" id="zp-dot"></span><span id="zp-status">connecting…</span>
      <span class="modes">
        <button data-mode="view">View</button>
        <button data-mode="panel" class="on">Panel</button>
        <button data-mode="mouse">Mouse</button>
        <button class="estop" id="zp-estop">Stop</button>
      </span>
    </div>
    <div class="pad" id="zp-pad">Trackpad — drag to move · tap to click · two fingers to scroll</div>`;
  document.body.appendChild(el);

  const statusEl = el.querySelector("#zp-status");
  const dot = el.querySelector("#zp-dot");
  const pad = el.querySelector("#zp-pad");
  let mode = "panel";
  let cursor = { x: 0.5, y: 0.5 };
  let lastMove = 0;

  function setMode(m) {
    mode = m;
    el.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    api("/api/remote/control", { action: "mode", mode: m }).then(refresh);
  }
  el.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  el.querySelector("#zp-estop").onclick = () =>
    api("/api/remote/control", { action: "stop" }).then(() => { setMode("view"); });

  async function refresh() {
    const s = await fetch("/api/remote/control", { credentials: "same-origin" })
      .then((r) => r.json()).catch(() => null);
    if (!s) { statusEl.textContent = "view only (sign in on phone)"; dot.classList.add("off"); return; }
    dot.classList.toggle("off", !s.enabled);
    statusEl.textContent = s.enabled ? (s.mode === "mouse" ? "CONTROL ACTIVE" : "connected") : "control disabled";
  }
  refresh(); setInterval(refresh, 5000);

  // --- touch handling (trackpad) --------------------------------------
  let touchStart = null, moved = false, lastTap = 0, longTimer = null, twoFinger = false;

  pad.addEventListener("touchstart", (e) => {
    if (mode !== "mouse") return;
    twoFinger = e.touches.length >= 2;
    touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
    moved = false;
    if (!twoFinger) longTimer = setTimeout(() => {
      if (!moved) { api("/api/remote/pointer", { action: "right", nx: cursor.x, ny: cursor.y }); moved = true; }
    }, 500);
  }, { passive: true });

  pad.addEventListener("touchmove", (e) => {
    if (mode !== "mouse" || !touchStart) return;
    const dx = e.touches[0].clientX - touchStart.x;
    const dy = e.touches[0].clientY - touchStart.y;
    if (Math.abs(dx) + Math.abs(dy) > 6) { moved = true; clearTimeout(longTimer); }
    if (e.touches.length >= 2) {                 // two-finger scroll
      if (Math.abs(dy) > 4) { api("/api/remote/pointer", { action: "scroll", amount: dy > 0 ? -1 : 1 }); touchStart.y = e.touches[0].clientY; }
      return;
    }
    cursor.x = Math.max(0, Math.min(1, cursor.x + (dx / pad.clientWidth) * SENS));
    cursor.y = Math.max(0, Math.min(1, cursor.y + (dy / pad.clientHeight) * SENS));
    touchStart.x = e.touches[0].clientX; touchStart.y = e.touches[0].clientY;
    const now = Date.now();
    if (now - lastMove > MOVE_MS) { lastMove = now; api("/api/remote/pointer", { action: "move", nx: cursor.x, ny: cursor.y }); }
  }, { passive: true });

  pad.addEventListener("touchend", () => {
    if (mode !== "mouse") return;
    clearTimeout(longTimer);
    if (touchStart && !moved && !twoFinger) {     // tap -> click (double if quick)
      const now = Date.now();
      const action = now - lastTap < 300 ? "double" : "click";
      api("/api/remote/pointer", { action, nx: cursor.x, ny: cursor.y });
      lastTap = now;
    }
    touchStart = null; twoFinger = false;
  }, { passive: true });
}
