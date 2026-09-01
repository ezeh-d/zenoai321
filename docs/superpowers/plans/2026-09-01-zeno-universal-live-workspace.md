# ZENO Universal Live Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one backend-authoritative ZENO workspace that dynamically manages panels, projects truthful live activity, reports evidence-based tool health, supports safe retry/history/search, and renders appropriately on desktop, Mini Orb, and phone.

**Architecture:** Preserve `reyes_agent.tools.run_tool`, the Event Bus, task engine, permission engine, recovery engine, and existing SSE/phone transports as authorities. Add one isolated `reyes_agent.workspace` projection/orchestration service with revisioned state, then connect it through small FastAPI and frontend adapters. Desktop renders full panels, while Mini Orb and phone receive compact projections of the same logical state.

**Tech Stack:** Python 3.11+, dataclasses, threading/concurrent futures, FastAPI/Pydantic, existing SQLite-backed Event Bus, vanilla ES modules, browser EventSource, pytest, optional Node.js for dependency-free JavaScript contract tests.

**Spec:** `docs/superpowers/specs/2026-09-01-zeno-universal-live-workspace-design.md`

## Global Constraints

- `reyes_agent.tools.run_tool` remains the only authoritative tool executor.
- Use the existing Event Bus and `/api/events/stream`; do not create another event transport or one SSE connection per panel.
- Do not modify TTS, prosody, voice, media, Spotify, package manifests, presentation data, cybersecurity, surveillance, RF, or security-agent functionality.
- Do not index private directories; file search remains an on-demand action through existing infrastructure.
- Never expose chain-of-thought, tokens, credentials, authorization headers, private message bodies, raw prompts, or unbounded tool output.
- No busy loops, simulated progress, provider warmups, or new periodic health polling.
- Live activities cap at 100; all queues, histories, records, text fields, panel instances, retries, probes, and search results have explicit bounds.
- Before editing a shared existing file, run `git diff -- <file>` and preserve concurrent changes.
- Use red-green-refactor for every behavior change and make a focused commit after each task.

---

## File map

### New backend files

- `reyes_agent/workspace/__init__.py`: lazy public service accessor and correlation helpers.
- `reyes_agent/workspace/models.py`: public enums and bounded record dataclasses.
- `reyes_agent/workspace/redaction.py`: recursive allow/deny redaction and safe summaries.
- `reyes_agent/workspace/registry.py`: dynamic panel, command, and health-probe registries.
- `reyes_agent/workspace/manager.py`: panel state machine, revisions, instances, and snapshots.
- `reyes_agent/workspace/intent_router.py`: deterministic presentation decisions and noise budget.
- `reyes_agent/workspace/defaults.py`: declarative built-in panel/command registrations.
- `reyes_agent/workspace/activity.py`: Event Bus to activity-card projection and coalescing.
- `reyes_agent/workspace/history.py`: bounded redacted execution history and retry metadata.
- `reyes_agent/workspace/tool_health.py`: safe probe execution, evidence merging, TTL cache, and capability answers.
- `reyes_agent/workspace/search.py`: metadata-only search across commands, panels, tools, agents, settings, and history.
- `reyes_agent/workspace/service.py`: one composed singleton, bounded Event Bus consumer, snapshot, routing, and lifecycle.
- `reyes_agent/workspace/api.py`: loopback FastAPI router for workspace state and commands.

### New frontend files

- `reyes_agent/static/workspace/client.js`: snapshot buffering, revision ordering, gap rehydration, and API commands.
- `reyes_agent/static/workspace/shell.js`: desktop panel adapters, generic panels, activity cards, focus, docking, and cleanup.
- `reyes_agent/static/workspace/styles.css`: workspace shell and card styles with reduced-motion support.

### Existing integration files

- `reyes_agent/web.py`: include the workspace API, route user requests, expose compact Mini status, and forward dashboard events.
- `reyes_agent/tools/__init__.py`: attach current correlation IDs and report execution evidence without changing execution authority.
- `reyes_agent/tools/intelligence_tools.py`: answer capability questions from dynamic health with a static fallback.
- `reyes_agent/static/index.html`: load the workspace shell, hand it existing SSE events, and augment the command palette.
- `reyes_agent/static/activity_view.js`: update managed activity state without auto-opening on every build delta.
- `reyes_agent/static/mini.html`: expose current activity and request the activity panel before opening the dashboard.
- `reyes_agent/static/phone.html`: keep one bounded WebSocket reconnect timer, back off reconnects, and rehydrate after reopening.
- `reyes_agent/remote_access/cloud_api.py`: return compact workspace activity when locally available and preserve the current remote-device fallback.

### New tests

- `tests/test_workspace_models.py`
- `tests/test_workspace_manager.py`
- `tests/test_workspace_intent_router.py`
- `tests/test_workspace_activity.py`
- `tests/test_workspace_tool_health.py`
- `tests/test_workspace_search.py`
- `tests/test_workspace_api.py`
- `tests/test_workspace_frontend.py`
- `tests/test_workspace_execution_bridge.py`

---

### Task 1: Bounded workspace models and redaction

**Files:**
- Create: `reyes_agent/workspace/__init__.py`
- Create: `reyes_agent/workspace/models.py`
- Create: `reyes_agent/workspace/redaction.py`
- Test: `tests/test_workspace_models.py`

**Interfaces:**
- Produces: `PanelState`, `PresentationMode`, `ActivityStatus`, `ToolHealthState`, `PanelDefinition`, `CommandDefinition`, `PanelInstance`, `PresentationPlan`, `ActivityRecord`, `HistoryRecord`, and `HealthRecord`.
- Produces: `sanitize_mapping(value: object, *, max_depth: int = 4) -> dict[str, Any]`, `safe_text(value: object, limit: int = 300) -> str`, and `secret_free(value: object) -> bool`.
- Every record exposes `as_dict() -> dict[str, Any]` with enum values serialized as strings and tuples serialized as lists.

- [ ] **Step 1: Write failing model and redaction tests**

