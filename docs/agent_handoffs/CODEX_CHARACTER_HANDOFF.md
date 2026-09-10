# Codex Character Support Handoff

## CURRENT CODEX TASK

Independent contract tests, lifecycle/performance review, gap-only research, and the isolated native motion primitive for Claude's 2D ZENO character integration. Baseline: `fb38214`.

## FILES CODEX OWNS

- `scripts/character_support/harness.mjs`
- `scripts/character_support/harness.test.mjs`
- `scripts/verify_character_contracts_codex.mjs`
- `scripts/verify_character_lifecycle_codex.mjs`
- `reyes_agent/companion_motion.py`
- `tests/test_companion_motion.py`
- `docs/superpowers/specs/2026-09-10-zeno-living-companion-design.md`
- `docs/superpowers/plans/2026-09-10-zeno-living-companion.md`
- `docs/superpowers/plans/2026-09-10-zeno-character-support.md`
- This handoff

## FILES CODEX MUST NOT TOUCH

Claude owns `character.js`, `character_brain.js`, `character_select.js`, character renderers/manifests/assets, desktop/mini entry points, panel manager, overlay shell and boot integration. `visual_events.js` is a shared interface and remains read-only here. The shared checkout's unrelated dirty files are out of scope.

## VIDEO-DERIVED TARGET EXPERIENCE

Watched `WhatsApp Video 2026-09-09 at 11.11.05 AM.mp4` in full (32.428 s, 478x850, 30 fps). Treat it as experiential reference, not source code or proof of hidden functionality:

- Directly visible: a small character lives over the Windows desktop, remains present while an application/browser is shown, speaks conversationally, and comments with personality. No separate chat window is the focal experience.
- Claimed by dialogue/captions but not technically demonstrated: that the character was downloaded two minutes earlier, is in “full control,” and can do anything the user says.
- Not demonstrated by this clip: dragging, pixel hit testing/click-through, walking, multi-monitor repair, reliable tool execution, resource usage, security boundaries, or state restoration.
- Acceptance direction for ZENO: resident transparent companion + immediate local reaction + voice conversation + capability/tool result shown in the normal app/panel, while preserving the supplied orange-haired ZENO identity.

The companion prompt kit is reference material only. Its PySide6 proposal must not replace the existing pywebview architecture without an explicit integration decision. Its useful requirements—transparent overlay, selective hit testing, bounded movement, local animation timer, app-state callbacks, multi-monitor safety—should map onto existing ZENO seams.

## FINDINGS

1. **Runtime disposal is absent.** `character.js:222,237,264,318,323,411,451` owns intervals/listeners; the API returned at line 459 exposes no disposal. Removing 25 test DOM roots retains 75 timers (50 intervals, 25 timeouts) and 125 listeners. Proposed minimal change: one idempotent lifecycle method that cancels every owned timer/RAF, removes named listeners and the owned root. Do not add cleanup solely for tests; renderer replacement needs it.
2. **Continuous cursor motion starves gaze.** `onPointerMove` at line 403 restarts a 120 ms trailing timer. In a deterministic 60-event/960 ms trace, gaze remained `0` until movement stopped, then reached `4.5`. Proposed minimal change: throttle/sample ongoing motion while retaining delayed acquisition and neutral timeout.
3. **Inactive runtime still works.** `setActive(false)` at line 346 hides and cancels the primary blink timeout only. Emotion decayed from `1` to `0.936` over a simulated 5 s; pointer events still drove gaze to `{x:4.5,y:2.88}`; visibility restored one hidden-character blink timeout. Proposed change: central active/disposed gates for all callbacks, with an explicit policy for whether emotion time pauses or merely rendering work pauses.
4. **Spatial contract is open-only.** The inspected seam contains `zeno:panel-opened` and aggregate `zeno:panels-state`, not panel moved/resized/closed target events. Existing methods recalculate from the current character rectangle when called, but no event updates a tracked target. Claude should define semantic spatial target update/clear events or a DesktopDirector subscription; avoid hardcoded screen coordinates.
5. **Research license wording:** simple-desktop-pet README declares MIT, but its tracked tree has no LICENSE/COPYING/NOTICE and package.json has no license field at local commit `1a265174e203169a75d0b525d246f1e26cf0b4e4`; asset provenance is unverified. Local source: `_research/character_engine/simple-desktop-pet`; upstream reference: `github.com/Evanfan007/desktop-pet`. Keep reference-only treatment.
6. **Research lifecycle pattern:** buddy's `PetSprite.svelte:36,64-67,90-92` combines timeout cancellation with a generation token to reject stale callbacks. Its renderer reports interactive regions while native `avatar-window.ts:79` owns OS click-through. This separation suits ZENO: renderer reports hit-test intent; pywebview/Windows shell owns native input behavior.
7. **Research timing caution:** simple-desktop-pet advances frames per RAF under a 60 Hz assumption. ZENO should base animation progress on elapsed time or configured sprite FPS. Its state machine starts in IDLE and rejects the initial IDLE transition, so the existing research statement that startup arms its idle timer is inaccurate.

## IMPLEMENTED

