# Codex / Claude coordination

Two agents work in this repo. This file keeps them out of each other's way.

## CLAUDE OWNS — ZENO Anywhere (remote reachability)

Everything that makes ZENO reachable from a phone/browser, securely:

| area | files |
|---|---|
| supervisor / persistence / recovery | `reyes_agent/remote_access/anywhere.py` |
| tunnel gateway | `reyes_agent/remote_access/tunnel.py` |
| Netlify rendezvous (PC side) | `reyes_agent/remote_access/rendezvous.py` |
| Netlify rendezvous (function) | `netlify/functions/endpoint.mjs` |
| Netlify launcher + build | `web/index.html`, `netlify.toml`, `package.json`, `scripts/build-config.js` |
| authenticated remote API | `reyes_agent/remote_access/cloud_api.py` |
| fail-closed boundary | `reyes_agent/remote_access/boundary.py` |
| owner auth / trusted devices | `reyes_agent/auth/owner.py`, `reyes_agent/auth/provision.py` |
| device link / command queue | `reyes_agent/remote_access/device_link.py` |
| desktop agent | `reyes_agent/remote_access/desktop_agent.py` |

Owner-facing entry point: **https://zenoai321.netlify.app** (Netlify site
`zenoai321`, account `owntred399`).

## CODEX OWNS — ZENO evolution

- GitHub research for improvements
- core stability, performance, architecture research
- agent and memory improvements
- general ZENO evolution

## SHARED FILES — touch with care

Both sessions may need these. Edit the smallest section; preserve the other's
changes; review the diff.

- `reyes_agent/config.py` — config for every subsystem
- `reyes_agent/web.py` — the FastAPI app both remote and core routes live on
- `reyes_agent/tools/__init__.py` — the tool registry
- `.env.example`, `.gitignore`
- `reyes_agent/agent.py` — the shared turn loop

## OBSERVED CO-DEVELOPMENT

The ZENO Anywhere files above (`anywhere.py`, `rendezvous.py`,
`endpoint.mjs`, `web/index.html`) have been edited by BOTH sessions this
cycle. The changes have been complementary and are kept: timing-safe secret
comparison and a 90s staleness window in the rendezvous function, a matching
`PUBLISH_EVERY_S=30s` refresh and `reap_failure` in the supervisor. If you are
Codex and these are yours: they are good, they are kept, and Claude built the
persistence/recovery/auto-start around them. Please leave ZENO Anywhere to
Claude from here to avoid two hands on the same wheel.

## POTENTIAL CONFLICTS

- **`web.py` startup** — Claude's supervisor spawns `uvicorn reyes_agent.web:app`
  on port 8768. If Codex changes app startup, the remote server inherits it.
- **`config.PHONE_COMPANION_PORT` (8768)** — the whole remote chain assumes it.
  Do not change without telling Claude.
- **`boundary._PUBLIC_REMOTE_PREFIXES`** — the allow-list that decides what a
  tunnelled request may reach. Claude owns it; a careless addition here is a
  remote-exposure bug.

## NON-DESTRUCTIVE GIT

Neither session runs `git reset --hard`, `git clean -fd`, forced checkout, or
forced push. Uncommitted work in `presentation/*.json` belongs to the other
session and is left untouched.

## RECENT CLAUDE CHANGES — phone→desktop latency (fast & stable)

Fixing slow/unstable phone-chat desktop automation. Root causes and fixes:

1. **Executor no longer uses the shared worker pool.** `desktop_agent.py`
   `_execute_with_heartbeat` ran interactive commands on the bounded worker
   pool, so a phone command queued behind background brain work for one of the
   ~4 slots (20–30s, intermittent). It now runs on a dedicated per-command
   thread (heartbeat + timeout preserved). Also `POLL_IDLE_S 3→1`.
2. **`provider.warm()` (NEW, additive).** The lazy `import openai` (~11s on this
   box) fired inside the FIRST turn *while holding the turn lock*, freezing the
   server on first use. `provider.warm()` pre-imports the SDK + builds the
   configured clients (network-free) up front. Codex: this only ADDS a function;
   `run_turn`/runners/retry are untouched.
3. **`web.py` startup warm-up (additive block).** A dedicated daemon thread
   calls `provider.warm()` then one throwaway `run_agent("hi")` on a private
   history to warm the network/tool path. Gated by `ZENO_BRAIN_PREWARM`.

Result: phone `ask` commands median ~2.2s (was 17–30s). Residual spikes are
hosted-model latency variance, not the queue.

## RECENT CLAUDE CHANGES — unified phone+laptop tool access

Phone and laptop already share ONE brain and tool registry; the gap was the
approval gate, not a separate implementation. Landed (committed as one unit):

