# ZENO Conversation Coordination and Hands Reliability Design

**Date:** 2026-08-27  
**Status:** Approved for planning  
**Scope:** Conversation continuity, turn coordination, and reliable handling of ZENO Hands tools.  
**Out of scope:** Replacing ZENO's brain, voice system, Event Bus, worker runtime, permission engine, computer-use engine, or Claude's concurrent work.

## Problem Statement

ZENO already has working components for conversation lifecycle state, wake/follow-up continuity, turn-boundary detection, shared conversation history, unified session coordination, tool routing, action authorization, and grounded desktop input. The components are not consistently projected into one turn-level view.

The confirmed user-visible tool defect is narrower and concrete: `type_text`, `press_keys`, `click_element`, `send_to_chat`, and `scroll_screen` exist as the ZENO Hands tools, and the capability router selects them for desktop intent, but they default to the `extended` provider group. A routed desktop turn normally builds only the core provider payload, so those selected tools may not actually be shown to the model.

Conversation state can also become difficult to interpret because lifecycle state, follow-up-window state, turn-boundary state, shared history, and unified session state are separately maintained. They have different responsibilities and should not be replaced by another competing state machine, but they need one read model and one turn context.

## Goals

1. Make conversation with ZENO coherent across typed voice, local, and paired-phone turns.
2. Preserve context for natural follow-ups such as “do that,” “click it,” and “continue,” without leaking context between users, devices, or sessions.
3. Make every tool call observable, cancellable where supported, and honestly classified.
4. Make ZENO Hands reliably reachable and grounded in the correct active surface.
5. Never claim that an action succeeded without verified evidence.
6. Avoid unnecessary approval prompts.
7. Preserve startup speed, bounded resource use, and all existing safety controls.

## Non-Goals

- No new model call solely to classify a turn.
- No second executor, worker pool, Event Bus, permission engine, or conversation history store.
- No permanent polling loop.
- No coordinate guessing or blind clicking.
- No automatic retry of consequential input actions.
- No change to unrelated presentation, defense, spatial-memory, Anywhere, or Claude-owned work.

## Design Principles

### One owner per responsibility

- `conversation_state.py` remains authoritative for observable lifecycle state.
- `voice/continuity.py` remains authoritative for whether a wake word is required.
- `voice/turn/manager.py` remains authoritative for speech turn-boundary decisions.
- `unified_session.py` remains authoritative for cross-surface coordination state.
- The existing mutable history remains the provider conversation history.
- `run_tool()` remains the only model-initiated tool execution gateway.
- `computer.agentic` remains the grounded and verified keyboard/mouse engine.

The new coordinator is a facade and projection layer. It does not duplicate any of those authorities.

### Current-command authorization, not approval fatigue

An authenticated, current owner command authorizes the exact routine, reversible action it requests. ZENO must not ask again merely because the action uses the mouse, keyboard, browser, or a normal application.

Confirmation remains necessary only when at least one of these applies:

- the target, recipient, content, or intended effect is materially ambiguous;
- the action is destructive or difficult to reverse;
- the action changes credentials or security settings;
- the action performs a financial transaction;
- the action publishes, submits, or sends high-consequence content not already authorized by the exact current command;
- the speaker or remote source is not sufficiently authenticated for the action;
- an existing installation policy explicitly requires confirmation.

Approval is bound to the exact tool arguments and current turn. It never becomes a general approval window. ZENO must not ask twice when the current authenticated instruction already satisfies the applicable policy.

## Architecture

### Conversation coordinator

Add a lightweight conversation coordinator that creates a bounded `TurnContext` for each accepted user turn and projects important changes into the existing systems.

The context contains only operational data:

- turn and session identifiers;
- source and speaker/privacy classification;
- original and normalized utterance;
- current topic and active surface;
- routed capability and confidence;
- bounded references needed for follow-ups;
- unresolved question or missing input;
- current tool transaction;
- last verified outcome;
- cancellation/supersession status.

It contains no hidden chain-of-thought. It is discarded or summarized at turn completion. Private owner context is never exposed to an unknown speaker.

### Session-scoped context

Follow-up context must be keyed by a stable conversation/session identity rather than a single process-global recent route. This prevents a phone turn, guest voice turn, background heartbeat, or local typed turn from accidentally inheriting another source's active app, recipient, or capability.

The default local session remains source-compatible for current callers. Explicit paired-phone and guest sessions receive separate keys.

The bounded context may retain:

- last explicit capability;
- active application/surface;
- last grounded UI target;
- last verified tool result;
- unresolved clarification;
- current topic/entity references.

It must not retain credentials, raw private tool payloads, or unbounded transcript copies.

### Tool transaction model

Every provider tool call receives a structured transaction record correlated by `turn_id` and `tool_call_id`:

```text
PLANNED
  -> RUNNING
  -> RETURNED_UNVERIFIED | VERIFIED | WAITING | FAILED | CANCELLED | TIMED_OUT
```

The record contains bounded, redacted inputs; timing; policy decision; progress; normalized outcome; evidence summary; retryability; and error category.

The transaction layer observes the existing `run_tool()` result. It does not execute around or bypass that gateway. Existing callbacks and Event Bus events carry the same identifiers so the GUI, activity view, and final response describe the same operation.

### Tool result normalization

All tools continue returning provider-compatible strings. At the execution boundary, ZENO normalizes the observable result into one of:

