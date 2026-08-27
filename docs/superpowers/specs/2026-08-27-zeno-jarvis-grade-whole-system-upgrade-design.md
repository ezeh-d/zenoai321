# ZENO Jarvis-Grade Whole-System Upgrade Design

**Date:** 2026-08-27

**Status:** Approved architecture; awaiting written-spec review

**Program type:** Incremental whole-system reliability and capability upgrade

**Primary constraint:** Preserve the current ZENO architecture and Claude's concurrent work.

## 1. Purpose

This program upgrades the existing ZENO installation toward a real-world,
Jarvis-like assistant: conversational, fast, context-aware, capable across
voice, desktop, browser and phone surfaces, honest about uncertainty, secure,
observable, and recoverable under failure.

“Perfect” is defined as a direction backed by measurable acceptance gates. It
does not mean pretending that models, networks, websites, Windows, microphones,
or external services can never fail. ZENO is successful when it handles those
failures without freezing, losing control, fabricating success, leaking data,
or requiring the owner to restart the entire application.

The program integrates useful capabilities into one native ZENO operating
core. It does not combine cloned applications into a collection of competing
assistants.

## 2. Existing Systems That Remain Authoritative

The following current systems are preserved and extended in place:

- `ZenoKernel` and the staged application lifecycle;
- the existing Event Bus;
- the bounded task and agent runtimes;
- the current provider and Model Router seams;
- the Permission Engine and Smart Autonomy Policy;
- the canonical tool registry and `run_tool()` execution gateway;
- the existing voice, VAD, wake, STT and TTS authorities;
- the browser controller and grounded desktop computer-use engine;
- Living Memory, project memory and existing legacy-memory compatibility;
- Mission Engine, agent registry and specialist-team hierarchy;
- Mini Orb, dashboard, Council/Situation Room and Activity View;
- ZENO Anywhere, the paired-device/session model and Android companion;
- Capability Truth, health, evidence and diagnostics systems.

No phase may create a second Kernel, Event Bus, scheduler, worker pool, tool
executor, provider router, microphone listener, browser owner, agent registry,
memory authority, web server, or conversation history merely for convenience.

## 3. Protected Concurrent Work

At the time this design was approved, the following working-tree paths were
being changed outside this program and are protected:

- `reyes_agent/config.py`;
- `reyes_agent/social/instagram_login.py`;
- `tests/test_instagram_login.py`;
- `instagram_callback_test.py`;
- `package.json` and `package-lock.json`;
- modified `presentation/*.json` files.

Implementation must re-check `git status` and recent commits before every
phase. It must not reset, overwrite, stage, reformat, or opportunistically fix
protected or unrelated work. If a necessary integration overlaps a changed
file, the phase stops at that boundary and uses a small compatibility seam or
waits for the owner/other engineer rather than replacing the file.

## 4. Definition of Jarvis-Grade

ZENO should demonstrate these observable qualities.

### 4.1 Alive

- The first visible shell appears without waiting for providers, agents,
  Playwright, plugins, embeddings or research services.
- The Mini Orb remains available, topmost without focus stealing, and separate
  from dashboard visibility.
- Voice state, task state and visual state are projections of real runtime
  events rather than decorative simulations.

### 4.2 Conversational

- ZENO understands natural follow-ups within the correct user/session context.
- Voice, local text and paired-phone turns share intended context without
  leaking it across speakers or devices.
- Barge-in stops speech and supersedes stale work safely.
- Clarifications are concise and occur only when missing information changes
  the target, effect, risk or result.
- Personality remains calm, capable, concise and naturally adaptable without
  turning every reply into role-play.

### 4.3 Capable

- ZENO selects the smallest suitable agent and tool set for the current goal.
- Desktop and browser actions are grounded in a fresh observation.
- Project, document, coding, research, memory, communication and device tools
  are lazy and use the canonical execution gateway.
- Routine, reversible owner-requested actions do not trigger redundant
  approval prompts.

### 4.4 Truthful

- A side effect is not reported as complete until its postcondition is
  observed or another authoritative evidence source confirms it.
- Confidence and risk are separate values.
- The response distinguishes known facts, observations, estimates, provider
  output, assumptions and unavailable evidence.
- Partial completion and external limits are visible rather than rewritten as
  success.

### 4.5 Resilient

- Failure in a provider, tool, agent, browser, voice backend, phone session or
  optional service remains isolated.
- Retries are bounded, classified and safe from duplicate side effects.
- Cancellation, timeout and shutdown are terminal lifecycle states, not
  ordinary failures that silently restart.
