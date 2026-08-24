// ZENO visual-event bus (Pack: PixiJS #28, #34, #35).
//
// The ONE seam between ZENO's real state (AI core, tools, agents) and ANY
// renderer (the CSS orb today, an optional Pixi layer, a HUD). AI/tool code
// emits semantic events; renderers subscribe. This is why business logic never
// imports renderer code, and why a renderer crash can never reach the core: a
// throwing subscriber is caught and isolated here.
//
// Framework-free ES module -- works in the browser and under node (tests).

const _subs = new Map(); // event -> Set<handler>

// The semantic events the brief enumerates. Renderers key off these, never off
// internal function names, so either side can change without touching the other.
export const EVENTS = Object.freeze({
  IDLE: "zeno:idle",
  LISTENING: "zeno:listening",
  THINKING: "zeno:thinking",
  SPEAKING: "zeno:speaking",
  EXECUTING: "zeno:executing",
  ERROR: "zeno:error",
  SUCCESS: "zeno:success",
  STATE: "zeno:state", // generic {state} for orb states not in the list above
  AGENT_ACTIVATED: "agent:activated",
  AGENT_THINKING: "agent:thinking",
  AGENT_COMPLETED: "agent:completed",
  MISSION_STARTED: "mission:started",
  MISSION_PROGRESS: "mission:progress",
  MISSION_COMPLETED: "mission:completed",
  NOTIFICATION: "notification",
  // Normalised 0..1 audio amplitude (mic while listening, TTS while speaking).
  // The amplitude SOURCE emits this; the visualizer subscribes -- so mic/audio
  // processing never touches the renderer (PixiJS brief #5, #6).
  AUDIO_LEVEL: "zeno:audio-level",
});

// Subscribe. Returns an unsubscribe function (idempotent).
export function on(event, handler) {
  if (typeof handler !== "function" || !event) return () => {};
  let set = _subs.get(event);
  if (!set) { set = new Set(); _subs.set(event, set); }
  set.add(handler);
  return () => off(event, handler);
}

export function off(event, handler) {
  const set = _subs.get(event);
  if (set) { set.delete(handler); if (set.size === 0) _subs.delete(event); }
}

// Emit. Every subscriber runs isolated: one throwing handler can neither break
// its siblings nor propagate into the emitting core code (#34, #35).
export function emit(event, detail) {
  const set = _subs.get(event);
  if (!set) return 0;
  let delivered = 0;
  for (const handler of Array.from(set)) {
    try { handler(detail); delivered++; }
    catch (err) {
      try { console && console.warn && console.warn("visual handler error:", err); }
      catch (_) { /* console may be absent */ }
    }
  }
  return delivered;
}

export function clear(event) {
  if (event) _subs.delete(event); else _subs.clear();
}

export function listenerCount(event) {
  const set = _subs.get(event);
  return set ? set.size : 0;
}

// A single shared bus for the app; also exposed on window for non-module callers.
export const visualEvents = { on, off, emit, clear, listenerCount, EVENTS };
try { if (typeof window !== "undefined") window.visualEvents = visualEvents; } catch (_) {}
