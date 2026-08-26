# ZENO Smart Autonomy Policy Design

## Purpose

ZENO must treat a clear command from an authenticated owner as authorization for the routine action described by that command. It must not ask the owner to approve the same action twice. It must still clarify ambiguous targets, require the deliberately requested approval for a full Council meeting, protect consequential actions, reject structurally forbidden operations, and verify outcomes independently of authorization.

## Confirmed Existing Problem

The current tool boundary composes several independent gates:

1. agent capability scope;
2. the contextual security facade;
3. installation capability permissions;
4. per-tool `requires_confirmation` flags;
5. confidence risk classification;
6. voice identity checks;
7. local autonomy flags; and
8. remote-owner auto-approval.

Those layers can disagree. In particular, outbound messaging is enabled for this installation, but `confidence.decide_tool()` classifies all messaging as high risk and treats missing intent confidence as a confirmation reason. The exact user command is not available to `run_tool()`, so the boundary cannot distinguish “write a message” from “send this exact message.” Full Council invocation currently has no confirmation flag, while several reversible actions such as moving one file or forgetting a recoverable memory have blanket flags.

## Considered Approaches

### A. Central contextual action policy (selected)

Create one `ActionPolicy` that receives the proposed tool call plus a request-scoped owner-command context and returns one of `EXECUTE`, `CLARIFY`, `COUNCIL_APPROVAL`, `HIGH_IMPACT_CONFIRMATION`, or `DENY`. Keep capability restrictions and verification as inputs/consumers of that result rather than competing approval engines.

This is selected because it can distinguish intent, actor, target, reversibility, and consequence at the one existing execution boundary.

### B. Expand `permissions.py` only

This is smaller but insufficient. A capability table cannot distinguish a draft from an explicit send, a normal rename from an overwrite, or one full Council meeting from normal agent delegation.

### C. Add per-tool conditional confirmation callbacks

This gives each tool precise control but scatters policy across many modules and recreates the drift the project already documents. It is rejected.

## Policy Model

### Decisions

- `EXECUTE`: run now and audit the scoped authorization.
- `CLARIFY`: do not execute because the intended action, target, recipient, or content is genuinely unclear.
- `COUNCIL_APPROVAL`: queue exactly one approval for `convene_council`.
- `HIGH_IMPACT_CONFIRMATION`: queue one approval for a consequential but permitted action.
- `DENY`: do not run because the capability, actor, or action is structurally forbidden.

### Autonomy levels

- Level 0 — thinking: analysis, planning, retrieval, and internal delegation; execute.
- Level 1 — routine: reversible local actions and ordinary tool use; execute.
- Level 2 — requested external action: execute only when the current owner command clearly asks to perform that exact outward action.
- Level 3 — special: a full Council meeting; ask once.
- Level 4 — high impact: confirm if permitted, deny if structurally forbidden.

### Request context

`ActionContext` is stored in a `ContextVar`, so it is scoped to one turn and follows worker-pool context without becoming global mutable state. It contains:

- original owner utterance;
- normalized utterance;
- source (`local_text`, `voice`, `paired_phone`, `background`, or `internal`);
- actor trust and whether the owner is strongly authenticated;
- turn ID and optional batch ID;
- explicit execution versus drafting intent;
- the approved tool/argument fingerprint after evaluation;
- creation and expiry timestamps.

The context is created once around `run_agent()`. Internal specialist calls inherit it only for subtasks that remain within the current request. Heartbeats and other background turns have no owner authorization and cannot manufacture Level 2 authority.

### Trusted command sources

- Local typed commands are owner commands on this installation.
- A paired phone command is trusted only after the existing authenticated/elevated session checks.
- Voice can authorize Level 2 only with `OWNER_CONFIRMED` speaker evidence.
- `LIKELY_OWNER`, unknown, insufficient, or multiple-speaker voice may converse, but cannot authorize outward/private actions.
- Device revocation, agent capability scopes, OS privacy controls, and blocked installation capabilities always win.

## Classification Rules

### Routine actions

Opening/focusing apps and sites, normal browsing, ordinary file creation or non-overwriting rename, clipboard use, media controls, screenshots explicitly requested, normal memory saves and recoverable removals, development inspection/edit/test/lint/format flows, internal delegation, Charm operations, and normal UI changes are Level 0 or 1.

