# ZENO Charm Engine Design

## Purpose

Build one native, lazy ZENO Charm Engine for context-aware conversational coaching and reply drafting. It must use ZENO's existing brain, provider router, memory, personality, voice path, Event Bus, and tool boundary. It must not embed or run the three cloned applications as separate assistants.

## Repository Findings

### `integrations/Rizzbot`

Useful ideas:

- structured user style profiles;
- multi-candidate response groups;
- explicit `WAIT`, `MATCH`, `PULL_BACK`, and `ABORT` recommendations;
- feedback bias only after a meaningful sample count;
- bounded local feedback history.

Rejected integration:

- its React/Vite/Cloudflare/Firebase/Gemini application stack;
- its independent voice recorder and service;
- its prescriptive slang-heavy prompts;
- its database and authentication services.

It has no repository license file, so only architectural ideas and independently implemented schemas/algorithms may be used.

### `integrations/rizz-ai`

Useful ideas:

- context-first analysis before reply generation;
- small deterministic context features.

Rejected integration:

- Flask server, OCR/screenshot pipeline, Gemini client, and template fallback replies.

No dependency from its seven-package requirements file is required. It has no repository license file.

### `integrations/RizzMa`

Useful ideas:

- bounded recent-message windows;
- cooldown/recent-suggestion caps;
- staged analyze/generate/review workflow;
- failure isolation and bounded caches.

Rejected integration:

- its 342-package environment, macOS-only packages, Supabase, LangChain/LangGraph, separate model clients, microphone/camera/face systems, Flutter app, web server, and import-time environment/network coupling.

It also has no repository license file. No code is copied verbatim.

## Considered Approaches

### A. Native deterministic analysis plus one existing-provider generation call (selected)

Local analyzers produce context, reciprocity, momentum, tone, pressure, and safety signals. ZENO's existing provider router generates a bounded candidate set in one call. A local critic normalizes scores and ranks candidates. This is light, testable, provider-independent, and preserves one brain.

### B. Prompt-only feature in the main system prompt

This is fast to add but cannot provide stable candidate schemas, ranking, callback memory, explicit safety signals, or testable behavior. It is rejected.

### C. Run/adapt one cloned application behind an HTTP bridge

This duplicates web servers, models, memory, microphone, and UI state and imports unnecessary dependencies. It is rejected.

## Package Architecture

`reyes_agent/charm/` contains:

- `models.py`: modes, request/response/candidate/score dataclasses, context signals, recommendations, and validation;
- `context.py`: deterministic conversation parsing, tone/reciprocity/momentum and back-off detection;
- `styles.py`: the fourteen supported style profiles and intensity constraints, without canned lines;
- `generator.py`: one adapter over `provider.run_turn`, structured candidate parsing, bounded failure handling, and injectable generation for tests;
- `critic.py`: deterministic risk/quality scoring, repetition detection, disqualification, and ranking;
- `memory.py`: bounded session callback memory and a privacy-filtered adapter to ZENO's normal memory;
- `engine.py`: orchestration and the public lazy singleton;
- `routing.py`: deterministic Charm-intent detection for capability routing;
- `__init__.py`: stable public API only.

`reyes_agent/tools/charm_tools.py` registers the native tools. No separate server, database, microphone, provider client, frontend framework, or background loop is introduced.

## Supported Modes

The mode enum and selector support exactly:

- Natural
- Smooth
- Sweet
- Flirty
- Playful
- Funny
- Witty
- Romantic
- Confident
- Gentleman
- Cheeky
- Deep
- Serious
- Pidgin Smooth

Mode profiles define goals, constraints, warmth/humor/flirt targets, and forbidden tendencies. They do not contain pickup lines or fixed candidate text.

## Request and Result Model

`CharmRequest` includes:

- current conversation/recent messages;
- owner instruction and objective;
- relationship/context supplied by the owner;
- mode;
- candidate count (bounded to 1–5);
- intensity (0–100);
- optional response-lab scores;
- feature (`reply`, `opener`, `compliment`, `humor`, `storytelling`, `recovery`, `after_send`, `simulator`, or `voice_coach`).

`CharmResult` includes:

- analyzed context signals;
- recommendation (`CONTINUE`, `WAIT`, `MATCH`, `PULL_BACK`, or `ABORT`);
- ranked candidates with stable IDs and component scores;
- selected best candidate when safe;
- transparent confidence/reasons;
- warnings and honest provider errors.

## Context Analyzer

The analyzer uses only the supplied current conversation plus a bounded recent window. It measures:

- speaker/message balance and reciprocity;
- unanswered streak and response length;
- repeated/dry replies;
- engagement and conversation momentum;
- current tone and relationship context;
- direct refusal, requests to stop, discomfort, or repeated lack of interest.

The analyzer is deterministic and lightweight. Nigerian English and Pidgin markers are treated as normal language variation, not lower quality.

