# ZENO capability audit

Audited 2026-08-24 against the current checkout and recent commits
`7eac001`, `33e7d15`, `9772375`, and `6c18787`. This is an implementation
classification, not a feature wish list. `IMPLEMENTED` means executable code
and tests exist; it does not imply that an external account, device, model, or
paid provider is configured on this machine.

## Existing-system classification

| Subsystem | Status | Authority / evidence | Audit conclusion |
|---|---|---|---|
| Kernel, staged lifecycle, workers | IMPLEMENTED | `kernel.py`, `worker_pool.py`, `scheduler.py` | Reused; no second scheduler added. |
| Global tool registry/router | IMPLEMENTED | `tools/__init__.py`, `routing/capability.py` | 304 tools import; registration alone is not treated as proof. |
| Capability inventory | IMPLEMENTED | `capabilities/`, `capability_snapshot.py` | Reused. |
| Capability truth/lifecycle | PARTIAL → IMPLEMENTED | `capability_truth.py`, `capability_lifecycle.py` | Added full availability states, metadata, dependency diagnosis, and honest TESTING state for unproven registered tools. |
| Session state/restart snapshot | PARTIAL → IMPLEMENTED | `session_recovery.py`, `unified_session.py` | Added one cross-surface authority with atomic durable/ephemeral boundaries. |
| Device and phone command state | IMPLEMENTED | `remote_access/device_link.py`, protected cloud API | Heartbeats now update shared session device state. |
| Agent work lifecycle | IMPLEMENTED | `agent_runtime.py`, `agent_presence.py` | Presence now also updates shared active-agent state; no visual summon starts a worker. |
| Action result classification | PARTIAL → IMPLEMENTED | `tools.classify_tool_result`, `execution_lifecycle.py`, `action_verifier.py` | Added independent verification strategies and five result states. |
| Event history | IMPLEMENTED | `event_bus.py` | Durable, bounded, non-blocking; reused. |
| Evidence/side-effect history | MISSING → IMPLEMENTED | `evidence_ledger.py` | Redacted SQLite ledger and claim-before-execute idempotency. |
| Retry/circuit breaker | IMPLEMENTED | `circuit_breaker.py`, `provider_manager.py` | Reused; recovery planner adds failure-aware policy/fallback decisions. |
| General recovery diagnosis | PARTIAL → IMPLEMENTED | `recovery_engine.py` | Bounded classification; no blind retry. |
| System health | IMPLEMENTED | `system_health.py` | Concurrent, time-bounded, cached on demand; no polling thread. |
| ZENO Doctor | MISSING → IMPLEMENTED | `doctor.py`, `zeno_doctor` tool | System and exact-capability root-cause modes. |
| Local observability | PARTIAL → IMPLEMENTED | `observability/tracer.py`, Event Bus | Added trace/parent/span IDs and command/task/session correlation; records remain bounded and durable via Event Bus. |
| External observability | EXPERIMENTAL / DISABLED | tracer adapter status | Langfuse/Phoenix remain mutually exclusive and opt-in; ZENO does not depend on either. |
| Resource admission/leases | IMPLEMENTED | `admission.py`, `resource_leases.py` | Reused as the concurrency authority. |
| Resource governor | PARTIAL → IMPLEMENTED | `resource_governor.py` | Measured CPU/RAM/disk/battery profile and pressure actions; interaction classes stay reserved. |
| Permission profiles | IMPLEMENTED | `permissions.py` | Reused; financial execution remains structurally blocked. |
| Consent state | PARTIAL → IMPLEMENTED | `conversation/consent.py` | One singleton now covers microphone, transcription, recording, camera, screen stream, remote control, enrollment, and retention. |
| Device trust/policy composition | MISSING → IMPLEMENTED | `policy_engine.py` | Local ALLOW/DENY/ASK over tool policy, action risk, device trust, and consent. |
| Failure regression corpus | MISSING → IMPLEMENTED | `failure_regression.py`, `tests/golden/` | Redacted deterministic JSON cases; production code never emits executable Python. |
| Mission durability | IMPLEMENTED | `missions/manager.py`, `missions/store.py` | SQLite checkpoints/idempotent mission keys; retained instead of deploying Temporal. |
| Mission Control read model | MISSING → IMPLEMENTED | `mission_control.py`, local API/tool | Real sections from existing authorities; no fake UI counters. |
| Quality scoring | MISSING → IMPLEMENTED | `quality_score.py` | Scores only measured samples; missing evidence is `None`, not zero or a fabricated percentage. |
| Model/agent reputation | PARTIAL → IMPLEMENTED CONTRACT | `quality_score.py`, `tool_reputation.py` | Bounded task-specific recording services; routing integration remains evidence-gated. |
| Procedural skill memory | IMPLEMENTED | `skills/`, `workflow_engine.py` | Existing library/compiler/executor retained; no duplicate. |
| Knowledge trust/provenance | MISSING → IMPLEMENTED | `knowledge_trust.py` | Source, confidence, freshness, supersession and bounded context namespace are durable. |
| Computer-use benchmark contract | MISSING → IMPLEMENTED | `computer_use_benchmark.py`, `tests/golden/` | Verifier-led local cases; does not touch the owner desktop automatically. |
| Memory policy/context | IMPLEMENTED WITH LIMITS | `memory/policies.py`, `memory/manager.py` | User/project/agent/session separation and secret rejection exist; fine-grained business/personal namespaces remain a future migration. |
| Browser automation | IMPLEMENTED WITH EXTERNAL LIMITS | `browser_controller.py`, `browser_runtime.py` | Lazy Playwright; website/account availability remains external. |
| Desktop automation | IMPLEMENTED WITH NATIVE ACCEPTANCE LIMIT | `computer/`, `remote_access/desktop_agent.py` | Real Windows executor and verification contracts; full OSWorld run is not installed. |
| Voice/wake/STT/TTS | IMPLEMENTED WITH PROVIDER/HARDWARE LIMITS | `voice/`, `wake/`, `microphone.py` | Single-stream ownership contract retained; live owner audio remains acceptance evidence. |
| WebRTC/phone/Anywhere | IMPLEMENTED WITH TURN/DEVICE LIMITS | `remote_access/`, `remote_mic/` | Protected owner routes and idempotent commands; internet-grade media still needs TURN credentials. |
| Slack/T21/external services | PARTIAL BY CONFIGURATION | provider adapters + Tool Library | Installed adapters are not equivalent to authenticated accounts. Capability truth now distinguishes auth/device/offline from unsupported. |

