# ZENO Smart Autonomy Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace overlapping routine-action confirmation decisions with one request-scoped policy while preserving Council, high-impact, authorization, privacy, and capability safeguards.

**Architecture:** A new `reyes_agent.action_policy` module owns contextual execute/clarify/confirm/deny classification. `run_agent()` establishes one owner-command context and `tools.run_tool()` becomes the single enforcement seam. Existing permission, security, confidence, speaker, audit, and confirmation modules remain authoritative inputs or compatibility facades, not competing routine approval engines.

**Tech Stack:** Python 3.11+, dataclasses, enums, contextvars, hashlib, pytest, existing ZENO tool/audit/permission infrastructure.

**Spec:** `docs/superpowers/specs/2026-08-26-smart-autonomy-design.md`

## Global Constraints

- Clear authenticated owner command is authorization only for the routine action it describes.
- Draft verbs never authorize sending.
- `convene_council` always uses one Council approval.
- Financial, unauthorized, destructive-disk, credential, and structurally blocked operations remain denied.
- Authorization and verification remain separate.
- No new scheduler, permission store, confirmation queue, dependency, or background loop.
- Preserve concurrent edits in `reyes_agent/cognition.py`, `reyes_agent/spatial_memory.py`, and presentation files.

---

### Task 1: Request-scoped policy types and lifecycle

**Files:**
- Create: `reyes_agent/action_policy.py`
- Create: `tests/test_smart_autonomy_policy.py`

**Interfaces:**
- Produces: `AutonomyLevel`, `PolicyEffect`, `ActionContext`, `ActionDecision`, `use_action_context(...)`, `current_action_context()`, and `argument_fingerprint(tool_name, arguments)`.

- [ ] **Step 1: Write the failing context lifecycle tests**

```python
def test_action_context_expires_after_turn():
    assert current_action_context().source == "internal"
    with use_action_context("Open Chrome", source="local_text", owner_authenticated=True):
        assert current_action_context().utterance == "Open Chrome"
    assert current_action_context().source == "internal"

def test_argument_fingerprint_is_order_independent_and_argument_bound():
    left = argument_fingerprint("send_message", {"message": "Hi", "destination": "Ada"})
    right = argument_fingerprint("send_message", {"destination": "Ada", "message": "Hi"})
    changed = argument_fingerprint("send_message", {"destination": "Ada", "message": "Bye"})
    assert left == right and left != changed
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q`

Expected: collection fails because `reyes_agent.action_policy` does not exist.

- [ ] **Step 3: Implement the minimal context and immutable types**

```python
class AutonomyLevel(IntEnum):
    THINKING = 0
    ROUTINE = 1
    REQUESTED_EXTERNAL = 2
    SPECIAL = 3
    HIGH_IMPACT = 4

class PolicyEffect(StrEnum):
    EXECUTE = "EXECUTE"
    CLARIFY = "CLARIFY"
    COUNCIL_APPROVAL = "COUNCIL_APPROVAL"
    HIGH_IMPACT_CONFIRMATION = "HIGH_IMPACT_CONFIRMATION"
    DENY = "DENY"
```

Use a `ContextVar[ActionContext]`; normalize the utterance once; hash canonical JSON containing the exact tool and arguments; reset the context token in `finally`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q`

Expected: lifecycle and fingerprint tests pass.

### Task 2: Contextual classification

**Files:**
- Modify: `reyes_agent/action_policy.py`
- Modify: `tests/test_smart_autonomy_policy.py`

**Interfaces:**
- Produces: `evaluate(tool_name: str, arguments: Mapping[str, Any], *, requires_confirmation: bool = False, permission_state: str = "enabled", capability: str = "") -> ActionDecision`.

- [ ] **Step 1: Add failing table-driven policy tests**

```python
@pytest.mark.parametrize("utterance,tool,args,expected", [
    ("Open Chrome", "open_app", {"name_or_path": "chrome"}, PolicyEffect.EXECUTE),
    ("Tell Ada I'll call later", "send_message", {"platform": "whatsapp", "destination": "Ada", "message": "I'll call later"}, PolicyEffect.EXECUTE),
    ("Write Ada a sweet message", "send_message", {"platform": "whatsapp", "destination": "Ada", "message": "Hi"}, PolicyEffect.DENY),
    ("Call the Council", "convene_council", {"question": "Review this"}, PolicyEffect.COUNCIL_APPROVAL),
    ("Delete it", "delete_file", {"path": ""}, PolicyEffect.CLARIFY),
    ("Transfer money", "transfer_funds", {"amount": 50}, PolicyEffect.DENY),
])
def test_policy_matrix(utterance, tool, args, expected):
    with use_action_context(utterance, source="local_text", owner_authenticated=True):
        assert evaluate(tool, args).effect is expected
```

Add tests for non-overwriting `move_file`, recoverable `forget_fact`, background sends, uncertain voice, owner-confirmed voice, paired phone, changed arguments, explicit post with sensitive content, ordinary batch commands, and exact retries.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q`

Expected: classification expectations fail because `evaluate` is absent or incomplete.

- [ ] **Step 3: Implement minimal deterministic classification**

Implement small named rule sets for drafting verbs, execution verbs, private/outward tool families, full Council, financial/critical markers, required target fields, system paths, overwrite/broad-delete signals, and normal routine tools. Order rules from immutable denial through actor trust, ambiguity, Council, high impact, explicit outward action, then routine execution.

