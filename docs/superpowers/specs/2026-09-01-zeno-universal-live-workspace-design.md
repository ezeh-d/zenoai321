# ZENO Universal Live Workspace, Panel Orchestrator, and Tool Health Design

**Date:** 2026-09-01  
**Status:** Approved for implementation  
**Scope owner:** ZENO desktop runtime  

## Approval record

The owner approved:

1. Replacing the earlier Charm Engine task with this Universal Live Workspace task.
2. Backend-authoritative logical workspace state with surface-specific rendering.
3. The core authority and component structure.
4. The panel registry and contextual-routing behavior.
5. The normalized activity, history, retry, and redaction behavior.
6. Continuing through the remaining design and implementation phases without repeated approval stops.

## Problem

ZENO already has strong execution authorities and several useful visual surfaces, but the user experience is fragmented:

- individual features open and close overlays directly;
- the command palette is a hard-coded frontend list;
- the Activity View understands only a subset of runtime events and opens too aggressively;
- several overlapping capability views treat registration or importability as readiness;
- refresh and reconnect behavior is not governed by a revisioned workspace snapshot;
- short operations, long-running tasks, tool failures, and capability questions do not share one safe user-facing projection.

The result is a capable runtime without one coherent live workspace. The goal is to add that coordination layer without creating another executor, event bus, task engine, policy engine, or media backend.

## Goals

Build one native ZENO workspace system that:

- dynamically registers panels and feature-owned panel adapters;
- owns panel lifecycle and valid state transitions;
- chooses no UI, a card, a mini surface, a full panel, or background-only execution from context;
- projects real Event Bus activity into bounded, human-readable cards and history;
- reports tool health from safe evidence rather than module presence alone;
- exposes capability truth to both ZENO and the owner dashboard;
- supports safe bounded retry, reconnect, rehydration, and recovery;
- upgrades the command palette and global search without invasive file indexing;
- projects the same logical state differently on desktop, Mini Orb, and phone;
- preserves conversational performance and existing ZENO authorities.

## Non-goals

- No second tool executor, event bus, task engine, model router, permission engine, or policy path.
- No rewrite of the concurrent TTS, prosody, voice, media, Spotify, or media-control work.
- No implementation of new cybersecurity, surveillance, penetration-testing, RF, or security-agent functionality.
- No automatic indexing of broad private directories.
- No raw chain-of-thought, hidden reasoning, secrets, credentials, or unnecessary private message content in activity or history.
- No attempt to make desktop geometry identical on phone or Mini Orb.
- No big-bang rewrite of all existing overlays.

## Repository findings and preserved authorities

The design reuses the following existing systems:

- `reyes_agent.event_bus`: durable typed events, bounded subscribers, correlation IDs, and history.
- `reyes_agent.tools.run_tool`: the sole authoritative tool execution boundary.
- `reyes_agent.task_engine`: finite task plans, observed progress, cancellation, retry budgets, and verification-backed completion.
- `reyes_agent.execution_lifecycle`: high-level execution trace and verification stages.
- `reyes_agent.tools.universal_registry`: normalized tool metadata and adapter execution contract over `run_tool`.
- `reyes_agent.capability_truth`, `capability_snapshot`, and `capabilities.registry`: existing capability evidence that must be converged rather than duplicated.
- `reyes_agent.circuit_breaker` and `recovery_engine`: existing bounded failure and recovery primitives.
- `reyes_agent.universal_search`: local typo-tolerant search with an optional healthy remote backend.
- `reyes_agent.static.activity_view.js`: truthful build/project activity projection to be retained as a managed panel.
- FastAPI, `/api/events/stream`, `/api/events`, and the existing phone transport: current backend/frontend communication authorities.
- Existing desktop overlays, Mini Orb, command palette, Tool Library, Situation Room, Council/agents surfaces, and Anywhere/phone UI.

## Considered approaches

### A. Backend-authoritative logical state with per-surface projections — selected

The backend owns panel lifecycle, activity state, health state, correlations, and revisions. Desktop, Mini Orb, and phone render the same logical facts differently.

Benefits:

- refresh and reconnect can restore current work;
- one panel decision is shared by every surface;
- backend execution truth remains authoritative;
- frontend modules remain lazy projections;
- no desktop geometry is forced onto mobile.

