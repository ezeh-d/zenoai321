// Event-driven specialist presence for ZENO's dashboard, Council and Mini Orb.
//
// This is deliberately an adapter around Claude's lightweight `agent_faces`
// primitive.  It never polls for animation and it never invents activity:
// cards exist only after an `agent.*` Event Bus event (or an explicit
// bootstrap of already-working agents) and are removed after the matching
// terminal event.

import { createFace, destroyAll, destroyFace, setAttention, setEmotion,
         setState as setFaceState } from "/static/agent_faces.js";

export const AGENT_IDENTITIES = {
  aris:        { name: "ARIS", color: "#3ddc7a", role: "Research Intelligence" },
  tosin:       { name: "TOSIN", color: "#a855f7", role: "Software Engineering" },
  stark:       { name: "STARK", color: "#ef4444", role: "Security" },
  zeal:        { name: "ZEAL", color: "#f5c518", role: "Creative Intelligence" },
  titan:       { name: "TITAN", color: "#f97316", role: "Business Intelligence" },
  apex:        { name: "APEX", color: "#22d3ee", role: "Gaming Intelligence" },
  nova:        { name: "NOVA", color: "#f472b6", role: "Vision Intelligence" },
  hermes_comm: { name: "HERMES", color: "#c8d0dc", role: "Communication" },
  oracle:      { name: "ORACLE", color: "#06b6d4", role: "Data Intelligence" },
  kate:        { name: "KATE", color: "#6366f1", role: "Academic & Science" },
  ultron:      { name: "ULTRON", color: "#b91c1c", role: "Critical Review" },
  atlas:       { name: "ATLAS", color: "#3b5a8a", role: "Mission Control" },
  helios:      { name: "HELIOS", color: "#10b981", role: "Wellbeing" },
  jarvis:      { name: "JARVIS", color: "#52e7ff", role: "Systems Integration" },
};

const VISUAL_STATES = new Set(["waiting", "thinking", "working", "speaking", "success", "error"]);
const TERMINAL_STATES = new Set(["success", "error"]);
const FALLBACK_COLOURS = ["#38bdf8", "#c084fc", "#fb7185", "#fbbf24", "#34d399", "#60a5fa"];
let presenceStylesInjected = false;