Unknown model confidence must not alter a routine decision. Return a reason, level, capability, fingerprint, and whether the decision is retryable.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q`

Expected: all policy matrix tests pass.

### Task 3: Establish owner-command context at the shared brain

**Files:**
- Modify: `reyes_agent/agent.py`
- Modify: `reyes_agent/web.py`
- Modify: `reyes_agent/remote_access/desktop_agent.py`
- Modify: `tests/test_smart_autonomy_policy.py`

**Interfaces:**
- Consumes: `use_action_context` and existing `speaker_identity.current_context()` / `confirmation.auto_approve_active()`.
- Produces: every main and delegated tool call sees one expiring turn context; background calls receive no owner authority.

- [ ] **Step 1: Add failing integration tests**

Capture the context inside a registered test tool while running a one-turn fake provider response. Assert local text is authenticated, uncertain voice is not, confirmed voice is, and the context resets even after a provider/tool exception.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q -k context`

- [ ] **Step 3: Wrap the existing `run_agent()` loop**

Create the context from the latest original user utterance, speaker context, turn ID, and remote owner elevation. Do not add another public brain. Ensure worker-pool delegated calls inherit contextvars; explicitly pass/copy context only where the existing worker runtime does not.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q -k context`

### Task 4: Make `run_tool` the single policy enforcement seam

**Files:**
- Modify: `reyes_agent/tools/__init__.py`
- Modify: `reyes_agent/confirmation.py`
- Modify: `reyes_agent/autonomy.py`
- Modify: `reyes_agent/security/policy/engine.py`
- Modify: `tests/test_smart_autonomy_policy.py`
- Modify: `tests/test_stepup_autoapprove.py`
- Modify: `tests/test_confidence_engine.py`

**Interfaces:**
- Consumes: `action_policy.evaluate`.
- Produces: one audited decision before execution and one queue path for Council/high impact.

- [ ] **Step 1: Add failing tool-boundary tests**

Register side-effect counters for routine, outward, Council, and high-impact fake tools. Assert `run_tool` executes routine/exact-send once, queues Council/high-impact once, denies unauthenticated outward actions, and never executes on `CLARIFY`/`DENY`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_smart_autonomy_policy.py tests/test_stepup_autoapprove.py tests/test_confidence_engine.py -q`

- [ ] **Step 3: Replace the competing `must_confirm` composition**

Keep capability argument authorization, blocked permissions, private voice retrieval checks, truncation protection, and execution isolation. Call the central policy once. Map its result to execute, concise clarification, the existing confirmation queue, or block. Audit `effect`, `level`, `reason`, `fingerprint`, source, and turn ID without logging secrets.

Make `autonomy.classify_tool()` and the security policy facade delegate to compatible static policy evaluation for existing callers. Keep remote durable approval consumption and catastrophic deny lists as defense in depth.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_smart_autonomy_policy.py tests/test_stepup_autoapprove.py tests/test_confidence_engine.py -q`

### Task 5: Correct tool metadata and prompts without weakening safeguards

**Files:**
- Modify: `reyes_agent/tools/system.py`
- Modify: `reyes_agent/tools/memory.py`
- Modify: `reyes_agent/tools/council_tools.py`
- Modify: `reyes_agent/coding_system/command_policy.py`
- Modify: `reyes_agent/computer/safety.py`
- Modify: `reyes_agent/config.py`
- Modify: `tests/test_smart_autonomy_policy.py`

**Interfaces:**
- Produces: descriptions and specialist policy aligned with the central decision model.

- [ ] **Step 1: Add failing source/behavior assertions**

Assert Council is classified special, explicit Slack/Telegram send descriptions do not require a second confirmation, ordinary rename and requested development work classify routine, while overwrite/delete/security/payment cases remain protected.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q -k "metadata or development or computer"`

- [ ] **Step 3: Update only obsolete blanket wording and subordinate classifiers**

Remove unconditional routine-confirmation claims. Keep descriptions honest about ambiguity, verification, unsaved work, and high-impact cases. Update computer safety so a generic explicit send is Level 2 rather than automatically destructive, while payment/security/private-public exposure rules win first. Update coding policy so an authenticated requested workspace edit/test is standard and shell/disk/secret/financial danger remains denied or high-impact.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_smart_autonomy_policy.py -q`

### Task 6: Regression verification and roadmap

**Files:**
- Modify: `ROADMAP.md`

**Interfaces:**
- Produces: evidence-backed completion record and documented remaining confirmations.

- [ ] **Step 1: Run focused policy regressions**

Run: `python -m pytest tests/test_smart_autonomy_policy.py tests/test_permissions.py tests/test_confidence_engine.py tests/test_stepup_autoapprove.py tests/test_fast_intelligence.py tests/test_capability_router.py tests/test_remote_access.py -q`

- [ ] **Step 2: Run static checks**

Run: `python -m compileall -q reyes_agent tests`

Run: `git diff --check`

- [ ] **Step 3: Update `ROADMAP.md` with measured evidence**

Record the centralized policy, exact remaining approval flows and reasons, focused test counts, and any honest limits. Do not mark unrelated roadmap items complete.

- [ ] **Step 4: Commit the independently working subsystem**

```powershell
git add -- reyes_agent/action_policy.py reyes_agent/agent.py reyes_agent/web.py reyes_agent/remote_access/desktop_agent.py reyes_agent/tools/__init__.py reyes_agent/confirmation.py reyes_agent/autonomy.py reyes_agent/security/policy/engine.py reyes_agent/tools/system.py reyes_agent/tools/memory.py reyes_agent/tools/council_tools.py reyes_agent/coding_system/command_policy.py reyes_agent/computer/safety.py reyes_agent/config.py tests/test_smart_autonomy_policy.py tests/test_stepup_autoapprove.py tests/test_confidence_engine.py ROADMAP.md
git commit -m "feat: centralize ZENO smart autonomy policy"
```
