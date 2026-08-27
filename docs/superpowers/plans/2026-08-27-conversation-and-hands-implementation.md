# ZENO Conversation and Hands Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ZENO one coherent, session-safe conversation projection and make its existing keyboard/mouse tools reliably reachable, authorized without approval fatigue, cancellable, and evidence-honest.

**Architecture:** Preserve the existing lifecycle state machine, voice continuity engine, turn detector, unified session manager, provider history, permission engine, `run_tool()` gateway, and grounded computer-use engine. Add a bounded conversation coordinator and tool-transaction ledger as projection layers, then pass a stable session key and exact action source through the existing web/agent path. Fix lazy tool exposure at the router/provider boundary instead of making Hands tools core.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, dataclasses, `threading.RLock`, `contextvars`, existing Event Bus, existing bounded worker pool, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-conversation-and-hands-design.md`

## Global Constraints

- Do not replace ZENO's existing conversation state, voice continuity, turn-boundary, unified-session, Event Bus, worker-pool, permission, or tool-execution authorities.
- `run_tool()` remains the only model-initiated tool execution gateway.
- `computer.agentic` remains the grounded keyboard/mouse executor.
- Add no provider call, startup service, polling loop, unbounded collection, or unbounded retry.
- Routine reversible actions explicitly requested by the authenticated owner execute without a redundant confirmation.
- Ambiguous, destructive, financial, credential, security, unauthenticated, and high-consequence actions remain gated or refused.
- Never report a side effect as successful without verified evidence.
- Keep ordinary conversation payloads small; Hands and browser schemas load only for relevant turns.
- Do not modify, stage, reset, or overwrite Claude's unrelated working files.
- Use `.venv\Scripts\python.exe -m pytest` for this workspace; the globally resolved Python lacks pytest.

---

## File Structure

**Create**

- `reyes_agent/conversation_coordinator.py` — bounded session/turn projection and active-surface resolution; no execution authority.
- `reyes_agent/tool_transactions.py` — bounded provider tool-call lifecycle ledger and normalized evidence state.
- `tests/test_conversation_coordinator.py` — isolation, follow-up, projection, bounds, and supersession tests.
- `tests/test_tool_transactions.py` — lifecycle, normalization, redaction, correlation, cancellation, and bounds tests.
- `tests/test_conversation_hands_integration.py` — provider payload, channel plumbing, and end-to-end Hands routing regressions.

**Modify**

- `reyes_agent/tools/__init__.py` — assign browser/Hands tools to explicit lazy groups; expose a safe diagnostic-input helper.
- `reyes_agent/routing/capability.py` — session-keyed bounded route context and active-surface-aware generic pointer routing.
- `reyes_agent/agent.py` — pass session context to routing, expose matching lazy groups, and record correlated tool transactions.
- `reyes_agent/web.py` — establish trusted session/source context at each front door and synchronize turn lifecycle.
- `reyes_agent/intelligence.py` — cancel superseded brain work only within the same conversation session.
- `reyes_agent/action_policy.py` — classify real `send_to_chat(send=True)` as an outward action while keeping type-only mode routine.
- `reyes_agent/permissions.py` — map Hands input tools to the existing `desktop_automation` capability.
- `reyes_agent/tools/hands_tools.py` — remove blanket approval and rely on exact-command policy plus computer safety.
- `tests/test_capability_router.py`, `tests/test_hands_tools.py`, `tests/test_smart_autonomy_policy.py`, `tests/test_conversation_state.py` — regression coverage.
- `ROADMAP.md` — record measured completion only after verification.

---

### Task 1: Make Routed Hands and Browser Tools Reach the Provider

**Files:**
- Modify: `reyes_agent/tools/__init__.py:133-280`
- Modify: `reyes_agent/agent.py:209-240`
- Create: `tests/test_conversation_hands_integration.py`

**Interfaces:**
- Consumes: `group_of(name: str) -> str`, `tool_definitions(groups: set[str] | None) -> list[dict]`, and `routing.capability.tools_for(message: str, expand: bool = False, context_key: str = "local", active_surface: str = "") -> Route`.
- Produces: explicit `desktop` and `browser` lazy groups which `agent.run_agent()` loads only for matching capability routes.

- [ ] **Step 1: Write failing group and provider-payload tests**

```python
from reyes_agent import agent
from reyes_agent.provider import AgentTurn
from reyes_agent.tools import group_of, tool_definitions

HANDS = {"type_text", "press_keys", "click_element", "send_to_chat", "scroll_screen"}


def _captured_tools(monkeypatch, message: str) -> set[str]:
    captured: list[set[str]] = []
    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append({item["name"] for item in tools})
        on_text("Acknowledged.")
        return AgentTurn(text="Acknowledged.")
    monkeypatch.setattr(agent, "run_turn", fake_turn)
    agent.run_agent([{"role": "user", "content": message}])
    assert len(captured) == 1
    return captured[0]


def test_hands_are_lazy_desktop_tools() -> None:
    assert {group_of(name) for name in HANDS} == {"desktop"}
    assert HANDS.isdisjoint({item["name"] for item in tool_definitions()})
    assert HANDS <= {item["name"] for item in tool_definitions(groups={"desktop"})}


def test_agent_exposes_hands_for_a_desktop_command(monkeypatch) -> None:
    visible = _captured_tools(monkeypatch, "Type hello into Notepad and press enter")
    assert {"type_text", "press_keys"} <= visible
    assert "browser_click" not in visible


def test_agent_exposes_browser_actions_for_a_browser_command(monkeypatch) -> None:
    visible = _captured_tools(monkeypatch, "Open Chrome and click the first result")
    assert {"browser_open", "browser_click"} <= visible
    assert "click_element" not in visible