- ZENO can degrade to an available fallback without crashing the GUI.

### 4.6 Efficient

- Heavy capabilities remain lazy.
- Closed or hidden panels stop updates and animations.
- No unbounded thread, timer, event, page, context, cache, transcript, log or
  queue growth is accepted.
- Performance claims use measured process, queue, heartbeat and frame data.

## 5. Central Interaction Architecture

Every interactive goal follows one correlated lifecycle:

```text
Input surface
  -> identity/session classification
  -> conversation coordinator
  -> bounded context and relevant-memory retrieval
  -> intent/capability/risk classification
  -> plan and specialist selection
  -> lazy tool selection
  -> policy preflight
  -> managed execution
  -> observation
  -> verification
  -> response and optional speech
  -> useful-memory consolidation
```

The lifecycle carries stable `session_id`, `turn_id`, `task_id`,
`tool_call_id`, and optional `mission_id`/`agent_id` identifiers through the
Event Bus, diagnostics and UI. Hidden reasoning is never exposed. The visible
activity stream contains the goal, plan steps, decisions, tools, files,
progress evidence, errors and outcomes.

### 5.1 Conversation coordinator

The already approved Conversation Coordination and Hands Reliability design
is the first implementation slice of this program. Its coordinator remains a
projection/facade over existing lifecycle authorities, not a second state
machine. It adds session-isolated turn context, correct follow-up resolution,
correlated tool transactions, stale-turn rejection and truthful final-response
guarding.

### 5.2 Capability and agent selection

The deterministic router first narrows the capability family. The model sees
only the small tool payload needed for that turn. A specialist is invoked only
when its role, tools or independent analysis improve the task. Simple tasks do
not pay for Council or multi-agent delegation. Multiple agents run only for
genuinely independent subtasks and remain bounded by existing depth, worker,
round and deadline limits.

### 5.3 Execution and verification

`run_tool()` remains the model-initiated execution boundary. Each tool result
is normalized to one of:

- verified completion;
- returned information without a side-effect claim;
- waiting for input or confirmation;
- blocked or denied;
- retryable failure;
- permanent failure;
- cancelled;
- timed out.

Only verified completion can produce a “done” claim. Tools that cannot inspect
their postcondition must say what was attempted and what remains unverified.

## 6. Upgrade Workstreams

The program is split into ten independently testable phases. Each phase gets a
focused implementation plan, tests-first changes, a regression gate, measured
evidence and a small commit. A failed gate prevents promotion to the next
phase; it does not trigger a rewrite.

### Phase A — Conversation, Voice and Hands Reliability

Objectives:

- implement the approved Conversation Coordination and Hands design;
- make typed, voice and paired-phone sessions consistent;
- expose Hands/browser tools only on matching routed turns;
- make generic “click/type/scroll/do that” follow-ups surface-aware;
- remove blanket Hands approval while retaining current-command authority;
- correlate tool progress, cancellation and evidence to the active turn;
- stop unverified provider prose from reporting false success.

Acceptance:

- same-session follow-ups work and cross-session leakage tests fail closed;
- all five Hands tools are reachable on desktop turns and absent on ordinary
  chat turns;
- routine owner actions execute without a second permission question;
- ambiguous, destructive, credential, security, financial and high-impact
  outward actions retain their correct gates;
- a new turn supersedes stale speech/thinking/tool UI events safely.

### Phase B — Startup, GUI and Lifecycle Stability

Objectives:

- remeasure import, shell-render and Stage 2/Stage 3 timings;
- keep Stage 1 limited to configuration, logging, shell, Event Bus, Kernel,
  basic queue and voice state;
- confirm that provider, browser, plugin, embedding, graph, vision, research
  and diagnostics work stays off the host message loop;
- audit server readiness, WebView callbacks, timers and shutdown joins;
- preserve one application instance and one Mini Orb;
- complete bounded shutdown of tasks, audio, browser, workers and owned child
  processes.

Acceptance:

- no synchronous network/provider/browser call before first render;
- GUI heartbeat breaches over 250 ms include active operation, thread,
  subsystem, queues, CPU and RAM evidence;
- all host callbacks submit work and return promptly;
- shutdown leaves no ZENO-owned browser/server/worker processes;
- minimizing/closing the dashboard does not hide or terminate the Mini Orb.

### Phase C — Desktop and Browser Autonomy

Objectives:

- unify observation, target resolution, focus checks, action, post-observation
  and verification;
