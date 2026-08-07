# ZENO — AI Engineering Status

Coordination channel between **CLAUDE** (implementation/integration) and
**CODEX** (validation/testing/second pass). Engineering coordination only —
no reasoning dumps, no long logs.

**Protocol:** claim files under ACTIVE WORK before writing. Reading another
agent's files is always fine; writing to them is not. Found a problem in a
file you don't own? Record it under ISSUES FOUND and keep moving.

---

## REPO STATE (2026-08-07)

Last commit: `be10e1a Re-enable guarded ZENO performance features`

Everything after that is **uncommitted** — 24 modified, 31 untracked, from
both agents. Full suite currently **284 passed, 0 failed**.

That is a lot of unprotected work. Proposal: commit the current green tree
once as a joint checkpoint, then both agents move to small scoped commits so
each side can review exactly what changed. CLAUDE will not commit anything
that discards or rewrites CODEX's work — commits preserve, they do not
overwrite.

---

## ACTIVE WORK

**Agent:** CLAUDE
**Task:** — (Remote Access phase 1 landed; files released)
**Status:** IDLE — files below are now free for CODEX

**Released by CLAUDE (safe to edit):**
`reyes_agent/remote_access/*`, `docs/MOBILE_API.md`, `.env.example`,
`tests/test_remote_access.py`

---

**Agent:** CODEX
**Task:** _(unclaimed — CODEX to fill in)_
**Files:** —
**Status:** —

Highest-value parallel work now that phase 1 is committed:
- **Attack-test the new surface.** Put them in
  `tests/test_remote_security.py` so we do not collide with
  `tests/test_remote_access.py` (CLAUDE's). Worth hitting: session fixation,
  replayed `request_id`, Bearer vs cookie CSRF asymmetry, `Origin: null`,
  WebSocket upgrade with a revoked session mid-stream, pairing brute force
  across rotating identities.
- Review `reyes_agent/remote_access/gateway.py` — it calls
  `web._conversation_turn` through the worker pool. Confirm a remote request
  cannot starve the local chat path under load.
- The phase21 browser-runtime timing flake (see ISSUES).

---

## COMPLETED

**Agent:** CLAUDE
**Task:** Website Studio — four architectural limitations
**Tests:** `tests/test_website_autonomy.py` 14/14; full suite 284/284
**Summary:** autonomous model-patch repair (validated, checkpointed,
rollback-on-worse, bounded); webpack/rollup/vitest analyzer plugins;
non-blocking job runner (`executors/jobs.py`) with per-kind timeouts and
scoped process-tree cancellation; dependency-aware rollback via manifests
(`npm ci`/`npm install`, never snapshotting `node_modules`).

**Agent:** CODEX
**Task:** Website Studio base layer + static repair loop
**Summary:** `website_builder.py` metadata/checkpoints/`safe_project_root`,
`coding.repair_project` bounded static repair with rollback, visual inspect,
Website Studio panel wiring.

**Agent:** CODEX
**Task:** Mini Orb wake commands
**Commit:** `1d61af9 fix(voice): run Mini Orb wake commands`
**Reviewed by:** CLAUDE — `test_voice_handoff.py` 3/3 green after my remote
changes; no interaction with the remote layer.

**Agent:** CLAUDE
**Task:** Remote Access phase 1 — domain/CORS/policy/gateway/API
**Commits:** `6779063`, `6f14f2e`, `ca5700a`
**Tests:** `tests/test_remote_access.py` 22/22; full suite **317 passed,
0 failed** after the regression fix.
**Verified end-to-end** against a live server on a spare port: pair →
session → "Hello ZENO" → real reply from the same brain (12s) → FINANCIAL
and SENSITIVE refused 403 → read-only views → disallowed website action
refused → revoked device 401 immediately → reconnect → audit carries no
token.

---

## ISSUES FOUND

**Issue:** `test_phase21_runtime.py::test_browser_runtime_returns_at_its_deadline_without_blocking_caller`
is a timing flake — measured 1 failure in 5 runs. Asserts `< 0.12s` wall
clock against a `0.04s` timeout, ~30ms headroom, fails under load.
**Severity:** LOW (test-only; no product impact)
**Found by:** CLAUDE
**Suggested owner:** CODEX
**Suggested fix:** assert the semantic (caller returned before the stalled
action finished) rather than a wall-clock bound — stronger and load-independent.

**Issue:** `XAI_API_KEY` in `.env` is rejected by x.ai ("Incorrect API key
provided"). Provider fallback is wired and proven with stubs, but this
machine effectively has one working provider, so a Gemini outage still
leaves ZENO mute.
**Severity:** MEDIUM (operational, needs owner action — not a code bug)
**Found by:** CLAUDE
**Suggested owner:** OWNER

**RESOLVED (6f14f2e, CLAUDE):** no CORS anywhere; `/ws/phone` did not check
`Origin`; no rate limiting. All three fixed and covered by
`tests/test_remote_access.py`.

**Issue:** `SameSite=strict` on `zeno_phone_session` means a browser will
never send it from `app.zenoassitant.com` to `api.zenoassitant.com`. Worked
around by accepting `Authorization: Bearer` for the same session token — the
companion must use the header, not the cookie. Documented in MOBILE_API.md.
**Severity:** MEDIUM (design constraint, not a defect)
**Found by:** CLAUDE
**Suggested owner:** — (accepted; revisit only if a same-site deployment is chosen)

**Issue:** Sessions expire at 30 minutes with no refresh-token rotation; the
phone must redo a WebAuthn assertion. Acceptable but worth revisiting.
**Severity:** LOW
**Found by:** CLAUDE
**Suggested owner:** CLAUDE (phase 2)

**Issue:** `app.routes` is not a flat endpoint list once a router is
included — an `_IncludedRouter` with no `.path` appears. Broke
`test_workflow_engine`. Fixed in ca5700a by reading `app.openapi()["paths"]`.
Anything new that inspects routes should do the same.
**Severity:** LOW (test-only; no production code iterates app.routes)
**Found by:** CLAUDE (self-caused, caught by full regression)
**Suggested owner:** — (resolved)

**Issue:** The owner's desktop ZENO (pid held on :8765) runs the code from
before this session. The remote API is only present after a restart.
**Severity:** INFO
**Found by:** CLAUDE
**Suggested owner:** OWNER

---

## NEXT TASKS

| Task | Suggested owner | Dependencies |
|---|---|---|
| Remote Access: domains + CORS + WS origin check | CLAUDE | — |
| Remote Access: permission categories + rate limits | CLAUDE | domains |
| Remote Access: gateway → existing `run_agent` router | CLAUDE | policy |
| Remote Access: `/api/v1` + Website Studio remote commands | CLAUDE | gateway |
| Attack tests for pairing/session/WS | CODEX | CLAUDE marks each COMPLETE |
| Mobile API docs verified against real implementation | CLAUDE | /api/v1 |
| Fix the phase21 timing flake | CODEX | — |
| DNS/deployment steps (owner action, no auto-deploy) | CLAUDE | all above |

---

## GROUND RULES IN FORCE

- No `git reset --hard`, `git clean -fd`, or force push.
- Never discard the other agent's uncommitted work.
- Remote access is **optional**: if the tunnel, internet, or a phone session
  fails, desktop ZENO must keep working.
- Mobile commands route through the **existing** `run_agent` router. No
  second brain.
- No unrestricted shell to the phone. Website Studio safety rules stand.
- No DNS changes, no purchases, no deploys without explicit owner approval.
