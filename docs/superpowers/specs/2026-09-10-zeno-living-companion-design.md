# ZENO Living Desktop Companion Design

**Status:** Approved in conversation on 2026-09-10 (“I approve all just finish it”).

## Goal

Make the full 2D ZENO character the primary desktop interface: a voice-first companion that lives directly over Windows, moves around the usable desktop, reacts locally and immediately, presents applications and ZENO panels, and preserves the existing assistant, voice, memory, and tool systems.

The reference WhatsApp clip defines the experience, not an implementation or a capability claim. It visibly demonstrates a small conversational character remaining over the desktop and another application. It does not prove unrestricted computer control, pixel hit testing, dragging, multi-monitor recovery, performance, or safety. Those behaviors require explicit implementation and verification.

## Non-goals

- Do not create another assistant, brain, conversation stack, model router, voice pipeline, event bus, or tool runner.
- Do not replace pywebview with PySide6 solely because the prompt kit suggests it.
- Do not grant unrestricted “full control.” All actions continue through registered ZENO tools and their existing authorization boundaries.
- Do not let an LLM schedule blinking, idle motion, gaze, lip animation, walking, dragging, or basic success/failure reactions.
- Do not redesign the supplied orange-haired, cyan-visor, white-coat ZENO identity.
- Do not make the orb primary. It remains compact, recovery, or low-resource fallback.

## Chosen architecture

Extend the existing compact pywebview companion rather than creating a monitor-sized web overlay or a second Qt process.

The native mini window is the physical desktop body. It stays compact, transparent, frameless, out of the taskbar, and topmost. Moving ZENO means moving this native window through the existing bridge, not translating a character inside a screen-sized surface. This preserves normal interaction with every application outside the small companion bounds and fits the current watchdog and saved-position mechanisms.

Within that window, the existing `CharacterRuntime` remains the semantic coordinator. Renderers only draw the body. The stable public commands remain:

- `setState(state)`
- `setEmotion(dimensions, options)`
- `lookAt(x, y, options)`
- `walkTo(x, y, options)`
- `pointAt(x, y, options)`

Runtime replacement adds one idempotent lifecycle command, named consistently across renderers (`dispose()` is preferred). It owns cancellation of timers, animation frames, listeners, stale async loads, and the root element.

## Components and ownership

### Native companion window

The existing desktop shell owns window creation, topmost repair, safe monitor geometry, native movement, persisted position, dragging, and OS-level input behavior. Renderer code may report whether a pointer lies over visible character pixels; only the native shell may decide whether the operating-system window is click-through.

The window must never grow to monitor size. Its saved position is normalized against the current work area on boot, resolution/DPI change, or monitor removal. At least the character’s head and drag target remain reachable.

This is Claude-owned integration in `desktop_app.py`; Codex contributes isolated contracts and tests unless explicitly handed the file.

### Character runtime and renderers

The runtime owns state priority, local behavior scheduling, semantic gestures, cooldowns, gaze targets, and renderer selection. It does not own tool execution or conversation generation. A renderer owns visual assets, frames, mouth shapes, and cheap DOM/Pixi updates; it never subscribes independently to core events when the runtime already does.

Claude owns the active runtime, renderer, manifest, and art integration. Codex must not race those files.

### Desktop director

One director translates desktop context into semantic character intent. It consumes normalized targets rather than raw application internals:

```text
target.updated { id, kind, bounds, monitorId, visible }
target.cleared { id, reason }
character.bounds { bounds, monitorId }
```

For any target it derives left/right/up/down relation from current character and target centers. Target movement or character movement recalculates the relationship. Closing the active target clears pointing and returns gaze to neutral. No screen coordinates are hardcoded.

Claude’s active `desktop_director.js` remains the single director; Codex will test its observable contract after it is committed/handed off rather than create a competitor.

### Local behavior engine

Blinking, breathing, gaze damping, walk cadence, idle wander, sleep, pickup/drag reaction, mouth amplitude, and basic task reactions run locally. They use a single clock tier where practical, monotonic elapsed time, explicit state priority, cooldowns, and generation tokens to reject stale callbacks after renderer changes.

Priority order:

```text
dragged / error / interrupted
authoritative voice or task state
direct spatial presentation gesture
short emotional reaction
idle wander / sleep
```

Automatic wandering is suspended during listening, speaking, tool execution, dragging, user pointer interaction, active target presentation, and low-resource/reduced-motion mode.

### Voice and conversation

The current mini voice flow remains authoritative: wake/VAD, transcription, `/api/chat`, TTS, barge-in, and status events. ZENO is voice-first. A transient speech bubble may be enabled for accessibility, errors, or silent mode, but it is not a chat surface and is off by default in the target experience.

