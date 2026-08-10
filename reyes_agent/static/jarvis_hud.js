// JARVIS Systems HUD -- an on-demand projection of ZENO's real runtime.
//
// The component owns no agent runtime and fabricates no "suit" sensors. It is
// created only when opened, reads existing measured endpoints, listens to the
// existing Event Bus, and releases its EventSource/timer/DOM when dismissed.

let session = null;
let stylesInstalled = false;

function installStyles() {
  if (stylesInstalled) return;
  stylesInstalled = true;
  const style = document.createElement("style");
  style.id = "jarvis-hud-styles";
  style.textContent = `
    .jh-overlay { position:fixed; inset:0; z-index:10020; display:grid; place-items:center; box-sizing:border-box;
      padding:clamp(10px,2vw,28px); color:#c8f8ff; background:rgba(1,8,15,.91);
      font-family:"Segoe UI",system-ui,sans-serif; backdrop-filter:blur(5px); }
    .jh-shell { position:relative; box-sizing:border-box; width:min(1380px,100%); height:min(860px,92vh); overflow:hidden;
      border:1px solid rgba(82,231,255,.45); clip-path:polygon(18px 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%,0 18px);
      background:linear-gradient(145deg,rgba(5,24,37,.98),rgba(2,9,17,.99));
      box-shadow:0 0 42px rgba(17,188,220,.13),inset 0 0 55px rgba(4,138,171,.08); }
    .jh-shell::before { content:""; position:absolute; inset:0; pointer-events:none; opacity:.25;
      background:linear-gradient(rgba(82,231,255,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(82,231,255,.06) 1px,transparent 1px);
      background-size:34px 34px; }
    .jh-header { position:relative; height:60px; display:flex; align-items:center; gap:14px; padding:0 18px;
      border-bottom:1px solid rgba(82,231,255,.24); background:rgba(4,19,30,.88); }
    .jh-mark { width:28px; height:28px; border:2px solid #52e7ff; transform:rotate(45deg); box-shadow:0 0 14px rgba(82,231,255,.45); }
    .jh-title { letter-spacing:.22em; font-weight:700; font-size:15px; overflow-wrap:anywhere; }
    .jh-subtitle { color:#78aabd; font:11px ui-monospace,"Cascadia Code",monospace; letter-spacing:.1em; }
    .jh-live { margin-left:auto; display:flex; align-items:center; gap:8px; color:#9eeef8; font:11px ui-monospace,monospace; }
    .jh-live i { width:7px; height:7px; border-radius:50%; background:#57efb1; box-shadow:0 0 10px #57efb1; }
    .jh-close { border:1px solid rgba(82,231,255,.35); background:transparent; color:#a7eaf4; width:34px; height:30px; cursor:pointer; font-size:20px; }
    .jh-grid { position:relative; height:calc(100% - 124px); display:grid; grid-template-columns:minmax(220px,1fr) minmax(300px,1.35fr) minmax(220px,1fr); gap:14px; padding:14px; }
    .jh-column { min-width:0; display:grid; align-content:start; gap:12px; overflow:auto; scrollbar-width:thin; }
    .jh-panel { border:1px solid rgba(82,231,255,.24); background:rgba(5,25,38,.7); padding:13px; clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px); }
    .jh-panel h3 { margin:0 0 10px; color:#63eaff; font:700 10px ui-monospace,"Cascadia Code",monospace; letter-spacing:.16em; }
    .jh-row { display:flex; justify-content:space-between; gap:10px; padding:5px 0; border-bottom:1px solid rgba(82,231,255,.08); font-size:12px; }
    .jh-row:last-child { border-bottom:0; } .jh-row span { color:#7799a8; } .jh-row b { max-width:62%; text-align:right; font-weight:600; overflow-wrap:anywhere; }
    .jh-core { display:grid; place-items:center; align-content:center; min-height:390px; border:1px solid rgba(255,177,67,.25); position:relative; overflow:hidden;
      background:radial-gradient(circle,rgba(45,221,255,.1),transparent 58%); }
    .jh-core::after { content:""; position:absolute; width:80%; height:1px; background:linear-gradient(90deg,transparent,#52e7ff,transparent); opacity:.22; animation:jh-scan 8s linear infinite; }
    @keyframes jh-scan { from { transform:translateY(-190px); } to { transform:translateY(190px); } }
    .jh-reactor { position:relative; width:min(31vw,250px); aspect-ratio:1; border-radius:50%; display:grid; place-items:center; }
    .jh-reactor::before { content:""; position:absolute; inset:4%; border-radius:50%; border:1px solid rgba(82,231,255,.58);
      background:repeating-conic-gradient(from 2deg,rgba(82,231,255,.8) 0 2deg,transparent 2deg 15deg);
      animation:jh-turn 24s linear infinite; }
    .jh-reactor::after { content:""; position:absolute; inset:24%; border-radius:50%; border:2px solid #ffb143;
      background:radial-gradient(circle,#eaffff 0 7%,#52e7ff 8% 22%,rgba(22,145,183,.35) 23% 52%,transparent 53%);
      box-shadow:0 0 25px rgba(82,231,255,.42); animation:jh-breathe 3.6s ease-in-out infinite; }
    @keyframes jh-turn { to { transform:rotate(360deg); } }
    @keyframes jh-breathe { 50% { opacity:.7; transform:scale(.96); } }
    .jh-reactor-label { position:relative; z-index:2; text-align:center; margin-top:62%; color:#dafcff; font:700 13px ui-monospace,monospace; letter-spacing:.18em; }
    .jh-state { margin-top:12px; color:#ffb143; font:700 11px ui-monospace,monospace; letter-spacing:.14em; }
    .jh-evidence { width:min(92%,620px); max-height:100px; margin-top:16px; padding:10px; border-left:2px solid #52e7ff; background:rgba(3,18,28,.82); color:#8db3c1; font:11px/1.5 ui-monospace,monospace; overflow:auto; }
    .jh-footer { position:relative; box-sizing:border-box; height:64px; display:flex; align-items:center; gap:9px; padding:0 14px; border-top:1px solid rgba(82,231,255,.24); background:rgba(4,19,30,.9); }
    .jh-input { flex:1; min-width:0; height:36px; border:1px solid rgba(82,231,255,.35); background:#03111b; color:#d9fbff; padding:0 11px; outline:none; }
    .jh-input:focus { border-color:#52e7ff; } .jh-button { height:36px; border:1px solid #52e7ff; background:rgba(20,132,157,.16); color:#bcf7ff; padding:0 14px; cursor:pointer; font-size:11px; letter-spacing:.08em; }
    .jh-button:hover { background:rgba(20,132,157,.32); }
    .jh-warn { color:#ffbd62 !important; } .jh-good { color:#57efb1 !important; } .jh-bad { color:#ff6e6e !important; }
    @media (max-width:850px) { .jh-overlay { padding:7px; } .jh-grid { grid-template-columns:1fr; overflow:auto; } .jh-column { overflow:visible; } .jh-core { min-height:360px; order:-1; } .jh-shell { height:calc(100vh - 14px); } .jh-reactor { width:210px; } .jh-subtitle,.jh-live { display:none; } .jh-title { font-size:12px; } .jh-footer { height:auto; padding:9px; flex-wrap:wrap; } .jh-input { flex-basis:100%; } }
    @media (prefers-reduced-motion:reduce) { .jh-overlay * { animation:none !important; transition:none !important; } }
    .jh-overlay[aria-hidden="true"] * { animation-play-state:paused !important; }
  `;
  document.head.appendChild(style);
}

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function panel(title) {
  const node = el("section", "jh-panel");
  node.appendChild(el("h3", "", title));
  return node;
}