```python
from reyes_agent.workspace.models import PanelDefinition, PanelState, ToolHealthState
from reyes_agent.workspace.redaction import sanitize_mapping, secret_free


def test_panel_definition_sanitizes_context_and_serializes_enums() -> None:
    panel = PanelDefinition(id="files", title="Files", component="builtin:files",
                            minimum_context=("query",))
    assert panel.validate_context({"query": "CV", "token": "secret"}) == {"query": "CV"}
    assert panel.as_dict()["id"] == "files"


def test_recursive_redaction_removes_secret_fields_and_bounds_text() -> None:
    safe = sanitize_mapping({"authorization": "Bearer x", "nested": {"password": "x"},
                             "result": "a" * 2000})
    assert secret_free(safe)
    assert "Bearer" not in repr(safe) and len(safe["result"]) <= 500


def test_required_public_states_are_exact() -> None:
    assert {state.value for state in PanelState} == {
        "CLOSED", "OPENING", "ACTIVE", "MINIMIZED", "EXPANDED",
        "DOCKED", "BACKGROUND", "CLOSING",
    }
    assert ToolHealthState.AUTH_REQUIRED.value == "AUTH_REQUIRED"
```

- [ ] **Step 2: Run the tests and confirm the expected import failure**

Run: `python -m pytest tests/test_workspace_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'reyes_agent.workspace'`.

- [ ] **Step 3: Implement the enums, bounded records, and recursive redaction**

```python
class PanelState(str, Enum):
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    ACTIVE = "ACTIVE"
    MINIMIZED = "MINIMIZED"
    EXPANDED = "EXPANDED"
    DOCKED = "DOCKED"
    BACKGROUND = "BACKGROUND"
    CLOSING = "CLOSING"


@dataclass(frozen=True)
class PanelDefinition:
    id: str
    title: str
    component: str
    supported_actions: tuple[str, ...] = (
        "show", "hide", "toggle", "minimize", "expand", "focus", "dock", "close")
    default_size: tuple[int, int] = (640, 480)
    preferred_position: str = "right"
    auto_open_policy: str = "contextual"
    priority: int = 50
    singleton: bool = True
    minimum_context: tuple[str, ...] = ()
    supported_surfaces: tuple[str, ...] = ("desktop", "mini", "phone")
    context_allowlist: tuple[str, ...] = (
        "query", "topic", "task_id", "activity_id", "location", "file",
        "project", "url", "agent", "category", "reason")

    def validate_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        safe = sanitize_mapping(context or {})
        selected = {key: safe[key] for key in self.context_allowlist if key in safe}
        missing = [key for key in self.minimum_context if not selected.get(key)]
        if missing:
            raise ValueError("missing panel context: " + ", ".join(missing))
        return selected
```

Implement record `as_dict()` methods through one `_public()` serializer. Bound IDs to 80 characters, titles/summaries to 300, details to 500, result references to 300, and lists to 50 entries. Redaction must case-insensitively remove keys containing `token`, `secret`, `password`, `authorization`, `cookie`, `api_key`, `private_message`, `prompt`, and `chain_of_thought`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_workspace_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the model contract**

```bash
git add reyes_agent/workspace/__init__.py reyes_agent/workspace/models.py reyes_agent/workspace/redaction.py tests/test_workspace_models.py
git commit -m "feat(workspace): add bounded public models"
```

---

### Task 2: Dynamic panel registry and authoritative state manager

**Files:**
- Create: `reyes_agent/workspace/registry.py`
- Create: `reyes_agent/workspace/manager.py`
- Test: `tests/test_workspace_manager.py`

**Interfaces:**
- Consumes: `PanelDefinition`, `PanelInstance`, `PanelState`, and `sanitize_mapping` from Task 1.
- Produces: `PanelRegistry.register(definition)`, `get(panel_id)`, `all()`, and `unregister(panel_id)`.
- Produces: `CommandRegistry.register(definition)`, `get(command_id)`, `all()`, and `unregister(command_id)`.
- Produces: `RevisionClock.current() -> int` and `next() -> int`.
- Produces: `WorkspaceManager(registry, publish=None, max_instances=24, revisions=None)` and methods `show_panel`, `hide_panel`, `toggle_panel`, `minimize_panel`, `expand_panel`, `focus_panel`, `dock_panel`, `close_panel`, `get_panel_state`, `get_active_panels`, and `snapshot`.
- `publish(event_type: str, payload: dict[str, Any], correlation_id: str) -> None` is injected for deterministic tests.

- [ ] **Step 1: Write failing registry and transition tests**

```python
def test_singleton_show_is_idempotent_and_revisions_are_monotonic() -> None:
    registry = PanelRegistry()
    registry.register(PanelDefinition("activity", "Activity", "builtin:activity"))
    events = []
    manager = WorkspaceManager(registry, publish=lambda kind, payload, corr: events.append(payload))
    first = manager.show_panel("activity", {"task_id": "t1"}, correlation_id="t1")
    second = manager.show_panel("activity", {"task_id": "t1"}, correlation_id="t1")
    assert first.instance_id == second.instance_id
    assert second.state is PanelState.ACTIVE
    assert second.revision > first.revision
    assert [event["panel"]["state"] for event in events[:2]] == ["OPENING", "ACTIVE"]


def test_invalid_panel_and_rapid_close_are_safe() -> None:
    manager = WorkspaceManager(PanelRegistry())
    with pytest.raises(KeyError):
        manager.show_panel("missing")
    assert manager.close_panel("missing") is None


def test_dock_focus_minimize_expand_and_close() -> None:
    registry = PanelRegistry()
    registry.register(PanelDefinition("system", "System", "builtin:health"))
    manager = WorkspaceManager(registry)
    manager.show_panel("system")
    assert manager.dock_panel("system", "right").state is PanelState.DOCKED
    assert manager.minimize_panel("system").state is PanelState.MINIMIZED
    assert manager.expand_panel("system").state is PanelState.EXPANDED
    assert manager.focus_panel("system").state is PanelState.ACTIVE
    assert manager.close_panel("system").state is PanelState.CLOSED
```

- [ ] **Step 2: Run the tests and confirm missing registry/manager failures**

Run: `python -m pytest tests/test_workspace_manager.py -q`

