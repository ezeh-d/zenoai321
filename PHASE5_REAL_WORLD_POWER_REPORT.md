# ZENO Phase 5 — Real-World Power and Secure Execution

Date: 2026-08-10
Branch: `codex/phase5-production-integrations`

## Outcome

Phase 5 strengthens the existing ZENO kernel rather than installing a second
assistant framework. The implementation adds technically enforced per-agent
capabilities, a credential-operation broker, one browser routing hierarchy,
one sandbox interface, private-network truth, optional push providers,
read-only local analytics, shared local-inference resources, and truthful
lazy integration health. No Phase 5 adapter starts a thread, model, browser,
database, container, remote desktop service, or network poller at import time.

The work is **READY WITH EXTERNAL LIMITATIONS**. Local security boundaries,
analytics, ONNX discovery, sqlite-vec retrieval, Notification Center, Tailscale
inspection, browser fallback logic, and restricted trusted-code execution are
working. Services and models that are not installed or authorized are reported
as `NOT_CONFIGURED`, `AUTH_REQUIRED`, `DISABLED`, or `NOT_IMPLEMENTED`; they are
not presented as connected.

## Repository Decisions

| Repository | Classification | Runtime label | Decision |
|---|---|---:|---|
| zeroclaw-labs/zeroclaw | ARCHITECTURAL_REFERENCE | PARTIAL | Reuse service/SOP/receipt patterns through the existing kernel; never replace ZENO. No Windows service was installed. |
| browserbase/stagehand | OPTIONAL_PLUGIN | NOT_CONFIGURED | Lazy bridge between deterministic Playwright and open-ended browser automation. No Node runtime/download at startup. |
| Infisical/agent-vault | LOCAL_SERVICE | NOT_CONFIGURED | Supported behind the credential-operation broker; the external vault is not installed. |
| Infisical/infisical | REMOTE_SERVICE | AUTH_REQUIRED | Optional production secret source; Windows Credential Manager remains the local default. |
| agent-infra/sandbox | LOCAL_SERVICE | NOT_CONFIGURED | Strong container backend is optional behind the single sandbox manager. Docker/AIO is absent. |
| tailscale/tailscale | LOCAL_SERVICE | WORKING | Installed service and CLI are connected. Peer transport and ZENO service publication are reported separately. |
| juanfont/headscale | OPTIONAL_PLUGIN | DISABLED | Abstraction exists; managed Tailscale remains selected. No self-hosted control plane was deployed. |
| binwiederhier/ntfy | REMOTE_SERVICE | NOT_CONFIGURED | Real bounded HTTP adapter; mutually exclusive with Gotify by default. |
| gotify/server | REMOTE_SERVICE | NOT_CONFIGURED | Real bounded HTTP adapter; mutually exclusive with ntfy by default. |
| rustdesk/rustdesk | OPTIONAL_PLUGIN | DISABLED | Manual owner-authorized administration only; never an agent backend. |
| QwenAudio/SenseVoice | OPTIONAL_PLUGIN | NOT_CONFIGURED | Lazy weak-signal audio adapter; no model or weight download was performed. |
| hexgrad/kokoro | OPTIONAL_PLUGIN | NOT_CONFIGURED | Preferred optional offline TTS after installation and a real benchmark. |
| OHF-Voice/piper1-gpl | OPTIONAL_PLUGIN | NOT_CONFIGURED | Emergency offline TTS only; distribution requires GPL review. |
| openvinotoolkit/openvino | OPTIONAL_PLUGIN | DISABLED | Intel hardware is present, but OpenVINO is absent and therefore was not enabled without a benchmark. |
| microsoft/onnxruntime | DIRECT_DEPENDENCY | WORKING | Existing runtime is detected; bounded lazy shared sessions prevent one session per subsystem. |
| asg017/sqlite-vec | DIRECT_DEPENDENCY | WORKING | Real portable vector index behind an adapter; caller supplies real embeddings. |
| duckdb/duckdb | DIRECT_DEPENDENCY | WORKING | Real read-only CSV/JSON/Parquet analysis with calculated result evidence. |
| bytecodealliance/wasmtime | OPTIONAL_PLUGIN | EXPERIMENTAL | Future manifest/capability-scoped plugin runtime; not installed or claimed implemented. |
| OpenVoiceOS/ovos-core | ARCHITECTURAL_REFERENCE | PARTIAL | Skill/fallback concepts only; ZENO voice/LiveKit architecture remains authoritative. |
| kyutai-labs/moshi | REJECTED | DISABLED | Mandatory local model/runtime is inappropriate for this 8 GiB, 2-core/4-thread Windows host. |

