# ZENO Production Reality Pass

Date: 2026-08-10
Environment inspected: `development`, explicit demo mode `false`
Starting checkpoint: `1bcfbca`
Concurrent Phase 4 commits reviewed: `f2251f0`, `233bf70`

## Standard used

`WORKING` here means a real backend was invoked, its result was observed, and
the result is not presented as more certain than the evidence. `PARTIAL` names
the exact gap. Credential presence alone is never connection evidence.

Allowed labels: `PRODUCTION_READY`, `WORKING`, `PARTIAL`, `AUTH_REQUIRED`,
`EXTERNAL_SETUP_REQUIRED`, `TEST_ONLY`, `NOT_IMPLEMENTED`.

## Implementation matrix

| Feature | State | Real backend / evidence | Auth | Persistence | Risk / remaining work |
|---|---|---|---|---|---|
| Runtime environment separation | PRODUCTION_READY | `runtime_environment.py` rejects production demo/mock flags and unsafe remote configuration | configuration | environment-specific config | Set `ZENO_ENV=production` only after public-domain setup if remote is enabled |
| Kernel and staged startup | WORKING | One `ZenoKernel`; final live Stage 2, 3/3 core services ready, 4 workers, queue 0 | local session | session snapshot + subsystem stores | FastAPI lifespan deprecation remains maintenance work |
| Mini Orb host | WORKING | Real HWND visible, non-minimized, `WS_EX_TOPMOST`, responding | signed-in Windows session | saved position and persistent WebView2 profile | WebView2 remains a material RAM/GPU cost under machine pressure |
| Owner profile / onboarding | PARTIAL | SQLite schema, indexes, roles, one-owner constraint, real dashboard setup flow; no sample user | local Windows + loopback | `identity/users.sqlite3` | Current state is `SETUP_REQUIRED`; owner must finish the visible form |
| Provider manager | WORKING | Real bounded endpoint validation; secret fingerprint only | provider keys | `providers/health.sqlite3` | OpenAI/Gemini/Ollama ONLINE; xAI AUTH_EXPIRED; Anthropic NOT_CONFIGURED |
| Model Router | WORKING | Operational state requires validated provider health; real measured latency and circuit state remain separate | provider keys | provider health + runtime metrics | Replace the rejected xAI key |
| Living Memory | WORKING | Canonical file store; real bounded read/write/delete health probe, 32 records sampled | local owner | versioned files | Optional Mem0 is disabled/uninstalled; canonical fallback is live |
| Durable skills | WORKING | Atomic JSON registry, constitution, learner, lazy list/inspect/approve/disable/delete/run tools | owner approval | one JSON per skill + audit JSONL | 0 skills currently; 127 real actions do not meet the repetition threshold |
| Skill execution verification | WORKING | Every step goes through `run_tool`; only verified completion advances | permission engine + owner approval | run history per skill | Unverified text results stop the run rather than becoming success |
| Missions | WORKING | Existing mission tools plus Phase 4 SQLite checkpoints and restart recovery tests | permission engine | SQLite migrations/checkpoints | Temporal external service deliberately not deployed |
| Agents / Council | WORKING | 14 registered specialists, bounded workers, real delegated provider contexts | provider + tool policy | event/task history | No claim that one provider equals 14 independent models; concurrency is bounded |
| Permission Centre | WORKING | UI writes durable overrides read by the one execution gate | local owner | atomic JSON | Financial execution is immutable BLOCKED |
| Consequential audit | WORKING | Append-oriented, structured, secret-redacted, rotating log | local owner | durable log, 5 MiB rotation, 3 backups | Historical test audit lines remain append-only; new regression writes are isolated |
| Typed failure recovery | WORKING | Shared categories include rate limit, offline, auth, model, timeout, permission, service crash | none | emitted/audited events | Recovery remains intentionally bounded |
| Windows automation | WORKING | Real Notepad open/focus/type/UIA readback/close; app launch verifies process/window | Windows session + permissions | action/event history | High-impact actions still require policy; UIA coverage varies by application |
| Playwright browser | WORKING | Persistent Chromium context; real navigation/read/click/fill/scroll/screenshot/close checks | saved browser profile | persistent Playwright user data | Sites can fail independently (httpbin returned a real 503 in the first smoke run) |
| Voice microphone | WORKING | Mini Orb supplied live processed audio; health returned `MICROPHONE_READY` | saved WebView2/Windows grant | persistent WebView2 profile | Driver/browser constraints can still be declined by the OS |
| Local wake word | PARTIAL | One deterministic stream/state machine; no second microphone | microphone grant | configuration | openWakeWord installed, custom trusted ZENO model not configured; phrase fallback remains |
| ElevenLabs speech | WORKING | Existing bounded real TTS path and cache; failure isolation tests pass | ElevenLabs key | generated cache (ignored by Git) | Voice-list permission scope limitation remains documented |
| Gmail | PARTIAL | Real Gmail IMAP authentication and read-only INBOX selection succeeded; no message content read during this pass | app password present | existing settings only | Read-only IMAP, not OAuth/API; send/archive/labels are not production integrations |
| Telegram | PARTIAL | Real Bot API `getMe` succeeded; send path validates `ok` + provider message ID | bot token present | configuration | Owner chat allowlist is empty, so inbound control correctly fails closed |
| Slack | AUTH_REQUIRED | No Slack API credentials/allowlist. Desktop keyboard path is explicitly unverified | Slack app/workspace required | none | Configure a real Slack app; do not rely on UI automation as delivery evidence |
| Calendar | PARTIAL | Real local durable calendar/reminders | local owner | SQLite | Google/Outlook OAuth sync is NOT_IMPLEMENTED |
| Phone Companion | PARTIAL | WebAuthn, expiring revocable sessions, CSRF, scopes, roles, replay/rate/origin tests | real paired device | SQLite schema/migrations | Remote access and Cloudflare tunnel are disabled/unconfigured on this install |
| Public status API | WORKING | `/api/v1/public-status` returns only real high-level states/counts, no private runtime data | none; boundary enforced | none | Cross-origin access activates only for configured allowlisted domains |
| Netlify web artifact | EXTERNAL_SETUP_REQUIRED | Static site, security headers, offline behavior and build script exist | Netlify + Git provider authorization | host-side | No CLI, token, Git remote, site, deploy, or production URL exists |
| GitHub / external MCP | AUTH_REQUIRED | MCP bus is real and allowlist-based; no production server is configured | GitHub/MCP authorization | registry when configured | Do not auto-install an untrusted server |
| Home Assistant | EXTERNAL_SETUP_REQUIRED | Real timeout-bounded adapter exists and reports unconfigured | HA URL/token | configuration | No Home Assistant deployment is connected |
| Android | EXTERNAL_SETUP_REQUIRED | Device abstraction exists; actual ADB executable/device absent | authorized device pairing | device registry when configured | No imaginary device is shown |
| Phase 3 optional services | PARTIAL | 5/25 local services enabled; unavailable adapters report real state | varies | varies | Screenpipe, Graphiti, Docling, Sherpa, OpenHands, n8n and others are not deployed |
| Paper trading | TEST_ONLY | Explicitly labeled simulated account using live prices; no money movement | none | isolated paper ledger | Must never be described as brokerage execution |
| Plan simulation | TEST_ONLY | Explicit non-executing `plan.simulated` event | none | bounded event record | Must never be described as completed work |
| Qdrant/Crawl4AI/pyannote/RNNoise | NOT_IMPLEMENTED | No package/deployment on this machine | external setup | none | Keep honest status; do not add shallow placeholders |