Expected: FAIL because `PanelRegistry` and `WorkspaceManager` do not exist.

- [ ] **Step 3: Implement registry validation and manager transitions**

```python
_TRANSITIONS = {
    PanelState.CLOSED: {PanelState.OPENING},
    PanelState.OPENING: {PanelState.ACTIVE, PanelState.CLOSING},
    PanelState.ACTIVE: {PanelState.MINIMIZED, PanelState.EXPANDED, PanelState.DOCKED,
                        PanelState.BACKGROUND, PanelState.CLOSING},
    PanelState.MINIMIZED: {PanelState.ACTIVE, PanelState.EXPANDED, PanelState.DOCKED,
                           PanelState.CLOSING},
    PanelState.EXPANDED: {PanelState.ACTIVE, PanelState.MINIMIZED, PanelState.DOCKED,
                          PanelState.CLOSING},
    PanelState.DOCKED: {PanelState.ACTIVE, PanelState.MINIMIZED, PanelState.EXPANDED,
                        PanelState.CLOSING},
    PanelState.BACKGROUND: {PanelState.ACTIVE, PanelState.CLOSING},
    PanelState.CLOSING: {PanelState.CLOSED},
}
```

Guard all state with `threading.RLock`. Increment one global revision for every accepted transition. `show_panel` must record `OPENING` and then `ACTIVE` synchronously. `close_panel` must record `CLOSING` and then `CLOSED`. Cap total non-closed instances at 24, evicting only the oldest closed instance. Cap multi-instance registrations at four instances per panel. Every publication contains `revision`, `panel`, and `action` and uses event type `workspace.panel.changed`.

`RevisionClock` owns a locked integer and is injected into the manager. Its `next()` method is the only way any workspace record obtains a new global revision. Task 4 will pass this same object to activity/history projections and Task 5 to health, giving reconnect logic one monotonic sequence.

Store immutable `PanelInstance` values or return `dataclasses.replace()` copies from every public method. A later transition must never mutate an object already returned to a caller or captured in an event.

- [ ] **Step 4: Run concurrency and transition tests**

Run: `python -m pytest tests/test_workspace_manager.py -q`

Expected: PASS, including a `ThreadPoolExecutor` test that submits 100 alternating show/close commands and verifies unique monotonic event revisions and a valid final state.

- [ ] **Step 5: Commit panel authority**

```bash
git add reyes_agent/workspace/registry.py reyes_agent/workspace/manager.py tests/test_workspace_manager.py
git commit -m "feat(workspace): add panel registry and manager"
```

---

### Task 3: Contextual intent router and declarative defaults

**Files:**
- Create: `reyes_agent/workspace/intent_router.py`
- Create: `reyes_agent/workspace/defaults.py`
- Test: `tests/test_workspace_intent_router.py`

**Interfaces:**
- Consumes: `PanelRegistry`, `CommandRegistry`, `PresentationMode`, and `PresentationPlan`.
- Produces: `PanelIntentRouter.route(message: str, *, correlation_id: str = "", source_surface: str = "desktop", capability_states: dict[str, str] | None = None, active_panels: tuple[str, ...] = ()) -> PresentationPlan`.
- Produces: `register_default_panels(registry: PanelRegistry) -> None`, `register_default_commands(registry: CommandRegistry) -> None`, and idempotent factories `default_panel_registry()` and `default_command_registry()`.

- [ ] **Step 1: Write failing routing/noise tests**

```python
@pytest.mark.parametrize((message, mode, panel), [
    ("what time is it", PresentationMode.NO_UI, ""),
    ("pause", PresentationMode.NO_UI, ""),
    ("find my CV", PresentationMode.FULL, "files"),
    ("check the news", PresentationMode.FULL, "news"),
    ("show my system performance", PresentationMode.FULL, "system"),
    ("ask the council", PresentationMode.FULL, "agents"),
    ("download this report", PresentationMode.CARD, "downloads"),
    ("open calculator", PresentationMode.CARD, ""),
    ("show what is playing", PresentationMode.FULL, "media"),
])
def test_route_examples(message, mode, panel) -> None:
    result = PanelIntentRouter(default_panel_registry()).route(message, correlation_id="turn-1")
    assert result.mode is mode and result.primary_panel == panel


def test_existing_panel_updates_without_opening_a_second_primary() -> None:
    result = PanelIntentRouter(default_panel_registry()).route(
        "find my assignment", active_panels=("files",), correlation_id="turn-2")
    assert result.primary_panel == "files"
    assert result.context["reuse_existing"] is True
```

- [ ] **Step 2: Run tests and confirm the missing router failure**

Run: `python -m pytest tests/test_workspace_intent_router.py -q`

Expected: FAIL because the router/defaults modules do not exist.

- [ ] **Step 3: Implement deterministic route rules and default registrations**

```python
@dataclass(frozen=True)
class RouteRule:
    panel: str
    terms: tuple[re.Pattern[str], ...]
    mode: PresentationMode
    context_key: str = "query"


NO_UI = (
    re.compile(r"^\s*(pause|stop|cancel)\s*[.!?]*$", re.I),
    re.compile(r"\b(what(?:'s| is) the time|what time is it)\b", re.I),
)
```

Use ordered, bounded regex rules for files/search, news, system, agents/council, downloads, media, messages, calendar/tasks, browser, coding/terminal, documents, images, and health. Explicit `show/open` language upgrades an applicable route to `FULL`; non-visual background phrasing may downgrade to `BACKGROUND`. If the required capability state is `AUTH_REQUIRED`, `DEPENDENCY_MISSING`, `DISCONNECTED`, `UNAVAILABLE`, or `ERROR`, return `CARD` with a safe reason and do not auto-open the target. The result contains exactly one `primary_panel`.

Register declarative definitions for `media`, `files`, `browser`, `news`, `weather`, `messages`, `calls`, `calendar`, `tasks`, `downloads`, `terminal`, `coding`, `agents`, `system`, `notifications`, `search`, `documents`, `images`, `activity`, `history`, and `tool-health`. Existing surfaces use `dom:` or `module:` components; missing dedicated surfaces use the generic `builtin:activity` or `builtin:search` projection rather than empty windows.