### B. Frontend-first panel manager — rejected

This is initially simpler, but refresh loses state, feature code remains coupled to DOM, and phone cannot reliably share current activity.

### C. Stateless reconstruction from Event Bus history for every request — rejected

This avoids a live manager but makes focus, docking, close transitions, coalescing, and reconnect hydration unnecessarily expensive and complex.

## Architecture

The existing execution path remains authoritative:

```text
user request
  -> existing intent/model routing
  -> existing capability and permission policy
  -> reyes_agent.tools.run_tool / task_engine
  -> Event Bus
```

The new workspace is a projection and orchestration layer:

```text
request context + Event Bus facts
  -> PanelIntentRouter
  -> ActivityProjector
  -> WorkspaceManager (revisioned logical state)
  -> existing Event Bus
  -> REST snapshot + existing SSE stream
  -> desktop / Mini Orb / phone projections
```

The workspace never executes a tool. It can request an existing runtime action only through the same public command/tool path used elsewhere.

The workspace service owns exactly one bounded Event Bus subscriber. Input projection ignores all `workspace.*` events emitted by the service itself, so a projected activity can never recursively create another activity. Startup is lazy and idempotent; shutdown always unsubscribes and releases its consumer.

## Proposed module boundaries

New backend modules live under an isolated `reyes_agent/workspace/` package:

- `models.py`: enums and immutable/public record shapes.
- `registry.py`: dynamic panel and safe-health-probe registration.
- `manager.py`: panel instances, transitions, revisions, snapshots, and event publication.
- `intent_router.py`: contextual presentation decisions and noise budget.
- `activity.py`: safe event normalization, coalescing, card lifecycle, and bounded live projection.
- `history.py`: redacted bounded execution-history projection and retry/resume eligibility.
- `tool_health.py`: evidence-based tool health, caching, transitions, and optional recovery hooks.
- `search.py`: commands, tools, panels, agents, settings, and recent-action search over the existing search service.
- `service.py`: one lazy singleton composing the above authorities and handling Event Bus updates.

New frontend behavior should be isolated in one or more small static modules rather than expanding the monolithic dashboard script:

- a workspace client that hydrates, applies revisioned events, and invokes commands;
- a workspace shell that renders managed panels and activity cards;
- generic adapters for existing DOM overlays and lazy module-backed panels;
- surface-specific compact renderers for Mini Orb and phone.

Only small integration seams should be added to `web.py`, `static/index.html`, `static/mini.html`, and the phone UI. Package manifests, voice, TTS, media, Spotify, presentation data, and unrelated systems remain untouched.

## Panel registry

### Panel definition

Each panel registration exposes:

```text
id
title
component
supported_actions
default_size
preferred_position
auto_open_policy
priority
singleton
minimum_context
supported_surfaces
context_sanitizer
```

`component` is a declarative adapter reference, not feature-owned DOM manipulation. Initial adapters support:

- `dom:<selector>` for an existing overlay;
- `module:<url>#<factory>` for an existing lazy module;
- `builtin:<name>` for the new generic activity, health, search, and history panels.

Feature modules may register additional definitions through the registry without editing router conditionals.

### Panel instance

Each live instance contains only bounded, sanitized state:

```text
panel_id
instance_id
state
context
dock_position
correlation_id
priority
revision
opened_at
updated_at
```

Singleton requests focus or update the existing instance. Multi-instance panels receive stable instance IDs and an explicit cap per definition.

### State machine

Supported states are:

```text
CLOSED
OPENING
ACTIVE
MINIMIZED
EXPANDED
DOCKED
BACKGROUND
CLOSING
```

Valid transitions are:

```text
CLOSED -> OPENING -> ACTIVE
ACTIVE <-> MINIMIZED | EXPANDED | DOCKED | BACKGROUND
any open state -> CLOSING -> CLOSED
```

Focus returns a visible instance to `ACTIVE` and advances its z-order/focus revision. Dock position remains a separate value. Invalid transitions return a structured refusal and do not mutate state. Repeated commands are idempotent.

Accepted changes emit `workspace.panel.changed` with the sanitized instance and global workspace revision. Rejections emit no noisy UI event unless they represent an actionable error.