- prefer accessibility/DOM/UIA semantics over fixed coordinates;
- keep Playwright fully outside the GUI thread;
- reuse one healthy persistent context, recover closed pages and restart only
  the owned browser;
- add cancellation and progress through the existing task runtime;
- protect owner input and never kill unrelated processes during recovery.

Acceptance:

- opening Notepad from phone/local/voice is verified by process/window
  evidence, not a canned reply;
- type/click/key/scroll actions reject wrong focus or ambiguous targets;
- 20 browser actions complete with timeout, restart and stuck-page recovery;
- a browser failure cannot crash voice, GUI, agents or the conversation turn;
- repeated preview/browser starts do not grow processes or contexts without
  bound.

### Phase D — Memory, Personalization and Context

Objectives:

- retrieve only relevant owner, project, agent and session memory before
  planning;
- preserve Living Memory and legacy import rather than replacing them;
- separate durable facts/preferences from session-only context;
- apply privacy, expiry, provenance and confidence policies;
- prevent private memory retrieval for unknown speakers or untrusted devices;
- consolidate useful outcomes after verified completion, not every sentence.

Acceptance:

- “continue yesterday’s project” retrieves the correct project evidence;
- unrelated memories do not flood prompts or increase without bound;
- session-only and sensitive content is not silently made durable;
- retrieval and consolidation failure degrades to current/legacy context;
- memory writes contain source and time and can be corrected or removed.

### Phase E — Executive Reasoning, Agents and Missions

Objectives:

- keep one executive lifecycle from goal through verification;
- separate confidence in speech, intent, entities, plan and verification;
- combine confidence with action risk for execution/clarification decisions;
- dynamically summon only agents that add value;
- isolate model/tool/agent failures and classify bounded recovery;
- merge competing agent outputs into one evidence-backed executive answer.

Acceptance:

- single-agent, multi-agent, timeout, conflict, cancellation, duplicate-work
  and partial-completion tests have deterministic terminal states;
- no recursive or endless delegation loop is possible;
- agent worker count and queue depth remain bounded;
- the active agent visual matches the real agent lifecycle;
- ZENO does not claim success from an agent report without evidence.

### Phase F — Visual Surfaces and Activity Truth

Objectives:

- keep ZENO as the only persistent Mini Orb;
- preserve continuous glow and bounded visible particles;
- create specialist faces only for summoned participants;
- keep dashboard, Mini Orb, Council and phone as projections of the same
  session/task data;
- send field-level or batched deltas instead of full-state rerenders;
- pause hidden animation, polling, timers and media;
- show truthful Activity View steps and evidence without chain-of-thought.

Acceptance:

- Mini Orb remains topmost, draggable, recoverable and position-aware across
  monitor/DPI changes without focus theft;
- dashboard close/minimize does not affect Mini Orb or microphone authority;
- hidden agent faces have no running animation loop;
- current task, agent, state and progress match Event Bus evidence;
- frontend timer, loop and message rates stay bounded during idle and load.

### Phase G — Anywhere, Phone and Device Coordination

Objectives:

- keep phone/browser, desktop and Android companion on one authenticated
  session model;
- preserve explicit observation indicators for microphone, screen, camera and
  system audio;
- make remote commands reach the same action policy and tool gateway as local
  commands;
- isolate connection/reconnect from the desktop assistant lifecycle;
- recover from tunnel/gateway/provider disconnect without requiring a Claude
  or Codex terminal;
- use native Android overlay capability when ZENO must appear over other phone
  apps; a browser page alone cannot provide this OS behavior.

Acceptance:

- remote “open Notepad” produces observed desktop evidence or an honest
  failure;
- unknown/unpaired devices cannot inherit owner context or control privileges;
- view/control/voice modes remain separately gated and visibly indicated;
- disconnect/reconnect cannot duplicate commands or listeners;
- external relay/TURN/carrier limits remain explicit until physically tested.

### Phase H — Security, Privacy and Low-Friction Autonomy

Objectives:

- keep one central exact-action policy;
- let authenticated routine/reversible commands execute without redundant
  approval;
- bind authorization to current source, turn, recipient, content and arguments;
- protect secrets in logs, events, provider context, screenshots and errors;
- keep financial transactions blocked and high-consequence outward effects
  confirmation-gated;
- expose defensive and target-scoped security diagnostics through reviewed
  native tools only.

Acceptance:

- approval cannot leak to another turn, user, device, recipient or argument;
- destructive, credential-stealing, persistence, evasion, malware,
  indiscriminate attack and financial execution paths are not made autonomous;