- [ ] **Step 4: Run routing tests**

Run: `python -m pytest tests/test_workspace_intent_router.py -q`

Expected: PASS.

- [ ] **Step 5: Commit routing and defaults**

```bash
git add reyes_agent/workspace/intent_router.py reyes_agent/workspace/defaults.py tests/test_workspace_intent_router.py
git commit -m "feat(workspace): route context to bounded panel plans"
```

---

### Task 4: Truthful activity, history, correlation, and composed service

**Files:**
- Create: `reyes_agent/workspace/activity.py`
- Create: `reyes_agent/workspace/history.py`
- Create: `reyes_agent/workspace/service.py`
- Modify: `reyes_agent/workspace/__init__.py`
- Test: `tests/test_workspace_activity.py`

**Interfaces:**
- Consumes: Event-shaped dictionaries with `type`, `payload`, `source`, `correlation_id`, `ts`, and `id`.
- Consumes: one shared `RevisionClock` from Task 2.
- Produces: `ActivityProjector.consume(event) -> ActivityRecord | None`, `snapshot()`, `dismiss(activity_id)`, and `current()`.
- Produces: `HistoryProjector.consume(event) -> HistoryRecord | None`, `snapshot(limit=50)`, and `record_request(correlation_id, summary)`.
- Produces: `WorkspaceService.start()`, `stop()`, `route_request()`, `consume_event()`, `snapshot()`, `mini_snapshot()`, and `phone_snapshot()`.
- Produces: `correlation(correlation_id: str, request_summary: str = "")` context manager and `current_correlation() -> str`.

- [ ] **Step 1: Write failing projection, redaction, coalescing, and loop-prevention tests**

```python
def test_tool_events_coalesce_and_never_expose_secret_input() -> None:
    projector = ActivityProjector(clock=lambda: 100.0)
    first = projector.consume({"type": "tool.returned", "correlation_id": "t1", "ts": 90,
        "payload": {"tool": "search_files", "input": {"query": "CV", "token": "x"},
                    "result": "Found CV.pdf", "duration_ms": 12}})
    second = projector.consume({"type": "tool.completed", "correlation_id": "t1", "ts": 91,
        "payload": {"tool": "search_files", "result": "Verified CV.pdf", "duration_ms": 18}})
    assert first.activity_id == second.activity_id
    assert second.status is ActivityStatus.SUCCEEDED
    assert "token" not in repr(second.as_dict()).casefold()


def test_workspace_output_events_are_not_reprojected() -> None:
    assert ActivityProjector().consume({"type": "workspace.activity.changed",
        "source": "workspace", "payload": {}, "correlation_id": "x"}) is None


def test_malformed_and_concurrent_events_remain_bounded() -> None:
    projector = ActivityProjector(max_live=100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: projector.consume({"type": "tool.failed", "payload": {
            "tool": f"tool_{i}", "result": object()}, "correlation_id": str(i)}), range(300)))
    assert len(projector.snapshot()) == 100
```

- [ ] **Step 2: Run tests and confirm missing projector/service failures**

Run: `python -m pytest tests/test_workspace_activity.py -q`

Expected: FAIL because activity/history/service are undefined.

- [ ] **Step 3: Implement event normalization, expiry-on-read, history, and service lifecycle**

```python
class ActivityProjector:
    def consume(self, event: dict[str, Any]) -> ActivityRecord | None:
        event_type = safe_text(event.get("type"), 80)
        if not event_type or event_type.startswith("workspace."):
            return None
        payload = sanitize_mapping(event.get("payload") or {})
        correlation = safe_text(event.get("correlation_id"), 80) or safe_text(event.get("id"), 80)
        operation = safe_text(payload.get("tool") or payload.get("action") or event_type, 80)
        key = f"{correlation}:{event_type.split('.', 1)[0]}:{operation}"
        # Map the event family to a human title/status, then replace the record
        # under the same key while preserving started_at and activity_id.
```

Implement explicit mappings for `tool.*`, `build.task`, `project.activity`, `execution.lifecycle`, `website.*`, `agent.*`, `mission.*`, `file.*`, `browser.*`, `download.*`, `system.warning`, and `workspace.panel.changed`. Unknown events return `None` unless their payload contains an explicit safe `user_visible=True` marker. Successful transient records receive `expires_at=now+5`; failures, warnings, authentication states, and waiting states receive `expires_at=0`. `snapshot()` removes expired successes and sorts newest first without a timer.

`WorkspaceService` creates one `RevisionClock` and injects it into the manager, activity projector, history projector, and health manager. `start()` subscribes once to `event_bus.subscribe()`, starts one named daemon consumer thread following the existing workflow-recorder pattern, and marks itself started under a lock. `stop()` sets a stop event, joins for at most one second, and always calls `event_bus.unsubscribe()`. The consumer ignores `workspace.*` inputs, publishes only changed activity/history/health records, and never lets projection failure block the bus. Tests instantiate the service with injected event source and publisher so they do not start a real background thread.

- [ ] **Step 4: Run activity and service tests**

Run: `python -m pytest tests/test_workspace_activity.py -q`

Expected: PASS, including start-twice/stop-twice idempotency and subscriber cleanup.

- [ ] **Step 5: Commit activity truth**

```bash
git add reyes_agent/workspace/__init__.py reyes_agent/workspace/activity.py reyes_agent/workspace/history.py reyes_agent/workspace/service.py tests/test_workspace_activity.py
git commit -m "feat(workspace): project safe live activity and history"
```

---

### Task 5: Evidence-based tool health and dynamic capability answers

**Files:**
- Modify: `reyes_agent/workspace/registry.py`
- Create: `reyes_agent/workspace/tool_health.py`
- Modify: `reyes_agent/workspace/service.py`
- Modify: `reyes_agent/tools/intelligence_tools.py:192-206`
- Test: `tests/test_workspace_tool_health.py`

