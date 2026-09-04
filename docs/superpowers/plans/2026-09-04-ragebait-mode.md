# ZENO Ragebait Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast, consent-scoped owner-to-ZENO Ragebait mode without affecting external actions or responsiveness.

**Architecture:** A local `reyes_agent.ragebait` state module owns consent, intensity, battle state, bounded anti-repeat history, motion cooldown, and Event Bus facts. Existing humour and the existing agent turn consume its directive. Existing panel infrastructure displays an active battle event-driven only.

**Tech Stack:** Python, pytest, existing Event Bus and panel manager; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-04-ragebait-mode-design.md`

## Global Constraints

- Only an owner conversation is eligible; external messages and all tool actions are always neutral.
- State starts off at restart and stores no transcript, secret, voice, or long-term memory.
- Intensity is exactly `0..5`; stop and serious/sensitive context precede generation.
- No polling, timers, workers, new microphone, animation loop, or physical-event model call.

---

### Task 1: Build the local state boundary

**Files:** Create `reyes_agent/ragebait.py` and `tests/test_ragebait.py`.

**Interfaces:** `handle(message, *, serious=False, now=None) -> dict`, `directive(message, *, audience, serious=False, now=None) -> str`, `record_reply(reply)`, `on_motion(event_name, *, now=None)`, `status()`, `reset()`.

- [ ] Write failing tests for activation, bounded intensity, battle start/end, stop, serious override, third-party isolation, repeat avoidance, shake cooldown, restart-off state, and redacted events.

```python
def test_stop_and_external_context_take_precedence():
    from reyes_agent import ragebait
    ragebait.reset(); ragebait.handle("ragebait me")
    assert ragebait.directive("send a Slack message", audience="external_action") == ""
    assert ragebait.handle("enough")["enabled"] is False
```

- [ ] Run `python -m pytest -q tests/test_ragebait.py`; expect module import failure.
- [ ] Implement one `RLock`-protected state object, with `deque(maxlen=8)` normalized reply fingerprints and copied snapshots. Clamp intensity with `max(0, min(5, value))`. Publish compact `ragebait.enabled`, `.disabled`, `.intensity_changed`, `.battle_started`, `.round_completed`, `.battle_finished`, and `.reaction` events outside the lock.
- [ ] Re-run `python -m pytest -q tests/test_ragebait.py`; expect pass, then commit as `feat: add consent-scoped ragebait state`.

### Task 2: Extend the existing one-turn humour policy

**Files:** Modify `reyes_agent/humour.py`, `reyes_agent/agent.py`, `tests/test_humour.py`, and `tests/test_ragebait.py`.

**Interfaces:** `humour.directive` calls `ragebait.handle` and then `ragebait.directive` for `audience="owner_conversation"`; `agent.run_agent` still makes exactly one existing `run_turn` call.

- [ ] Write failing regression test that patches `agent.run_turn`, activates Ragebait, sends one comeback request, and asserts exactly one captured system prompt containing `Ragebait`.
- [ ] Run `python -m pytest -q tests/test_humour.py -k ragebait`; expect failure.
- [ ] Add the local bridge before existing humour branches. Stop/serious return no directive. `record_reply` may update only bounded Ragebait state after a normal response. Do not change tool permission, outbound-message, provider, or voice routing.
- [ ] Add provider-failure test that terminates an active battle safely without breaking the normal response fallback.
- [ ] Run `python -m pytest -q tests/test_ragebait.py tests/test_humour.py tests/test_charm_engine.py`; expect pass, then commit as `feat: route owner ragebait through humour policy`.

### Task 3: Add a disposable live battle panel

**Files:** Modify `reyes_agent/panels.py`, `reyes_agent/web.py`, `reyes_agent/static/panels/manager.js`, `tests/test_panels.py`; create `reyes_agent/static/panels/ragebait.js` and `tests/test_ragebait_panel.py`.

**Interfaces:** register `PANELS["ragebait"]` with `support="live"`; expose `GET /api/panels/ragebait` returning `ragebait.status()`; panel opens only for `ragebait.battle_started`, updates from `ragebait.*`, and closes for `.battle_finished` / `.disabled`.

- [ ] Write failing tests for live registry metadata, safe snapshot shape, renderer lifecycle events, and the absence of `setInterval(`.
- [ ] Run `python -m pytest -q tests/test_panels.py tests/test_ragebait_panel.py`; expect failure.
- [ ] Register the live panel and endpoint. Renderer uses the existing drag/resize/minimize manager, displays only intensity, round/max round, and user/ZENO entertainment scores, and disposes its subscription on close. It never maps a conversational tool or capability to the panel.
- [ ] Re-run `python -m pytest -q tests/test_panels.py tests/test_ragebait_panel.py`; expect pass, then commit as `feat: add event-driven ragebait battle panel`.

### Task 4: Evidence-based closeout

**Files:** Modify `ROADMAP.md`, `tests/test_ragebait.py`, and `tests/test_ragebait_panel.py`.

- [ ] Add an end-to-end event redaction/no-voice-collision assertion.
- [ ] Run `python -m pytest -q tests/test_ragebait.py tests/test_ragebait_panel.py tests/test_humour.py tests/test_charm_engine.py tests/test_charm_integration.py tests/test_panels.py tests/test_proactive_panel.py tests/test_phase22_stability.py`; expect zero failures.
- [ ] Run `git diff --check` and `python -m compileall -q reyes_agent/ragebait.py reyes_agent/humour.py reyes_agent/agent.py reyes_agent/panels.py reyes_agent/web.py`; expect exit code zero.
- [ ] Update Roadmap with only verified implementation facts and explicitly retain the manual Windows visual panel check as a remaining validation item. Commit as `test: verify ragebait mode integration`.