```

- [ ] **Step 2: Run the new tests and verify the confirmed defect**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py`

Expected: FAIL because Hands/browser actions default to `extended`, and the agent does not load `desktop`/`browser` groups.

- [ ] **Step 3: Assign explicit lazy groups**

Add to `TOOL_GROUPS`:

```python
    "type_text": "desktop", "press_keys": "desktop",
    "click_element": "desktop", "send_to_chat": "desktop",
    "scroll_screen": "desktop",
    "browser_open": "browser", "browser_click": "browser",
    "browser_read": "browser", "browser_fill": "browser",
    "browser_scroll": "browser", "browser_extract": "browser",
    "browser_screenshot": "browser", "browser_close": "browser",
    "browser_vision_click": "browser",
```

Keep `open_app` and `web_search` in their existing core roles.

- [ ] **Step 4: Load groups from the deterministic route**

Extend `_capability_groups` in `agent.py` with `"browser": "browser"` and `"desktop": "desktop"`, then rebuild definitions before narrowing as the current lazy-group path does.

- [ ] **Step 5: Run focused payload and router tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py tests/test_capability_router.py tests/test_voice_response_budget.py`

Expected: PASS; ordinary chat still exposes no Hands/browser actions.

- [ ] **Step 6: Commit the independently working routing fix**

```powershell
git add -- reyes_agent/tools/__init__.py reyes_agent/agent.py tests/test_conversation_hands_integration.py
git commit -m "fix: expose routed desktop and browser tools"
```

---

### Task 2: Isolate Follow-Up Routing by Conversation Session

**Files:**
- Modify: `reyes_agent/routing/capability.py:330-445`
- Modify: `tests/test_capability_router.py`

**Interfaces:**
- Consumes: existing deterministic capability patterns and `Route`.
- Produces: `classify(message: str, *, context_key: str = "local", active_surface: str = "")`, `tools_for(message: str, *, expand: bool = False, context_key: str = "local", active_surface: str = "")`, `clear_context(context_key: str = "")`.

- [ ] **Step 1: Add failing session-isolation and surface tests**

```python
def test_follow_up_context_is_isolated_by_session() -> None:
    cap.tools_for("Open Chrome", context_key="desktop-owner")
    cap.tools_for("Open Notepad", context_key="phone-owner")
    assert "browser" in cap.tools_for("click it", context_key="desktop-owner").capabilities
    assert "desktop" in cap.tools_for("type hello", context_key="phone-owner").capabilities


def test_generic_click_uses_the_known_active_surface() -> None:
    browser = cap.tools_for("click the Save button", context_key="a", active_surface="browser")
    desktop = cap.tools_for("click the Save button", context_key="b", active_surface="desktop")
    unknown = cap.tools_for("click the Save button", context_key="c", active_surface="")
    assert "browser" in browser.capabilities and "desktop" not in browser.capabilities
    assert "desktop" in desktop.capabilities and "browser" not in desktop.capabilities
    assert "browser_click" not in unknown.tools and "click_element" not in unknown.tools


def test_route_context_count_is_bounded() -> None:
    for index in range(cap.MAX_CONTEXTS + 20):
        cap.tools_for("Open Notepad", context_key=f"session-{index}")
    assert cap.context_count() <= cap.MAX_CONTEXTS
```

- [ ] **Step 2: Run and observe process-global leakage**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_capability_router.py -k "isolated or active_surface or bounded"`

Expected: FAIL because the router currently has one process-global `_context` and no active-surface input.

- [ ] **Step 3: Replace the singleton cache with a bounded ordered map**

```python
from collections import OrderedDict

MAX_CONTEXTS = 32
_contexts: OrderedDict[str, dict[str, Any]] = OrderedDict()

def _key(value: str) -> str:
    return str(value or "local").strip()[:160] or "local"

def remember_context(capabilities: tuple[str, ...], *, source: str = "",
                     context_key: str = "local") -> None:
    key = _key(context_key)
    with _lock:
        _contexts[key] = {"capabilities": tuple(capabilities), "at": time.time(),
                          "source": str(source)[:80]}
        _contexts.move_to_end(key)
        while len(_contexts) > MAX_CONTEXTS:
            _contexts.popitem(last=False)

def _inherited(context_key: str = "local") -> tuple[str, ...]:
    key = _key(context_key)
    with _lock:
        item = _contexts.get(key)
        if item and time.time() - item["at"] <= CONTEXT_TTL_S:
            _contexts.move_to_end(key)
            return tuple(item["capabilities"])
    return ()
```

`clear_context("")` clears all contexts for existing test setup; a non-empty key removes one. `context_count()` returns the locked count.

- [ ] **Step 4: Resolve generic click/scroll before broad browser patterns**

```python
_GENERIC_POINTER = re.compile(r"^\s*(?:please\s+)?(?:click|tap|scroll|press)\b", re.I)

def _surface_capability(active_surface: str, carried: tuple[str, ...]) -> str:
    for candidate in (str(active_surface).casefold(), *carried):
        if candidate in {"browser", "desktop"}:
            return candidate
    return ""
```

When the expression matches, return the known surface. With no known surface, return no execution capability with reason `generic pointer target has no known active surface` so ZENO observes or asks rather than guesses.

- [ ] **Step 5: Thread `context_key` through `tools_for()` and telemetry**

Call `classify(..., context_key=context_key, active_surface=active_surface)` and `remember_context(..., context_key=context_key)`. Store only bounded labels in route diagnostics.