## Architecture Changes

### Agent capability enforcement

`AgentCapabilityProfile` formally carries exact tools, service rules,
filesystem roots, network scopes, approval level, and secret-broker rules.
`tools.run_tool` enforces the active context before executing a tool; specialist
and worker scopes are installed by the existing delegation paths. A prompt
cannot expand the profile. Denials are audited without exposing arguments that
may contain secrets.

### Credential architecture

Agents request a service operation, not a secret. The broker validates agent,
service, endpoint category, HTTP method, HTTPS/loopback transport, and egress
host before an internal request. It applies a credential at the request seam,
returns only a redacted receipt, and never includes the raw value in agent
context or audit output. Agent Vault and Infisical remain optional external
backends. Missing external deployment means the integration is not complete;
it does not weaken the local keyring/env fallback.

### Browser routing and recovery

One router chooses exactly one backend:

- stable known DOM operation → Playwright;
- known intent with unstable DOM → Stagehand when configured;
- open-ended task → browser-use when available;
- extraction/research → Crawl4AI when available;
- inaccessible DOM → the existing visual backend.

Recovery is finite and requires an explicit verifier before success. Stagehand
is a configured bridge only and is currently `NOT_CONFIGURED`; therefore the
selector-change contract proves routing/fallback behavior but is not represented
as a live Stagehand service test.

### Sandbox architecture

One manager selects AIO, E2B, or the local restricted backend. Untrusted code is
refused unless a strong sandbox is really configured. The local backend is
intentionally `PARTIAL`: it runs only policy-screened, owner-trusted generated
Python in a temporary directory under the approved workspace, with isolated
Python mode, a clean environment, a timeout, capped output, and guaranteed
cleanup. It is not falsely described as an OS/container security boundary.

### Private networking

Tailscale status comes from a bounded `tailscale status --json` call and removes
login names and node/public keys. A connected peer is never authorized merely
because it is in the tailnet; ZENO has an independent peer allowlist. Transport
connectivity is separate from `zeno_service_exposed`. On the audited machine
Tailscale is online, zero peers are present, and ZENO service publication is
`NOT_CONFIGURED`. Public exposure of CUA, filesystem, model, shell, and internal
APIs remains forbidden.

### Notification Center and push

The existing durable Notification Center is preserved. Its canonical states
are now `UNREAD`, `READ`, `ACTION_REQUIRED`, and `RESOLVED`; legacy rows migrate
without losing message content. ntfy and Gotify implement real finite HTTP
requests with severity/source/task metadata and aggressive secret redaction.
Only one provider is selected. Remote delivery is submitted to the existing
bounded kernel workers and never blocks the publisher. The audit found and
fixed Notification Center SQLite handles that committed but were not closed.

### Analytics and local inference

DuckDB opens a fresh bounded connection per request (two threads, 256 MiB
memory limit), imports only approved local CSV/JSON/Parquet files, accepts only
read-only analysis statements, blocks external-file functions and mutations,
caps returned rows, and closes every handle. TITAN owns the analytics tools.
Calculated rows and the SQL used are returned separately from any later LLM
interpretation.

sqlite-vec performs real nearest-vector queries with caller-provided embeddings
and closes Windows database handles. It does not invent embeddings. ONNX session
creation is lazy and LRU-bounded to three entries. OpenVINO cannot be selected
until an installed backend wins a real model benchmark.

### Voice and audio

The existing ElevenLabs path remains primary. On a generation failure the
router can try configured Kokoro, configured Piper, and then working Windows
SAPI. Optional engines are checked lazily and none is initialized at boot.
SenseVoice is isolated behind a lazy weak-signal adapter; because no model is
installed, language/emotion/event detection is `NOT_CONFIGURED`, not simulated.

## Dependencies Added