`OPENING` and `CLOSING` are short authoritative transitions, not animation timers. A manager command records the transitional state and then the resulting `ACTIVE` or `CLOSED` state synchronously when the logical operation succeeds. Frontend animation never advances backend state. A component render failure reports a safe client error and triggers rehydration or closure through an explicit manager command.

## Contextual panel routing

### Presentation plan

The router returns one immutable plan:

```text
mode: NO_UI | CARD | MINI | FULL | BACKGROUND
primary_panel
card_kind
reason_code
priority
context
correlation_id
```

### Inputs

The router evaluates:

- the user request and any existing routed intent;
- explicit show/open/hide language;
- expected operation duration and available progress evidence;
- current tool/capability health;
- existing relevant panels;
- surface and performance mode;
- panel auto-open policy and minimum context;
- whether the action occurs in an external application.

### Noise budget

- At most one automatically opened primary panel per request.
- At most two transient cards per correlation at once.
- Existing relevant panels update rather than reopen.
- Short factual responses and pause/cancel acknowledgements do not open full panels.
- External app launches normally receive a brief card rather than a ZENO panel.
- Authentication and actionable failures receive a persistent card.
- A full health panel opens automatically only for a serious actionable failure; otherwise it opens on request.
- Background maintenance does not announce itself unless it blocks requested work or crosses a warning threshold.

### Initial routing examples

- Find a CV/assignment/file -> files or search panel.
- Check the news -> news panel.
- Show system performance -> system panel.
- Ask the council -> agents panel.
- Download something -> download activity card, expandable to activity.
- Open calculator -> external app plus a brief card.
- Ask the time or say pause -> no full panel.
- Show what is playing -> media panel request through the workspace contract; no media backend changes.

## Activity projection

### Normalized activity record

```text
activity_id
correlation_id
category
status
title
safe_detail
progress
progress_unit
importance
panel_target
result_reference
retryability
started_at
updated_at
finished_at
expires_at
```

Activity states are:

```text
PENDING -> RUNNING -> WAITING -> SUCCEEDED
                           -> FAILED | CANCELLED
```

### Event inputs

The projector initially consumes existing event families instead of forcing an immediate producer migration:

- `build.task` and `project.activity`;
- `tool.returned`, `tool.completed`, `tool.waiting`, and `tool.failed`;
- execution lifecycle events;
- website, mission, agent, file, browser, download, notification, and panel events when present.

New producers may emit more specific events later, but they must still flow through the same Event Bus.

### Truth and privacy rules

- Progress is shown only when a producer supplies a real bounded count or percentage.
- Result text is truncated and redacted again even if the producer already audited it.
- Tool arguments are omitted by default and allow-listed only when needed for a safe title.
- Agent thinking is shown only as a coarse status such as “Council is working,” never hidden reasoning.
- Passwords, tokens, authorization headers, secret-like fields, private message bodies, and raw prompts are removed.
- Failed and malformed input events produce a safe diagnostic record, never a frontend exception.

### Coalescing and retention

- Events coalesce by correlation ID, category, and operation key.
- The live store holds at most 100 activities.
- Each activity holds bounded detail and at most a small recent-event tail.
- Successful transient cards expire after about five seconds.
- Important success results remain accessible through history.
- Failures, authentication requirements, and actionable warnings remain until acknowledged, resolved, or explicitly dismissed.
- UI rendering batches events within one animation frame and never starts a progress timer.

## Execution history, retry, and resume

History is a bounded read model over existing Event Bus and task-engine facts, not another execution database. It records:

- task/correlation ID;
- safe request summary;
- tools used;
- start and finish timestamps;
- final status;
- safe result summary and result references;
- retry/resume eligibility and linked attempts.

Recent history is reconstructed from durable events after process restart. Raw chain-of-thought, secrets, credentials, private message bodies, and unbounded tool output are never stored in this projection.

Retry behavior:

- read-only and idempotent operations may use the existing bounded recovery budget;
- resumable operations require an explicit safe continuation token or checkpoint;
- consequential or irreversible operations require confirmation and are never blindly repeated;
- manual retry creates a linked attempt while retaining the original correlation;
- the existing circuit breaker and recovery planner determine whether another attempt is admitted;
- cards expose Cancel, Retry, Resume, Open Result, Details, and Dismiss only when valid.

## Tool capability and health truth

### Convergence rule