function row(parent, label, value, tone = "") {
  const line = el("div", "jh-row");
  line.append(el("span", "", label), el("b", tone, value == null || value === "" ? "UNKNOWN" : String(value)));
  parent.appendChild(line);
}

function setRows(parent, title, values) {
  parent.replaceChildren(el("h3", "", title));
  for (const [label, value, tone] of values) row(parent, label, value, tone || "");
}

function safeNumber(value, suffix = "") {
  return Number.isFinite(Number(value)) ? `${Number(value)}${suffix}` : "UNKNOWN";
}

function normalAgentEvent(event) {
  try {
    const parsed = JSON.parse(event.data);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch { return null; }
}

function build(runCommand) {
  const overlay = el("div", "jh-overlay");
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "JARVIS Systems HUD");
  const shell = el("section", "jh-shell");
  const header = el("header", "jh-header");
  header.append(el("div", "jh-mark"));
  const names = el("div");
  names.append(el("div", "jh-title", "JARVIS // SYSTEMS INTEGRATION"), el("div", "jh-subtitle", "ZENO RUNTIME COMMAND INTERFACE"));
  const live = el("div", "jh-live");
  live.append(el("i"), el("span", "", "LIVE EVIDENCE"));
  const close = el("button", "jh-close", "×"); close.type = "button"; close.title = "Close JARVIS HUD"; close.setAttribute("aria-label", "Close JARVIS HUD");
  header.append(names, live, close);

  const grid = el("main", "jh-grid");
  const left = el("div", "jh-column"), center = el("div", "jh-column"), right = el("div", "jh-column");
  const runtime = panel("RUNTIME CORE"), awareness = panel("SITUATIONAL AWARENESS"), mission = panel("MISSION CONTROL"), provider = panel("MODEL ROUTER"), eventBus = panel("EVENT BUS");
  left.append(runtime, awareness); right.append(mission, provider, eventBus);
  const core = el("section", "jh-core");
  const reactor = el("div", "jh-reactor"); reactor.append(el("div", "jh-reactor-label", "JARVIS"));
  const state = el("div", "jh-state", "CONNECTING");
  const evidence = el("div", "jh-evidence", "Waiting for a measured ZENO runtime snapshot…");
  core.append(reactor, state, evidence); center.append(core);
  grid.append(left, center, right);

  const footer = el("footer", "jh-footer");
  const input = el("input", "jh-input"); input.placeholder = "Give JARVIS an operational task through ZENO…"; input.autocomplete = "off";
  const summon = el("button", "jh-button", "SYSTEMS REPORT"); summon.type = "button";
  const send = el("button", "jh-button", "DISPATCH"); send.type = "button";
  footer.append(input, summon, send);
  shell.append(header, grid, footer); overlay.append(shell); document.body.appendChild(overlay);

  function dispatch(text) {
    const command = String(text || "").trim();
    if (!command || typeof runCommand !== "function") return;
    state.textContent = "DISPATCHED THROUGH ZENO";
    evidence.textContent = `Owner command submitted to the normal ZENO permission and evidence pipeline: ${command}`;
    runCommand(`Ask JARVIS to ${command}`);
    input.value = "";
  }
  send.addEventListener("click", () => dispatch(input.value));
  input.addEventListener("keydown", event => { if (event.key === "Enter") dispatch(input.value); });
  summon.addEventListener("click", () => dispatch("inspect current runtime health and missions, then give me a concise systems report using measured evidence"));
  close.addEventListener("click", closeJarvisHud);
  overlay.addEventListener("click", event => { if (event.target === overlay) closeJarvisHud(); });

  return { overlay, runtime, awareness, mission, provider, eventBus, state, evidence, input };
}