**Interfaces:**
- Produces: `HealthProbe(name, category, check, supported_operations=(), dependencies=(), permissions_required=(), timeout_s=2.0, recover=None)`.
- Produces: `HealthProbeRegistry.register(probe)`, `get(name)`, and `all()` in `registry.py`.
- Produces: `ToolHealthManager.check(name, force=False) -> HealthRecord`, `check_many(names=None, force=False)`, `observe_execution(name, ok, latency_ms, error_code="")`, `snapshot()`, `capability_summary(query)`, and `close()`.
- Consumes: `get_global_tool_registry()`, `tool_reputation`, `circuit_breaker`, adapter metadata/configuration health, and registered safe probes.

- [ ] **Step 1: Write failing honesty, transition, timeout, TTL, and coalescing tests**

```python
def test_registration_without_probe_or_execution_is_degraded() -> None:
    manager = ToolHealthManager(adapters=[FakeAdapter("slack", state="READY")], clock=lambda: 10)
    result = manager.check("slack")
    assert result.status is ToolHealthState.DEGRADED
    assert result.available is False
    assert result.evidence_source == "registration_only"


@pytest.mark.parametrize((probe_value, expected), [
    ({"ok": True, "initialized": True}, ToolHealthState.AVAILABLE),
    ({"ok": False, "auth_required": True}, ToolHealthState.AUTH_REQUIRED),
    ({"ok": False, "dependency_missing": "client"}, ToolHealthState.DEPENDENCY_MISSING),
    ({"ok": False, "disconnected": True}, ToolHealthState.DISCONNECTED),
])
def test_real_probe_maps_specific_states(probe_value, expected) -> None:
    probes = HealthProbeRegistry()
    probes.register(HealthProbe("browser", "browser", lambda: probe_value))
    assert ToolHealthManager(probes=probes).check("browser", force=True).status is expected


def test_concurrent_checks_share_one_inflight_probe() -> None:
    calls = 0
    lock = threading.Lock()
    def probe():
        nonlocal calls
        with lock: calls += 1
        time.sleep(.05)
        return {"ok": True}
    manager = ToolHealthManager(probes=registry_with("files", probe))
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: manager.check("files", force=True), range(20)))
    assert calls == 1 and all(row.status is ToolHealthState.AVAILABLE for row in rows)
```

- [ ] **Step 2: Run tests and confirm missing health manager failures**

Run: `python -m pytest tests/test_workspace_tool_health.py -q`

Expected: FAIL because `HealthProbeRegistry` and `ToolHealthManager` do not exist.

- [ ] **Step 3: Implement safe evidence merging and bounded probe execution**

```python
class ToolHealthManager:
    def __init__(self, *, adapters=None, probes=None, ttl_s=30.0, max_workers=4,
                 clock=time.time):
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4)),
                                            thread_name_prefix="zeno-health")
        self._inflight: dict[str, Future] = {}
        self._cache: dict[str, HealthRecord] = {}
        self._lock = threading.RLock()

    def check(self, name: str, force: bool = False) -> HealthRecord:
        # Return a fresh TTL entry when allowed. Otherwise share one future,
        # wait no longer than the probe timeout, normalize its safe result,
        # cache the record, and publish only if the state changed.
```

Mapping precedence is permission blocked, missing dependency, authentication required, disconnected/device offline, open circuit, successful probe/recent verified execution, probe error, then registration-only degradation. A successful execution observed through the Event Bus records `AVAILABLE`, timestamps, latency, and evidence source `verified_execution`; failure updates `last_failure` without erasing an earlier success. `close()` shuts down the probe executor with `wait=False` and `cancel_futures=True`.

Update `capability_status()` to query `get_workspace_service().health.capability_summary(capability)` first. If no registered tools/panels/commands match, retain `intelligence.capability()` and its existing static fallback. Return only public health fields.

- [ ] **Step 4: Run health and existing capability tests**

Run: `python -m pytest tests/test_workspace_tool_health.py tests/test_universal_tool_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit health truth**

```bash
git add reyes_agent/workspace/registry.py reyes_agent/workspace/tool_health.py reyes_agent/workspace/service.py reyes_agent/tools/intelligence_tools.py tests/test_workspace_tool_health.py
git commit -m "feat(workspace): report evidence based tool health"
```

---

### Task 6: Unified metadata search and loopback workspace API

**Files:**
- Create: `reyes_agent/workspace/search.py`
- Create: `reyes_agent/workspace/api.py`
- Modify: `reyes_agent/workspace/service.py`
- Modify: `reyes_agent/web.py:1235-1259,1554-1610,2351-2410,3148-3177`
- Test: `tests/test_workspace_search.py`
- Test: `tests/test_workspace_api.py`

**Interfaces:**
- Produces: `WorkspaceSearch.refresh_metadata()` and `search(query: str, limit: int = 12) -> list[dict[str, Any]]`.
- Produces loopback routes under `/api/workspace` for state, panels, panel actions, activities, history, health, health refresh, search, retry, and resume.
- `WorkspaceService.route_request(message, correlation_id, source_surface)` is invoked exactly once after `_open_turn()` assigns the turn ID.

- [ ] **Step 1: Write failing search and API tests**

```python
def test_search_returns_typed_panel_tool_command_and_history_results() -> None:
    search = seeded_workspace_search()
    kinds = {row["kind"] for row in search.search("system", limit=12)}
    assert {"panel", "command", "tool"} <= kinds
    assert all("action" in row and "target" in row for row in search.search("system"))


def test_search_never_indexes_file_contents_or_secret_history() -> None:
    search = seeded_workspace_search(history=[HistoryRecord(
        task_id="t", request_summary="find CV", status="FAILED",
        safe_result="token=secret", started_at=1)])
    payload = repr(search.search("secret"))
    assert "token=" not in payload and "path" not in search.health()["sources"]


def test_workspace_api_is_loopback_only_and_revisioned() -> None:
    from reyes_agent.workspace.api import create_router
    app = FastAPI(); app.include_router(create_router(service=fake_service()))
    local = TestClient(app, client=("127.0.0.1", 5000))
    assert local.get("/api/workspace/state").json()["revision"] == 7
    remote = TestClient(app, client=("203.0.113.9", 5000))
    assert remote.get("/api/workspace/state").status_code == 403