`universal_registry` remains the normalized inventory and execution adapter. `ToolHealthManager` adds dynamic evidence; it does not register or execute a parallel tool.

The manager consumes:

- registry metadata and required permissions;
- dependency/configuration facts from the existing capability registry;
- circuit-breaker state;
- recent verified tool reputation and latency;
- a registered safe probe result;
- optional provider-owned status adapters, including media status exposed by the concurrent media work.

Existing `capability_truth` and `capability_snapshot` should read the resulting normalized health view for dynamic questions, with compatibility adapters retained during migration.

### Tool health record

```text
name
category
status
available
initialized
reason
dependencies
permissions_required
last_checked
last_success
last_failure
latency_ms
last_error_code
suggested_repair
supported_operations
evidence_source
```

Statuses are:

```text
AVAILABLE
DEGRADED
UNAVAILABLE
AUTH_REQUIRED
DEPENDENCY_MISSING
DISCONNECTED
ERROR
```

### Evidence rules

- Importability or registration alone never yields `AVAILABLE`.
- A recent successful real execution may serve as health evidence.
- Otherwise a registered probe performs the smallest safe real operation.
- A probe may inspect configuration or dependency presence, but that alone produces `DEGRADED` or a specific unavailable state unless it proves operational reachability.
- Effectful operations are never used as health probes.
- Unknown/unprobed tools are honest: defined and registered, but `DEGRADED` with “not recently verified,” not falsely connected.
- Secret values never appear in health records or suggested repairs.

### Probe execution

- Probes are lazy and run on explicit dashboard refresh, capability query, preflight, or after relevant failure/success events.
- Results have a short TTL, defaulting to 30 seconds, and concurrent requests for the same probe coalesce.
- Each probe has a strict timeout and no retry unless its registration declares a safe recovery strategy.
- A forced refresh is owner-initiated and still respects concurrency and timeout bounds.
- The manager caps concurrent probes and publishes only meaningful state transitions.

### Capability answers

Capability discovery uses dynamic health rather than static prompt assumptions:

- `AVAILABLE`: “Yes, it is connected and ready.”
- `DEGRADED`: “Support exists, but it has not been fully verified or is partially impaired.”
- `AUTH_REQUIRED`: “It is supported, but you need to sign in.”
- `DEPENDENCY_MISSING`: “It is supported, but a required dependency is missing.”
- `DISCONNECTED`: “It is configured, but the service/device is not connected.”
- `UNAVAILABLE` or `ERROR`: explain the safe reason and repair action.

## Tool health dashboard

The owner/developer panel groups tools by category and shows:

- status and availability;
- safe human-readable reason;
- last successful check and last failure;
- latency when measured;
- missing dependency or authentication requirement;
- suggested repair;
- supported operations;
- an explicit Refresh control.

Details are lazy-loaded. The default view shows category rollups and actionable failures rather than rendering every tool row at startup. It never displays environment values, tokens, credentials, or raw exception payloads.

## Recovery

Recovery composes existing `recovery_engine` and `circuit_breaker` behavior.

Rules:

- automatic recovery is allowed only for registered, reversible recovery hooks;
- attempts are bounded, normally one retry after the original failure;
- backoff is exponential with jitter and a maximum delay;
- repeated failures open the existing circuit breaker;
- half-open probes admit one bounded trial;
- optional backends fall back to existing local providers where available;
- reconnecting transports rehydrate workspace state after connection returns;
- background recovery produces one coalesced activity, not repeated cards or speech;
- owner-visible failures remain truthful even when recovery later succeeds.

No infinite restarts, busy loops, or autonomous repetition of consequential actions are permitted.

## Backend API and event contracts

Proposed loopback workspace endpoints:

```text
GET  /api/workspace/state
GET  /api/workspace/panels
POST /api/workspace/panels/{panel_id}/{action}
GET  /api/workspace/activities
POST /api/workspace/activities/{activity_id}/dismiss
GET  /api/workspace/history
POST /api/workspace/history/{task_id}/retry
POST /api/workspace/history/{task_id}/resume
GET  /api/workspace/health
POST /api/workspace/health/refresh
GET  /api/workspace/search
```

Mutating endpoints validate loopback/owner authority, panel action support, and safe retry policy. Existing tool permission checks remain authoritative.

Workspace events use the existing Event Bus and SSE transport:

```text
workspace.panel.changed
workspace.activity.changed
workspace.activity.dismissed
workspace.health.changed
workspace.history.changed
workspace.snapshot.invalidated
```

Each event carries the global workspace revision, a record revision, correlation ID, safe payload, and timestamp. The manager never sends the full workspace snapshot on every event.

## Reconnect and synchronization

The backend is authoritative for logical state. Physical size and coordinates are surface-local preferences.

Frontend startup/reconnect sequence:

1. Open the existing SSE stream and temporarily buffer workspace events.
2. Fetch `/api/workspace/state` with its global revision.
3. Render the snapshot.
4. Apply buffered events newer than the snapshot revision.
5. Continue applying ordered deltas.
6. If a revision gap is observed, fetch a fresh snapshot.

The browser `EventSource` reconnect behavior remains the transport mechanism; the workspace client owns rehydration and gap detection. Phone WebSocket/SSE consumers follow the same snapshot-plus-revision contract rather than duplicating state.

## Surface projections

### Desktop

The desktop workspace shell supports:

- show, hide, toggle, minimize, expand, focus, dock, and close;
- lazy component loading;
- one focused panel and bounded open instances;
- activity cards in a compact stack;
- managed existing-overlay adapters;
- an activity/history drawer and tool-health panel;
- keyboard navigation and accessible focus restoration.

### Mini Orb

The Mini Orb retains its lightweight document and existing performance behavior. It receives only compact state:

- idle, listening, thinking, executing, speaking, waiting, success, warning, or error;
- one safe current-activity title and status;
- no full task or tool inventory.

Clicking the orb activates the dashboard and requests the current activity panel. It does not add expensive constant effects or another polling loop.

### Phone / ZENO Anywhere

Phone renders logical activity, health warnings, and panel targets as compact cards/lists. It does not reproduce desktop position or size. Actions continue to use the existing authenticated phone boundary and scopes.

## Command palette and global search

The existing Ctrl+Space/Ctrl+K palette becomes a search client instead of a fixed list only. Search sources are:

- registered commands;
- tools and supported operations;
- registered panels;
- known apps;
- agents;
- recent safe history;
- settings;
- file-search actions.

The new workspace search service reuses `UniversalSearchService`. It indexes only metadata and bounded recent records. A file query returns an action that invokes existing file search; it does not recursively index private directories in advance.

Results have typed actions such as open panel, run command, focus agent, open setting, retry task, or start file search. Keyboard navigation, cancellation of stale requests, and a strict result limit are required.

## Human-facing language

Activity titles come from centralized templates keyed by operation/category, for example:

- “Opening Spotify…”
- “Searching your files…”
- “Found it.”
- “Slack needs you to sign in.”
- “That download failed — the connection dropped.”

Unknown operations fall back to a sanitized tool description, never “executing tool invocation.” UI may show richer status than speech; this design does not add automatic spoken announcements.

## Performance and bounds

- No busy loops or workspace polling timers.
- One existing SSE connection per surface, not one connection per panel.
- Event Bus subscribers remain bounded and are always unsubscribed.
- Workspace events are deltas, not repeated whole snapshots.
- Frontend rendering is batched to animation frames.
- Heavy panels load only when opened.
- Health probes are TTL-cached, timeout-bounded, concurrency-limited, and coalesced.
- Live activities cap at 100; open panel instances and history have explicit caps.
- Event text, context, and result references have size limits.
- Hidden panels stop optional frontend updates while backend truth continues.
- No provider warmup is introduced at startup.

## Failure handling

- Malformed events are rejected or converted to one safe diagnostic activity.
- Unknown panel IDs return `NOT_REGISTERED` without changing state.
- Missing components leave the panel in `CLOSED` or `BACKGROUND` and expose a repairable error card.
- Frontend render exceptions do not mutate backend state; the client can request rehydration.
- An unavailable health probe produces an honest status rather than failing the dashboard.
- Event subscriber overflow causes a revision gap and snapshot rehydration.
- Activity projection failures never block real tool execution.
- Workspace manager failures never bypass permissions or run tools directly.

## Integration and migration strategy

### Phase 1 — Core contracts

- Add panel, activity, history, health, and revision models.
- Add dynamic registries and deterministic state transitions.
- Add redaction and bounded stores.
- Unit-test all contracts before integration.