## Confirmed production defects fixed

1. API-key presence was shown as provider availability. Real validation state
   now controls `ONLINE` and the UI displays validation separately from circuit
   health.
2. Controlled test provider failures poisoned the durable production health
   database. Canonical SDK runners now have immutable identity; injected test
   runners cannot write durable health.
3. Memory and browser health contained optimistic/hardcoded states. Memory now
   probes real storage; browser is ONLINE only while a real context is open and
   otherwise truthful STANDBY/DEGRADED.
4. Any normally returned tool value became `tool.completed`. Results now become
   FAILED, WAITING, RETURNED/unverified or COMPLETED/verified.
5. Browser click/fill/scroll/screenshot/close and Windows app/volume/microphone
   operations lacked sufficient postcondition checks. Targeted read-backs were
   added.
6. Slack desktop automation said “Sent” while admitting it could not identify
   the recipient. It now reports the action as unverified. Telegram validates
   the authenticated provider response without echoing message content.
7. Tool telemetry persisted message/form/file bodies. Sensitive content fields
   are now represented by length-only redaction in durable diagnostics.
8. Permission settings were descriptive but not durable owner overrides. They
   now persist atomically and are used by enforcement; financial remains locked.
9. Phone sessions lacked durable OWNER/TRUSTED_USER/GUEST/SERVICE roles. Role
   persistence, single-owner constraint and owner/scope endpoint guards were
   added.
