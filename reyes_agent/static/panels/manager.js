// ZENO Universal Live Panel System -- the browser-side host.
//
// One UniversalPanelManager owns every panel: create/open/close/focus/minimize/
// maximize/pin/split/persist. It fetches the server registry (/api/panels/
// registry), subscribes ONCE to the existing unified event stream
// (/api/events/stream), runs the PanelDecisionEngine on tool events to surface
// the right panel, and dispatches live events to each open panel's renderer.
//
// Reuses ZENO's real infrastructure: the event bus (via SSE), the capability/
// tool -> panel maps from the server, and the per-panel data endpoints. Every
// renderer shows REAL state; a renderer that throws is isolated and never takes
// down the HUD (crash isolation, master prompt s51).
//
// Design note (s3/s48/s60): ZENO's front-end is vanilla ES modules inside a
// PyQt-hosted web view, not React/Electron. dockview (React/TS) and Electron
// WebContentsView were evaluated and rejected as architectural mismatches; this
// is a lightweight native dock manager that integrates cleanly with the stack.

import { RENDERERS } from "/static/panels/renderers.js?v=1";

const LS_KEY = "zeno.panels.layout.v1";
const AUTO_OPEN_SUPPORT = new Set(["live", "state"]); // 'planned' opens on request only

export class PanelManager {
  constructor() {
    this.panels = new Map();      // id -> {def, el, body, kind, state, renderer, cleanup}
    this.registry = null;
    this.toolPanel = {};
    this.capabilityPanel = {};
    this.host = null;
    this.dockbar = null;
    this._source = null;
    this._z = 100;
    this._seq = 0;
  }

  // -- lifecycle ---------------------------------------------------------
  async init() {
    // The laptop (loopback) is the panel HOST and broadcasts its layout; any
    // other origin (the phone over the tunnel) is a MIRROR that follows it.
    this.isHost = /^(127\.0\.0\.1|localhost|::1|\[::1\])$/.test(location.hostname);
    this._buildHost();
    try {
      this.registry = await (await fetch("/api/panels/registry")).json();
      this.toolPanel = this.registry.tool_panel || {};
      this.capabilityPanel = this.registry.capability_panel || {};
    } catch (_e) {
      this.registry = { panels: {} };
    }
    this._connectEvents();
    this._restore();
    return this;
  }

  _buildHost() {
    const wrap = document.createElement("div");
    wrap.id = "zeno-panels";
    wrap.innerHTML = `
      <div class="zp-workspace" id="zp-workspace"></div>
      <div class="zp-dockbar" id="zp-dockbar"></div>`;
    document.body.appendChild(wrap);
    this.host = wrap.querySelector("#zp-workspace");
    this.dockbar = wrap.querySelector("#zp-dockbar");
  }

  // -- events / decision engine -----------------------------------------
  _connectEvents() {
    try {
      this._source = new EventSource("/api/events/stream");
      this._source.onmessage = (m) => {
        let evt;
        try { evt = JSON.parse(m.data); } catch (_e) { return; }
        if (!this.isHost) this._mirror(evt);   // phone follows the laptop's layout
        this._route(evt);
        this._dispatch(evt);
      };
      this._source.onerror = () => {}; // EventSource auto-reconnects
    } catch (_e) { /* SSE unsupported -> manual open still works */ }
  }

  // Decide whether an event should surface a panel, and open/focus it.
  _route(evt) {
    const type = evt.type || evt.event_type || "";
    const payload = evt.payload || evt.data || {};
    if (type !== "execution.lifecycle") return;
    const tool = payload.tool || (payload.detail && payload.detail.tool) || "";
    if (!tool) return;
    const panelType = this.toolPanel[tool] || this._capForTool(tool);
    if (!panelType) return;
    const def = this.registry.panels[panelType];
    if (!def) return;
    if (!AUTO_OPEN_SUPPORT.has(def.support)) return; // planned: open on request
    this.open(panelType, { reason: `tool:${tool}`, focus: true });
  }

  _capForTool(_tool) { return null; } // server already folds capability into tool_panel

