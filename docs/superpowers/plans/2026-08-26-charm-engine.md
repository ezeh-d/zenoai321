# ZENO Charm Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one lazy, context-aware ZENO Charm Engine with fourteen modes, local analysis, one-call candidate generation, deterministic ranking/risk filtering, bounded callback memory, coaching features, and normal ZENO tool/voice integration.

**Architecture:** `reyes_agent.charm` is a focused Python package. Deterministic local analyzers and critic surround one injectable adapter over ZENO's existing provider router. Tools route through the existing shared brain and Smart Autonomy policy; generation never sends messages.

**Tech Stack:** Python 3.11+, dataclasses, enums, regex, collections/deque, existing ZENO provider/memory/Event Bus/tools, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-charm-engine-design.md`

## Global Constraints

- Do not install or merge the cloned applications or copy their unlicensed code.
- No new model client, web server, microphone, camera, database, frontend, polling loop, or background worker.
- Candidate count is 1–5 and one request makes at most one provider generation call.
- Do not hard-code pickup lines or claim a provider result when generation fails.
- Generate/draft does not send; only a later explicit authenticated send command may use messaging.
- Conversation and suggestion caches are bounded; durable memory is explicit opt-in.
- Preserve ZENO personality, voice, router, memory, Event Bus, and concurrent spatial-memory edits.

---

### Task 1: Domain models and style profiles

**Files:**
- Create: `reyes_agent/charm/__init__.py`
- Create: `reyes_agent/charm/models.py`
- Create: `reyes_agent/charm/styles.py`
- Create: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `CharmMode`, `Recommendation`, `CharmRequest`, `ContextSignals`, `CandidateScores`, `CharmCandidate`, `CharmResult`, `StyleProfile`, `get_style`, and `list_styles`.

- [ ] **Step 1: Write failing model/style tests**

```python
def test_all_requested_modes_are_supported():
    assert {m.value for m in CharmMode} == {
        "Natural", "Smooth", "Sweet", "Flirty", "Playful", "Funny", "Witty",
        "Romantic", "Confident", "Gentleman", "Cheeky", "Deep", "Serious", "Pidgin Smooth",
    }

def test_request_bounds_candidate_count_and_intensity():
    req = CharmRequest(instruction="reply", conversation=["Hi"], count=99, intensity=-5)
    assert req.count == 5 and req.intensity == 0
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q`

Expected: collection fails because `reyes_agent.charm` does not exist.

- [ ] **Step 3: Implement immutable models and fourteen non-canned style profiles**

Use enum values exactly as the UI/user vocabulary. Clamp count/intensity in `CharmRequest.__post_init__`. Profiles define target warmth, humor, flirt, directness, and prompt constraints, never candidate lines.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "mode or request or style"`

### Task 2: Context, reciprocity, momentum, and back-off analysis

**Files:**
- Create: `reyes_agent/charm/context.py`
- Modify: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `analyze_conversation(messages, relationship="") -> ContextSignals` and `is_charm_request(text) -> bool`.

- [ ] **Step 1: Add failing analyzer tests**

Test engaged reciprocal conversation, dry one-word replies, unanswered streaks, current tone, Nigerian English/Pidgin, direct no, repeated no, discomfort, and requests to stop. Assert recommendations change from `CONTINUE` to `MATCH`, `PULL_BACK`, or `ABORT` based on observable messages.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q -k "context or reciprocity or momentum or backoff"`

- [ ] **Step 3: Implement bounded deterministic analysis**

Normalize at most the last 20 messages, preserve speaker labels when present, compute message balance/length/unanswered streak, and evaluate stop/refusal markers before tone heuristics. Do not assign identities or invent sentiment certainty.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "context or reciprocity or momentum or backoff"`

### Task 3: Bounded callback memory and voice preferences

**Files:**
- Create: `reyes_agent/charm/memory.py`
- Modify: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `CharmSessionStore`, `MemoryAdapter`, `record_candidates`, `record_feedback`, `recent_hashes`, and bounded preference retrieval.

- [ ] **Step 1: Add failing memory tests**

Assert candidate history evicts old entries, conversation windows are bounded, feedback requires a known candidate, no full transcript is durably stored, and the adapter requests only communication-preference memories from the existing manager.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q -k "memory or callback or feedback"`

- [ ] **Step 3: Implement deques/maps with explicit caps**

Use `deque(maxlen=...)`, content hashes rather than transcript copies for repetition memory, and dependency injection for the existing memory manager. Never import eMEM.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "memory or callback or feedback"`

### Task 4: Candidate critic, Cringe Firewall, and ranker

**Files:**
- Create: `reyes_agent/charm/critic.py`
- Modify: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `score_candidate(text, request, signals, recent_hashes) -> CandidateScores` and `rank_candidates(...) -> tuple[CharmCandidate, ...]`.

- [ ] **Step 1: Add failing score/rank tests**

Use candidate pairs where one is concise/contextual and one pleads, pressures, repeats punctuation, overclaims intimacy, or duplicates a recent suggestion. Assert all ten fields are 0–100, risk fields rise appropriately, unsafe candidates are disqualified, and the strongest eligible response wins regardless of generation order.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q -k "score or rank or cringe or desperation or repetition"`

- [ ] **Step 3: Implement transparent deterministic heuristics**

Use named regex/length/context/mode-alignment signals, cap every component, compute an explicit weighted rank score, and attach short reasons. Do not encode canned response text.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "score or rank or cringe or desperation or repetition"`