10. Forwarded callers could potentially reach desktop routes. A fail-closed
    boundary allows only the phone/pair/versioned API surface.
11. The optional Cloudflare service appeared as permanently pending and never
    started when enabled. It is lazy when unconfigured and a real health-
    affecting Stage 2 service when enabled/configured.
12. The kernel stayed numerically at Stage 1 even after individually scheduled
    core services started. Lifecycle stage and core health now reflect actual
    service readiness.
13. First-run onboarding returned HTTP 500 because microphone status was not
    imported, and a fresh microphone runtime exposed a blank state. The endpoint
    works and the initial state is explicit until real browser evidence arrives.
14. Legacy root launchers could start parallel brains/microphone listeners or an
    unauthenticated demo-like server. They now delegate to authoritative ZENO
    entry points; the legacy server is loopback-only compatibility code.
15. Phase 4 skills were persistent but unreachable from conversation, and skill
    steps treated ordinary text as success. Lazy tools and verified step gating
    now connect the real subsystem to the existing planner/permission engine.
16. The static public site called a nonexistent status route. A minimal,
    credential-free, private-data-free real status endpoint now exists.

## Authentication and authorization

- Desktop: signed-in Windows session plus loopback-only HTTP.
- Owner onboarding: one durable OWNER profile; no automatic example user.
- Phone: WebAuthn device registration, secure/strict cookie or Bearer session,
  expiry, revocation, CSRF on cookie writes, replay/rate/origin checks, scopes,
  and OWNER-only administration/private memory.
- Remote boundary: Cloudflare-forwarded requests fail closed when remote access
  is disabled and never receive raw desktop chat/admin/shell/filesystem routes.
- Provider secrets: remain in existing secret/config mechanisms; provider
  health stores only SHA-256-derived fingerprints and bounded redacted errors.

## Storage architecture

- Living Memory: versioned canonical files.
- Identity, provider health, phone devices/sessions/roles, missions, events and
  runtime state: independent bounded SQLite stores/tables with schema metadata,
  indexes/constraints, busy timeouts and transactions where applicable.
- Skills: inspectable atomic JSON files plus append-only JSONL audit.
- Permissions: small atomic JSON override file because it is installation
  configuration, not a general application database.
- Audit: append-oriented rotating JSONL.
- A backup of the runtime SQLite database was created before removing exact
  `reality_*` test contamination:
  `REYES/07-System/heartbeat/state.db.pre-production-reality-cleanup-20260810.bak`.
- Universal scheduled backups for every subsystem are still PARTIAL; database
  migration/versioning is implemented where this pass introduced schemas.

## Real measurements and smoke tests

### Startup/live host

- Process start to visible Mini Orb: 2.284 s.
- Process start to first loopback HTTP response: 7.037 s.
- Process start to settled ONLINE core + live microphone evidence: 10.054 s.
- Settled runtime: Stage 2, 3/3 core services ready, 4/4 workers alive, queue 0.
- Mini Orb HWND: visible, non-minimized, topmost, 210 x 210 px, responding.
- Desktop Python host: 107.8 MiB; web Python host: 135.3 MiB at the
  measured snapshot. Wrapper processes were about 4.5 MiB each.
- Voice: live Mini Orb audio received; `MICROPHONE_READY`.

### Providers (real endpoint probes)

| Provider | Result | Latency |
|---|---|---:|
| OpenAI | ONLINE | 1,989.23 ms final retry (one earlier bounded probe timed out) |
| xAI | FAILED / AUTH_EXPIRED (rejected key) | 1,466.81 ms |
| Gemini | ONLINE | 855.48 ms validation; later real model success recorded |
| Ollama | ONLINE | 2,065.79 ms |
| Anthropic | NOT_CONFIGURED | — |

