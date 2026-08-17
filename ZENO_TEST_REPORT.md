# ZENO Full-System Test Report

Date: 2026-08-17

## Baseline before this upgrade

- Maintained repository suite: **960 passed**, 4 existing FastAPI lifespan
  deprecation warnings, 0 failed, 308.81 seconds.
- Live start state: Stage 2, 3/3 core services ready, four workers, queue zero,
  persistent WebView2 profile, responding Mini Orb.

## Upgrade regression coverage

`tests/test_jarvis_ultron_upgrade.py` covers transparent/inverted scoring,
required factor validation, evidence typing/source enforcement, persistence,
token-safe citations, expiry, existing-agent plans, lazy tool registration,
guarded deletion, deep routing, truthful lifecycle verification, explicit
plugin loading, learned-skill prompt delivery, capability detection, and
nonblocking notification submission. It also deterministically reproduces the
Website Studio cancellation/watchdog race and proves an owner cancellation
cannot be overwritten by a non-zero process-exit observation.

Current focused results:

- Upgrade-only regression file: **13 passed** (included in the full run).
- Upgrade plus Phase 21 runtime: **31 passed** before the cancellation test was
  added; the complete run below includes that additional regression.
- Phase 2/capability/creator/security/production affected set: **78 passed**.
- Website Studio plus upgrade regression set: **49 passed**.
- Voice, Website Studio, and workflow set: **50 passed**, 4 existing FastAPI
  lifespan deprecation warnings.
- Real Node timeout/cancel/process-tree test: **5 consecutive passes**; an
  unrelated Node process remained alive.

## Static checks

- `python -m compileall -q reyes_agent tests`: pass
- `python -m pip check`: pass
- `node --check` across 11 runtime JavaScript files: pass
- `git diff --check`: pass
- tracked-secret/generated-file audit: pass; `.env.example` is intentionally
  tracked, `.env` is ignored

## Final run

An intermediate whole-project run completed with **973 passed, 5 non-failing
warnings**. During that run the real Windows UI Automation probe emitted COM
`0x80040155` (interface not registered) diagnostics, but the probe and suite
completed successfully; the same test also passed in isolation. Claude then
added routing coverage concurrently. The final combined repository run,
including those changes and the lazy-audio regression, completed with
**1,010 passed, 4 known FastAPI lifespan warnings, 0 failed in 236.84
seconds**.

Live desktop verification against the running application:

- one native `ZENO Mini Orb` window, Windows `Responding=True`;
- visible, not minimized, `TOPMOST` and `NOACTIVATE` native flags present;
- a forced native hide was observed and the existing overlay watchdog restored
  the same window in 4,280 ms; it remained responsive and was not recreated;
- Stage 2 ready, 3/3 core services ready, 4/4 bounded workers alive, queue 0;
- central health `ONLINE`; voice, memory and core `ONLINE`; browser `STANDBY`;
- Mini Orb microphone `MICROPHONE_READY` with real audio received, Windows
  consent allowed, eight input endpoints detected, Deepgram configured;
- ElevenLabs synthesis configured; 13/14 specialists have distinct voices,
  while JARVIS deliberately falls back to ZENO's voice;
- three harmless real provider turns returned the exact requested replies in
  1,651 ms, 1,524 ms and 1,052 ms.

Measured Mini Orb first-window times were **7,513 ms** and **10,369 ms** while
reusing a concurrently managed backend under development load. Both windows
were responsive, but this remains above the sub-three-second target. The
second host was then terminated when Claude's benchmark intentionally replaced
all Python processes; a clean desktop-owned launch is recorded separately once
that benchmark releases the port.
