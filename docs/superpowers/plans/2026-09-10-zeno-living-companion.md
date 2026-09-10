# ZENO Living Desktop Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing compact pywebview Mini ZENO into the full 2D, voice-first, autonomous desktop companion demonstrated by the reference video without creating a second assistant or disrupting Claude's active character integration.

**Architecture:** Keep the compact native pywebview window as ZENO's desktop body. A Python motion controller moves the native HWND smoothly; the existing JavaScript runtime/director drives semantic animation and spatial intent; the current voice and registered-tool systems remain authoritative. Claude owns edits to active runtime/native files, while Codex owns new isolated motion code, regression tests, review, and evidence.

**Tech Stack:** Python 3.11+, pywebview/WebView2, Windows user32, vanilla ES modules, Node.js 20+, pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-zeno-living-companion-design.md`

## Global Constraints

- The supplied orange-haired, cyan-visor, white-coat ZENO is the visual source of truth.
- The orb remains compact/recovery/low-resource fallback only.
- Preserve semantic methods `setState`, `setEmotion`, `lookAt`, `walkTo`, and `pointAt`.
- Basic animation is local; no LLM controls blink, gaze, walking, idle motion, lip amplitude, or basic reactions.
- All application actions use existing registered tools and authorization boundaries.
- Never restart conversation, voice, tool, browser, terminal, agent, or media state because the companion moves.
- Do not replace pywebview with PySide6.
- Do not modify Claude-active files until Claude commits or explicitly hands them to the executor.
- No edits to unrelated security, surveillance, RF, network-security, penetration-testing, trading, or agent systems.
- Simulated tests are not evidence of native hit testing, CPU/RAM, frame pacing, audio continuity, or real tool execution.

---

### Task 1: Native motion controller — CODEX OWNED

**Files:**
- Create: `reyes_agent/companion_motion.py`
- Create: `tests/test_companion_motion.py`

**Interfaces:**
- Produces: `ease_in_out(progress: float) -> float` and `interpolate_position(start, target, progress) -> tuple[int, int]`.
- Produces: `CompanionMotionController(move, *, fps=30.0, clock=time.monotonic)` with `walk_to(start, target, duration_s, on_complete=None) -> int`, `cancel() -> None`, `close(timeout_s=1.0) -> None`, and `active` property.
- `move(x: int, y: int) -> bool` performs the existing no-activate native movement. A false result ends the plan and reports `on_complete(False)` once.
- One daemon worker handles every plan. A generation counter makes the latest walk win without spawning a thread per command.

- [x] **Step 1: Write pure motion tests**

```python
from reyes_agent.companion_motion import ease_in_out, interpolate_position

def test_interpolation_has_exact_endpoints_and_monotonic_middle():
    assert interpolate_position((10, 20), (110, 220), 0) == (10, 20)
    middle = interpolate_position((10, 20), (110, 220), 0.5)
    assert middle == (60, 120)
    assert interpolate_position((10, 20), (110, 220), 1) == (110, 220)
    assert 0 < ease_in_out(0.25) < ease_in_out(0.75) < 1
```

- [x] **Step 2: Run the pure tests and observe the missing-module failure**

Run: `python -m pytest tests/test_companion_motion.py -q`

Expected: collection fails because `reyes_agent.companion_motion` does not exist.

- [x] **Step 3: Implement pure easing and interpolation**

```python
def ease_in_out(progress: float) -> float:
    p = max(0.0, min(1.0, float(progress)))
    return p * p * (3.0 - 2.0 * p)

def interpolate_position(start, target, progress):
    p = ease_in_out(progress)
    return (round(start[0] + (target[0] - start[0]) * p),
            round(start[1] + (target[1] - start[1]) * p))