```

- [ ] **Step 2: Run tests and confirm missing search/API failures**

Run: `python -m pytest tests/test_workspace_search.py tests/test_workspace_api.py -q`

Expected: FAIL because workspace search and API routes do not exist.

- [ ] **Step 3: Implement metadata-only search and API commands**

Use a dedicated `UniversalSearchService(index_name="zeno-workspace")`. Index only panel definitions, command definitions, tool metadata, agent IDs/roles, setting labels, and the last 100 redacted history records. Re-index stable IDs idempotently. File-related results use `{kind: "action", action: "start_file_search", target: query}` rather than pre-indexing directories. Clamp queries to 200 characters and results to 25.

```python
@router.post("/panels/{panel_id}/{action}")
def panel_action(panel_id: str, action: str, payload: PanelActionRequest,
                 request: Request) -> dict[str, Any]:
    require_loopback(request)
    if action not in {"show", "hide", "toggle", "minimize", "expand",
                      "focus", "dock", "close"}:
        raise HTTPException(400, "Unsupported panel action.")
    return service.panel_action(panel_id, action, payload.context,
                                payload.correlation_id, payload.position)
```

Include the router once in `web.py`. Call `get_workspace_service().route_request()` from `_open_turn()` after the turn ID exists; failures are observability-only and cannot block chat. Add `workspace` compact state to `/api/mini-status`. Keep the existing `/api/events/stream` unchanged.

Bind `turn_id` to the workspace correlation context immediately after `_conversation_turn()` acquires the serialized conversation lock, and reset the context token in the same `finally` block that releases the lock. This makes all tool events in that turn inherit the ID without changing tool signatures or leaking correlation into the next turn.

- [ ] **Step 4: Run API, chat, event, and search tests**

Run: `python -m pytest tests/test_workspace_search.py tests/test_workspace_api.py tests/test_universal_search.py tests/test_visual_performance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit backend integration**

```bash
git add reyes_agent/workspace/search.py reyes_agent/workspace/api.py reyes_agent/workspace/service.py reyes_agent/web.py tests/test_workspace_search.py tests/test_workspace_api.py
git commit -m "feat(workspace): expose revisioned workspace API and search"
```

---

### Task 7: Correlated execution evidence and safe retry/resume bridge

**Files:**
- Modify: `reyes_agent/tools/__init__.py:393-407,446-512`
- Modify: `reyes_agent/workspace/history.py`
- Modify: `reyes_agent/workspace/service.py`
- Modify: `reyes_agent/workspace/api.py`
- Test: `tests/test_workspace_execution_bridge.py`

**Interfaces:**
- Consumes: `current_correlation()` and `WorkspaceService.observe_tool_execution(name, raw_input, outcome, duration_ms)`.
- Produces: ephemeral `RetryHandle` records keyed by task/correlation ID, never included in public history or durable events.
- Produces: `retry_task(task_id) -> dict[str, Any]` and `resume_task(task_id) -> dict[str, Any]` that delegate to `run_tool` through the existing bounded worker pool.

- [ ] **Step 1: Write failing correlation, redaction, and irreversible-retry tests**

```python
def test_tool_event_uses_current_workspace_correlation(monkeypatch) -> None:
    subscription = event_bus.subscribe()
    tool = Tool("workspace_read_test", "read", {"type": "object"}, lambda: "ordinary data")
    try:
        with correlation("turn-77", request_summary="read status"):
            execute_tool(tool, {})
        event = next_event(subscription, "tool.returned")
        assert event.correlation_id == "turn-77"
    finally:
        event_bus.unsubscribe(subscription)


def test_retry_handle_is_ephemeral_and_irreversible_action_is_refused() -> None:
    service = isolated_workspace_service()
    service.observe_tool_execution("send_message", {"body": "private"},
                                   {"outcome": "failed", "retryable": True}, 10)
    public = repr(service.history.snapshot())
    assert "private" not in public
    result = service.retry_task(current_correlation())
    assert result["ok"] is False and result["state"] == "CONFIRMATION_REQUIRED"
```

- [ ] **Step 2: Run tests and confirm missing correlation/retry behavior**

Run: `python -m pytest tests/test_workspace_execution_bridge.py -q`

Expected: FAIL because tool events do not yet carry workspace correlation and retry handles are absent.

- [ ] **Step 3: Attach correlation and store only bounded ephemeral retry inputs**

In `_publish_tool_failure()` and the successful `event_bus.publish()` call, pass `correlation_id=current_correlation()` through a guarded lazy import. After classification, call `get_workspace_service().observe_tool_execution(...)` in a guarded block. This call is telemetry and must never alter the tool result or catch policy exceptions raised before execution.

Classify safe automatic/manual retry with the existing `autonomy.classify_tool()` decision plus tool metadata. Permit only read-only/idempotent tools or task-engine operations with a real checkpoint. Do not create a retry handle when raw inputs contain secret-like keys or private message content. Store at most 20 eligible raw retry handles for ten minutes in memory; zeroize/remove a handle on expiry or successful retry. Consequential actions return `CONFIRMATION_REQUIRED` and do not run. Retry execution submits `run_tool(name, input)` to the existing worker pool with one attempt and the existing circuit-breaker admission.

- [ ] **Step 4: Run execution bridge and production-reality tests**

Run: `python -m pytest tests/test_workspace_execution_bridge.py tests/test_production_reality.py -q`

Expected: PASS, with existing result classification unchanged.

- [ ] **Step 5: Commit the execution bridge**

```bash
git add reyes_agent/tools/__init__.py reyes_agent/workspace/history.py reyes_agent/workspace/service.py reyes_agent/workspace/api.py tests/test_workspace_execution_bridge.py
git commit -m "feat(workspace): correlate execution and gate safe retries"
```

---

### Task 8: Desktop workspace shell, cards, health panel, and command palette

**Files:**
- Create: `reyes_agent/static/workspace/client.js`
- Create: `reyes_agent/static/workspace/shell.js`
- Create: `reyes_agent/static/workspace/styles.css`
- Modify: `reyes_agent/static/index.html:1742-1815,5297-5380`
- Modify: `reyes_agent/static/activity_view.js:89-110,470-530`
- Test: `tests/test_workspace_frontend.py`