- Deterministic, dependency-free browser boundary with fake chronological timer/RAF scheduling, runaway guard, listener accounting, distinct DOM roots and global restoration.
- Real-module contract tests for event isolation/snapshot behavior, 1,000 subscription cycles, emotion bounds/decay/snapshot isolation, protected pipeline states, gaze/gesture geometry and timer replacement.
- Executable known-gap tests. Normal mode reports TODOs; `--strict` makes them CI-failing. This prevents unresolved product behavior from being presented as green.
- One production module, `reyes_agent/companion_motion.py`, added in this isolated branch. It uses one bounded daemon worker, condition-based plan replacement, monotonic easing, explicit cancellation, idempotent shutdown, and callback isolation. It does not import or modify the desktop shell, voice system, tools, renderer, or Claude-owned files.
- No asset pipeline created because Claude is actively adding manifest/renderer/art files in the shared checkout.

## TESTS

- `node --no-warnings --test scripts/character_support/harness.test.mjs`: 5 pass.
- `node --no-warnings --test scripts/verify_character_contracts_codex.mjs scripts/verify_character_lifecycle_codex.mjs`: 19 pass, 5 expected TODO gaps, exit 0.
- `node --no-warnings scripts/verify_character_lifecycle_codex.mjs --strict`: 7 pass, 4 accepted failures, 1 unresolved-policy TODO, exit 1. Accepted failures reproduce the runtime findings above; inactive emotion timing remains undecided.
- Fresh broad run: `verify_character_engine.mjs`, `verify_character_select.mjs`, and `verify_orb_emotion_engine.mjs` all exited 0; the combined new Node run reported 24 pass and 5 expected TODO gaps.
- `python -m pytest tests/test_visual_performance.py -q`: 4 pass, 1 pre-existing failure. The August test prohibits any `setInterval(` in `orb.js`; the September emotion-engine commit `d8a157b` intentionally added one. This is an obsolete source-text assertion on baseline `fb38214`, unrelated to this branch's changes. Claude/test owner should replace it with a behavioral work-rate assertion rather than globally permitting or forbidding timer syntax.
- `python -m pytest tests/test_companion_motion.py -q`: 11 pass. Repeated five times: 11 pass on every run.
- `python -m pytest tests/test_companion_motion.py tests/test_mini_overlay.py -q`: 16 pass after installing the repository-pinned `pywebview==6.2.1` into the isolated environment. The first attempt failed during collection solely because that declared dependency was absent.

- Existing `verify_character_engine.mjs` showed one intermittent gaze failure during final verification: its fixed 400 ms wall-clock sleep observed only one damping frame (`x=0.81`, expected `>1`). Ten immediate isolated reruns all passed. Treat this as a pre-existing timing-sensitive test (1 observed failure in 11 final attempts), not proof of a runtime regression; migrate it onto the deterministic clock or a condition-based wait.

## PERFORMANCE FINDINGS

- Synthetic only: 1,000 point replacements retained one point timeout, did not increase listener count, and returned to the initial three standing timers after expiration.
- The Node run completed that test in single-digit milliseconds on this host, but runner timing is not a desktop FPS/latency benchmark.
- Real pywebview CPU, RAM, frame pacing, click-through and microphone/voice responsiveness remain unmeasured. Do not infer them from this harness.

## CHANGES CLAUDE SHOULD REVIEW

- Decide lifecycle API name (`dispose` or `destroy`) and integration call sites before implementing finding 1.
- Resolve the active-vs-disposed policy and continuous-gaze scheduling in Claude-owned runtime.
- Define spatial target update/clear events before DesktopDirector movement tests are added.
- Preserve `setState`, `setEmotion`, `lookAt`, `walkTo`, and `pointAt` as semantic renderer-independent interfaces.
- Re-run these tests on Claude's current uncommitted renderer integration; this branch intentionally starts at `fb38214` and does not contain his newer files.

Research audit commands: `git ls-files | rg '(LICENSE|COPYING|NOTICE)'`, `git show HEAD:package.json`, and targeted README/source reads. Buddy lifecycle/input reference: local `_research/character_engine/buddy` at `4ac2428e46ff40505d61df15afbe07252b334902`, upstream `github.com/AG9898/buddy`.

## READY COMMITS

- `6604923` — deterministic browser harness and implementation plan
- `f04e97b` — semantic/lifecycle contract tests
- `3cccdc7` — approved living desktop companion design
- `b7e1846` — concrete living companion implementation plan
- `bb1d425` — bounded native motion controller and TDD suite
- Final handoff commit is the commit containing this file.

## BLOCKERS

- Claude's current uncommitted renderer/manifest/art state cannot be safely copied into this isolated branch. Integration verification belongs in Claude's checkout after cherry-picking these support commits.
- Native bridge wiring, runtime disposal/gaze repair, spatial target tracking, selective click-through, and live voice/lip verification remain Claude-owned Tasks 2–6. The complete task cannot honestly be called integrated until those dirty active files are committed or explicitly handed off.
- The video does not prove the claimed “full control” capability; that requires separate tool execution tests outside this character-support scope.