### Browser (real Playwright)

- example.com open/title verified: 2.107 s.
- “Learn more” click changed the real URL to IANA: 3.072 s.
- IANA rendered text read: 0.009 s.
- Selenium public web form open/title verified: 3.546 s.
- Form field fill and exact value read-back: 0.067 s.
- Persistent context close and closed-state verification: 2.783 s.
- The first httpbin attempt returned a genuine HTTP 503 page. Fill correctly
  failed because the element was absent; this is recorded as external-site
  failure, not a ZENO success.

### Windows (real Notepad)

- Opened a new Notepad process and verified its visible window.
- Focused it, typed a unique production-test marker, read the exact value back
  through UI Automation, observed the modified-title marker, and closed only
  the test PID.

### External integrations

- Gmail: real app-password login `OK`, read-only INBOX select `OK`; no email
  body or subject was read for this check.
- Telegram: real Bot API `getMe` returned `ok=true`; owner allowlist absent, so
  inbound control remains denied.
- ADB: executable absent. Netlify CLI/token/Git remote: absent.

## Marker inventory classification

### TEST_ONLY

- Automated test mocks, injected runners, fixtures and synthetic failure cases.
- Paper-trading account and `plan.simulated`, both explicitly labeled and unable
  to execute real financial/desktop effects.

### INTENTIONALLY DEMO

- Website Studio's demo/sample markers are safety analysis rules that require a
  generated demo to label itself; they are not fake backend data.
- Documentation examples and HTML input placeholders are presentation text.

### MUST REPLACE — fixed in this pass

- Credential-is-health provider status.
- Hardcoded/optimistic memory and browser state.
- Unverified tool return promoted to completion.
- Unverified Slack delivery wording.
- Duplicate legacy launchers and unauthenticated legacy server behavior.
- Decorative permission mutation and missing phone role authorization.
- Missing public status route and unreachable skill controls.

No remaining production dependency was found on a mock provider, fake account,
sample owner, imaginary device, fabricated notification, or hardcoded ONLINE
response.

## Tests

- Compilation: all `reyes_agent` modules and compatibility launchers pass.
- Production reality regressions: 16/16.
- Focused router: 26/26.
- Phase 2 foundations: 26/26.
- Phase 4 skills: 12/12.
- Remote access: 22/22.
- Phase 21 runtime: 15/15.
- Phase 22 stability: 9/9.
- Peak Core: 9/9.
- Earlier complete 45-file sweep found one remote state-precedence bug; after
  correction the affected suites pass. Final 48-file post-integration sweep:
  **48/48 files passed in 171.36 seconds** (24/24 in 63.11 s and 24/24 in
  108.25 s), with `ZENO_ENV=test` stores verified separate from production.

## External/manual actions required

1. Open the dashboard and complete the real owner profile form.
2. Replace the rejected xAI key or disable xAI.
3. Add the real owner Telegram chat ID to the allowlist if Telegram control is
   desired.
4. Configure a Slack app/API if verifiable Slack delivery is required.
5. Authorize Google/Outlook Calendar, GitHub/MCP, Home Assistant or an Android
   device only when those services are actually wanted.
6. For Netlify: create/authorize the real Netlify account and Git repository,
   connect the site, set the public API URL if desired, deploy, and then record
   the verified URL. No site URL exists today.
7. Enroll/configure a trusted custom local openWakeWord model for fully local
   “ZENO” detection.

## Honest limits

- No Netlify deployment URL exists.
- No automatic third-party OAuth/account creation was attempted.
- Gmail is real but read-only IMAP/app-password based, not full Gmail OAuth API.
- Google/Outlook Calendar synchronization is not implemented.
- Slack API, GitHub MCP, Home Assistant and Android are not connected.
- Mem0, Open Interpreter, local vision models, Qdrant, Crawl4AI, diarization and
  RNNoise remain unavailable or uninstalled; their fallbacks/statuses are
  honest.
- System-wide pressure and WebView2 GPU/RAM cost can still affect latency; this
  pass proves the host message loop, queues and tested operations remain
  responsive, not that an 8 GiB machine has unlimited capacity.
