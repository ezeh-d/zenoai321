// ZENO panel renderers -- each shows REAL state from the real event stream or a
// real data endpoint. No fake activity, no invented metrics (master prompt s59).
// A renderer is { mount(api), event(api, evt)?, update(api, payload)?,
// unmount(api)? }. `api` gives {id,type,def,body,el,setStatus,setBody,title,fail}.
// Every handler is wrapped by the manager, so throwing here is isolated.

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const evType = (e) => e.type || e.event_type || "";
const evPayload = (e) => e.payload || e.data || {};

// rolling log helper shared by streaming panels
function pushLog(api, line, cls = "") {
  let box = api.body.querySelector(".zp-log");
  if (!box) { api.body.innerHTML = `<div class="zp-log"></div>`; box = api.body.querySelector(".zp-log"); }
  const row = document.createElement("div");
  row.className = `zp-line ${cls}`;
  row.innerHTML = line;
  box.appendChild(row);
  while (box.children.length > 200) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

export const RENDERERS = {
  // --- Activity: the live "ZENO is working" stream ---------------------
  activity: {
    mount(api) { api.setStatus("active"); api.setBody(`<div class="zp-log"></div>`); },
    event(api, evt) {
      const t = evType(evt), p = evPayload(evt);
      if (t === "execution.lifecycle") {
        const stage = esc(p.stage || "");
        const tool = esc(p.tool || (p.detail && p.detail.tool) || "");
        const mark = /result|verified|complete/i.test(stage) ? "✓"
          : /error|fail/i.test(stage) ? "✗" : "●";
        pushLog(api, `<span class="zp-mark">${mark}</span> <b>${stage}</b> ${tool}`);
      } else if (t === "tool.failed") {
        pushLog(api, `<span class="zp-mark">✗</span> ${esc(p.tool || "tool")} failed`, "err");
      } else if (t === "project.activity") {
        pushLog(api, `<span class="zp-mark">•</span> ${esc(p.summary || p.detail || "activity")}`);
      }
    },
  },

  // --- System: real live metrics ---------------------------------------
  system: {
    mount(api) {
      api.setStatus("active");
      api.setBody(`<div class="zp-metrics">loading…</div>`);
      const tick = async () => {
        try {
          const m = await (await fetch("/api/panels/system")).json();
          if (!m.ok) { api.setStatus("error"); return; }
          const bar = (v) => `<div class="zp-bar"><i style="width:${Math.max(0, Math.min(100, v))}%"></i></div>`;
          api.body.querySelector(".zp-metrics").innerHTML = `
            <div class="zp-metric"><span>CPU</span><b>${m.cpu_percent ?? "–"}%</b>${bar(m.cpu_percent || 0)}</div>
            <div class="zp-metric"><span>RAM</span><b>${m.ram_percent ?? "–"}%</b>${bar(m.ram_percent || 0)}
              <em>${m.ram_used_gb}/${m.ram_total_gb} GB</em></div>
            ${m.disk_percent != null ? `<div class="zp-metric"><span>Disk</span><b>${m.disk_percent}%</b>${bar(m.disk_percent)}<em>${m.disk_free_gb} GB free</em></div>` : ""}
            ${m.battery_percent != null ? `<div class="zp-metric"><span>Battery</span><b>${m.battery_percent}%${m.charging ? " ⚡" : ""}</b>${bar(m.battery_percent)}</div>` : ""}
            <div class="zp-metric"><span>Net</span><em>↓${m.net_recv_mb} MB ↑${m.net_sent_mb} MB</em></div>
            <div class="zp-metric"><span>Processes</span><b>${m.process_count}</b></div>`;
        } catch (_e) { api.setStatus("offline"); }
      };
      tick();
      api._timer = setInterval(tick, 2500);   // throttled (s39)
    },
    unmount(api) { if (api._timer) clearInterval(api._timer); },
  },

  // --- Agents / Council: real sub-agent activity -----------------------
  agents: {
    mount(api) { api.setStatus("idle"); api.setBody(`<div class="zp-log"><div class="zp-hint">Agent activity will appear here.</div></div>`); },
    event(api, evt) {
      const t = evType(evt), p = evPayload(evt);
      if (t === "agent.speaking" || t === "agent.message") {
        api.setStatus("active");
        const who = esc(p.agent || "agent").toUpperCase();
        const msg = esc(p.message || p.visual_state || "working");
        pushLog(api, `<b>${who}</b> — ${msg}`);
      } else if (t === "agent.handoff") {
        pushLog(api, `↪ handoff to <b>${esc(p.to || p.agent || "?")}</b>`);
      } else if (t === "agent.voice_stopped") {
        api.setStatus("idle");
      }
    },
  },

  // --- Notifications: real notification center -------------------------
  notifications: {
    mount(api) {
      api.setStatus("idle");
      api.setBody(`<div class="zp-notes"><div class="zp-hint">No notifications yet.</div></div>`);
      fetch("/api/events?event_type=notification.created&limit=15")
        .then((r) => r.json()).then((rows) => {
          for (const e of (rows || []).reverse()) this.event(api, e);
        }).catch(() => {});
    },
    event(api, evt) {
      if (evType(evt) !== "notification.created") return;
      const p = evPayload(evt);
      const box = api.body.querySelector(".zp-notes");
      const hint = box.querySelector(".zp-hint"); if (hint) hint.remove();
      const row = document.createElement("div");
      row.className = "zp-note";
      row.innerHTML = `<b>${esc(p.title || p.kind || "Notice")}</b>` +
        `<div>${esc(p.body || p.message || "")}</div>`;
      box.insertBefore(row, box.firstChild);
      while (box.children.length > 40) box.removeChild(box.lastChild);
      api.setStatus("active");
    },
  },

  // --- Files: real directory browser -----------------------------------
  files: {
    async mount(api, path) {
      api.setStatus("loading");
      try {
        const url = "/api/panels/files" + (path ? `?path=${encodeURIComponent(path)}` : "");
        const d = await (await fetch(url)).json();
        if (!d.ok) throw new Error(d.error || "cannot list");
        api.setStatus("active");
        api.title(`Files — ${d.path.split(/[\\/]/).pop() || d.path}`);
        const up = d.parent ? `<div class="zp-file zp-dir" data-path="${esc(d.parent)}">↩ ..</div>` : "";
        const rows = d.entries.map((e) =>
          `<div class="zp-file ${e.dir ? "zp-dir" : ""}" data-path="${esc(e.path)}" data-dir="${e.dir}">` +
          `${e.dir ? "▸" : "·"} ${esc(e.name)}${e.dir ? "" : ` <em>${(e.size / 1024).toFixed(0)}k</em>`}</div>`).join("");
        api.setBody(`<div class="zp-files">${up}${rows || '<div class="zp-hint">empty</div>'}</div>`);
        api.body.querySelectorAll(".zp-file").forEach((el) => {
          el.onclick = () => {
            if (el.dataset.dir === "true" || el.classList.contains("zp-dir"))
              RENDERERS.files.mount(api, el.dataset.path);
          };
        });
      } catch (e) { api.fail(e); }
    },
  },

  // --- Terminal: real command + output (from terminal.* events) --------
  terminal: {
    mount(api) { api.setStatus("idle"); api.setBody(`<div class="zp-log zp-term"><div class="zp-hint">Command output will stream here.</div></div>`); },
    event(api, evt) {
      const t = evType(evt), p = evPayload(evt);
      if (t === "terminal.command") {
        api.setStatus("active");
        pushLog(api, `<span class="zp-prompt">$</span> ${esc(p.command || "")}`, "cmd");
      } else if (t === "terminal.output") {
        const lines = String(p.output || "").split("\n");
        for (const ln of lines) if (ln !== "") pushLog(api, esc(ln));
      } else if (t === "terminal.exit") {
        pushLog(api, `<span class="zp-dim">[exit ${esc(p.code)}]</span>`, "dim");
        api.setStatus(p.code === 0 ? "success" : "warning");
      } else if (t === "execution.lifecycle" && p.tool === "run_command" && /select/i.test(p.stage || "")) {
        api.setStatus("active");
      }
    },
  },

  // --- Browser: real automation state (s7 honesty: not an embedded browser) ---
  browser: {
    mount(api) {
      api.setStatus("idle");
      api.setBody(`<div class="zp-browser">
        <div class="zp-url">—</div>
        <div class="zp-log zp-bactions"></div>
        <div class="zp-note zp-hint">Live automation state. This build hosts a
          web UI (not Electron), so pages open in ZENO's controlled browser and
          their activity streams here.</div></div>`);
    },
    event(api, evt) {
      const t = evType(evt), p = evPayload(evt);
      if (!t.startsWith("browser.") && !(evType(evt) === "execution.lifecycle" && (evPayload(evt).tool || "").startsWith("browser"))) return;
      api.setStatus("active");
      if (t === "browser.navigate" || t === "browser.page_loaded") {
        const u = esc(p.url || p.title || "");
        const box = api.body.querySelector(".zp-url"); if (box) box.textContent = u;
        pushLog({ body: api.body.querySelector(".zp-bactions") }, `→ ${u}`);
      } else if (t === "browser.click") pushLog({ body: api.body.querySelector(".zp-bactions") }, `ZENO clicked ${esc(p.target || "")}`);
      else if (t === "browser.type") pushLog({ body: api.body.querySelector(".zp-bactions") }, `ZENO typed ${esc(p.text || "…")}`);
      else if (t === "browser.download") pushLog({ body: api.body.querySelector(".zp-bactions") }, `↓ ${esc(p.file || "download")}`);
    },
  },

  // --- Voice / mic: real listening + transcription state ---------------
  voice: {
    mount(api) { api.setStatus("idle"); api.setBody(`<div class="zp-voice"><div class="zp-vstate">idle</div><div class="zp-vtext"></div></div>`); },
    event(api, evt) {
      const t = evType(evt), p = evPayload(evt);
      const st = api.body.querySelector(".zp-vstate");
      const tx = api.body.querySelector(".zp-vtext");
      if (t === "wake.detected") { api.setStatus("active"); if (st) st.textContent = "wake word"; }
      else if (t === "wake.state") { if (st) st.textContent = esc(p.state || "listening"); }
      else if (t === "voice.stt.final" || t === "audio.recognized") {
        if (st) st.textContent = "recognized";
        if (tx) tx.textContent = esc(p.text || p.transcript || "");
      } else if (t === "agent.speaking") { if (st) st.textContent = "ZENO speaking"; }
      else if (t === "agent.voice_stopped") { api.setStatus("idle"); if (st) st.textContent = "idle"; }
    },
  },

  // --- Network: real connectivity + companion/tunnel state -------------
  network: {
    mount(api) {
      api.setStatus("active");
      const tick = async () => {
        try {
          const m = await (await fetch("/api/panels/system")).json();
          const online = navigator.onLine;
          api.setBody(`<div class="zp-metrics">
            <div class="zp-metric"><span>Internet</span><b>${online ? "UP" : "DOWN"}</b></div>
            <div class="zp-metric"><span>Traffic</span><em>↓${m.net_recv_mb || 0} MB ↑${m.net_sent_mb || 0} MB</em></div>
            <div class="zp-metric"><span>Host</span><em>${esc(location.host)}</em></div>
          </div>`);
        } catch (_e) { api.setStatus("offline"); }
      };
      tick(); api._timer = setInterval(tick, 4000);
    },
    unmount(api) { if (api._timer) clearInterval(api._timer); },
  },

  // --- Media: fuller view, reuses the media backend --------------------
  media: {
    mount(api) {
      api.setStatus("active");
      const tick = async () => {
        try {
          const d = await (await fetch("/api/media/panel")).json();
          const a = d.active;
          if (!a || !a.title) { api.setBody(`<div class="zp-hint">Nothing playing.</div>`); api.setStatus("idle"); return; }
          api.setStatus(a.playing ? "active" : "idle");
          const art = a.art_path ? `<img class="zp-art" src="/api/media/art?app_id=${encodeURIComponent(a.app_id)}&v=${encodeURIComponent(a.title)}">` : "";
          api.setBody(`<div class="zp-mediafull">${art}
            <div class="zp-mtitle">${esc(a.title)}</div>
            <div class="zp-martist">${esc(a.artist || "")}</div>
            <div class="zp-msrc">${esc((a.source || "").toUpperCase())} · ${a.playing ? "playing" : "paused"}</div>
            <div class="zp-mctrls"><button data-a="previous">⏮</button><button data-a="toggle">${a.playing ? "⏸" : "▶"}</button><button data-a="next">⏭</button></div>
          </div>`);
          api.body.querySelectorAll("[data-a]").forEach((b) => b.onclick = () =>
            fetch("/api/media/command", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ action: b.dataset.a, reference: "it" }) }).then(() => setTimeout(tick, 700)));
        } catch (_e) { api.setStatus("offline"); }
      };
      tick(); api._timer = setInterval(tick, 3000);
    },
    unmount(api) { if (api._timer) clearInterval(api._timer); },
  },

  // --- honest fallback for registered-but-not-yet-rich panels ----------
  generic: {
    mount(api) {
      api.setStatus("idle");
      const sup = api.def.support;
      const note = sup === "planned"
        ? `The <b>${esc(api.def.title)}</b> panel is registered so ZENO routes to it, but its rich view isn't available on this build yet. It will show real ${esc(api.def.kind)} state when enabled.`
        : `${esc(api.def.title)} — live state will appear here.`;
      api.setBody(`<div class="zp-note zp-hint">${note}</div>`);
    },
    event(api, evt) {
      // show any directly-relevant events rather than pretending to work
      const t = evType(evt);
      if (t.startsWith(api.type + ".")) pushLog(api, esc(t));
    },
  },
};