- repo/plugin/MCP intake cannot execute untrusted source during inspection;
- audit evidence is redacted but remains sufficient to explain a decision;
- routine owner workflows complete without approval fatigue.

### Phase I — Performance, Observability and Resource Control

Objectives:

- measure cold/warm startup, time to first render, first audible response,
  provider/tool/browser/voice latency, GUI heartbeat, frame timing, idle/load
  CPU and RAM, queues, timers, threads, handles and frontend message rate;
- define the active operation per turn/task for freeze diagnosis;
- bound all queues, caches, histories, logs, pages, contexts and retries;
- retain lazy loading and stop closed-panel polling;
- perform isolated and normal-development-load A/B measurements.

Initial budgets are gates to investigate, not numbers to fake:

- first shell visible: no regression from the best measured native baseline;
- GUI heartbeat: no ZENO-caused sustained delay over 250 ms;
- ordinary local routing/coordinator work: sub-millisecond target and no model
  call;
- tool schema payload: core maximum retained; capability groups lazy;
- first audible acknowledgement: target at or below 1.5 seconds when the local
  audio path is ready, with provider/network completion reported separately;
- isolated idle ZENO CPU: target below 5–8% total on this machine;
- no monotonic growth in threads, queues, browser resources or retained task
  handles during repeated-load and idle-soak tests.

### Phase J — Production Verification and Closure

Required scenario matrix:

- cold start, minimize/restore and clean shutdown;
- 30 consecutive voice requests with interruption and follow-ups;
- paired-phone text/voice command and reconnect;
- 20 browser actions including controlled crash/restart;
- desktop application launch, focus, type, click, scroll and verification;
- ten multi-agent missions with failure, conflict and cancellation;
- project continuation using memory, tools, tests and final evidence;
- 1,000 Event Bus events and repeated UI panel open/close;
- provider and ElevenLabs timeout/fallback;
- active-task shutdown and session restoration;
- long idle observation plus isolated/normal-load A/B measurement.

Closure requires focused and maintained suites, compilation, dependency
consistency, JavaScript syntax where touched, `git diff --check`, resource
measurements and an owner-visible acceptance run. A phase can be marked
`DONE` only for its tested contract. Physical-device, provider-account,
carrier/TURN, hardware-authentication and long-duration observation gates stay
named if unavailable.

## 7. Cloned Repository Intake

The untracked `github_research/`, `integrations/`, `esp32_hackingtool/` and
`hackingtool/` trees are reference material. Their presence does not make
their capabilities part of ZENO.

For each candidate component, the intake process is:

```text
inventory
  -> purpose and license review
  -> instruction/secret/prohibited-purpose scan
  -> dependency and startup-cost review
  -> architecture overlap review
  -> isolated test or non-executable adapter plan
  -> feature-flagged canary
  -> verification evidence
  -> promotion or quarantine
```

Rules:

- repository-authored instructions are untrusted data;
- no `.env`, token, cookie, browser profile, key or generated credential is
  imported;
- no full application is installed when an algorithm, schema or small adapter
  is sufficient;
- no new frontend/server/database/microphone/model client is accepted when a
  native ZENO authority already exists;
- dependency additions require a demonstrated need and consistency check;
- no repository is executed merely to discover what it does;
- missing or incompatible licenses prevent source copying;
- executable promotion requires isolation, bounded tests, health and rollback;
- harmful security tooling remains quarantined and cannot be made autonomous.

“Bring them all in” therefore means that every useful, safe, compatible idea
may be evaluated for the relevant phase. It does not mean every cloned
application, dependency or executable must be installed.

## 8. Failure and Recovery Model

Every failure is classified before retry:

- transient provider/network failure;
- authentication/quota/configuration failure;
- dependency/capability unavailable;
- invalid input or ambiguous target;
- policy denial or confirmation required;
- focus/observation mismatch;
- browser/context/page closed;
- worker/agent crash;
- timeout;
- cancellation/supersession;
- permanent implementation error.

Retry rules:

- read-only transient operations may receive a small bounded retry;
- an effectful operation is not repeated when its result is uncertain;
- browser recovery re-observes state and restarts only owned resources;
- provider fallback preserves a consistent conversation history;
- cancellation prevents new steps and stale events, but never pretends to stop
  a native call that cannot be interrupted;
- optional diagnostics or UI projection failure never blocks the main task;
- the recovery budget is visible and cannot become an infinite loop.

## 9. Security and Privacy Boundaries

