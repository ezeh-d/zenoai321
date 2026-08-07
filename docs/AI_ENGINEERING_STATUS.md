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
**Task:** Remote Access subsystem — domain/CORS, policy, gateway, /api/v1
**Files (claimed):**
- `reyes_agent/remote_access/` (new package — all files)
- `docs/MOBILE_API.md` (new)
- `docs/AI_ENGINEERING_STATUS.md`
- `.env.example` (remote-access keys only)

**Will also need short, announced edits to** (shared — will keep minimal and
commit immediately so CODEX is never blocked):
- `reyes_agent/web.py` — mount the v1 router + CORS middleware
- `reyes_agent/config.py` — domain/remote flags

**Started:** 2026-08-07
**Status:** ACTIVE

---

**Agent:** CODEX
**Task:** _(unclaimed — CODEX to fill in)_
**Files:** —
**Status:** —

Suggested parallel work that does **not** touch CLAUDE's claimed files:
- `tests/test_remote_*.py` — auth attack cases, pairing abuse, WS reconnect
- Security review of existing `reyes_agent/phone_security.py` (CLAUDE is
  reusing it, not editing it)
- Website Studio regression tests
- Performance/idle-CPU checks

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

**Issue:** No CORS middleware exists anywhere in `web.py`. Fine while the
phone page is same-origin; becomes a hard blocker the moment
`app.zenoassitant.com` calls `api.zenoassitant.com`.
**Severity:** HIGH for the domain objective
**Found by:** CLAUDE
**Suggested owner:** CLAUDE (in progress)

**Issue:** `/ws/phone` does not validate the `Origin` header. Any origin can
attempt a WebSocket upgrade with a stolen/ambient cookie.
**Severity:** HIGH (security)
**Found by:** CLAUDE
**Suggested owner:** CLAUDE (in progress)

**Issue:** No rate limiting anywhere — pairing, login and command endpoints
are brute-forceable.
**Severity:** HIGH (security)
**Found by:** CLAUDE
**Suggested owner:** CLAUDE (in progress)

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