- [ ] **Step 6: Run router regressions**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_capability_router.py tests/test_reputation_routing.py tests/test_phase4_routing.py`

Expected: PASS with payload-budget and no-sharp-tool assertions unchanged.

- [ ] **Step 7: Commit**

```powershell
git add -- reyes_agent/routing/capability.py tests/test_capability_router.py
git commit -m "fix: isolate capability follow-ups by session"
```

---

### Task 3: Add the Bounded Conversation Coordinator Projection

**Files:**
- Create: `reyes_agent/conversation_coordinator.py`
- Create: `tests/test_conversation_coordinator.py`

**Interfaces:**
- Consumes: existing `conversation_state`, `unified_session.get_session_state()`, and Event Bus.
- Produces: `get_coordinator() -> ConversationCoordinator`; `begin_turn`, `record_route`, `record_reference`, `record_tool_result`, `set_pending_clarification`, `authorization_utterance`, `finish_turn`, `cancel_turn`, `active_surface`, `snapshot`, `reset`.

- [ ] **Step 1: Write failing coordinator tests**

```python
from reyes_agent.conversation_coordinator import ConversationCoordinator

def test_turn_context_is_session_scoped() -> None:
    coordinator = ConversationCoordinator(max_sessions=2, max_turns=4)
    coordinator.begin_turn("t1", session_key="desktop", source="local_text",
                           utterance="Open Notepad", owner_authenticated=True)
    coordinator.begin_turn("t2", session_key="phone", source="paired_phone",
                           utterance="Open Chrome", owner_authenticated=True)
    coordinator.record_route("t1", ("desktop",), "clear")
    coordinator.record_route("t2", ("browser",), "clear")
    assert coordinator.active_surface("desktop") == "desktop"
    assert coordinator.active_surface("phone") == "browser"

def test_new_turn_supersedes_only_its_session() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn("old", session_key="owner", source="local_text",
                           utterance="first", owner_authenticated=True)
    coordinator.begin_turn("other", session_key="guest", source="voice",
                           utterance="hello", owner_authenticated=False)
    coordinator.begin_turn("new", session_key="owner", source="local_text",
                           utterance="second", owner_authenticated=True)
    assert coordinator.snapshot("owner")["active_turn_id"] == "new"
    assert coordinator.turn("old").status == "SUPERSEDED"
    assert coordinator.snapshot("guest")["active_turn_id"] == "other"

def test_guest_never_inherits_owner_reference() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn("o", session_key="owner", source="local_text",
                           utterance="Open my private report", owner_authenticated=True)
    coordinator.record_reference("o", "target", "private report")
    coordinator.begin_turn("g", session_key="guest", source="voice",
                           utterance="open it", owner_authenticated=False)
    assert "private report" not in str(coordinator.snapshot("guest"))

def test_clarification_resumes_only_the_same_authenticated_session() -> None:
    coordinator = ConversationCoordinator()
    coordinator.begin_turn("t1", session_key="owner", source="local_text",
                           utterance="Send hello", owner_authenticated=True)
    coordinator.set_pending_clarification("t1", "Which recipient?", "recipient")
    effective = coordinator.authorization_utterance(
        "owner", "Ada", owner_authenticated=True)
    assert "Send hello" in effective and "Ada" in effective
    assert coordinator.authorization_utterance(
        "guest", "Ada", owner_authenticated=False) == "Ada"

def test_pending_clarification_expires(monkeypatch) -> None:
    coordinator = ConversationCoordinator(clarification_ttl_s=120)
    coordinator.begin_turn("t1", session_key="owner", source="local_text",
                           utterance="Send hello", owner_authenticated=True)
    coordinator.set_pending_clarification("t1", "Which recipient?", "recipient")
    initial = coordinator._now()
    monkeypatch.setattr(coordinator, "_now", lambda: initial + 121)
    assert coordinator.authorization_utterance(
        "owner", "Ada", owner_authenticated=True) == "Ada"
```

- [ ] **Step 2: Run and verify the module is absent**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_coordinator.py`

Expected: collection FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement focused bounded dataclasses**

```python
@dataclass
class TurnContext:
    turn_id: str
    session_key: str
    source: str
    owner_authenticated: bool
    utterance: str
    normalized_utterance: str
    capabilities: tuple[str, ...] = ()
    route_confidence: str = ""
    active_surface: str = ""
    references: dict[str, str] = field(default_factory=dict)
    pending_question: str = ""
    last_verified_outcome: str = ""
    status: str = "ACTIVE"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

@dataclass
class SessionContext:
    session_key: str
    active_turn_id: str = ""
    last_capabilities: tuple[str, ...] = ()
    active_surface: str = ""
    references: dict[str, str] = field(default_factory=dict)
    pending_question: str = ""
    last_verified_outcome: str = ""
    updated_at: float = field(default_factory=time.time)
```

Use `OrderedDict` plus `RLock`; defaults: `max_sessions=32`, `max_turns=128`, `max_references=12`, `value_limit=240`, `clarification_ttl_s=120`.

Add `PendingClarification(original_utterance, question, missing_field, owner_authenticated, created_at)` to `SessionContext`. `authorization_utterance()` consumes it once only when the session key and authentication class match, returning `"<original>\nClarification answer: <answer>"`. Closing/cancel phrases clear it and return only the current text.

- [ ] **Step 4: Project without creating another authority**

`begin_turn()` calls existing lifecycle only with `manage_lifecycle=True`; web can register an already-open ID with `False`. Project only `{turn_id, state}` into unified session `current_task`. Never persist utterances/references there. Publish bounded `conversation.context.changed` events.

- [ ] **Step 5: Add deterministic isolation-key helper**

```python
def session_key(*, source: str, device_id: str = "", owner: bool = True) -> str:
    kind = str(source or "local_text").casefold()
    if kind == "paired_phone":
        return f"phone:{str(device_id)[:80]}"
    if kind == "voice" and not owner:
        return f"guest-voice:{str(device_id or 'local')[:80]}"
    return "desktop-owner"
```