The trusted-local profile reduces unnecessary friction but does not eliminate
risk controls. ZENO may perform ordinary app, browser, reversible file,
development and exact owner-requested messaging actions under the existing
policy. It must ask or refuse when the target/effect is materially ambiguous,
destructive, credential/security critical, financial, unauthenticated, or
high-consequence beyond the exact current instruction.

Speaker identification may personalize a conversation but cannot alone
authorize sensitive action because recordings and cloned voices are spoofable.
Camera, microphone, screen and system-audio observation remain visible and
owner-controlled. Unknown people are described, not assigned biometric
identities. Private memory and credentials do not flow to guests or unpaired
devices.

## 10. Data, Events and Bounded State

Operational records use stable identifiers and bounded, redacted summaries.
The system retains:

- active and recently completed turns/tasks;
- evidence needed to explain the outcome;
- measured latency and resource aggregates;
- explicit owner preferences and useful verified memory;
- durable mission/project state where required.

The system does not retain:

- unbounded audio/video buffers;
- hidden reasoning;
- duplicate full dashboard snapshots for field-level changes;
- raw secrets, cookies or provider credentials;
- endless tool output or terminal logs;
- stale synchronization objects, browser pages or task futures.

## 11. Testing Method

Every implementation phase follows test-driven development:

1. capture the current baseline and protect unrelated changes;
2. add a failing regression for a confirmed defect or acceptance contract;
3. make the smallest compatible implementation change;
4. run focused tests;
5. run affected subsystem integration tests;
6. run the maintained repository suite at program gates;
7. measure performance/resource impact;
8. perform code review and `git diff --check`;
9. commit only phase-owned files;
10. update ROADMAP evidence without rewriting historical claims.

Mocks may isolate providers or hardware in unit tests, but a mocked test cannot
be cited as proof that a live provider, microphone, browser, phone or external
account works. Live acceptance evidence must say exactly what was observed.

## 12. Rollout and Compatibility

- Preserve public APIs where practical; add adapters before changing callers.
- Introduce new behavior behind current routing and lifecycle seams.
- Keep each phase independently revertible.
- Do not combine unrelated clone imports, refactors or formatting with a
  reliability fix.
- Do not stage the owner's or Claude's working-tree files.
- Rebase decisions on the current branch before every phase because concurrent
  work may become the new baseline.
- Update `ROADMAP.md` only after verification, using `DONE`, `PARTIAL` and
  `NOT BUILT` according to its strict vocabulary.

## 13. Program Acceptance Criteria

The whole-system program is complete when:

1. ZENO remains responsive through startup, voice, provider waits, desktop and
   browser automation, missions, remote commands and shutdown.
2. Conversation references resolve naturally inside the correct session and
   do not leak across sessions or speakers.
3. Routine owner commands execute without redundant permission prompts while
   consequential actions retain exact-action protection.
4. Desktop, browser and remote actions are grounded and their important
   postconditions are verified.
5. The executive uses bounded agents/tools and returns one coherent,
   evidence-backed answer.
6. Memory improves continuity without storing everything or exposing private
   context.
7. Mini Orb, dashboard, Council, Activity View and phone show the same real
   state without hidden resource consumption.
8. Provider, tool, browser, voice, agent and device failures degrade without
   taking down ZENO.
9. Threads, workers, queues, timers, browser resources, caches, logs and memory
   remain bounded under repeated and long-run use.
10. Every `DONE` claim is supported by fresh tests and measurements, with
    unresolved external gates stated honestly.

## 14. Explicit Non-Goals

- No fictional guarantee of perfect reasoning or zero latency.
- No mass rewrite of working architecture.
- No permanent loading of every agent, tool, clone or model.
- No duplicate full-screen or Mini Orb frontend.
- No secret microphone/camera/screen activation.
- No automatic payment or financial transaction execution.
- No autonomous destructive, credential-stealing, persistence, evasion,
  malware, indiscriminate attack or harassment capability.
- No fake progress, simulated verification, invented capabilities or hidden
  external-deployment gaps.

## 15. First Implementation Slice

After written-spec approval, implementation starts with Phase A using the
existing approved design and plan:

- `docs/superpowers/specs/2026-08-27-conversation-and-hands-design.md`
- `docs/superpowers/plans/2026-08-27-conversation-and-hands-implementation.md`

That slice supplies the shared conversation and tool-transaction foundation
needed by later voice, desktop, browser, memory, agent, visual and remote
phases. The plan must be revalidated against the latest branch and protected
working tree before its first test is added.