### Tool and application behavior

Conversation chooses intents through the existing model/tool router. A tool result emits semantic lifecycle events. The character reacts immediately to the event while the tool continues independently:

```text
user speech
  -> listening/thinking local state
  -> registered tool request
  -> tool.started: local working reaction
  -> application/panel opens
  -> target.updated: gaze + walk/present + point
  -> tool.succeeded or tool.failed: local reaction
  -> spoken explanation
```

UI movement never restarts the voice pipeline, tool process, browser session, terminal, agent, or media playback.

## Interaction behavior

- ZENO remains visible above normal applications without repeatedly stealing keyboard focus.
- Transparent parts of the compact window pass pointer input through where the native host supports reliable hit testing.
- Visible character pixels or an explicit interaction mode accept click, drag, and context actions.
- Press-and-hold starts pickup/drag; release drops ZENO at a safe bounded position and persists it after movement settles.
- A short click wakes/opens ZENO; movement beyond the drag threshold never triggers the click action.
- Autonomous movement yields immediately to user drag and never fights a panel-layout gesture.
- Escape/cancel, lost pointer, window deactivation, and interrupted touch end the gesture safely.
- ZENO may walk toward an application/panel but stops outside its content and never hides critical controls.

## State, persistence, and recovery

Persist only UI state: position, monitor identity, facing, companion visibility, animation/accessibility preferences, and last safe dock. Do not persist microphone audio, screen contents, tool secrets, or arbitrary panel data.

On invalid/corrupt state, use a safe bottom-right position on the primary work area. On renderer/asset failure, fall back to the existing CSS character, then orb only if the character runtime itself cannot start. Recovery never repeats the previous tool action.

## Performance requirements

- No animation work while disposed.
- Hidden/inactive behavior policy is explicit: visual work pauses; whether emotion values decay in background is a product choice and must not be embedded accidentally in a renderer.
- Continuous pointer gaze is sampled/throttled so it updates during motion instead of waiting for motion to stop.
- Repeated gesture replacement retains a bounded number of timers/listeners.
- Asset loads are cached by URL and renderer generation; stale results cannot mount.
- Movement and resize use compositor/native window operations and never remount the character or voice stack.
- Reduced-motion and low-resource modes disable wander and expensive effects.

## Error handling

- Character/renderer failures are isolated from conversation and tools.
- Missing/corrupt assets fall back locally and emit one structured diagnostic, not a retry loop.
- Native movement failures retain the last safe position and stop autonomous movement until the next explicit request.
- Voice/tool failures change expression and speak/report the real failure without pretending an action succeeded.
- Disposal is idempotent and safe after partial initialization.

## Testing and evidence

### Deterministic module tests

- Event-bus isolation, subscription cleanup, state priority, emotion decay, cooldowns, stale generation rejection.
- Gaze direction/dead zone/bounds/continuous motion and neutral return.
- Walk target clamping, current-monitor geometry, target movement/closure, character relocation, drag override.
- Repeated initialization/disposal and renderer fallback.
- 1,000 replacements/moves with bounded timers, listeners, DOM roots, and cached assets.

### Native integration tests

- Always-on-top without focus theft.
- Transparent background and click-through outside visible pixels.
- Drag threshold, pickup/drop, position persistence, crash restart.
- Resolution, DPI, orientation, and monitor removal repair.
- Browser/terminal/media/voice state remains alive while ZENO moves.

### Live acceptance

1. Speak to ZENO without opening a chat window.
2. Observe immediate listening/thinking/speaking reactions.
3. Ask ZENO to open an allowed application or panel.
4. Confirm ZENO remains visible, looks/walks toward it, points, and explains.
5. Drag ZENO elsewhere; confirm movement wins over automation and saves safely.
6. Work through transparent space around ZENO without blocked clicks.
7. Restart ZENO and change display configuration; confirm a reachable companion returns.
8. Run voice and tool latency checks with animation enabled and disabled; regressions must remain within the project’s agreed budgets.

Simulated DOM/clock tests are not evidence of native hit testing, frame pacing, CPU/RAM, audio continuity, or real application control. Those claims require live Windows measurements.

## Delivery and collaboration

Claude remains lead integrator for active character/runtime/native files. Codex owns isolated test utilities, regression suites, review findings, and new modules explicitly assigned after Claude’s active work lands. Codex commits remain on `codex/zeno-character-support`; Claude cherry-picks or integrates them. No automatic merge into the shared feature branch.

The implementation is complete only when deterministic tests pass, known-gap strict tests are resolved or explicitly waived, native Windows acceptance is recorded, and the handoff states measured limitations honestly.