### Task 5: Existing-provider generator and failure isolation

**Files:**
- Create: `reyes_agent/charm/generator.py`
- Modify: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `CandidateGenerator(generate_turn=None)` and `generate(request, signals, style, preferences) -> list[str]`.

- [ ] **Step 1: Add failing generator tests**

Inject a fake existing-provider callable. Assert one call produces the requested number of unique candidates for Natural, Smooth, Sweet, Funny, and Pidgin Smooth; JSON fenced/plain payloads parse; malformed output raises `CharmGenerationError`; no fixed fallback line appears.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q -k "generate or natural or smooth or sweet or funny or pidgin"`

- [ ] **Step 3: Implement one-call structured generation**

Build a bounded system/user payload from analyzed signals, style constraints, intensity, objective, and privacy-filtered preferences. Default adapter calls `provider.run_turn(history, system=..., tools=[])`. Parse only a JSON object containing a `candidates` string list; cap length/count; raise an honest error otherwise.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "generate or natural or smooth or sweet or funny or pidgin"`

### Task 6: Engine orchestration and coaching features

**Files:**
- Create: `reyes_agent/charm/engine.py`
- Modify: `reyes_agent/charm/__init__.py`
- Modify: `tests/test_charm_engine.py`

**Interfaces:**
- Produces: `CharmEngine`, `get_charm_engine()`, `reply`, `analyze`, `set_mode`, `feedback`, `coach`, and `status`.

- [ ] **Step 1: Add failing engine tests**

Assert initialization is lazy, analyze does not call provider, unsafe context skips generation, safe reply uses one call then ranks, all coach feature values work through the same pipeline, status reports real bounded counts, and emitted events omit transcript content.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_engine.py -q -k "engine or coach or event or lazy"`

- [ ] **Step 3: Implement the staged engine**

Flow: validate request → analyze → early back-off → retrieve bounded preferences → generate once → score/rank → record hashes/IDs → emit bounded event → return immutable result. Catch provider/memory/Event Bus failures independently.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_engine.py -q -k "engine or coach or event or lazy"`

### Task 7: Native tools and hybrid routing

**Files:**
- Create: `reyes_agent/tools/charm_tools.py`
- Modify: `reyes_agent/tools/__init__.py`
- Modify: `reyes_agent/routing/capability.py`
- Modify: `reyes_agent/agent.py`
- Create: `tests/test_charm_integration.py`

**Interfaces:**
- Produces registered tools `charm_reply`, `charm_analyze`, `charm_set_mode`, `charm_status`, `charm_feedback`, and `charm_coach`; capability `charm`; lazy tool-group activation.

- [ ] **Step 1: Add failing registry/routing tests**

Assert every tool is registered, explicit commands route to `charm`, “make that smoother” and Pidgin requests retain tools even when cognition would call them chat, normal greetings do not load Charm, and tool execution returns structured JSON without starting voice/server threads.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_charm_integration.py -q`

- [ ] **Step 3: Register tools and preselect the lazy group**

Add the module import and tool-group entries. Extend capability routing with deterministic patterns. In `agent.py`, determine Charm relevance before building schemas, add only the Charm group, preserve route narrowing, and prevent pure-chat schema removal only for confident Charm requests. Do not modify Claude's pending spatial-memory markers.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_charm_integration.py -q`

### Task 8: Smart Autonomy integration, regression tests, and roadmap

**Files:**
- Modify: `tests/test_charm_integration.py`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: Smart Autonomy `ActionPolicy` at the tool boundary.
- Produces: generation/draft never sends; later exact authenticated send uses normal messaging with Level 2 authorization.

- [ ] **Step 1: Add failing/guard integration tests**

Assert `charm_reply` has no transport call, “give me three replies” produces candidates only, `send her the second one` authorizes only the exact resulting messaging call in that turn, and changed content/recipient does not reuse authorization.

- [ ] **Step 2: Run focused Charm and autonomy suites**

Run: `python -m pytest tests/test_charm_engine.py tests/test_charm_integration.py tests/test_smart_autonomy_policy.py -q`

- [ ] **Step 3: Run core regressions and static checks**

Run: `python -m pytest tests/test_conversation_engine.py tests/test_memory.py tests/test_memory_policy.py tests/test_voice_system.py tests/test_capability_router.py tests/test_fast_intelligence.py tests/test_universal_tool_registry.py -q`

Run: `python -m compileall -q reyes_agent tests`

Run: `git diff --check`

- [ ] **Step 4: Update the roadmap honestly**

Record repositories inspected, concepts reused, no dependencies installed, completed tools, test counts, provider/live limitations, and no automatic-send claim.

- [ ] **Step 5: Commit the independently working subsystem**

```powershell
git add -- reyes_agent/charm reyes_agent/tools/charm_tools.py reyes_agent/tools/__init__.py reyes_agent/routing/capability.py reyes_agent/agent.py tests/test_charm_engine.py tests/test_charm_integration.py ROADMAP.md
git commit -m "feat: add native ZENO Charm Engine"
```
