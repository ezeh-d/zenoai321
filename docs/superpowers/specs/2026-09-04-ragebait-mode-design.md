# ZENO Ragebait Mode Design

## Purpose and scope

Ragebait Mode is a consensual, owner-to-ZENO entertainment mode for playful
teasing, competitive banter, absurd hot takes, and short battle exchanges. It
extends ZENO's existing humour, Charm Engine, Event Bus, panel engine, and
agent-presence system. It does not introduce a second assistant, a background
listener, a permanent animation loop, or a new model runtime.

The feature is intentionally confined to direct owner conversation. It is not
an instruction modifier for messaging, browser, desktop, phone, social, or
other tool execution.

## Decisions

- Ragebait is off after every restart; no previous consent or battle is
  restored automatically.
- Intensity is bounded to `0..5`, where zero is off.
- A compact battle panel auto-opens only for an active Ragebait battle and is
  removed at the terminal event.
- The default target is the consenting owner. Third-party targets receive no
  ragebait directive, and external messages remain professional unless the
  owner explicitly drafts a harmless message through the existing normal
  drafting flow.
- Stop and serious commands have absolute precedence. They do not receive a
  final joke or comeback.

## Architecture

### `reyes_agent/ragebait.py`

This local, lock-protected module is the authoritative state machine. It
contains:

- `RagebaitState`: enabled/consent state, intensity, optional battle state,
  bounded recent line fingerprints, and a local motion-reaction cooldown.
- `RagebaitBattleState`: active flag, round, maximum rounds, user and ZENO
  entertainment scores, combo count, and non-sensitive summaries of the last
  exchange.
- command classification for activation, deactivation, intensity changes,
  battle starts, and clear stop language;
- `directive(...)` for a compact, safe prompt instruction to the existing
  authoritative turn; and
- local event publication under `ragebait.*`.

No conversation transcript, private memory, voice print, or tool output is
stored in Ragebait state. Recent lines are normalized fingerprints with a
small bounded display-safe summary solely to avoid repetition during a live
session.

### Existing ZENO integrations

`reyes_agent/humour.py` remains the lightweight timing and non-ragebait
humour policy. It consults Ragebait state only after serious-context and stop
checks. The normal conversation pipeline gets a compact directive; it remains
responsible for generating the actual response through its existing fast
provider/fallback path.

The integration must pass an explicit `audience`/`surface` classification.
Only `owner_conversation` is eligible. Tool and messaging paths default to
`external_action`, which always yields no Ragebait directive.

An optional fast local fallback returns a short neutral acknowledgement or
ends a battle if the configured provider fails. Physical/motion events never
invoke a provider directly.

### Event contract

The state module publishes compact, redacted events:

- `ragebait.enabled`, `ragebait.disabled`, `ragebait.intensity_changed`
- `ragebait.battle_started`, `ragebait.round_completed`,
  `ragebait.battle_finished`
- `ragebait.reaction`
- `ragebait.paused` for serious-context interruption

Payloads contain state, bounded score/round data, requested agent identity,
and a safe status label. They do not contain raw user conversation or model
prompt content.

The existing event bridge feeds existing web, phone, mini-orb, agent-presence,
and workspace/panel consumers. No additional Event Bus or polling worker is
created.

### Visuals and agent presence

The presence code consumes the published events to set an existing summoned
agent face to a reviewed expression such as `skeptical`, `smug` (mapped to
`proud`), `thinking`, `excited`, or `success`. ZENO remains the primary face.
Other agents only appear when the current task already summons them; they do
not create desktop windows or voice turns themselves.

A panel-engine view subscribes while a battle is open. It renders round,
maximum rounds, user and ZENO entertainment scores, and local score facets.
It updates only on Ragebait events, preserves panel engine drag/resize/minimize
behavior, and releases the subscription/UI state at battle finish.

### Motion reactions

Existing `motion.shake`, `motion.dizzy`, and `motion.recovered` events are
handled locally. With Ragebait on, a shake can cause one short expression or
directive only after a cooldown. Without it, motion behavior is unchanged.
No motion event makes a model/network request.

## State flow

1. Owner says a clear activation phrase, optionally specifying intensity,
   battle, roast, or explicit dark-humour combination.
2. The state module records consent and emits the activation event.
3. A normal owner turn asks the local policy for a directive; it prevents
   duplicate phrasing and keeps assistance concise.
4. Battle turns increment a bounded round counter. At maximum rounds, ZENO
   emits a completion event and disables the battle while retaining only
   session-bounded anti-repetition history.
5. A clear stop phrase or serious/sensitive context disables or pauses the
   feature before generation. This is synchronous and local.
6. Restart initializes a new state with Ragebait off.

## Safety and failure handling

- `Stop`, `Enough`, `Turn it off`, `Normal mode`, `Serious mode`, and `Don't
  joke` disable the mode immediately.
- Sensitive, emergency, medical, financial-confirmation, destructive,
  security-incident, or serious-system-failure context pauses it.
- Direct insults about protected traits, identity, appearance, trauma,
  disability, finances, or personal vulnerability are explicitly disallowed
  in directives and fallback text.
- Ragebait never changes permissions, confirmation requirements, action
  routing, or tool execution.
- Provider errors are caught by the existing conversation fallback; Ragebait
  state moves to a safe neutral/finished state and keeps the GUI responsive.
- Event publication is best-effort and cannot block the conversation turn.

## Performance

Command parsing, state transition, anti-repeat lookup, score calculation, and
motion cooldown are local O(1) work under a brief lock. History is bounded.
There is no timer, polling loop, microphone, worker pool, animation loop,
or permanent model request. The battle panel is event-driven and exists only
while a battle is active.

## Verification plan

Test-first coverage will include activation/deactivation, intensity bounds,
battle start/round/max-round completion, immediate stop, serious override,
external-message isolation, no duplicate bait, motion cooldown, dark/roast
combination permissions, provider-fallback behavior, restart-off behavior,
event payload redaction, no voice collision, and event-publisher timing.

Integration tests will prove that humour/conversation obtains a Ragebait
directive only for a consenting owner conversation and that the existing panel
engine receives lifecycle events without creating persistent UI activity.