If the other person says no, asks to stop, appears uncomfortable, or repeatedly disengages, the result recommends `PULL_BACK` or `ABORT`. Romantic/flirty candidate generation is skipped rather than escalated.

## Generation

The generator uses `reyes_agent.provider.run_turn()` with no tools and one tightly bounded structured-output request. This preserves configured provider fallback, timeouts, metrics, and circuit-breaking. It requests the candidate text and short rationale only; scores are not trusted solely because a model claimed them.

Malformed or unavailable provider output returns an explicit error. The engine does not fall back to hard-coded pickup lines or claim generated advice exists when it does not.

## Critic and Ranker

The critic scores each candidate from 0–100 for:

- naturalness;
- context relevance;
- confidence;
- warmth;
- humor;
- flirt level;
- pressure;
- desperation risk;
- cringe risk;
- repetition risk.

Quality scores reward context fit, brevity appropriate to the conversation, mode alignment, and non-repetition. Risk scores detect pressure, repeated requests, excessive pleading, manipulation, overclaiming intimacy, spammy punctuation, and copied recent suggestions. Candidates that violate explicit back-off signals are disqualified. The ranker selects the best eligible candidate rather than the first response.

## Your Voice Model and Memory

The engine keeps a bounded, process-local session store containing recent conversations, recent candidate hashes, selected candidate IDs, callback topics, mode, and aggregated feedback. This supports Callback Memory, Conversation Momentum, Response Lab, After-Send Coach, and repetition prevention without retaining unbounded conversations.

Durable memory is opt-in only. Explicit instructions such as “remember that I prefer short playful replies” use ZENO's existing memory tools/policy. The Charm adapter retrieves only relevant non-sensitive communication preferences through the normal memory manager. It never uses eMEM spatial memory and never copies private conversation transcripts into long-term memory automatically.

## Tool Surface

- `charm_reply`: analyze context, generate/rank 1–5 candidates, and return the best reply plus optional scores.
- `charm_analyze`: context/tone/reciprocity/momentum/back-off analysis without generation.
- `charm_set_mode`: change the session mode directly.
- `charm_status`: list modes, current mode, intensity, provider state, and bounded session counts.
- `charm_feedback`: record bounded owner feedback against a generated candidate.
- `charm_coach`: expose opener, compliment, humor, storytelling, recovery, after-send, simulator, and voice-coach features through the same engine.

All tools are lazy and use the existing tool registry. The routing layer recognizes explicit commands and the hybrid automatic case: clear social-reply requests load Charm quietly, while low-confidence ordinary conversation stays on the normal ZENO path.

## Messaging and Smart Autonomy

Charm generates or analyzes by default; it never sends. `charm_reply` and `charm_coach` do not contain transport code.

If the owner later says “send her the second one,” the existing messaging tool performs the send. The Smart Autonomy Policy treats that explicit authenticated command as Level 2 authorization for the selected candidate and exact recipient/content. No automatic sending, mass messaging, impersonation, harassment, or open-ended conversation delegation is added.

## Voice

Voice requests enter through ZENO's existing microphone/VAD/STT/wake pipeline and the shared agent loop. Charm starts no audio stream and imports no independent STT/TTS package. Results are spoken through the existing TTS path. `voice_coach` analyzes supplied transcript/context; it is not another continuously listening service.

## Events and Performance

The engine emits bounded `charm.started`, `charm.analyzed`, `charm.generated`, `charm.ranked`, `charm.backoff`, and `charm.failed` events without storing full private transcripts in event payloads. There is no polling, timer, hidden render loop, eager model load, or startup initialization.

One request uses at most one generation call. Candidate count is capped at five, context windows and session caches are bounded, and hidden/inactive state consumes effectively no CPU.

## Testing

Tests cover:

1. initialization and lazy singleton behavior;
2. every mode name and mode selection;
3. Natural, Smooth, Funny, Sweet, and Pidgin Smooth generation;
4. 1–5 candidate generation and malformed-provider isolation;
5. deterministic ranking and every score field;
6. cringe, desperation, pressure, and repetition penalties;
7. context, reciprocity, momentum, callback memory, and intensity;
8. no/repeated-no/uncomfortable/stop back-off behavior;
9. all coach feature names;
10. privacy-safe bounded memory;
11. tool and capability-router integration;
12. draft/send separation through Smart Autonomy;
13. no microphone/web-server/provider duplication;
14. existing conversation, provider, memory, voice, tool, safety, and routing regressions.

## Dependencies

No new dependency is required. The cloned applications remain uninstalled and unmerged. ZENO reuses its current standard library, provider, memory, Event Bus, and pytest infrastructure.

## Non-goals

- No canned pickup-line database.
- No coercive, deceptive, harassing, or automated mass messaging.
- No automatic send from a generation request.
- No new microphone, camera, web server, database, provider client, or frontend.
- No eMEM/spatial-memory coupling.
- No guarantee that a social outcome will succeed; the system reports advice and confidence, not certainty.