- `duckdb>=1.4,<2` — installed version 1.5.5.
- `sqlite-vec>=0.1,<0.2` — installed version 0.1.9; kept behind an adapter due to its pre-v1 API.

No Docker image, browser framework, speech model, OpenVINO runtime, remote
desktop tool, Wasmtime runtime, or large model was downloaded.

## Security Verification

- An agent cannot call a tool outside its active profile.
- Absolute file paths outside its approved roots are denied at execution.
- The broker blocks disallowed hosts before reaching the network.
- Untrusted page text asking for every API key is detected, provenance-fenced,
  audited, and cannot request a credential.
- Untrusted code is refused without a strong sandbox.
- The restricted backend rejects host paths and network modules.
- Tailscale output exposes neither login identity nor node/public keys.
- Notification payloads redact token/password/key-like content.
- Private-network connectivity does not imply ZENO endpoint publication or
  peer authorization.

No destructive exploit was used.

## Performance and Live Verification

Reference before this integration layer (same-day prior report): backend ready
was approximately 2.65 s; host-to-HTTP approximately 8.3 s; a pressured normal
workload measured 10.08% total-machine ZENO CPU and 607.3 MiB. Those figures
were collected under materially different system pressure and are references,
not a controlled A/B claim.

After Phase 5, a live 30-second Mini Orb idle sample measured:

- total ZENO process-tree CPU: **3.84% of the four-logical-CPU machine**;
- process-tree working set: **359.62 MiB**;
- process tree: **11 processes / 191 threads** (Python, WebView2 and audio);
- host message loop: **responding throughout**;
- windows: **one visible `ZENO Mini Orb`; no eager dashboard**;
- voice evidence: **`MICROPHONE_READY`, real audio received from Mini Orb**;
- kernel: four bounded workers, queue depth zero;
- Phase 5 catalogue: 3 direct local backends working, Tailscale online, all
  other optional components honestly disabled/not configured.

A five-second sample transiently measured 8.2% and is retained as a warning
against drawing conclusions from a short interval. Phase 5 imports start no
threads and load none of DuckDB, sqlite-vec, Kokoro, SenseVoice, OpenVINO, or
Wasmtime until requested.

## Tests

- Baseline before edits: **49/49 standalone test files passed** in 217.94 s.
- Phase 5 contracts after implementation: **21/21 passed**.
- Initial complete post-change matrix: **50/50 standalone files passed** in
  276.52 s, plus `compileall`.
- Existing focused Phase 1, Phase 2, Phase 3, Phase 4 security/routing,
  production-reality, and agent-team suites all passed.
- Real local operations exercised: DuckDB JSON analysis (10 verified rows),
  sqlite-vec nearest-vector retrieval and handle deletion, local ntfy protocol
  request with redacted receipt, trusted restricted-script execution and
  cleanup, Tailscale CLI status, ONNX provider discovery, live Mini Orb/API,
  microphone evidence, and 30-second process sampling.

The notification-state test initially found a real Windows SQLite-handle leak.
All Notification Center connections now close explicitly, and the test proves
the temporary database can be deleted after use.

A loaded final matrix also exposed a bounded process-receipt defect: ownership
matching found a long `reyes_agent` command and then prefix-truncated away the
matching text. Receipts are now centered on the ownership marker. The complete
12-test Phase 4 health suite and 21-test Phase 5 suite pass after the fix.

## Requested End-to-End Test Matrix