```

- [x] **Step 4: Add controller lifecycle tests**

```python
def test_latest_walk_wins_and_close_is_idempotent():
    moves = []
    reached = threading.Event()
    controller = CompanionMotionController(lambda x, y: moves.append((x, y)) or True, fps=120)
    controller.walk_to((0, 0), (100, 0), 0.2)
    controller.walk_to((0, 0), (20, 30), 0.03, lambda ok: reached.set() if ok else None)
    assert reached.wait(1.0)
    assert moves[-1] == (20, 30)
    controller.close()
    controller.close()
    assert not controller.active
```

Also cover cancel-before-completion, failed `move`, callback isolation, invalid duration normalization, 1,000 rapid replacements with one worker, and no movement after close.

- [x] **Step 5: Implement one condition-driven daemon worker**

Use `threading.Condition`, one `_Plan` dataclass, monotonic deadlines, bounded `fps` from 10–60, generation comparison before every move/callback, and callback execution outside the condition lock.

- [x] **Step 6: Verify and commit**

Run: `python -m pytest tests/test_companion_motion.py -q`

Expected: all motion tests pass with no live threads retained after `close()`.

Commit: `feat(character): add bounded native motion controller`

---

### Task 2: Native window integration — CLAUDE OWNED, CODEX TESTED

**Files:**
- Modify: `reyes_agent/desktop_app.py`
- Modify: `tests/test_mini_overlay.py`
- Test: `tests/test_companion_motion.py`

**Interfaces:**
- Consumes `CompanionMotionController` from Task 1.
- Produces JS bridge methods `walk_companion_to(x: int, y: int, duration_ms: int = 900) -> dict`, `cancel_companion_walk() -> bool`, and existing `begin_orb_drag`/`move_orb_drag`/`end_orb_drag` behavior.
- The runtime publishes `desktop.companion_motion` only at start/completion/cancel/failure, never per pixel.

- [ ] **Step 1: Write failing integration tests**

```python
def test_owner_drag_cancels_autonomous_motion(monkeypatch):
    api = _DesktopApi()
    cancelled = []
    api._companion_motion = SimpleNamespace(cancel=lambda: cancelled.append(True))
    monkeypatch.setattr(desktop_app, "_native_window_rect", lambda _w: (100, 100, 210, 210))
    api.attach_mini_window(SimpleNamespace())
    assert api.begin_orb_drag(110, 120, 210)
    assert cancelled == [True]

def test_shutdown_closes_companion_motion_once():
    api = _DesktopApi()
    motion = CountingMotionController()
    api._companion_motion = motion
    api.shutdown()
    api.shutdown()
    assert motion.close_count == 1