This key provides isolation and is never authentication evidence.

- [ ] **Step 6: Run coordinator/state tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_coordinator.py tests/test_conversation_state.py tests/test_conversation_continuity.py`

Expected: PASS; existing lifecycle transitions remain unchanged.

- [ ] **Step 7: Commit**

```powershell
git add -- reyes_agent/conversation_coordinator.py tests/test_conversation_coordinator.py
git commit -m "feat: add bounded conversation coordinator"
```

---

### Task 4: Add Correlated Tool Transactions Without a Second Executor

**Files:**
- Create: `reyes_agent/tool_transactions.py`
- Create: `tests/test_tool_transactions.py`
- Modify: `reyes_agent/tools/__init__.py:44-95`

**Interfaces:**
- Consumes: `tools.classify_tool_result(result)` and public redacted `diagnostic_tool_input`.
- Produces: `get_ledger() -> ToolTransactionLedger`; `planned`, `started`, `finished`, `cancel_turn`, `snapshot`, `reset`.

- [ ] **Step 1: Write failing transaction tests**

```python
from reyes_agent.tool_transactions import ToolTransactionLedger

def test_evidence_is_required_for_verified() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "1", "click_element", {"target": "Save"})
    assert ledger.finished("t", "1", "clicked").status == "RETURNED_UNVERIFIED"
    ledger.planned("t", "2", "click_element", {"target": "Save"})
    result = '{"ok": true, "verified": true, "evidence": "window changed"}'
    assert ledger.finished("t", "2", result).status == "VERIFIED"

def test_waiting_failure_and_cancel_are_distinct() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "w", "delete_file", {"path": "report.txt"})
    assert ledger.finished("t", "w", "Queued as request #7 for high-impact confirmation").status == "WAITING"
    ledger.planned("t", "f", "click_element", {"target": "Missing"})
    assert ledger.finished("t", "f", "Error: target missing").status == "FAILED"
    ledger.planned("t", "c", "browser_open", {"url": "https://example.com"})
    ledger.cancel_turn("t", reason="owner interrupted")
    assert ledger.get("t", "c").status == "CANCELLED"
    ledger.planned("t", "q", "send_message", {"message": "hello"})
    clarification = "Clarification needed: the intended recipient is missing. Nothing ran."
    assert ledger.finished("t", "q", clarification).status == "WAITING"

def test_ledger_redacts_and_bounds_records() -> None:
    ledger = ToolTransactionLedger(max_records=3)
    for index in range(8):
        ledger.planned("t", str(index), "type_text", {"password": "secret", "text": "hello"})
    assert len(ledger.snapshot()) == 3
    assert "secret" not in str(ledger.snapshot())

def test_unverified_success_claim_is_replaced() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    ledger.planned("t", "1", "click_element", {"target": "Save"})
    ledger.finished("t", "1", "clicked")
    reply = ledger.guard_reply("t", "Done, I saved it.")
    assert reply.startswith("I could not verify that action completed.")
    assert not reply.casefold().startswith("done")

def test_uncertain_hand_action_cannot_repeat_automatically() -> None:
    ledger = ToolTransactionLedger(max_records=8)
    arguments = {"target": "Send"}
    ledger.planned("t", "1", "click_element", arguments)
    ledger.finished("t", "1", "clicked but verification unavailable")
    allowed, reason = ledger.allow_attempt("t", "click_element", arguments)
    assert allowed is False
    assert "uncertain" in reason.casefold()

def test_safe_retryable_failure_has_one_bounded_retry() -> None:
    ledger = ToolTransactionLedger(max_records=8, max_retries=1)
    arguments = {"query": "weather"}
    ledger.planned("t", "1", "web_search", arguments)
    ledger.finished("t", "1", "Error: temporary network timeout")
    assert ledger.allow_attempt("t", "web_search", arguments)[0] is True
    ledger.planned("t", "2", "web_search", arguments)
    ledger.finished("t", "2", "Error: temporary network timeout")
    assert ledger.allow_attempt("t", "web_search", arguments)[0] is False
```

- [ ] **Step 2: Run and verify the module is absent**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_tool_transactions.py`

Expected: collection FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Expose the existing audit sanitizer narrowly**

```python
def diagnostic_tool_input(name: str, value: dict[str, Any]) -> Any:
    tool = TOOLS.get(str(name))
    return _tool_audit_input(tool, value) if tool else _audit_safe(value)
```

- [ ] **Step 4: Implement bounded transaction records**

```python
@dataclass
class ToolTransaction:
    turn_id: str
    call_id: str
    tool: str
    safe_input: Any
    status: str = "PLANNED"
    verification_state: str = "pending"
    error_category: str = ""
    retryable: bool = False
    evidence: str = ""
    result_preview: str = ""
    fingerprint: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

_STATUS = {"completed": "VERIFIED", "returned": "RETURNED_UNVERIFIED",
           "waiting": "WAITING", "failed": "FAILED"}
```

Add `clarification needed` to the existing waiting-prefix classification in `tools.classify_tool_result()`. Map cancelled/time-out prefixes separately. Keep at most 256 records. Publish `tool.transaction.changed` with `turn_id` correlation and redacted inputs.

Add a deliberately narrow leading-success guard:

```python
_SUCCESS_CLAIM = re.compile(
    r"^\s*(?:done|completed|finished|it(?:'s| is) (?:open|saved|sent)|"
    r"i (?:opened|saved|sent|deleted|posted|submitted)\b)[\s,.:;-]*", re.I)

def guard_reply(self, turn_id: str, text: str) -> str:
    records = self.snapshot(turn_id=turn_id)
    if not records or all(item["status"] == "VERIFIED" for item in records):
        return str(text)
    match = _SUCCESS_CLAIM.match(str(text))
    if not match:
        return str(text)
    remainder = str(text)[match.end():].strip()
    if any(item["status"] == "FAILED" for item in records):
        note = "The action failed; I did not verify completion."
    elif any(item["status"] == "WAITING" for item in records):
        note = "The action is still waiting and has not completed."
    else:
        note = "I could not verify that action completed."
    return f"{note} {remainder}".strip()
```