**Interfaces:**
- Produces: `WorkspaceRevisionBuffer.applySnapshot(snapshot)`, `pushEvent(event)`, `needsRehydrate`, and `state`.
- Produces: `createWorkspaceShell({fetchImpl, documentRef})` with `hydrate`, `consumeEvent`, `panelAction`, `search`, `executeSearchResult`, and `dispose`.
- Consumes the existing dashboard `EventSource`; it does not open a second stream.

- [ ] **Step 1: Write failing frontend source and revision-buffer tests**

```python
def test_dashboard_uses_one_event_stream_and_lazy_workspace_modules() -> None:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    shell = (STATIC / "workspace" / "shell.js").read_text(encoding="utf-8")
    assert page.count("new EventSource('/api/events/stream')") == 1
    assert "workspace/shell.js" in page and "consumeEvent(update)" in page
    assert "setInterval" not in shell
    assert "requestAnimationFrame" in shell


def test_activity_view_no_longer_opens_for_every_delta() -> None:
    source = (STATIC / "activity_view.js").read_text(encoding="utf-8")
    build_branch = source[source.index("if (type === 'build.task'"):source.index("if (type === 'project.activity'")]
    assert "show()" not in build_branch


def test_revision_buffer_rehydrates_on_gap() -> None:
    output = run_node_module("workspace/client.js", """
      const b = new WorkspaceRevisionBuffer();
      b.applySnapshot({revision: 4, panels: [], activities: []});
      b.pushEvent({type:'workspace.panel.changed', payload:{revision:6}});
      console.log(JSON.stringify({gap:b.needsRehydrate, revision:b.revision}));
    """)
    assert output == {"gap": True, "revision": 4}
```

- [ ] **Step 2: Run tests and confirm missing frontend module failures**

Run: `python -m pytest tests/test_workspace_frontend.py -q`

Expected: FAIL because the workspace static modules do not exist.

- [ ] **Step 3: Implement the revision client and workspace shell**

```javascript
export class WorkspaceRevisionBuffer {
  constructor(){ this.revision=0; this.hydrated=false; this.needsRehydrate=false; this.buffer=[]; this.state={}; }
  applySnapshot(snapshot){
    this.state=structuredClone(snapshot||{}); this.revision=Number(snapshot?.revision||0);
    this.hydrated=true; this.needsRehydrate=false;
    const pending=this.buffer.splice(0).sort((a,b)=>Number(a.payload?.revision||0)-Number(b.payload?.revision||0));
    pending.forEach(event=>this.pushEvent(event));
  }
  pushEvent(event){
    if(!String(event?.type||'').startsWith('workspace.')) return false;
    if(!this.hydrated){ this.buffer.push(event); return true; }
    const next=Number(event?.payload?.revision||0);
    if(next<=this.revision) return false;
    if(next!==this.revision+1){ this.needsRehydrate=true; return false; }
    this.revision=next; return true;
  }
}
```

The shell creates one `#zeno-workspace-root`, one panel host, and one activity-card stack. Generic component adapters support `dom:`, `module:`, and `builtin:` definitions. Built-ins render activity, history, tool health, and search. Apply state changes in one queued `requestAnimationFrame`; detach listeners and abort pending fetches in `dispose()`. Honor `prefers-reduced-motion` and pause hidden panel render updates.

In `index.html`, load the module once, call `hydrate()`, pass every existing dashboard SSE update to `consumeEvent(update)`, and call `hydrate()` again from `dashboardEvents.onopen`. Add remote search results to the existing `COMMANDS` rendering with an abort controller and sequence guard; preserve arrow keys, Enter, Escape, Ctrl+Space, and Ctrl+K. Do not add package dependencies.

Change `activity_view.js` so `consumeEvent()` updates its maps and renders only when already open. Panel opening comes from the workspace shell or the existing explicit Website Studio button.

- [ ] **Step 4: Run frontend, build activity, and visual-performance tests**

Run: `python -m pytest tests/test_workspace_frontend.py tests/test_build_execution.py tests/test_project_activity.py tests/test_universal_tool_registry.py tests/test_visual_performance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit desktop workspace UI**

```bash
git add reyes_agent/static/workspace/client.js reyes_agent/static/workspace/shell.js reyes_agent/static/workspace/styles.css reyes_agent/static/index.html reyes_agent/static/activity_view.js tests/test_workspace_frontend.py
git commit -m "feat(workspace): add live desktop workspace shell"
```

---

### Task 9: Mini Orb and phone compact projections

**Files:**
- Modify: `reyes_agent/static/mini.html:34-48,90-108`
- Modify: `reyes_agent/static/phone.html:48-52`
- Modify: `reyes_agent/remote_access/cloud_api.py:1093-1095`
- Modify: `tests/test_workspace_frontend.py`
- Modify: `tests/test_visual_performance.py:45-60`

**Interfaces:**
- Consumes: `/api/mini-status.workspace.current_activity` and `POST /api/workspace/panels/activity/show`.
- Produces: owner activity rows with `event`, `summary`, `outcome`, `state`, and `at`, using compact workspace activity when present and existing device activity otherwise.

- [ ] **Step 1: Add failing Mini and phone projection tests**

```python
def test_mini_reuses_status_fetch_and_click_requests_current_activity() -> None:
    mini = (STATIC / "mini.html").read_text(encoding="utf-8")
    assert mini.count("/api/mini-status") == 1
    assert "/api/workspace/panels/activity/show" in mini
    assert "workspace.current_activity" in mini
    assert "setInterval" not in extract_workspace_block(mini)


def test_owner_activity_has_workspace_projection_and_remote_fallback() -> None:
    source = (ROOT / "reyes_agent" / "remote_access" / "cloud_api.py").read_text(encoding="utf-8")
    assert "phone_snapshot" in source
    assert "device_link.get_link().activity" in source


def test_phone_websocket_reconnect_is_single_bounded_and_rehydrates() -> None:
    phone = (STATIC / "phone.html").read_text(encoding="utf-8")
    reconnect = phone[phone.index("function connectEvents"):phone.index("async function enrollBiometric")]
    assert "wsReconnectTimer" in reconnect
    assert "Math.min(30000" in reconnect
    assert "refreshAll()" in reconnect
    assert "if(wsReconnectTimer)" in reconnect
