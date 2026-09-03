# ZENO Proactive Heartbeat and Autonomous Assistant Design

**Date:** 2026-09-03  
**Status:** Approved design direction; written-spec review pending  
**Scope owner:** ZENO core runtime

## Goal

Make ZENO a quiet proactive assistant that observes safe facts, retains useful changes, and surfaces only relevant notices. A proactive path remains a normal ZENO turn or a registered read-only check. It must not become a second assistant, executor, scheduler, notification store, memory authority, or permission bypass.

## Existing systems retained

- agent.run_agent is the shared reasoning and tool-turn entry point and already supports a background action source.
- scheduler.BackgroundScheduler is the single periodic scheduler; it submits finite jobs to the worker pool and avoids overlap.
- heartbeat.py persists scheduled checks, simple notice records, and a pause switch. Its generic checks are model-first and it lacks typed check metadata and full delivery lifecycle.
- proactive.py separately polls battery, long sessions, Dream Mode, and morning briefing. It duplicates heartbeat notice behavior and must lose its independent schedule.
- notifications.py persists delivery settings, deduplicates records, applies quiet hours and Do Not Disturb, and owns the notification bus/channel adapter.
- activity_monitor.py supplies non-invasive local idle signals; dream_mode.py supplies interruptible low-priority maintenance.
- event_bus.py, workspace, the existing phone projection, memory manager, action policy, and confirmation remain authoritative.

## Boundaries

- Do not add Dockview, React, Electron, a new scheduler thread, another event bus, another notification endpoint, or a direct tool-execution path.
- Do not change cybersecurity, surveillance, RF, network-security, penetration-testing, or security-agent behavior.
- Never store tool input, secrets, arbitrary result bodies, private message text, raw memory, or prompt content in proactive state.
- No automatic consequential action. A heartbeat may create a held proposal but existing policy and confirmation control every external, destructive, account, payment, messaging, or privileged action.
- The Proactive Panel uses the existing UniversalPanelManager contract. This work does not create independent panel movement logic.

## Architecture

    registered typed checks and Event Bus changes
                     |
                     v
              HeartbeatEngine
                     |
          due, overlap, budget, load gates
                     |
                     v
     existing scheduler and worker pool
                     |
             bounded CheckResult
                     |
                     v
      ProactiveImportanceEvaluator
                     |
      ignore | log | inbox | notify | urgent
                     |
                     v
       ProactiveNoticeStore
                     |
      existing notifications delivery adapter
                     |
                     v
 Workspace, desktop, Mini Orb, and phone projections

HeartbeatEngine replaces only scheduling ownership: heartbeat.py becomes the one engine and proactive.py becomes a compatibility adapter with no scheduled loop. Existing heartbeat SQLite tables migrate forward, preserving user-created schedules and existing notices.

## Shared turn context

Add a TurnContext record at the shared agent entry seam:

    turn_id, source, user_present, proactive, priority,
    owner_authenticated, conversation_id, execution_id, timestamp

Source is TEXT, VOICE, PHONE, PANEL, HEARTBEAT, AGENT, or SYSTEM_EVENT. Interactive front doors map into the same context without changing permissions. A proactive synthesis call uses the existing agent turn with HEARTBEAT, proactive true, user_present false, and owner_authenticated false. It receives only compact factual data. It may summarize candidates; it cannot authorize side effects.

Threshold checks, deadline calculation, dedupe, quiet-hour decisions, presence, and delivery are deterministic and never invoke a model.

## Scheduled check registry

A versioned ScheduledCheck record contains:

    id, description, enabled, interval_s, priority, timeout_s,
    overlap_policy, quiet_hours_policy, handler_id, event_types,
    next_due_at, last_run_at, last_success_at, last_failure_at,
    consecutive_failures, last_result_fingerprint

The registry maps safe handler IDs to registered callables. A handler returns bounded CheckResult facts: state, subject, summary, dedupe key, importance hints, and optional panel target. It cannot return instructions.

Initial checks use only verified existing capabilities: calendar due events, notification changes, downloads/tasks/activity events, safe system/provider/battery/storage probes, current workspace activity, Dream Mode eligibility, and existing authenticated phone-connection events. No fake email, GitHub, job, or message check is added.

Overlap policies are SKIP, COALESCE, and QUEUE_ONE. The existing scheduler stays responsible for finite job execution. Check state is persisted in the heartbeat database and startup staggering spreads non-critical first runs so restart cannot create a burst.

## Importance, deduplication, and notice lifecycle

ProactiveImportanceEvaluator is deterministic. It maps CheckResult to IGNORE, LOG, INBOX, NOTIFY, or URGENT from state transitions, configured thresholds, due windows, priority, and owner preferences. CPU within normal range is IGNORE; download completion is INBOX; a meeting due soon is NOTIFY; critically low storage is URGENT; a recovered provider is LOG.

ProactiveNoticeStore extends the heartbeat SQLite database with:

    id, created_at, updated_at, source, subject, condition, dedupe_key,
    importance, title, summary, facts_json, delivery_state, voice_policy,
    panel_target, explanation, count, surfaced_at, seen_at,
    acknowledged_at, expires_at