`allow_attempt()` hashes tool name plus canonical JSON arguments. It permits no more than `max_retries=1` after an explicitly retryable `FAILED` result. It refuses exact repeats after `WAITING`, `VERIFIED`, `RETURNED_UNVERIFIED`, `CANCELLED`, or `TIMED_OUT`, and always refuses automatic repeats for `click_element`, `type_text`, `press_keys`, `send_to_chat`, browser fill/click, send/publish/submit, delete, payment, and security-changing tools.

- [ ] **Step 5: Run transaction/audit tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_tool_transactions.py tests/test_charm_integration.py tests/test_universal_tool_registry.py`

Expected: PASS; private Charm content remains redacted.

- [ ] **Step 6: Commit**

```powershell
git add -- reyes_agent/tool_transactions.py reyes_agent/tools/__init__.py tests/test_tool_transactions.py
git commit -m "feat: track correlated tool transactions"
```

---

### Task 5: Wire Session, Source, Coordinator, and Transactions Through Real Turns

**Files:**
- Modify: `reyes_agent/agent.py:32-119, 170-240, 607-741`
- Modify: `reyes_agent/web.py:1214-1284, 1345-1477, 1521-1665, 3793-3837, 3889-3918`
- Modify: `reyes_agent/intelligence.py:90-210`
- Modify: `tests/test_conversation_hands_integration.py`
- Modify: `tests/test_conversation_coordinator.py`

**Interfaces:**
- Consumes: `ConversationCoordinator`, `ToolTransactionLedger`, session-keyed `tools_for()`.
- Produces: `run_agent(..., session_key: str = "local")`; `_conversation_turn(..., session_key, action_source, owner_authenticated)`; internal `_chat_request(...)` for local/phone front doors.

- [ ] **Step 1: Add failing source/session plumbing tests**

```python
def test_agent_passes_session_key_to_capability_router(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []
    def fake_tools_for(message: str, **kwargs):
        captured.append((kwargs["context_key"], kwargs["active_surface"]))
        return type("Route", (), {"capabilities": ("desktop",),
                                   "tools": ("type_text",), "confidence": "clear"})()
    monkeypatch.setattr("reyes_agent.routing.capability.tools_for", fake_tools_for)
    _captured_tools(monkeypatch, "type hello")
    assert captured[0][0] == "local"


def test_phone_command_preserves_remote_source(monkeypatch) -> None:
    captured: dict[str, object] = {}
    def fake_chat_request(req, *, session_key, action_source, owner_authenticated):
        captured.update(session_key=session_key, action_source=action_source,
                        owner_authenticated=owner_authenticated)
        return {"reply": "ok", "tool_calls": []}
    monkeypatch.setattr(web, "_chat_request", fake_chat_request)
    from starlette.requests import Request
    from reyes_agent import phone_security
    from reyes_agent.remote_access import policy
    class Security:
        @staticmethod
        def claim_command(_device_id, _command_id, _nonce):
            return True
    monkeypatch.setattr(phone_security, "get_phone_security", lambda: Security())
    monkeypatch.setattr(web, "_chat_request", fake_chat_request)
    policy.reset_rates()
    request = Request({"type": "http", "method": "POST",
                       "path": "/api/phone/command", "headers": [],
                       "scheme": "http", "server": ("192.168.1.2", 8768),
                       "client": ("192.168.1.20", 50000)})
    command = web.PhoneCommandRequest(command_id="one", nonce="nonce-one",
                                      timestamp=time.time(), message="open Notepad")
    web.phone_command(command, request, session={
        "device_id": "phone-1", "auth_level": web.OWNER_AUTH,
        "scopes": json.dumps(["status", "talk"]),
    })
    assert captured["action_source"] == "paired_phone"
    assert str(captured["session_key"]).startswith("phone:")


def test_new_message_cancels_only_same_session_brain_work() -> None:
    class Handle:
        def __init__(self, identity):
            self.id, self.done, self.cancelled = identity, False, False
        def cancel(self):
            self.cancelled = True
            return True
        def snapshot(self):
            return {"id": self.id}
    control = RuntimeControl()
    desktop = Handle("desktop-old")
    phone = Handle("phone-live")
    control.register(desktop, label="Conversation", kind="brain",
                     session_key="desktop-owner")
    control.register(phone, label="Conversation", kind="brain",
                     session_key="phone:one")
    assert control.supersede("desktop-owner", kind="brain") == ["Conversation"]
    assert desktop.cancelled is True and phone.cancelled is False
```

Reuse phone-security fixtures/patterns from `tests/test_owner_access.py`; do not create an authentication bypass fixture.

- [ ] **Step 2: Run and verify channel identity is currently lost**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py -k "session_key or phone_command"`

Expected: FAIL because `phone_command()` currently calls the public local `chat()` path.

- [ ] **Step 3: Extend `run_agent()` source-compatibly**

Add `session_key: str = "local"` to `run_agent()` and `_run_agent_impl()`, including the nested active-context call. Before `use_action_context`, call `get_coordinator().authorization_utterance(session_key, utterance, owner_authenticated=bool(authenticated))`; use that bounded result only for action authorization while provider history keeps the original user text. Route with:

```python
surface = get_coordinator().active_surface(session_key)
_route = _capability.tools_for(latest, context_key=session_key,
                               active_surface=surface)
get_coordinator().record_route(turn_id, _route.capabilities, _route.confidence)
```

If `turn_id` is empty, projection methods are no-ops while routing still works.

- [ ] **Step 4: Record tool calls around the existing gateway**

Before every sequential/parallel call:

```python
ledger.planned(turn_id, tc.id, tc.name, tc.input)
ledger.started(turn_id, tc.id)
```

First call `ledger.allow_attempt(turn_id, tc.name, tc.input)`. When it refuses, do not call `run_tool()`; feed the bounded reason back as a failed tool result and record `duplicate_retry_blocked`. This is the only retry enforcement added here; it does not create a retry loop.

After `run_tool()` returns:

```python
transaction = ledger.finished(turn_id, tc.id, result)
coordinator.record_tool_result(turn_id, tool=tc.name,
                               status=transaction.status,
                               evidence=transaction.evidence)
```

On cancellation/exception call `ledger.cancel_turn(turn_id, reason=str(exc))` before re-raising. When a normalized result is `WAITING` and begins with `Clarification needed:`, call `coordinator.set_pending_clarification(turn_id, result, missing_field)` with the missing field parsed from the action-policy reason. The ledger never invokes the tool.

- [ ] **Step 5: Guard post-tool streamed replies before they reach the UI**

Only provider rounds after at least one tool result are buffered. Ordinary first-round conversation continues streaming immediately. For a post-tool final response, call `ledger.guard_reply(turn_id, turn.text)`, append the guarded text to history, and emit that guarded text once through `on_text`. This prevents an unverified streamed “Done” from escaping before the evidence guard can inspect it.

Add an integration test whose first fake provider turn returns an unverified tool result and whose second turn streams `Done, it is saved.` Assert the callback and final history both start with `I could not verify` and never start with `Done`.

- [ ] **Step 6: Add session-aware supersession to runtime control**

Extend `ActiveOperation` and `register()` source-compatibly:

```python
@dataclass
class ActiveOperation:
    id: str
    label: str
    kind: str
    handle: Any
    started_at: float
    session_key: str = ""

def register(self, handle: Any, *, label: str, kind: str,
             session_key: str = "") -> str:
    operation = ActiveOperation(handle.id, _safe_text(label, 160), kind,
                                handle, time.time(), str(session_key)[:160])
    with self._control_lock:
        self._operations[operation.id] = operation
    _publish("runtime.operation_started", self.snapshot_operation(operation))
    return operation.id

def supersede(self, session_key: str, *, kind: str = "brain") -> list[str]:
    key = str(session_key)[:160]
    with self._control_lock:
        operations = [item for item in self._operations.values()
                      if item.session_key == key and item.kind == kind
                      and not getattr(item.handle, "done", False)]
    cancelled: list[str] = []
    for operation in operations:
        if operation.handle.cancel():
            cancelled.append(operation.label)
    return cancelled
```

Call `control.supersede(session_key, kind="brain")` for an accepted normal message before submitting its new task. A phone turn cannot cancel desktop work or another phone's work.

- [ ] **Step 7: Refactor non-streaming chat into a trusted internal helper**

```python
@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    return _chat_request(req, session_key="desktop-owner",
                         action_source="local_text", owner_authenticated=True)

def _chat_request(req: ChatRequest, *, session_key: str,
                  action_source: str, owner_authenticated: bool) -> dict[str, Any]:
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message.")
    from reyes_agent.intelligence import get_runtime_control, update_situation
    control = get_runtime_control()
    control_reply, message = control.handle_user_message(message)
    if control_reply is not None:
        return {"reply": control_reply, "tool_calls": [], "interrupted": True}
    control.supersede(session_key, kind="brain")
    update_situation(recent_command=message, current_task="conversation",
                     current_step="planning")
    voice_identity = _validated_voice_identity(
        req.voice_identity, req.voice_identity_proof)
    turn_id = _open_turn(message, req.turn_id, kind=req.turn_kind)
    try:
        from reyes_agent.voice import narration
        narration.begin_turn(turn_id)
    except Exception:
        pass
    fast_reply = _fast_local_reply(message)
    if fast_reply is not None:
        _mark_fast_reply(turn_id)
        _end_turn(turn_id)
        return {"reply": fast_reply.text, "tool_calls": [],
                "interrupted": False, "local_fast_path": True,
                "intent": fast_reply.intent}
    from reyes_agent.worker_pool import PRIORITY_BRAIN, get_worker_pool
    handle = get_worker_pool().submit(
        _conversation_turn, message, voice_identity=voice_identity,
        turn_id=turn_id, session_key=session_key,
        action_source=action_source,
        owner_authenticated=owner_authenticated,
        name="chat", priority=PRIORITY_BRAIN,
        timeout=config.AI_REQUEST_TIMEOUT_S + 60, with_context=True)
    control.register(handle, label="Conversation", kind="brain",
                     session_key=session_key)
    try:
        return _background_result(handle, config.AI_REQUEST_TIMEOUT_S + 65)
    finally:
        control.release(handle)
        _end_turn(turn_id)
```

This moves the existing `chat()` behavior without exposing `action_source` or `owner_authenticated` in public request JSON.

- [ ] **Step 8: Preserve channel identity at phone and voice front doors**

```python
result = _chat_request(
    ChatRequest(message=req.message.strip()),
    session_key=f"phone:{session['device_id']}",
    action_source="paired_phone",
    owner_authenticated=session["auth_level"] == OWNER_AUTH,
)
```

Remote microphone calls use `phone:<device_id>` and source `voice`; speaker identity remains the owner-authentication authority. Local streaming uses `desktop-owner` and validated local/voice source.

- [ ] **Step 9: Register and finish coordinator turns at lifecycle seams**

After `_open_turn()`, register the same ID with `manage_lifecycle=False`. `_finish_turn()` marks response generation complete without ending browser TTS. `_end_turn()` closes the coordinator turn. Errors and explicit interruption mark failed/cancelled before lifecycle cleanup.

- [ ] **Step 10: Run channel, policy, state, and transaction tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py tests/test_conversation_coordinator.py tests/test_tool_transactions.py tests/test_owner_access.py tests/test_smart_autonomy_policy.py tests/test_conversation_state.py`

Expected: PASS; phone commands retain paired-phone policy and local calls remain source-compatible.

- [ ] **Step 11: Commit**

```powershell
git add -- reyes_agent/agent.py reyes_agent/web.py reyes_agent/intelligence.py tests/test_conversation_hands_integration.py tests/test_conversation_coordinator.py
git commit -m "feat: coordinate conversation and tool turns"
```

---

### Task 6: Remove Hands Approval Bypass Without Approval Fatigue

**Files:**
- Modify: `reyes_agent/permissions.py:131-205`
- Modify: `reyes_agent/action_policy.py:138-175, 332-374`
- Modify: `reyes_agent/tools/hands_tools.py:58-68`
- Modify: `tests/test_hands_tools.py`
- Modify: `tests/test_smart_autonomy_policy.py`

**Interfaces:**
- Consumes: current-turn `ActionContext`, installation profile, `computer.safety.gate()`.
- Produces: routine exact owner commands execute once; unsafe/ambiguous actions remain protected; Hands never supply blanket approval.

- [ ] **Step 1: Write failing authorization tests**

```python
def test_hands_never_pass_blanket_approval(monkeypatch) -> None:
    captured: list[bool] = []
    def fake_act(action, target="", text="", **kwargs):
        captured.append(bool(kwargs.get("approved")))
        return FakeStep(True, True, "changed")
    monkeypatch.setattr("reyes_agent.computer.agentic.act", fake_act)
    hands_tools.type_text("hello")
    hands_tools.click_element("Save")
    assert captured == [False, False]


def test_destructive_hand_target_still_needs_confirmation(monkeypatch) -> None:
    from reyes_agent import vision
    from reyes_agent.vision.elements import Element, Scene
    scene = Scene(window="Notepad", window_handle=10,
                  elements=[Element(type="button", label="Delete",
                                    position=(10, 10, 100, 40), interactive=True)])
    monkeypatch.setattr(vision.scene_state, "current", lambda force=False: scene)
    monkeypatch.setattr(vision.parser, "foreground_handle", lambda: 10)
    with use_action_context("Click Delete", source="local_text",
                            owner_authenticated=True):
        result = run_tool("click_element", {"target": "Delete"})
    assert "needs your explicit go-ahead" in result.casefold()


def test_exact_owner_send_does_not_ask_twice(monkeypatch) -> None:
    monkeypatch.setattr(hands_tools, "_run",
                        lambda action, **kwargs: (True, True, "changed"))
    with use_action_context("Send hello in the current chat", source="local_text",
                            owner_authenticated=True):
        result = run_tool("send_to_chat", {"message": "hello", "send": True})
    assert json.loads(result)["success"] is True
```

- [ ] **Step 2: Run and confirm the blanket-approval defect**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_hands_tools.py tests/test_smart_autonomy_policy.py -k "blanket or destructive_hand or exact_owner_send"`

Expected: FAIL because `_run()` passes `approved=True`, Hands are not all mapped to desktop automation, and real `send_to_chat` is not in `_EXTERNAL_TOOLS`.

- [ ] **Step 3: Map input tools to the existing capability**

```python
    "type_text": "desktop_automation",
    "press_keys": "desktop_automation",
    "click_element": "desktop_automation",
    "scroll_screen": "desktop_automation",
```

Keep `send_to_chat` mapped to `messaging_send`.

- [ ] **Step 4: Treat chat send as outward and type-only as routine**

Add `send_to_chat` to `_EXTERNAL_TOOLS`. Preserve the existing `send is False` routine branch before outward evaluation. Exact current send commands must match their content; draft commands remain denied for `send=True`.

- [ ] **Step 5: Remove blanket approval from Hands**

```python
def _run(action: str, *, target: str = "", text: str = "") -> tuple[bool, bool, str]:
    from reyes_agent.computer import agentic
    step = agentic.act(action, target=target, text=text, approved=False)
    return bool(step.ok), bool(step.changed), str(step.detail)
```

Outer `run_tool()` authorizes the exact routine call; computer safety independently refuses financial/security targets and gates destructive labels.

- [ ] **Step 6: Run Hands, policy, permission, and computer tests**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_hands_tools.py tests/test_smart_autonomy_policy.py tests/test_anywhere_executors.py tests/test_phase1_integrations.py tests/test_phase4_routing.py`

Expected: PASS with no duplicate routine prompt and no weakened refusal/gating assertion.

- [ ] **Step 7: Commit**

```powershell
git add -- reyes_agent/permissions.py reyes_agent/action_policy.py reyes_agent/tools/hands_tools.py tests/test_hands_tools.py tests/test_smart_autonomy_policy.py
git commit -m "fix: authorize ZENO Hands without blanket approval"
```

---

### Task 7: Close Lifecycle Gaps and Keep UI State Truthful

**Files:**
- Modify: `reyes_agent/web.py:1287-1342, 1521-1665`
- Modify: `tests/test_conversation_state.py`
- Modify: `tests/test_conversation_hands_integration.py`

**Interfaces:**
- Consumes: `_open_turn`, `_mark_fast_reply`, `_finish_turn`, `_end_turn`, coordinator/ledger status.
- Produces: non-audio turns end; streamed audio turns remain open until playback ends; narration receives the real turn ID.

- [ ] **Step 1: Add failing lifecycle tests**

```python
def test_non_streaming_fast_typed_reply_closes_turn(monkeypatch) -> None:
    monkeypatch.setattr(web, "_fast_local_reply",
                        lambda _message: FastReply("Hello.", "greeting"))
    result = web.chat(web.ChatRequest(message="hello", turn_kind="typed"))
    assert result["local_fast_path"] is True
    assert conversation_state.current() == conversation_state.IDLE

def test_narration_begins_with_a_real_turn_id(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(narration, "begin_turn", lambda value: seen.append(value))
    monkeypatch.setattr(web, "_fast_local_reply",
                        lambda _message: FastReply("Hello.", "greeting"))
    web.chat(web.ChatRequest(message="hello", turn_kind="typed"))
    assert seen and seen[0]

def test_failed_turn_cancels_outstanding_transactions(monkeypatch) -> None:
    ledger = get_ledger()
    ledger.reset()
    ledger.planned("failed-turn", "call-1", "click_element", {"target": "Save"})
    ledger.cancel_turn("failed-turn", reason="provider failed")
    assert ledger.get("failed-turn", "call-1").status == "CANCELLED"
```

- [ ] **Step 2: Run and confirm stale/unbound lifecycle behavior**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_state.py tests/test_conversation_hands_integration.py -k "fast_typed or narration_begins or outstanding_transactions"`

Expected: narration test FAILS because `begin_turn(turn_id)` currently executes before `turn_id` assignment; fast typed test determines the missing explicit close.

- [ ] **Step 3: Move narration after `_open_turn()`**

```python
turn_id = _open_turn(message, req.turn_id, kind=req.turn_kind)
try:
    narration.begin_turn(turn_id)
except Exception:
    pass
```

Remove the earlier block that references the unbound local.

- [ ] **Step 4: End only turns that cannot produce audio**

Non-streaming typed local fast replies call `_end_turn(turn_id)` before returning. Streamed browser turns remain open for `/api/turn/end` after TTS. Errors cancel coordinator/ledger records and end exactly once.

- [ ] **Step 5: Extend redacted conversation diagnostics**

```python
return {
    "state": conversation_state.snapshot(),
    "duplicates": conversation_state.duplicate_report(),
    "context": get_coordinator().snapshot("desktop-owner"),
    "tool_transactions": get_ledger().snapshot(limit=20),
}
```

Tests assert no raw password, token, private message, or tool body appears.

- [ ] **Step 6: Run lifecycle/voice/worker regressions**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_conversation_state.py tests/test_conversation_continuity.py tests/test_voice_response_budget.py tests/test_phase21_runtime.py tests/test_phase22_stability.py`

Expected: PASS with no GUI-thread or worker-bound regression.

- [ ] **Step 7: Commit**

```powershell
git add -- reyes_agent/web.py tests/test_conversation_state.py tests/test_conversation_hands_integration.py
git commit -m "fix: keep conversation lifecycle truthful"
```

---

### Task 8: Final Regression, Performance Evidence, and Roadmap Update

**Files:**
- Modify: `ROADMAP.md`
- Inspect: every file changed in Tasks 1-7

**Interfaces:**
- Consumes: complete implementation and existing test suites.
- Produces: measured completion record with honest limitations.

- [ ] **Step 1: Run syntax checks**

Run: `.venv\Scripts\python.exe -m compileall -q reyes_agent tests`

Expected: exit code 0.

- [ ] **Step 2: Run complete focused suite**

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py tests/test_conversation_coordinator.py tests/test_tool_transactions.py tests/test_conversation.py tests/test_conversation_state.py tests/test_conversation_continuity.py tests/test_capability_router.py tests/test_hands_tools.py tests/test_smart_autonomy_policy.py tests/test_anywhere_executors.py tests/test_owner_access.py tests/test_phase1_integrations.py tests/test_phase4_routing.py tests/test_phase21_runtime.py tests/test_phase22_stability.py
```

Expected: all selected tests PASS.

- [ ] **Step 3: Measure schema/state bounds**

```powershell
@'
from reyes_agent.routing.capability import tools_for
from reyes_agent.tools import tool_definitions
for message in ("hello", "type hello into Notepad", "open Chrome and click the first result"):
    route = tools_for(message, context_key="measurement")
    print(message, route.exposed, route.capabilities, route.latency_ms)
print("core_schemas", len(tool_definitions()))
'@ | .venv\Scripts\python.exe -
```

Expected: ordinary chat stays at the core budget; desktop/browser remain below configured ceilings; router latency passes its 15 ms test.

- [ ] **Step 4: Run full repository suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS. Capture exact names/output of environment-only failures instead of hiding them.

- [ ] **Step 5: Inspect overlap and staging**

```powershell
git status --short
git diff --check
git diff --name-only HEAD
```

Expected: only planned files belong to this implementation; package, presentation, integration, hacking-tool, or Claude-owned changes remain unstaged and unmodified.

- [ ] **Step 6: Update ROADMAP with measured facts**

Record the lazy-group defect, process-global follow-up risk, channel source/auth correction, no-double-approval behavior, retained safeguards, exact test counts/commands, measured schema counts/router latency, and the honest limitation that physical UI verification requires an interactive Windows desktop.

- [ ] **Step 7: Commit roadmap evidence**

```powershell
git add -- ROADMAP.md
git commit -m "docs: record conversation and Hands verification"
```

- [ ] **Step 8: Run final post-commit verification**

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_conversation_hands_integration.py tests/test_conversation_coordinator.py tests/test_tool_transactions.py tests/test_hands_tools.py tests/test_conversation_state.py
git status --short
git log -8 --oneline
```

Expected: focused tests PASS; only intentionally excluded pre-existing files remain dirty; implementation commits are visible.