## Reused rather than duplicated

The implementation deliberately reuses the Kernel, Event Bus, worker pool,
GlobalToolRegistry, permission profiles, conversation consent, mission store,
device link, circuit breaker, tool reputation, session recovery, agent runtime,
and system health. The new `control_plane.py` is a facade over those authorities,
not a runtime or scheduler.

## Confirmed limits

- A registered tool without successful telemetry is `TESTING`, not proven
  `AVAILABLE`.
- External accounts cannot be made operational without owner authentication.
- An offline phone/laptop cannot be live-tested from a single process.
- GPU/VRAM vendor telemetry is optional; CPU/RAM pressure control works without it.
- OSWorld V2 requires a pinned VM/image and gated assets; its repository was
  researched but not executed against the owner's real desktop.
- Mission Control is a real backend/read model and API; the current dashboard
  lazy-loads a no-polling panel from the existing command palette.

## Verification and measurements

- Pre-change focused baseline: 71/71 tests passed in 1.83 s.
- First complete audit run: 1,826 passed and 10 failed in 533.51 s. Nine failures
  exposed the Pack 6 package shadowing the existing guest/presentation API; one
  exposed a duplicate lifecycle notification. Both causes were repaired.
- Final complete run: 1,836/1,836 passed in 536.79 s.
- Final control-plane contracts: 23/23 passed in 1.35 s; compatibility group:
  78/78 passed in 20.32 s.
- Tool registry cold import: 304 tools, 1,115.44 ms, +16.08 MiB RSS, one thread.
  The immediately preceding catalog baseline was 299 tools, 950.6 ms and
  +17.38 MiB; the new import remains thread-neutral and occurs in background
  runtime loading rather than the first-render path.
- Warm full capability snapshot: 305 records in 23.91 ms. The first snapshot
  including the cold registry import took 996.98 ms.
- Cold Mission Control composition: 1,475.93 ms. It runs only when opened or
  manually refreshed and creates no polling loop.
- Rendered 1280×800 Playwright check: 15 sections, quality evidence visible,
  zero console errors, and overlay DOM count returned to zero after Close.
- Dependency integrity: `pip check` reported no broken requirements; Python
  compilation, JavaScript syntax and `git diff --check` passed.
- Recorded post-change quality is 100.0 from two measured sources only:
  1,836/1,836 full regression and 23/23 control-plane contracts. Runtime Tool
  Execution and Verification remain explicitly unmeasured until real actions
  generate telemetry; they are not filled with invented values.