Delivery state is NEW, HELD, SURFACED, SEEN, ACKNOWLEDGED, DISMISSED, or EXPIRED. The dedupe key is source + subject + condition. A repeated condition updates one record's count and safe summary; it never creates another alert. Existing notifications remain the delivery mechanism. Proactive records are stored first, then eligible records are projected through the existing notification API and bus. The generic notification database is not replaced.

## Presence and delivery

Presence derives only from existing normal signals: dashboard activity, conversation state, desktop idle duration, and safely available locked/unknown signals. It is ACTIVE, IDLE, AWAY, LOCKED, or UNKNOWN. No camera, microphone, screenshot, or surveillance signal is used.

Delivery evaluates pause state, quiet hours, timed Focus Mode, presence, current conversation state, importance, and voice policy in that order. Quiet hours and focus hold normal and important notices. Urgent delivery follows explicit owner policy. During a conversation, non-critical notices remain HELD until a terminal conversation-state event. On owner return, eligible HELD notices become SURFACED and ZENO offers one concise catch-up, never a speech burst.

Voice policy is SILENT, VISUAL_ONLY, VOICE_WHEN_IDLE, or VOICE_NOW. Only explicit urgent rules may use VOICE_NOW. Voice delivery uses the existing TTS path and failure never removes the stored notice.

Pause Proactive ZENO stops new scheduled executions and interruptions but leaves direct turns available. Resume recomputes what remains relevant and discards stale low-value work; it does not replay every missed interval. Focus Mode is a persisted expiry that suppresses delivery while retaining inbox records.

## Performance, budgets, and recovery

HeartbeatEngine is one modest scheduler job. It returns immediately when no check is due. Checks run at worker-pool background priority with finite timeouts. Existing load evidence postpones low-priority work under CPU, RAM, queue, active-worker, gaming, voice, media, or active-conversation pressure.

Background model use is disabled by default for user-created plain-language checks. Explicit synthesis checks have per-hour call, daily token, and concurrent-call budgets. A rejected synthesis request produces at most a LOG record.

A check failure is isolated, persisted, and backed off. Existing health/circuit-breaker evidence controls repeated external failures. On recovery, only a fresh current check runs; stale missed polls do not replay. A confirmation-required opportunity becomes a HELD proposal and no worker waits for owner input.

Dream Mode becomes a registered low-priority, interruptible check. It yields when user activity, conversation, voice, or load returns. It may compact expired notices and safe metadata, never permissions or safety thresholds.

## Workspace, phone, agents, and memory

Add Proactive Panel to the existing workspace registry. Its projection shows NOW, NEEDS ATTENTION, HELD, COMPLETED, and DISMISSED. Acknowledge, dismiss, and Why actions use bounded workspace API calls. It inherits the shared panel capability contract; no panel-specific geometry implementation is added.

Workspace and Event Bus provide one compact redacted snapshot to desktop, Mini Orb, and phone. Phone uses the same notice records and does not own a second inbox. Existing protected notification delivery can be reused without adding public endpoints or altering authentication.

Memory retrieval is bounded, redacted, and treated as data rather than instructions. It can supply owner-approved preferences such as quiet hours or briefing style. Repeated dismissals lead to a suggestion, never an automatic safety-threshold or permission change.

Heartbeat does not casually summon specialists. A complex allowed task uses the normal ZENO task/policy path and returns one synthesized result to HeartbeatEngine. Specialists never produce parallel owner notifications.

## Configuration, diagnostics, and verification

Persist one ProactiveSettings record: enabled state, quiet-hour override, focus expiry, gaming behavior, check enablement/interval overrides, thresholds, voice/delivery policy, briefing settings, and model budgets. Defaults are conservative and quiet.

A loopback diagnostic projection exposes heartbeat health, registered/enabled/running counts, next due, held count, failures, pause/focus state, model budget, and last tick duration. It excludes secrets, message bodies, raw prompts, tool inputs, and private memory.

TDD covers migration/restart/staggering, all overlap policies, deterministic importance, dedupe/lifecycle/expiry/explainability, quiet/focus/away/conversation delivery, direct-turn priority, action-policy denial, load and gaming deferral, zero model use for deterministic checks, model budgets, failure isolation/backoff, shared desktop/phone state, panel registration, Dream Mode interruption, memory bounds, agent result synthesis, and duplicate-loop prevention. Deterministic stress covers repeated events, schedules, and restart integrity. Physical CPU, RAM, event-loop lag, and voice latency are reported only from an actual desktop measurement.

## Acceptance criteria

- Check schedules survive restart without a startup burst.
- Duplicate running checks and duplicate notices are prevented.
- Routine inactivity is silent and uses no model.
- Away, quiet, focus, and active-conversation notices persist as HELD then surface once appropriately.
- Direct conversation, voice, and user work take priority over heartbeat and Dream Mode.
- Pause preserves direct ZENO interaction while stopping proactive work.
- Proactive work stays inside current registry, execution, health, confirmation, and permission boundaries.
- Desktop and phone share one proactive state; the panel uses shared panel behavior.
- Offline or failed checks cannot crash the engine, leak data, or spin retries.