### Phase 2 — Backend service and runtime projection

- Compose one lazy workspace service.
- Subscribe once to the existing Event Bus using a bounded consumer.
- Map current task/tool/project events into normalized activities.
- Add snapshot and command endpoints.
- Feed dynamic health into capability answers without removing compatibility APIs.

### Phase 3 — Desktop workspace

- Add the isolated workspace client and shell.
- Register new generic activity, history, health, and search panels.
- Adapt selected existing overlays through declarative registrations.
- Stop Activity View from opening solely because every build delta arrived.
- Upgrade command palette search and keyboard behavior.

### Phase 4 — Mini Orb and phone projections

- Add compact current-activity data to the existing lightweight status/snapshot.
- Make an orb click reveal current activity through the workspace manager.
- Add compact activity/health projections to Anywhere without desktop geometry.

### Phase 5 — Recovery, migration, and compatibility

- Connect safe retry/resume to existing task and recovery authorities.
- Add registered provider health probes incrementally.
- Route remaining feature-owned overlay manipulation through adapters as touched.
- Preserve existing endpoints and globals during migration.

## Testing strategy

Implementation follows red-green-refactor. Targeted tests cover:

### Panel system

- dynamic registration and duplicate rejection;
- singleton and bounded multi-instance behavior;
- every valid and invalid state transition;
- idempotent rapid open/close/toggle sequences;
- focus and docking behavior;
- context validation and sanitization;
- concurrent manager commands and monotonic revisions.

### Intent routing

- explicit panel requests;
- no-panel short answers;
- external app cards;
- file, news, system, agent, download, and media panel decisions;
- health-aware fallback;
- one-primary-panel noise budget.

### Activity and history

- lifecycle projection from real event families;
- progress truth and coalescing;
- success expiry and persistent failure behavior;
- malformed event handling;
- bounded concurrent events;
- redaction of secrets, tokens, message bodies, and raw prompts;
- history reconstruction and linked attempts.

### Tool health and recovery

- every health state transition;
- registration/importability not yielding false availability;
- recent verified execution evidence;
- safe probe timeout and TTL behavior;
- concurrent probe coalescing;
- bounded retry/backoff and circuit-breaker opening;
- unavailable, disconnected, authentication, dependency, and error cases;
- no secret values in health responses.

### API and synchronization

- loopback/owner boundary on workspace commands;
- snapshot revision and delta contracts;
- frontend reconnect buffering and revision-gap rehydration;
- existing SSE unsubscribe behavior;
- phone projection scope and compactness;
- retry refusal for irreversible actions.

### Frontend

- panel component lazy loading;
- activity-card lifecycle and actions;
- keyboard command-palette navigation;
- search request cancellation and result routing;
- current-activity reveal from Mini Orb;
- no workspace polling, simulated progress, or expensive constant visual effects.

### Regression

- existing Event Bus, task-engine, build activity, tool registry, universal search, status dashboard, Mini Orb, production-reality, and visual-performance tests;
- repository tests related to files modified by the integration;
- import and syntax checks for new modules;
- focused FastAPI endpoint tests.

## Definition of done

The feature is complete only when:

- one operational `PanelManager` owns logical panel state;
- panels register dynamically and existing overlays can be adapted;
- intent routing selects appropriate surface size without visual noise;
- real Event Bus activity drives cards and managed panels;
- refresh/reconnect restores revisioned workspace state;
- health distinguishes ready, degraded, unavailable, authentication, dependency, disconnection, and error conditions from evidence;
- capability answers query dynamic state;
- safe retry/resume and bounded recovery are wired to existing authorities;
- command palette/global search spans panels, tools, commands, agents, settings, and recent actions;
- Mini Orb and phone project current activity without copying desktop geometry;
- relevant tests pass with no regression in existing ZENO features;
- concurrent voice, TTS, media, Spotify, package, and presentation work remains untouched.

## Expected collision boundaries

Intentionally avoid or minimize edits to:

- `package.json` and `package-lock.json`;
- `presentation/` data;
- `reyes_agent/voice/`;
- `reyes_agent/media/`;
- media, Spotify, and prosody integration files;
- unrelated untracked research and integration repositories.

Before every shared-file edit, inspect its current diff and recent modification state. Never reset, revert, delete, or overwrite unrelated work.