function injectPresenceStyles() {
  if (presenceStylesInjected) return;
  presenceStylesInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    .agent-presence { pointer-events: none; }
    .agent-presence .zf-card { opacity: 0; transform: translateY(7px) scale(.92); transition: opacity .28s ease, transform .28s ease; }
    .agent-presence .zf-card.agent-presence-in { opacity: 1; transform: translateY(0) scale(1); }
    .agent-presence .zf-card.agent-presence-out { opacity: 0; transform: translateY(-5px) scale(.92); }
    .agent-presence.agent-presence-paused *, .agent-presence.agent-presence-paused *::before, .agent-presence.agent-presence-paused *::after { animation-play-state: paused !important; }
    .agent-presence--mini { position: fixed; inset: 0; z-index: 4; overflow: hidden; }
    .agent-presence--mini .zf-card { position: absolute; width: 54px; gap: 1px; text-align: center; }
    .agent-presence--mini .zf-name { font-size: 8px; color: #e8f3ff; max-width: 54px; overflow: hidden; text-overflow: ellipsis; }
    .agent-presence--mini .zf-role { display: none; }
    .agent-presence--mini .zf-state { font-size: 7px; letter-spacing: .04em; }
    .agent-presence--mini .zf-card:nth-child(1) { left: 150px; top: 10px; }
    .agent-presence--mini .zf-card:nth-child(2) { left: 150px; top: 112px; }
    .agent-presence--mini .zf-card:nth-child(3) { left: 3px; top: 64px; }
    .agent-presence--mini .zf-card:nth-child(n+4) { left: 78px; top: 2px; transform: scale(.75); }
    .agent-presence--council { display: flex; flex-wrap: wrap; justify-content: center; gap: 18px 10px; }
    .agent-presence--situation { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; justify-content: center; }
    .agent-presence--situation .zf-card { width: 64px; gap: 2px; }
    .agent-presence--situation .zface { --zf-size: 48px !important; }
    .agent-presence--situation .zf-role { display: none; }
  `;
  document.head.appendChild(style);
}

function normalAgent(value) {
  const id = String(value || "").trim().toLowerCase();
  return /^[a-z0-9_-]{1,64}$/.test(id) ? id : "";
}

function identityFor(id, payload = {}) {
  if (AGENT_IDENTITIES[id]) return AGENT_IDENTITIES[id];
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return {
    name: id.toUpperCase().replace(/_/g, " "), color: FALLBACK_COLOURS[hash % FALLBACK_COLOURS.length],
    role: String(payload.role || "Registered specialist"),
  };
}

function normalState(value, fallback = "waiting") {
  const state = String(value || "").trim().toLowerCase();
  return VISUAL_STATES.has(state) ? state : fallback;
}

function emotionFor(state, supplied = "") {
  // Event producers can supply a specific, reviewed emotion.  Otherwise the
  // fallback is a deterministic interpretation of REAL task state, never a
  // random facial loop or a claim about private model reasoning.
  const value = String(supplied || "").trim().toLowerCase();
  if (value) return value;
  return ({ waiting: "curious", thinking: "thinking", working: "serious",
            speaking: "neutral", success: "proud", error: "concerned" })[state] || "neutral";
}

/**
 * A bounded visual projection of real Event Bus agent events.
 *
 * `councilContainer` and `situationContainer` are optional display targets.
 * Existing cards are reparented rather than cloned, so there is one visual
 * resource per called agent and no permanently hidden Council animation.
 */
export function createAgentPresence({ container, mode = "dashboard", councilContainer = null, situationContainer = null, terminalMs = 1450 } = {}) {
  if (!container) throw new Error("Agent presence needs a container");
  injectPresenceStyles();
  container.classList.add("agent-presence", `agent-presence--${mode}`);
  const entries = new Map();
  let councilOpen = false;
  let situationOpen = false;

  function destination() {
    if (councilOpen && councilContainer) return councilContainer;
    if (situationOpen && situationContainer) return situationContainer;
    return container;
  }

  function reflowMini() {
    if (mode !== "mini") return;
    const slots = [[150, 10], [150, 112], [3, 64]];
    [...entries.values()].forEach((entry, index) => {
      const slot = slots[index];
      // A full Council is rendered in the Council room. The compact 210px
      // companion can present three real participants around ZENO without
      // overlapping the main orb; further participants are not animated in
      // this tiny overlay.
      entry.card.style.display = slot ? "flex" : "none";
      if (slot) { entry.card.style.left = `${slot[0]}px`; entry.card.style.top = `${slot[1]}px`; }
    });
  }

  function place(entry) {
    const target = destination();
    if (entry.card.parentElement !== target) target.appendChild(entry.card);
  }

  function ensure(agentId, payload = {}) {
    const id = normalAgent(agentId);
    if (!id) return null;
    let entry = entries.get(id);
    if (entry) return entry;
    const card = createFace(id, identityFor(id, payload), { size: mode === "mini" ? 46 : 84 });
    card.classList.add("agent-presence-card");
    entry = { id, card, state: "waiting", taskIds: new Set(), dismissTimer: null };
    entries.set(id, entry);
    place(entry);
    reflowMini();
    // Let the browser paint the static face before transitioning it in.
    requestAnimationFrame(() => card.classList.add("agent-presence-in"));
    return entry;
  }

  function setVisualState(agentId, state, emotion = "") {
    const entry = ensure(agentId);
    if (!entry) return false;
    if (entry.dismissTimer) { clearTimeout(entry.dismissTimer); entry.dismissTimer = null; }
    entry.card.classList.remove("agent-presence-out");
    entry.state = normalState(state);
    setFaceState(entry.id, entry.state);
    setEmotion(entry.id, emotionFor(entry.state, emotion));
    return true;
  }

  function dismiss(agentId) {
    const entry = entries.get(agentId);
    if (!entry) return;
    if (entry.dismissTimer) clearTimeout(entry.dismissTimer);
    entry.card.classList.add("agent-presence-out");
    entry.dismissTimer = setTimeout(() => {
      destroyFace(agentId);
      entries.delete(agentId);
      reflowMini();
    }, Math.max(0, terminalMs));
  }

  function finish(agentId, state = "success", taskId = "", emotion = "") {
    const entry = ensure(agentId);
    if (!entry) return;
    if (taskId) entry.taskIds.delete(String(taskId));
    if (entry.taskIds.size) return;
    setVisualState(entry.id, TERMINAL_STATES.has(state) ? state : "success", emotion);
    dismiss(entry.id);
  }

  function consume(event) {
    const type = String(event?.type || "");
    const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
    const agentId = normalAgent(payload.agent);
    if (!agentId) return false;
    const taskId = payload.task_id ? String(payload.task_id) : "";
    if (type === "agent.activated") return setVisualState(agentId, "waiting", payload.emotion);
    if (type === "agent.task_queued") {
      const entry = ensure(agentId, payload); if (!entry) return false;
      if (taskId) entry.taskIds.add(taskId);
      return setVisualState(agentId, "waiting", payload.emotion);
    }
    if (type === "agent.task_started" || type === "agent.thinking" || type === "agent.working") {
      const entry = ensure(agentId, payload); if (!entry) return false;
      if (taskId) entry.taskIds.add(taskId);
      return setVisualState(agentId, payload.visual_state || (type === "agent.working" ? "working" : "thinking"), payload.emotion);
    }
    if (type === "agent.speaking") {
      for (const id of entries.keys()) setAttention(id, agentId);
      return setVisualState(agentId, "speaking", payload.emotion);
    }
    if (type === "agent.task_finished") {
      return finish(agentId, payload.visual_state || (payload.ok === false ? "error" : "success"), taskId, payload.emotion) || true;
    }
    if (type === "agent.restarting") return setVisualState(agentId, "waiting", payload.emotion || "warning");
    if (type === "agent.restarted") {
      return finish(agentId, payload.ok === false ? "error" : "success", "", payload.emotion) || true;
    }
    return false;
  }

  function bootstrap(agentIds) {
    for (const agentId of Array.isArray(agentIds) ? agentIds : []) setVisualState(agentId, "working");
  }

  function reparent() { for (const entry of entries.values()) place(entry); reflowMini(); }
  function setCouncilOpen(open) { councilOpen = !!open; if (councilOpen) situationOpen = false; reparent(); }
  function setSituationOpen(open) { situationOpen = !!open; if (situationOpen) councilOpen = false; reparent(); }
  function speak(agentId, speaking) {
    if (speaking) for (const id of entries.keys()) setAttention(id, agentId);
    return setVisualState(agentId, speaking ? "speaking" : "success");
  }
  function express(agentId, emotion) {
    const entry = ensure(agentId);
    if (!entry) return false;
    setEmotion(entry.id, emotion);
    return true;
  }
  function activeAgents() { return [...entries.keys()]; }
  function animatingCount() { return [...entries.values()].filter((entry) => ["thinking", "working", "speaking"].includes(entry.state)).length; }

  const visibility = () => container.classList.toggle("agent-presence-paused", document.visibilityState !== "visible");
  document.addEventListener("visibilitychange", visibility);
  visibility();

  function dispose() {
    document.removeEventListener("visibilitychange", visibility);
    for (const entry of entries.values()) {
      if (entry.dismissTimer) clearTimeout(entry.dismissTimer);
      entry.card.remove();
    }
    entries.clear();
    // Each document creates one controller. The page is unloading, so this
    // releases the face module's bounded DOM references as well.
    destroyAll();
  }

  return { consume, bootstrap, setCouncilOpen, setSituationOpen, speak, express, activeAgents, animatingCount, dispose };
}