  // Host -> event bus: publish a layout change so mirrors follow (loopback-only
  // on the server; a no-op fetch from a mirror is simply refused).
  _broadcast(type, payload) {
    if (!this.isHost) return;
    try {
      fetch("/api/panels/broadcast", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, payload }),
      }).catch(() => {});
    } catch (_e) {}
  }

  // Mirror <- event bus: follow the host's panel.* layout events.
  _mirror(evt) {
    const t = evt.type || evt.event_type || "";
    const p = evt.payload || evt.data || {};
    if (t === "panel.opened" && p.type) this.open(p.type, { focus: false, mirror: true });
    else if (t === "panel.closed" && p.type) {
      const ids = this.findByType(p.type);
      if (ids.length) this.close(ids[0]);
    } else if (t === "panel.focused" && p.type) {
      const ids = this.findByType(p.type);
      if (ids.length) this.focus(ids[0]);
    }
  }

  _dispatch(evt) {
    for (const p of this.panels.values()) {
      if (p.renderer && p.renderer.event) {
        try { p.renderer.event(this._api(p), evt); }
        catch (_e) { /* one panel's event handler never breaks others */ }
      }
    }
  }

  // -- panel API (s45) ---------------------------------------------------
  open(type, opts = {}) {
    const def = (this.registry.panels || {})[type];
    if (!def) return null;
    // singleton reuse
    if (def.singleton) {
      for (const p of this.panels.values()) {
        if (p.type === type) {
          if (opts.arg !== undefined && p.renderer && p.renderer.mount) {
            try { p.renderer.mount(this._api(p), opts.arg); } catch (e) { this._panelError(p, e); }
          }
          if (opts.focus !== false) this.focus(p.id);
          return p.id;
        }
      }
    }
    const id = `${type}-${++this._seq}`;
    const el = this._frame(id, def);
    this.host.appendChild(el);
    const panel = {
      id, type, def, el,
      body: el.querySelector(".zp-body"),
      kind: def.kind, state: "initializing",
      renderer: RENDERERS[def.kind] || RENDERERS.generic,
    };
    this.panels.set(id, panel);
    this._setStatus(panel, "idle");
    try { panel.renderer.mount && panel.renderer.mount(this._api(panel), opts.arg); }
    catch (e) { this._panelError(panel, e); }
    if (opts.focus !== false) this.focus(id);
    this._persist();
    this._log("panel.created", { id, type, reason: opts.reason || "manual" });
    if (!opts.mirror) this._broadcast("panel.opened", { type });
    return id;
  }

  close(id) {
    const p = this.panels.get(id);
    if (!p) return;
    try { p.renderer.unmount && p.renderer.unmount(this._api(p)); } catch (_e) {}
    p.el.remove();
    this.panels.delete(id);
    this._pushRecent(p.type);
    this._syncDockbar();
    this._persist();
    this._log("panel.closed", { id });
    this._broadcast("panel.closed", { type: p.type });
  }

  focus(id) {
    const p = this.panels.get(id);
    if (!p) return;
    p.el.style.zIndex = String(++this._z);
    for (const q of this.panels.values()) q.el.classList.toggle("zp-active", q === p);
    if (p.el.classList.contains("zp-min")) this.restore(id);
    this._log("panel.focused", { id });
    this._broadcast("panel.focused", { type: p.type });
  }

  minimize(id) {
    const p = this.panels.get(id); if (!p) return;
    p.el.classList.add("zp-min"); p.el.classList.remove("zp-max");
    this._syncDockbar(); this._persist();
  }
  maximize(id) {
    const p = this.panels.get(id); if (!p) return;
    p.el.classList.toggle("zp-max"); p.el.classList.remove("zp-min");
    this.focus(id); this._persist();
  }
  restore(id) {
    const p = this.panels.get(id); if (!p) return;
    p.el.classList.remove("zp-min", "zp-max");
    this._syncDockbar(); this._persist();
  }
  pin(id) {
    const p = this.panels.get(id); if (!p) return;
    p.pinned = !p.pinned;
    p.el.classList.toggle("zp-pinned", p.pinned);
    p.el.querySelector(".zp-pin").textContent = p.pinned ? "★" : "☆";
    this._persist();
  }
  update(id, payload) {
    const p = this.panels.get(id); if (!p) return;
    try { p.renderer.update && p.renderer.update(this._api(p), payload); }
    catch (e) { this._panelError(p, e); }
  }
  getActive() {
    for (const p of this.panels.values())
      if (p.el.classList.contains("zp-active")) return p.id;
    return null;
  }
  findByType(type) {
    return [...this.panels.values()].filter((p) => p.type === type).map((p) => p.id);
  }
  list() {
    return [...this.panels.values()].map((p) => ({ id: p.id, type: p.type,
      status: p.state, min: p.el.classList.contains("zp-min"),
      max: p.el.classList.contains("zp-max"), pinned: !!p.pinned }));
  }

  // -- frame + header ----------------------------------------------------
  _frame(id, def) {
    const el = document.createElement("div");
    el.className = "zp-panel";
    el.dataset.id = id;
    el.innerHTML = `
      <div class="zp-head">
        <span class="zp-icon">${def.icon || "▤"}</span>
        <span class="zp-title">${def.title}</span>
        <span class="zp-status" title="status">idle</span>
        <span class="zp-spacer"></span>
        <button class="zp-pin" title="Pin">☆</button>
        <button class="zp-min-btn" title="Minimize">–</button>
        <button class="zp-max-btn" title="Maximize">▢</button>
        <button class="zp-close" title="Close">×</button>
      </div>
      <div class="zp-body"></div>`;
    const head = el.querySelector(".zp-head");
    el.addEventListener("mousedown", () => this.focus(id), true);
    el.querySelector(".zp-close").onclick = (e) => { e.stopPropagation(); this.close(id); };
    el.querySelector(".zp-min-btn").onclick = (e) => { e.stopPropagation(); this.minimize(id); };
    el.querySelector(".zp-max-btn").onclick = (e) => { e.stopPropagation(); this.maximize(id); };
    el.querySelector(".zp-pin").onclick = (e) => { e.stopPropagation(); this.pin(id); };
    this._makeDraggable(el, head);
    return el;
  }

  _makeDraggable(el, handle) {
    let sx, sy, ox, oy, moving = false;
    handle.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      moving = true; sx = e.clientX; sy = e.clientY;
      const r = el.getBoundingClientRect();
      ox = r.left; oy = r.top;
      el.classList.add("zp-float");
      document.body.style.userSelect = "none";
    });
    window.addEventListener("mousemove", (e) => {
      if (!moving) return;
      el.style.left = `${ox + e.clientX - sx}px`;
      el.style.top = `${oy + e.clientY - sy}px`;
    });
    window.addEventListener("mouseup", () => {
      if (moving) { moving = false; document.body.style.userSelect = ""; this._persist(); }
    });
  }

  // -- status / errors ---------------------------------------------------
  _setStatus(panel, status) {
    panel.state = status;
    const dot = panel.el.querySelector(".zp-status");
    if (dot) { dot.textContent = status; dot.dataset.state = status; }
  }
  _panelError(panel, err) {
    this._setStatus(panel, "error");
    if (panel.body) {
      panel.body.innerHTML =
        `<div class="zp-err">This panel hit an error and was isolated.<br>` +
        `<span>${String(err && err.message || err).slice(0, 200)}</span></div>`;
    }
    this._log("panel.error", { id: panel.id, error: String(err) });
  }

  // -- dockbar (minimized panels) ---------------------------------------
  _syncDockbar() {
    this.dockbar.innerHTML = "";
    for (const p of this.panels.values()) {
      if (!p.el.classList.contains("zp-min")) continue;
      const b = document.createElement("button");
      b.className = "zp-dockitem";
      b.innerHTML = `${p.def.icon} ${p.def.title}`;
      b.onclick = () => { this.restore(p.id); this.focus(p.id); };
      this.dockbar.appendChild(b);
    }
    this.dockbar.style.display = this.dockbar.children.length ? "flex" : "none";
  }

  // -- persistence (s38) -------------------------------------------------
  _persist() {
    try {
      const open = [...this.panels.values()].map((p) => ({
        type: p.type,
        min: p.el.classList.contains("zp-min"),
        max: p.el.classList.contains("zp-max"),
        pinned: !!p.pinned,
        left: p.el.style.left || "", top: p.el.style.top || "",
      }));
      localStorage.setItem(LS_KEY, JSON.stringify({ open }));
    } catch (_e) { /* storage may be unavailable; ignore */ }
  }
  _restore() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem(LS_KEY) || "{}"); }
    catch (_e) { return; }
    for (const s of (saved.open || [])) {
      // Only restore persistent/pinned panels automatically -- never re-open a
      // transient/dangerous operation (s38).
      const def = (this.registry.panels || {})[s.type];
      if (!def || !(def.persistent || s.pinned)) continue;
      const id = this.open(s.type, { focus: false });
      if (!id) continue;
      const p = this.panels.get(id);
      if (s.pinned) this.pin(id);
      if (s.min) this.minimize(id);
      if (s.left) { p.el.style.left = s.left; p.el.style.top = s.top; p.el.classList.add("zp-float"); }
    }
  }
  _recent = [];
  _pushRecent(type) { this._recent = [type, ...this._recent.filter((t) => t !== type)].slice(0, 8); }
  recent() { return this._recent.slice(); }

  // -- per-panel API handed to renderers --------------------------------
  _api(panel) {
    const mgr = this;
    return {
      id: panel.id, type: panel.type, def: panel.def, body: panel.body, el: panel.el,
      setStatus: (s) => mgr._setStatus(panel, s),
      setBody: (html) => { panel.body.innerHTML = html; },
      title: (t) => { const el = panel.el.querySelector(".zp-title"); if (el) el.textContent = t; },
      fail: (e) => mgr._panelError(panel, e),
      open: (type, opts) => mgr.open(type, opts),
    };
  }

  _log(kind, data) {
    try { window.dispatchEvent(new CustomEvent("zeno-panel-log", { detail: { kind, ...data } })); }
    catch (_e) {}
  }
}

let _mgr = null;
export function getPanelManager() {
  if (!_mgr) _mgr = new PanelManager();
  return _mgr;
}