The legacy `requires_confirmation` flag becomes a risk hint, not an unconditional queue. This prevents reversible operations from being trapped by historical blanket flags.

### Outward actions

Messaging, email, ordinary authorized service submissions, and public posts are Level 2 only when the current command uses a clear execution verb such as `send`, `tell`, `message`, `reply`, `forward`, `post`, or `submit`. `write`, `draft`, `suggest`, and `create a message` never authorize sending.

The policy fingerprints the exact tool arguments for that turn. The fingerprint cannot authorize changed recipients, changed content, a reply to a later message, or an extended autonomous conversation. Extractable quoted content and named recipients must match the proposed arguments. References such as “send that” are valid only in the current conversation turn and are still bound to the final proposed arguments in the audit record.

### Ambiguity

Missing required target/content, unresolved pronouns without conversation context, conflicting recipients, and unclear destructive targets produce `CLARIFY`. After clarification, a routine action executes without a second approval. Clarification is not confirmation.

### Full Council

Only `convene_council` is Level 3. Normal `delegate` and specialist/team routing remain Level 0. A direct request to call the Council still uses the single explicit Council approval required by the specification; approval executes the already fingerprinted queued request.

### High impact and denied actions

High-impact confirmation remains for irreversible/broad deletion, overwriting important data, account/security credential changes, public exposure of private information, major permission grants, and similarly consequential operations.

Financial execution, unauthorized access, destructive disk operations, credential theft/exposure, and other structurally blocked actions remain denied. No wording or confidence score can open them.

## Enforcement Flow

`tools.run_tool()` remains the sole gated execution boundary:

1. validate tool registration and canonical arguments;
2. enforce agent capability/argument scope;
3. evaluate installation capability and device/voice trust;
4. call `ActionPolicy.evaluate(tool, args, context)` once;
5. execute, clarify, queue one approval, or deny according to that decision;
6. audit the decision and authorization fingerprint;
7. execute through the existing isolated executor;
8. verify/report the outcome through existing result classification.

Compatibility facades in `autonomy.py`, `policy_engine.py`, and `security/policy/engine.py` delegate to the central policy where appropriate. They must not independently reintroduce confirmation.

## Confidence and Verification

Confidence remains diagnostic evidence. Low intent/entity confidence may cause `CLARIFY` when it means the target is unclear. Unknown confidence alone does not turn a routine explicit command into a confirmation prompt.

Authorization answers “may ZENO attempt this?” Verification answers “did it actually happen?” These remain separate. ZENO must not report success until the existing tool verifier or result classifier provides evidence.

## Retries and Batches

A batch owner command creates one turn-scoped authorization envelope. Every child action is evaluated independently but is not reconfirmed merely because it is a later step. Safe transient retries reuse the same tool-and-argument fingerprint, have a bounded attempt count, and never widen the action scope.

## Prompt Behavior

System/router/tool wording will state:

- clear routine commands are already authorized;
- draft verbs never mean send;
- full Council requires its one approval;
- consequential/ambiguous/unauthorized actions retain safeguards;
- routine development continues through inspect/edit/test/fix/retest without administrative pauses.

Only obsolete blanket-confirmation wording will be changed.

## Testing

Tests will exercise the policy directly and through `run_tool()`:

- routine app/site/search/folder/mode/memory actions execute;
- explicit exact sends do not queue;
- drafts do not send;
- uncertain voice cannot authorize outward actions;
- owner-confirmed voice and paired-owner phone can authorize exact Level 2 actions;
- authorization expires and argument changes do not reuse it;
- normal delegation executes while Council queues;
- ambiguity clarifies once;
- high-impact, financial, and unauthorized actions remain protected;
- batches and bounded safe retries do not create repeated confirmations;
- existing safety, confidence, permission, remote-access, Council, tool, and conversation tests remain green.

## Non-goals

- No weakening of OS microphone/privacy permission.
- No financial transaction capability.
- No automatic romantic-message sending without an explicit execution command.
- No second scheduler, permission database, or confirmation queue.
- No removal of audit or postcondition verification.
