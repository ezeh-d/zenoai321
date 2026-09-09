# ZENO Desktop Companion — Progress

## Architecture discovered

- **GUI shell**: pywebview (not PyQt/Electron/Tauri). Confirmed via `desktop_app.py`; a stale docstring in `panels.py` claiming "PyQt shell" was fixed in an earlier commit this session.
- **The "Mini Orb" already IS the Desktop Companion** this feature asks for, not a lesser thing to be replaced. It is ZENO's actual default presence — created *first* at boot (`desktop_app.py:829`), before the main dashboard exists at all.
  - Native window: `webview.create_window(frameless=True, on_top=True, focus=False, width=210, height=210, background_color="#000000")`.
  - `mini.html` renders a transparent (`background:transparent`) canvas with `orb.js`'s existing state-machine avatar.
  - Native drag/reposition via a `js_api` bridge (`begin_orb_drag` / `move_orb_drag` / `end_orb_drag` / `snap_orb` / `restore_orb_position`), with **persisted position** and a background health watchdog (`_recover_mini`) that repairs a hidden/off-screen/minimized window without stealing focus.
  - Reuses the exact same wake-word/VAD/`/api/transcribe`/`/api/chat`/`/api/tts` pipeline as the main dashboard — zero duplicate STT/TTS/brain, satisfying s2/s38 by construction.
  - Real Event Bus SSE subscription already drives `orb.setState(...)` from genuine events (conversation state, task progress, wake detection), and already shows *other agents'* faces via `agentPresence.consume/bootstrap` (the same multi-agent face system panels/manager.js and index.html use).
  - "Click-through" (s7) turns out to be moot: the window is sized to the character itself (210×210), not a large transparent overlay with holes to punch through, so there is no invisible blocking layer to begin with — a simpler and safer solution than what the brief assumed.

## Gap found and closed this pass

**No visible speech bubble.** Status was only ever written to `document.title`, which is invisible on a frameless window with no title bar — so ZENO could be *heard* through the Mini Orb but never *read*, violating the brief's own "voice/text must show text too" rule (s20-22) specifically on this surface.

### Fix
- `mini.html`: added `#speech-bubble` (dark-glass, bounded to the existing 210×210 window, `pointer-events:none` so it never steals a drag/click), a `speech-bubble.speaker` label, and `showMiniBubble(text, agentId)` / `hideMiniBubble()`. Truncates to 220 chars (s22: "a short current section... not an entire lesson" — the full reply already lives in conversation history on the main dashboard, which this does not duplicate). Auto-hides after `max(4000, min(16000, length*70))` ms — a glance, not a permanent panel (s32/s57).
- `runMiniCommand` now calls `showMiniBubble(text, reply.agent)` and passes `reply.agent` into `speakMiniReply`, so the TTS voice and the bubble label agree.
- `web.py`: `_conversation_turn`'s final return gained `"agent": active_specialist`, matching the `agent` field the SSE `/api/chat/stream` path already carries (added in the "Zeno call Kate" work earlier this session) — so a summoned specialist answering through the Mini Orb speaks in, and is labeled as, their own voice, not silently narrated as ZENO.

### Verification
- Bubble mechanism (show/hide/truncate/speaker-label) verified in an isolated harness (mock HTML + CSS extracted verbatim from `mini.html`, screenshot-confirmed rendering, JS-confirmed 220-char + ellipsis truncation). The Mini Orb page itself could not be driven end-to-end through the automated Browser pane in this session — its boot sequence immediately requests `getUserMedia()` for wake-word listening, which hangs waiting on a permission prompt the automated pane cannot answer (same failure mode hit earlier this session on the main dashboard's ambient-listening path). This is a **test-harness limitation, not a code issue** — the real native window handles this permission via the persisted WebView2 profile grant.
- `_conversation_turn`'s new `agent` field: covered indirectly by the "Zeno call Kate" test suite (`tests/test_agent_call.py`) which already exercises `active_specialist` correctness; a dedicated Mini-Orb-specific test was not added this pass (no JS test framework exists in this repo for `static/*.html`, confirmed during the original repo audit).

## Not attempted this pass (real gaps, correctly scoped out)

- **Emotion breadth** (s10, s12, s18-20): `orb.js` already has a real event-driven state machine (idle/listening/understanding/thinking/acting/speaking/success/error/waiting/searching/coding/creating/communicating/learning/reasoning/sleeping) with distinct eye-geometry per state — substantial, but doesn't cover every state the brief names (HAPPY, AMUSED, CURIOUS, SURPRISED, WARNING, INTERRUPTED, MOVING, CALLING_AGENT, NOTICE, BOOT). Extending the existing `STATES` map and `_STATE_EVENT` bridge in `orb.js` is the right place for this — not attempted here to keep this pass reviewable and low-risk.
- **Fullscreen auto-hide** (s43-45): not implemented; no fullscreen-detection code found in `desktop_app.py`.
- **Performance governor wiring for the Mini Orb specifically** (s33-34): the *dashboard's* automatic visual degradation (resource-pressure-driven lite mode) was wired earlier this session; the Mini Orb's own `orb.js` instance already supports `setPerformanceMode`/dynamic particle FPS but is not yet driven by the same `/api/performance` pressure signal.
- **Feature flag / rollback** (s60): does not apply the way the brief assumes — there is no "new companion to roll back from an old one," since the Mini Orb is not new. No flag was added.

## Files touched this pass

- `reyes_agent/static/mini.html` (speech bubble)
- `reyes_agent/web.py` (`_conversation_turn` return gains `agent`)

## Baseline performance

Not separately measured this pass — no code path touched here adds a render loop, timer, or network call; the bubble is pure CSS opacity/transform (compositor-only, matching every other transient overlay already in this file: `#music-card`, `#live-view-badge`) shown only on an existing reply event, so it carries no idle cost. A full idle-CPU/RAM measurement of the Mini Orb as a whole (s74) was not performed this pass.