- verified completion;
- useful returned data with no claimed side effect;
- waiting for input or confirmation;
- blocked/denied;
- retryable failure;
- permanent failure;
- cancelled/timed out.

The final response may say “done” only for verified completion. An unverified return may be described as information received or an attempted action, not success.

## ZENO Hands

### Routing and lazy loading

Assign the five Hands tools to a dedicated lightweight `desktop` tool group and expose that group only when the deterministic capability router selects desktop interaction. This preserves the small ordinary-chat tool payload.

Generic commands such as “click that” or “scroll down” are resolved using the current session's active surface:

- browser surface -> browser tools;
- Windows application surface -> ZENO Hands;
- unknown or conflicting surface -> observe or ask one concise clarification rather than guess.

Follow-ups inherit the surface only within the same bounded session context.

### Grounding and focus safety

Before input is sent:

1. Capture or reuse a fresh, reliable active-window observation.
2. Resolve a click by semantic description/accessibility evidence.
3. Reject ambiguous or missing targets.
4. Confirm the foreground window still matches the observed window.
5. Respect the owner's active keyboard/mouse use.
6. Run the action through existing safety and action-policy gates.
7. Observe the postcondition and report whether it changed.

The Hands wrapper must not pass a blanket `approved=True`. The exact current command and central action policy should authorize routine actions, while the computer safety layer still refuses payments/security actions and gates destructive or irreversible targets.

### Retries

Retries are allowed only when all of the following are true:

- the failure category is explicitly retryable;
- no irreversible or outward effect may already have happened;
- the active window and target are re-observed;
- the current turn is not cancelled or superseded;
- the bounded retry budget remains.

Clicks, sends, submissions, deletes, payments, and security actions are never automatically replayed after an uncertain result.

## Conversation Flow

```text
User input
  -> establish session/speaker context
  -> open turn and normalize language
  -> resolve bounded follow-up references
  -> route capability and active surface
  -> plan or respond
  -> preflight each tool request
  -> execute through run_tool()
  -> observe and normalize evidence
  -> verify or report the exact limitation
  -> update bounded context and unified-session projection
  -> speak/display response
  -> close or supersede the turn
```

### Interruption and supersession

A new user message during speaking stops audio and supersedes the old turn. A new message during thinking or tool execution cancels work when supported and marks late events stale. A consequential action that cannot be safely cancelled is allowed to finish its atomic step, then ZENO reports its observed state rather than starting a conflicting replacement action.

### Clarifications

ZENO asks a question only when the missing information materially changes the target, recipient, content, safety classification, or result. It does not ask for permission to perform routine steps already requested. After the user answers, the pending action resumes within the same session context without requiring them to repeat the full request.

## Error Handling

- Provider failure rolls back only the failed provider turn additions, not previously verified history.
- Tool failure becomes a tool result for the model and a correlated Event Bus event; it does not crash the conversation runtime.
- Malformed tool arguments fail closed or use a deliberately supported safe alias.
- A disconnected UI cannot grow an unbounded event queue.
- Late tool and UI events from superseded turns are ignored.
- Optional diagnostic/projection failures never block the main turn.

## Performance

- Conversation coordination is local and deterministic.
- No extra provider call is added.
- Context and transaction histories are bounded.
- Hands schemas load only for desktop turns.
- No new startup initialization or permanent polling loop is introduced.
- Existing worker-pool boundaries remain unchanged.

## Testing Strategy

Test-driven implementation will add regression coverage for:

1. session-isolated follow-up context;
2. typed and voice turn synchronization;
3. interruption and stale-event rejection;
4. pending clarification continuation;
5. desktop Hands schemas actually present on desktop turns;
6. Hands schemas absent from ordinary chat;
7. browser versus desktop resolution for generic click/scroll;
8. type, key, click, scroll, and chat-send success/failure paths;
9. focus moved, target missing, target ambiguous, and owner-busy behavior;
10. routine owner commands executing without redundant approval;
11. destructive, payment, security, unauthenticated, and ambiguous actions remaining protected;
12. normalized verified/unverified/waiting/failed/cancelled tool outcomes;
13. no duplicate or uncertain automatic retries;
14. no false success response;
15. bounded state, event, queue, thread, and tool-schema counts;
16. regression coverage for existing conversation, voice, action-policy, tool-router, and computer-use suites.

## Rollout

Implementation should be split into small compatibility changes:

1. Add failing integration tests for the confirmed Hands routing defect.
2. Correct group mapping and context-aware surface routing.
3. Add the turn-context/coordinator projection behind current APIs.
4. Add tool transaction normalization and correlated events.
5. Remove blanket Hands approval while preserving exact-command authorization.
6. Run focused tests, then the broader ZENO regression suite.

Each step must leave existing callers source-compatible and must not modify or stage Claude's unrelated work.

## Acceptance Criteria

- ZENO follows natural conversation references within the correct session.
- Another device, guest, or background task cannot inherit private/local context.
- ZENO Hands are available when desktop interaction is requested and absent from ordinary chat.
- Routine actions explicitly requested by the authenticated owner do not generate redundant approval prompts.
- Ambiguous, destructive, financial, credential, security, and high-consequence actions remain appropriately gated or refused.
- Every tool operation has a correlated status and honest evidence state.
- Cancellation and interruption prevent stale work from taking over the UI or reply.
- No action is reported as successful without verified evidence.
- Existing conversation, voice, browser, desktop, memory, agent, and tool behavior remains functional.