```

Define `CountingMotionController` in the test module with production-shaped `cancel()` and `close()` methods; `close()` increments `close_count` only on its first call. Keep the real `_DesktopApi.shutdown()` path under test and assert the externally visible close count, not private thread internals.

- [ ] **Step 2: Confirm the tests fail because the bridge/controller wiring is absent**

Run: `python -m pytest tests/test_mini_overlay.py tests/test_companion_motion.py -q`

- [ ] **Step 3: Wire the controller without changing voice or server ownership**

Construct one controller in `_DesktopApi.__init__` using a callable that resolves the current mini window under `_window_lock` and calls `_move_native_overlay`. `walk_companion_to` clamps its requested endpoint through `_visible_or_default_position`, reads the actual native start rect, starts the plan, and returns `{ok, generation, x, y}`.

`begin_orb_drag`, `set_mini(False)`, and `shutdown` cancel motion. `shutdown` closes the worker idempotently. Do not create another server, window, microphone, or event bus.

- [ ] **Step 4: Verify drag priority, failure behavior, and persistence**

Run: `python -m pytest tests/test_mini_overlay.py tests/test_companion_motion.py -q`

Expected: existing multi-monitor/drag tests and new motion tests pass.

- [ ] **Step 5: Commit Claude's integration separately**

Commit: `feat(character): move companion through native overlay controller`

---

### Task 3: Character lifecycle and continuous gaze — CLAUDE OWNED, CODEX CONTRACT

**Files:**
- Modify: `reyes_agent/static/character.js`
- Test: `scripts/verify_character_lifecycle_codex.mjs`

**Interfaces:**
- Produces idempotent `dispose()` on the object returned by `initCharacter`.
- `setActive(false)` pauses visual callbacks and ignores pointer input; the product may separately choose whether emotion values decay in background.
- Continuous pointer motion produces a gaze update after initial acquisition and at most once per animation frame; it does not wait until motion ends.

- [ ] **Step 1: Run strict regressions before production edits**

Run: `node --no-warnings scripts/verify_character_lifecycle_codex.mjs --strict`

Expected baseline: four accepted failures plus one non-blocking emotion-policy probe.

- [ ] **Step 2: Name every owned callback and timer**

Replace anonymous `visibilitychange`, `resize`, `zeno:panels-state`, and `zeno:panel-opened` handlers with named functions. Track blink inner timeouts, pulse, walk, point, gaze debounce/neutral, animation frame, emotion interval, and idle interval in owned handles.

- [ ] **Step 3: Implement idempotent disposal**

```js
let disposed = false;
function dispose() {
  if (disposed) return;
  disposed = true;
  // Clear every owned timeout/interval/RAF, remove every named listener,
  // dispose the active renderer/lip-sync attachment, then remove only root.
}
```

Every async callback checks `disposed` before DOM work. Renderer loads use a generation/token check so a stale manifest/image cannot mount after replacement.

- [ ] **Step 4: Replace trailing-only gaze with delayed acquisition plus frame sampling**

The first pointer event starts the 120 ms acquisition timer. Subsequent events update `pendingPointer` without restarting acquisition. Once acquired, one rAF samples the latest point while movement continues. The existing 1,400 ms neutral timeout remains trailing and replaceable.

- [ ] **Step 5: Run strict and existing character suites**

Run:

```powershell
node --no-warnings scripts/verify_character_lifecycle_codex.mjs --strict
node --no-warnings scripts/verify_character_engine.mjs
node --no-warnings scripts/verify_character_renderers.mjs
node --no-warnings scripts/verify_character_sprite_integration.mjs
```

Expected: accepted strict failures are resolved. The inactive-emotion item remains explicitly decided/documented rather than accidentally dictated by renderer code.

- [ ] **Step 6: Commit**

Commit: `fix(character): dispose runtime and sample continuous gaze`

---

### Task 4: Spatial DesktopDirector contract — CLAUDE OWNED, CODEX TESTED

**Files:**
- Modify: `reyes_agent/static/desktop_director.js`
- Modify: `scripts/verify_desktop_director.mjs`
- Modify: `reyes_agent/static/character.js`
- Modify: panel event producer only after Claude confirms the single canonical source.

**Interfaces:**
- Produces `updateTarget({id, kind, bounds, monitorId, visible}) -> intent`.
- Produces `clearTarget(id, reason) -> intent`.
- Produces `updateCharacterBounds(bounds, monitorId) -> intent`.
- Intent is `{targetId, lookAt:{x,y}|null, pointAt:{x,y}|null, walkTo:{x,y}|null, relation:'left'|'right'|'above'|'below'|'overlap'|'none'}`.

- [ ] **Step 1: Add literal geometry cases before implementation**

```js
const director = createDesktopDirector({safeGap:24});
director.updateCharacterBounds({x:800,y:400,width:200,height:240}, 'primary');
let intent = director.updateTarget({id:'browser',kind:'panel',bounds:{x:1200,y:100,width:400,height:600},monitorId:'primary',visible:true});
check('right target points right', intent.relation === 'right' && intent.pointAt.x === 1400);
intent = director.updateTarget({id:'browser',kind:'panel',bounds:{x:100,y:100,width:400,height:600},monitorId:'primary',visible:true});
check('moved target recalculates left', intent.relation === 'left' && intent.pointAt.x === 300);
```

Cover target close, character movement, hidden target, overlap, different monitor, panel movement during user drag, and invalid bounds.

- [ ] **Step 2: Run and observe missing methods**

Run: `node --no-warnings scripts/verify_desktop_director.mjs`

- [ ] **Step 3: Implement target state in the existing director**

Keep one active target record. Derive centers from bounds on every update. Same-monitor targets may produce gaze/point/walk intent; different-monitor targets produce no walk until the native shell maps the destination work area. `clearTarget` returns neutral intent. No DOM imports, tool calls, timers, or hardcoded screen coordinates.

- [ ] **Step 4: Wire semantic events once**

The canonical panel/application layer emits target updates. `character.js` subscribes once through named handlers and calls its existing semantic methods. During native user drag, queue the latest non-critical target intent and apply it after drag completion.

- [ ] **Step 5: Verify and commit**

Run: `node --no-warnings scripts/verify_desktop_director.mjs scripts/verify_character_engine.mjs`

Commit: `feat(character): track moving desktop presentation targets`

---

### Task 5: Interaction mode and selective click-through — CLAUDE OWNED

**Files:**
- Modify: `reyes_agent/desktop_app.py`
- Modify: `reyes_agent/static/mini.html`
- Modify: `tests/test_mini_overlay.py`
- Create: `docs/superpowers/reports/2026-09-10-zeno-click-through-live.md`

**Interfaces:**
- Produces bridge `set_companion_interactive(enabled: bool) -> bool`.
- Produces bridge `companion_interaction_state() -> {supported: bool, enabled: bool, reason: str}`.
- Mini renderer reports `visible-hit` versus `transparent-hit`; the native host controls Windows input transparency.

- [ ] **Step 1: Add native-style unit tests around an injected user32 boundary**

Test that enabling interaction clears only `WS_EX_TRANSPARENT`; disabling sets only that flag; both preserve every other extended style bit; missing HWND/unsupported platform returns `False`; repeated calls are idempotent.

- [ ] **Step 2: Implement a narrow Windows helper**

Use `GetWindowLongPtrW`/`SetWindowLongPtrW` with `GWL_EXSTYLE=-20` and `WS_EX_TRANSPARENT=0x20`. Never toggle topmost, activation, focus, visibility, or ownership flags in this helper. Expose unsupported state honestly outside Windows.

- [ ] **Step 3: Add an explicit interaction-state machine in mini.html**

States are `PASS_THROUGH`, `ARMED`, `DRAGGING`, and `MENU`. A trusted click/wake command or pointer entering a verified visible character hit arms interaction; drag begins only past the existing movement threshold. Pointer cancel, blur, Escape, release, and timeout return to pass-through. Do not depend on hover-only controls for touch.

If WebView2 cannot deliver the first pointer event while native pass-through is enabled, do not fake pixel hit testing. Use a documented owner hotkey/voice command to arm interaction and record that limitation in the live report.

- [ ] **Step 4: Run unit tests and execute native manual checks**

Run: `python -m pytest tests/test_mini_overlay.py -q`

Manual checks record: click through transparent corner, click/drag visible character, typing focus remains in Notepad, Escape cancels, drag persists, overlay stays topmost, touch behavior where hardware exists.

- [ ] **Step 5: Commit**

Commit: `feat(character): add safe companion interaction mode`

---

### Task 6: Voice-driven visual performance — CLAUDE OWNED, CODEX VERIFIED

**Files:**
- Modify: `reyes_agent/static/mini.html`
- Modify: `reyes_agent/static/lip_sync.js`
- Modify: `scripts/verify_lip_sync.mjs`
- Create: `docs/superpowers/reports/2026-09-10-zeno-companion-live.md`

**Interfaces:**
- Existing wake/VAD/transcription/chat/TTS flow remains unchanged.
- One lip-sync attachment per audio element exposes idempotent `detach()`.
- Voice states drive the same active renderer: listening, thinking, speaking, interrupted, success, error.

- [ ] **Step 1: Add repeated-attachment and lifecycle tests**

Use a complete fake Web Audio graph and real module behavior to assert: one media source per audio element, analyser tap removed on detach, repeat detach safe, pause/end/error stops rAF, new TTS element can attach, stale attachment cannot update the renderer.

- [ ] **Step 2: Run and observe lifecycle failures**

Run: `node --no-warnings scripts/verify_lip_sync.mjs`

- [ ] **Step 3: Wire lip sync to every Mini ZENO TTS path**

Attach when reply or thinking-ack audio starts; detach and revoke URLs on ended/error/barge-in/replacement. Map open/close to the current renderer mouth/expression interface. Do not create another `AudioContext` for an already-bound element and never close a cached context that the element will reuse.

- [ ] **Step 4: Verify live voice-first experience**

Record wake-to-visible-reaction, speech-start-to-mouth-motion, barge-in-to-audio-stop, reply audio continuity while dragging, and absence of a persistent chat surface. Capture median and worst of at least ten local turns; separate animation cost from provider/network latency.

- [ ] **Step 5: Commit**

Commit: `feat(character): synchronize companion expression with voice`

---

### Task 7: End-to-end acceptance and handoff — SHARED

**Files:**
- Modify: `docs/agent_handoffs/CODEX_CHARACTER_HANDOFF.md`
- Modify: `docs/superpowers/reports/2026-09-10-zeno-companion-live.md`
- Modify: `docs/superpowers/reports/2026-09-10-zeno-click-through-live.md`

**Interfaces:** All preceding tasks.

- [ ] **Step 1: Run deterministic suites**

```powershell
python -m pytest tests/test_companion_motion.py tests/test_mini_overlay.py -q
node --no-warnings --test scripts/character_support/harness.test.mjs scripts/verify_character_contracts_codex.mjs scripts/verify_character_lifecycle_codex.mjs
node --no-warnings scripts/verify_character_engine.mjs
node --no-warnings scripts/verify_character_select.mjs
node --no-warnings scripts/verify_character_renderers.mjs
node --no-warnings scripts/verify_character_sprite_integration.mjs
node --no-warnings scripts/verify_desktop_director.mjs
node --no-warnings scripts/verify_screen_awareness.mjs
node --no-warnings scripts/verify_lip_sync.mjs
```

- [ ] **Step 2: Stress lifecycle and motion**

Perform 1,000 walk replacements, 1,000 point replacements, 100 runtime init/dispose cycles, 100 renderer swaps, and 50 drag/auto-walk conflicts. Record timer/listener/thread/root counts before and after. Counts must return to baseline after settling.

- [ ] **Step 3: Execute the reference-video acceptance flow**

Start ZENO as the compact full-body character; converse by voice; open an allowed application/panel; confirm ZENO remains above it without focus theft, reacts locally, moves/looks/points toward it, speaks the result, accepts owner drag, and restores safely after restart/display change.

- [ ] **Step 4: Verify non-regression boundaries**

Confirm one mini window, one microphone owner, one assistant conversation path, registered tools only, no renderer-to-tool imports, no security-scope changes, and no restart of active browser/terminal/media/tool processes during movement.

- [ ] **Step 5: Independent review**

Request read-only review of the exact commit range. Resolve critical/important findings, rerun the full commands, and update reports with exact outputs and limitations.

- [ ] **Step 6: Handoff without merging Claude's branch automatically**

List commits in dependency order, files Claude must review, live evidence, known limitations, and any expected failing policy probes. Claude/user chooses cherry-pick or integration. Preserve the worktree until integration is verified.

## Plan self-review

- Coverage: native movement, lifecycle, gaze, spatial targeting, selective input, voice/lip state, fallback, recovery, performance, stress and live Windows evidence map to Tasks 1–7.
- Isolation: Task 1 is immediately Codex-owned. Tasks 2–6 name Claude-owned files and cannot be edited in parallel until handed off. Task 7 is shared verification.
- Interface consistency: `walk_companion_to`, `cancel_companion_walk`, `dispose`, director target methods, and interaction bridge names are defined once and reused consistently.
- Intentional limitation: true per-pixel pass-through may require native host support beyond pywebview's public API. The plan requires an explicit interaction fallback and evidence instead of claiming unsupported behavior.