async function refresh(current) {
  if (!current || current.loading) return;
  current.loading = true;
  try {
    const response = await fetch("/api/situation", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (session !== current) return;
    const sys = data.system || {}, agents = data.agents || {}, model = data.model || {}, missions = data.missions || {}, events = data.events || {};
    setRows(current.ui.runtime, "RUNTIME CORE", [
      ["CPU", safeNumber(sys.cpu, "%"), Number(sys.cpu) >= 85 ? "jh-warn" : "jh-good"],
      ["MEMORY", `${safeNumber(sys.ram, "%")}  ${safeNumber(sys.ram_used_gb, " GB")}/${safeNumber(sys.ram_total_gb, " GB")}`],
      ["SPECIALISTS ACTIVE", safeNumber(agents.alive)],
      ["TASKS WORKING", safeNumber(agents.working)],
      ["QUEUE DEPTH", safeNumber(agents.queued), Number(agents.queued) ? "jh-warn" : "jh-good"],
      ["SUPERVISOR", agents.supervisor === true ? "ONLINE" : "OFFLINE", agents.supervisor === true ? "jh-good" : "jh-bad"],
    ]);
    const micSituation = data.intelligence?.situation || {};
    const observed = data.intelligence?.observed || {};
    const pattern = data.intelligence?.anticipation?.current_prediction || null;
    const learned = data.intelligence?.anticipation?.readiness || {};
    setRows(current.ui.awareness, "SITUATIONAL AWARENESS", [
      ["CURRENT APP", observed.app || "UNKNOWN"],
      ["FOCUS", observed.focus_minutes == null ? "UNKNOWN" : safeNumber(observed.focus_minutes, " MIN")],
      ["ACTIVE SESSION", observed.session_minutes == null ? "UNKNOWN" : safeNumber(observed.session_minutes, " MIN")],
      ["CURRENT TASK", micSituation.current_task || "STANDBY"],
      ["NEXT EVENT", observed.next_event ? `${observed.next_event} · ${safeNumber(observed.next_event_minutes, " MIN")}` : "NONE"],
      ["LEARNED PATTERN", pattern ? `${pattern.value} · ${Math.round(Number(pattern.confidence) * 100)}% / ${pattern.observations} samples` : "NO CONFIDENT PATTERN"],
      ["EVIDENCE SAMPLES", safeNumber(learned.total_samples)],
    ]);
    setRows(current.ui.mission, "MISSION CONTROL", [
      ["OPEN MISSIONS", safeNumber(missions.open)],
      ["ACTIVE MISSION", micSituation.active_mission || "NONE"],
      ["TOP RECORD", missions.top?.[0]?.name || "NONE"],
      ["VERIFIED PROGRESS", missions.top?.[0] ? safeNumber(missions.top[0].progress, "%") : "NONE"],
    ]);
    setRows(current.ui.provider, "MODEL ROUTER", [
      ["ACTIVE PROVIDER", model.provider || "UNAVAILABLE", model.provider ? "jh-good" : "jh-bad"],
      ["LATENCY MEASURED", model.measured === true ? "YES" : "NO", model.measured === true ? "jh-good" : "jh-warn"],
      ["POLICY PROFILE", data.permissions?.profile || "UNKNOWN"],
      ["PENDING APPROVALS", safeNumber(data.pending_approvals), Number(data.pending_approvals) ? "jh-warn" : "jh-good"],
    ]);
    setRows(current.ui.eventBus, "EVENT BUS", [
      ["DURABLE EVENTS", safeNumber(events.total)],
      ["SUBSCRIBERS", safeNumber(events.subscribers)],
      ["TOP EVENT TYPE", Object.entries(events.by_type || {}).sort((a, b) => Number(b[1]) - Number(a[1]))[0]?.[0] || "NONE"],
      ["TOP EVENT COUNT", safeNumber(Object.entries(events.by_type || {}).sort((a, b) => Number(b[1]) - Number(a[1]))[0]?.[1])],
    ]);
    if (!current.jarvisActive) {
      current.ui.state.textContent = "STANDBY // RUNTIME LINK ONLINE";
      current.ui.evidence.textContent = `Measured snapshot received ${new Date().toLocaleTimeString()}. JARVIS is not currently delegated; no agent activity is being implied.`;
    }
  } catch (error) {
    if (session === current) {
      current.ui.state.textContent = "RUNTIME LINK DEGRADED";
      current.ui.evidence.textContent = `The live snapshot could not be read: ${error.message}`;
    }
  } finally { current.loading = false; }
}

function connectEvents(current) {
  if (!window.EventSource) return;
  current.source = new EventSource("/api/events/stream");
  current.source.onmessage = event => {
    if (session !== current) return;
    const update = normalAgentEvent(event);
    if (!update) return;
    const type = String(update.type || "");
    const payload = update.payload && typeof update.payload === "object" ? update.payload : {};
    if (String(payload.agent || "").toLowerCase() !== "jarvis") return;
    current.jarvisActive = !["agent.task_finished", "agent.restarted"].includes(type);
    const visual = String(payload.visual_state || "").toUpperCase();
    const labels = {
      "agent.activated": "AWAKE", "agent.task_queued": "WAITING", "agent.task_started": "THINKING",
      "agent.thinking": "THINKING", "agent.working": "WORKING", "agent.speaking": "SPEAKING",
      "agent.task_finished": payload.ok === false ? "ERROR" : "SUCCESS",
      "agent.restarting": "RECOVERING", "agent.restarted": payload.ok === false ? "ERROR" : "READY",
    };
    current.ui.state.textContent = `JARVIS // ${visual || labels[type] || "ACTIVE"}`;
    current.ui.evidence.textContent = payload.task || payload.description || payload.error || payload.result || `Observed real Event Bus event: ${type}`;
    if (!current.jarvisActive) setTimeout(() => { if (session === current && !current.jarvisActive) refresh(current); }, 1500);
  };
}

export async function openJarvisHud({ runCommand } = {}) {
  if (session) {
    session.ui.overlay.removeAttribute("aria-hidden");
    session.ui.input.focus();
    return;
  }
  installStyles();
  const current = { ui: build(runCommand), source: null, timer: null, loading: false, jarvisActive: false };
  session = current;
  connectEvents(current);
  await refresh(current);
  if (session !== current) return;
  current.timer = setInterval(() => { if (document.visibilityState === "visible") refresh(current); }, 2000);
  current.ui.input.focus();
}

export function closeJarvisHud() {
  const current = session;
  if (!current) return;
  session = null;
  current.ui.overlay.setAttribute("aria-hidden", "true");
  if (current.timer) clearInterval(current.timer);
  if (current.source) current.source.close();
  current.ui.overlay.remove();
}

export function isJarvisHudOpen() { return !!session; }