- **Fingerprint auto-approve** — `confirmation.owner_auto_approve` (context-var,
  audited) + a denylist (`remote_auto_run_allowed`) so a WebAuthn-elevated
  trusted-owner turn runs ordinary tools directly, but never arbitrary-exec /
  irreversible / public / security tools. `tools.run_tool` honours it.
- **Session elevation** — `owner.py` `passkey_stepup_options` /
  `finish_passkey_stepup` / `session_elevated` (10-min, in-memory).
- **T21 knowledge** — new `tools/t21_tools.py` (+ `capability.py` routing).
- **Diagnostics** — new `remote_access/diagnostics.py` capability/health snapshot.

**NOW COMMITTED TOGETHER (98ec711).** At the user's request the wiring and your
`live_desktop` + `agent_presence` feature were co-committed to keep the tree
buildable (104 tests green). Both sets of edits sit side by side in the shared
files (`cloud_api.py`, `desktop_agent.py`, `app.html`, `web.py`, `agent.py`,
`agent_space.py`, `anywhere_gateway.py`, static presence UI) — all preserved.
Left untouched for you: `presentation/*.json`, `.env.example`, `AGENT.md`,
`ROADMAP.md`.

**Fix that also helps live_desktop:** "webauthn origin is not allowed" — an
ephemeral tunnel URL has no stable WebAuthn RP id, so the fingerprint step-up
can't run there. Added `/auth/stepup/phrase` (reusing the unlock phrase) and a
client `unlockActions()` that tries the fingerprint, then falls back to the
phrase. Your `live-desktop` REMOTE_CONTROL start now calls `unlockActions()` too,
so remote-control elevation works over the tunnel. For a true fingerprint,
configure a stable `ZENO_PUBLIC_DOMAIN` (real domain / named tunnel).

## RECENT CLAUDE CHANGES — action-unlock actually works on the phone

The step-up gate (previous section) was correct server-side but unusable from a
real phone, so consequential actions ("open Slack", "open Chrome", "send a
message") kept returning `needs_stepup` and looked like missing tools. Two
client bugs in `static/app.html`, both fixed (Claude domain — phone UI):

1. **`window.prompt()` phrase fallback** — blocked/ignored in mobile browsers
   and every installed PWA, which is how the phone reaches ZENO. Replaced with
   `askPhraseInline()`, a self-contained in-page overlay that always works.
2. **Pill hidden without WebAuthn** — `unlockpill.hidden = !PublicKeyCredential`
   stranded phrase-only phones (the tunnel case). Now shown when WebAuthn is
   present OR an unlock phrase is configured (checked via `/auth/unlock/status`).

Net effect: tap "🔒 Tap to unlock actions" (or trigger any consequential
command) → fingerprint if possible, else a reliable phrase prompt → session
elevates → the laptop executes. No server/auth logic changed; `stepup/phrase`
and the elevation model are untouched.

## RECENT CLAUDE CHANGES — build-next stability layer (from Expansion Pack 3 #258)

Building the optimized P0/P1 list one at a time, each self-contained + tested.

**1. FailureClassifier hardened (`failures.py`).** Kept the existing
`classify(message, status_code)` verbatim (still used by `tools/__init__.py`,
policy, etc.). ADDED, backward-compatibly: `classify_exception(exc)` (type-first,
message fallback), `RETRYABLE`/`TRANSIENT` sets, `RECOVERY` hints, `is_retryable`,
`describe`, `explain`. Shared-file touch: `tools/__init__.py`
`classify_tool_result` now ADDS `retryable`+`recovery` keys to failed results
(via `failures.explain`); `error_category` value is unchanged. 46 tests green.

**2. ActionVerifier (`action_verifier.py`, NEW).** One uniform verdict layer:
`verify(action, args, result) -> Verdict{verified, verifiable, method, evidence}`.
Evidence-first (honours a tool's own `ok`+`evidence`), then an independent
OS-level check (process running via psutil / file on disk), else
`verifiable=False` -- never a false pass. Extensible via `register()`. Wired
into `desktop_agent._run_tool`: an `open_app` that didn't self-verify is now
corroborated by "is the process actually running?", upgrading a false failure
to a verified success on real evidence only. 22 tests green.

**3. ToolReputation (`tool_reputation.py`, NEW).** Bounded rolling window
(WINDOW=100) of recent tool outcomes -> `reputation(tool)` = success_rate,
Wilson-lower-bound `confidence` (sample-size aware: 2/2 < 190/200), median/p95
latency, trailing-failure streak. `best_of([...])` for the router; in-memory,
thread-safe, never raises. Wired via `desktop_agent._note_reputation` on every
remote tool run (success/failure + latency). Codex: adopt for all tools by
calling `tool_reputation.record(name, ok, latency_ms=…)` from `run_tool` if you
want registry-wide coverage -- the API is stable. 18 tests green.