| Test | Result |
|---|---|
| Stagehand selector self-healing | **NOT_CONFIGURED** externally; bounded route/recovery/verifier contract passes. |
| GitHub through Agent Vault | **AUTH_REQUIRED / NOT_CONFIGURED**; broker egress and no-raw-secret boundaries pass. No fake GitHub receipt. |
| Generated script in sandbox | **PARTIAL / WORKING for trusted restricted code**; untrusted code denied until AIO/E2B exists. |
| Push reaches ntfy/Gotify | **NOT_CONFIGURED** remotely; real local ntfy HTTP protocol test passes. No fake phone receipt. |
| Internet disabled fallback | **PARTIAL**; local Ollama and Windows SAPI are available, but no controlled full network-outage live voice turn was claimed. |
| Kokoro/Piper fallback | **NOT_CONFIGURED**; Windows SAPI fallback is available. |
| SenseVoice detection | **NOT_CONFIGURED**; no model installed. |
| DuckDB real dataset | **WORKING**, verified calculated result. |
| sqlite-vec retrieval | **WORKING**, real extension and handle cleanup verified. |
| Tailscale peer truth | **WORKING**, live connected transport with zero peers and no service-exposure claim. |
| Unauthorized secret request | **WORKING**, denied before network. |
| Out-of-profile tool | **WORKING**, denied at the tool execution boundary. |
| Service crash recovery | **WORKING contract**, bounded browser recovery and existing worker isolation tests pass. |
| Netlify while desktop offline | **NOT_IMPLEMENTED / USER_ACTION_REQUIRED**; no connected Netlify site or production URL exists. |
| Shutdown orphan check | **PARTIAL**; existing shutdown tests pass. Final live restart measurements are recorded separately when the machine permits the cold cycle. |

## Files Created

- `reyes_agent/phase5.py`
- `reyes_agent/security/capabilities.py`
- `reyes_agent/security/credentials/{broker,service_rules}.py`
- `reyes_agent/security/secrets/infisical_backend.py`
- `reyes_agent/network/private/{manager,tailscale,peers,authorization}.py`
- `reyes_agent/notification_channels/{common,manager,ntfy,gotify}.py`
- `reyes_agent/analytics/{manager,safety}.py`
- `reyes_agent/knowledge/sqlite_vec_backend.py`
- `reyes_agent/sandbox/{interface,policy,local_restricted_backend,aio_backend,e2b_backend}.py`
- `reyes_agent/browser/{stagehand_adapter,recovery}.py`
- `reyes_agent/acceleration/{detector,session_manager,benchmark}.py`
- `reyes_agent/audio/understanding/{sensevoice,events}.py`
- `reyes_agent/voice/tts_router.py`
- `reyes_agent/tools/phase5_tools.py`
- `tests/test_phase5_power.py`

Package `__init__.py` files in the new module directories are included.

## Files Modified

- `.env.example`, `requirements.txt`
- `reyes_agent/agent.py`, `agent_teams.py`
- `reyes_agent/browser/router.py`
- `reyes_agent/notifications.py`, `health/processes.py`
- `reyes_agent/sandbox/manager.py`
- `reyes_agent/security/ai/guardrails.py`
- `reyes_agent/security/secrets/manager.py`
- `reyes_agent/system_health.py`
- `reyes_agent/tools/__init__.py`, `tools/council_tools.py`, `tools/subagents.py`
- `reyes_agent/voice/tts.py`
- `reyes_agent/web.py`
- `ROADMAP.md`, `AGENT.md`

## External Action Required

- Deploy and authenticate Agent Vault before claiming credential-proxy service
  calls such as GitHub are production ready.
- Configure Infisical machine identity only if a production environment needs
  it; do not replace local development keyring by default.
- Select and authorize exactly one ntfy/Gotify destination for real phone push.
- Configure Stagehand only if it is operationally justified; existing
  Playwright remains the working deterministic browser.
- Install Docker/AIO or E2B credentials before allowing untrusted code.
- Install and benchmark Kokoro/SenseVoice/OpenVINO models before enabling them.
- Review Piper GPL-3.0 obligations before distributing it with ZENO.
- Explicitly enable a private ZENO service endpoint and independently authorize
  each peer before remote execution; Tailscale connectivity alone is not access.

## Remaining Risks and Next Phase

The dominant cost remains WebView2 visual/audio processes, not the lazy Phase 5
adapters. External provider/model tests are blocked by absent installation or
owner authentication. The local restricted backend is a defense-in-depth tool,
not a strong hostile-code sandbox. sqlite-vec is pre-v1 and deliberately
isolated. Notification/health requests can be slower under severe machine-wide
paging even while the native message loop remains responsive.

The next phase should be deployment validation, not another library expansion:
choose at most one credential vault, one strong sandbox, one push provider and
one adaptive browser service; configure each with real owner credentials; run
the currently blocked end-to-end tests; then measure a controlled cold-start,
voice, browser, and shutdown cycle on an otherwise idle machine.