```

- [ ] **Step 2: Run tests and confirm missing compact projection failures**

Run: `python -m pytest tests/test_workspace_frontend.py tests/test_visual_performance.py -q`

Expected: FAIL because Mini click and owner activity do not consult workspace state.

- [ ] **Step 3: Add compact projections without new loops or geometry**

Extend the existing Mini status rendering to map current workspace activity statuses to `executing`, `waiting`, `success`, `warning`, or `error`, keeping conversation speaking/listening state higher priority. On an unmoved click, first issue the loopback panel-show request with `{context:{source:"mini"}}`, ignore network failure, then invoke the existing `openDashboard()`.

Replace the phone companion's fixed reconnect timeout with one `wsReconnectTimer`, an attempt counter, exponential backoff capped at 30 seconds, and reset-on-open. `onopen` calls `refreshAll()` once to rehydrate missed state. Visibility restore cancels a stale timer before reconnecting. Existing origin/rate checks and authentication behavior remain unchanged.

In the protected owner activity endpoint, try `get_workspace_service().phone_snapshot()` and convert non-empty compact activities to the shape already rendered by `vActivity()`. When the local workspace has no activities—such as a cloud gateway process—return `device_link.get_link().activity(limit)` unchanged. Never include panel coordinates, tool inputs, or result bodies.

- [ ] **Step 4: Run Mini, phone, and owner-boundary tests**

Run: `python -m pytest tests/test_workspace_frontend.py tests/test_visual_performance.py tests/test_production_reality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit compact surfaces**

```bash
git add reyes_agent/static/mini.html reyes_agent/static/phone.html reyes_agent/remote_access/cloud_api.py tests/test_workspace_frontend.py tests/test_visual_performance.py
git commit -m "feat(workspace): project activity to mini and phone"
```

---

### Task 10: End-to-end recovery, malformed-event, reconnect, and regression verification

**Files:**
- Modify: `tests/test_workspace_manager.py`
- Modify: `tests/test_workspace_activity.py`
- Modify: `tests/test_workspace_tool_health.py`
- Modify: `tests/test_workspace_api.py`
- Modify: `tests/test_workspace_frontend.py`
- Modify only if a failing test proves a defect: files created or modified in Tasks 1-9.

**Interfaces:**
- Verifies all public contracts from Tasks 1-9 together.
- Produces no new runtime authority.

- [ ] **Step 1: Add end-to-end contract tests**

```python
def test_request_tool_event_activity_panel_and_reconnect_share_correlation() -> None:
    service, published = running_isolated_service()
    plan = service.route_request("find my CV", "turn-9", "desktop")
    service.consume_event({"type": "tool.returned", "correlation_id": "turn-9",
                           "payload": {"tool": "search_files", "result": "CV.pdf"}})
    snap = service.snapshot()
    assert plan.primary_panel == "files"
    assert any(p["panel_id"] == "files" and p["correlation_id"] == "turn-9"
               for p in snap["panels"])
    assert any(a["correlation_id"] == "turn-9" for a in snap["activities"])
    assert snap["revision"] == max(e["payload"]["revision"] for e in published)


def test_probe_failure_recovery_is_bounded_and_opens_circuit() -> None:
    attempts = []
    manager = failing_recoverable_health_manager(attempts)
    first = manager.check("browser", force=True)
    second = manager.check("browser", force=True)
    assert len(attempts) <= 2
    assert second.status in {ToolHealthState.UNAVAILABLE, ToolHealthState.ERROR}
    assert circuit_breaker.is_open("browser") is True


def test_malformed_events_and_rapid_panel_commands_do_not_escape() -> None:
    service = isolated_workspace_service()
    for event in (None, {}, {"type": 7}, {"type": "tool.failed", "payload": object()}):
        service.consume_event(event)
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda i: service.panel_action("activity", "toggle", {}, str(i), ""), range(200)))
    assert service.snapshot()["panels"][0]["state"] in {state.value for state in PanelState}
```

- [ ] **Step 2: Run the complete focused workspace suite**

Run:

```bash
python -m pytest tests/test_workspace_models.py tests/test_workspace_manager.py tests/test_workspace_intent_router.py tests/test_workspace_activity.py tests/test_workspace_tool_health.py tests/test_workspace_search.py tests/test_workspace_api.py tests/test_workspace_frontend.py tests/test_workspace_execution_bridge.py -q
```

Expected: PASS.

- [ ] **Step 3: Run relevant ZENO regression suites**

Run:

```bash
python -m pytest tests/test_phase21_runtime.py tests/test_phase22_stability.py tests/test_build_execution.py tests/test_project_activity.py tests/test_universal_tool_registry.py tests/test_universal_search.py tests/test_production_reality.py tests/test_visual_performance.py tests/test_website_builder_mode.py -q
```

Expected: PASS. If an unrelated environment-dependent test is skipped, record the exact skip reason; failures are not converted into skips.

- [ ] **Step 4: Run syntax, import, formatting, and collision checks**

Run:

```bash
python -m compileall -q reyes_agent/workspace
python -c "from reyes_agent.workspace import get_workspace_service; print(get_workspace_service().snapshot()['revision'])"
git diff --check
git status --short
```

Expected: compile/import commands exit 0, `git diff --check` has no output, and status lists only the intended task changes plus the pre-existing unrelated owner changes.

- [ ] **Step 5: Perform verification-before-completion and commit final test refinements**

Re-run the focused workspace suite after the last code change, capture the exact pass/fail/skip totals, and inspect the branch diff against its base for voice, TTS, media, Spotify, package, presentation, security, and unrelated files. None may appear.

```bash
git add tests/test_workspace_manager.py tests/test_workspace_activity.py tests/test_workspace_tool_health.py tests/test_workspace_api.py tests/test_workspace_frontend.py
git commit -m "test(workspace): verify orchestration and recovery"
```

Expected: no commit is created when there are no final test refinements; verification evidence still appears in the final handoff.
