# ZENO Proactive Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Consolidate ZENO's existing heartbeat and proactive loops into one quiet, durable, permission-safe heartbeat service with a shared inbox and workspace/phone projections.

**Architecture:** Add focused proactive models, persistence, registry, delivery, and engine modules while retaining the existing scheduler, worker pool, event bus, notification delivery, agent turn, action policy, and workspace authorities. Convert heartbeat.py into the public compatibility facade and remove proactive.py's independent schedule; registered checks and event changes become bounded CheckResult records that flow through deterministic importance and notice delivery.

**Tech Stack:** Python 3.11 dataclasses, SQLite, FastAPI, pytest, vanilla ES modules, existing Event Bus/SSE, existing ZENO worker pool and scheduler.

**Spec:** docs/superpowers/specs/2026-09-03-zeno-proactive-heartbeat-design.md

## Global Constraints

- Do not add React, Dockview, Electron, external schedulers, or package dependencies.
- Do not change cybersecurity, surveillance, RF, network-security, penetration-testing, or security-agent functionality.
- Retain agent.run_agent, BackgroundScheduler, worker pool, action policy, confirmation, notifications, Event Bus, and workspace as the sole existing authorities.
- Store only bounded safe proactive data; never persist secrets, raw prompts, memory text, tool inputs, or private message bodies.
- A proactive turn is owner-unverified and cannot cause consequential tool execution.
- Preserve the pre-existing dirty package, presentation, provider, voice, web, worker-pool, and untracked owner changes.
- Implement with test-driven development and use apply_patch for all repository edits.
- Physical resource claims require a real desktop measurement; deterministic tests must not claim FPS, RAM, or voice latency.

---

### Task 1: Add durable proactive records, preferences, and SQLite migration

**Files:**
- Create: reyes_agent/proactive_models.py
- Create: reyes_agent/proactive_store.py
- Test: tests/test_proactive_store.py

**Interfaces:**
- Produces Importance, DeliveryState, VoicePolicy, PresenceState, OverlapPolicy enums.
- Produces immutable ScheduledCheck, CheckResult, ProactiveNotice, and ProactiveSettings records.
- Produces ProactiveStore(path: Path) with migrate(), load_settings(), save_settings(), load_checks(), upsert_check(), claim_due(), record_check_result(), upsert_notice(), list_notices(), transition_notice(), and diagnostics().

- [ ] **Step 1: Write failing migration and lifecycle tests**

    def test_store_migrates_legacy_check_and_notice_rows(tmp_path: Path) -> None:
        store = ProactiveStore(tmp_path / "state.db")
        store.migrate()
        store.upsert_check(ScheduledCheck("calendar", "Calendar", True, 300, 20, 30,
                                          OverlapPolicy.SKIP, "hold", "calendar_due"))
        assert store.load_checks()[0].handler_id == "calendar_due"
        notice = store.upsert_notice(CheckResult.changed("calendar", "meeting", "due",
                                                          "Meeting in ten minutes"))
        assert notice.delivery_state is DeliveryState.NEW

    def test_notice_dedupe_updates_one_record_and_state_transitions_are_valid(tmp_path: Path) -> None:
        store = ProactiveStore(tmp_path / "state.db"); store.migrate()
        result = CheckResult.changed("battery", "laptop", "low", "Battery at 15 percent")
        first = store.upsert_notice(result); second = store.upsert_notice(result)
        assert first.id == second.id and second.count == 2
        assert store.transition_notice(first.id, DeliveryState.HELD).delivery_state is DeliveryState.HELD
        with pytest.raises(ValueError):
            store.transition_notice(first.id, DeliveryState.NEW)

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: python -m pytest tests/test_proactive_store.py -q
Expected: FAIL because proactive_models and proactive_store do not exist.

- [ ] **Step 3: Implement records and atomic migration**

Use a schema version table in the existing heartbeat state database. Migrate legacy check_state, notices, and settings without deleting old rows. Scheduled checks have persisted last-run, success/failure, next-due, consecutive-failure, and fingerprint data. Persist delivery states NEW, HELD, SURFACED, SEEN, ACKNOWLEDGED, DISMISSED, and EXPIRED. Use source + subject + condition as the normalized dedupe key, constrain text fields to 500 characters, JSON facts to 4 KiB, at most 500 retained notices, and last 20 records for each diagnostic list. Reject invalid state transitions rather than changing the record.

- [ ] **Step 4: Run store tests**

Run: python -m pytest tests/test_proactive_store.py tests/test_phase5_power.py -q
Expected: PASS.

- [ ] **Step 5: Commit the durable model layer**

    git add reyes_agent/proactive_models.py reyes_agent/proactive_store.py tests/test_proactive_store.py
    git commit -m "feat(proactive): persist typed checks and notices"

### Task 2: Build the registered-check engine on ZENO's existing scheduler and worker pool

**Files:**
- Create: reyes_agent/proactive_checks.py
- Create: reyes_agent/heartbeat_engine.py
- Modify: reyes_agent/heartbeat.py
- Modify: reyes_agent/proactive.py
- Test: tests/test_heartbeat_engine.py

**Interfaces:**
- Produces ScheduledCheckRegistry.register(check: ScheduledCheck, handler: Callable[[CheckContext], CheckResult]).
- Produces HeartbeatEngine(store, registry, scheduler, worker_pool, clock) with start(), tick(), pause(), resume(), run_event(event), and diagnostics().
- heartbeat.start_background() starts get_heartbeat_engine() once.
- proactive.start_background() delegates to heartbeat.start_background() and owns no scheduled job.

- [ ] **Step 1: Write failing due, overlap, restart-stagger, and failure-isolation tests**

    def test_due_check_runs_once_and_skip_policy_never_overlaps(tmp_path: Path) -> None:
        handler = BlockingHandler()
        engine = seeded_engine(tmp_path, handler, policy=OverlapPolicy.SKIP)
        engine.tick(now=100); engine.tick(now=101)
        assert handler.calls == 1
        assert engine.diagnostics()["skipped_overlap"] == 1

    def test_restart_restores_due_state_with_noncritical_stagger(tmp_path: Path) -> None:
        engine = seeded_engine(tmp_path, lambda ctx: CheckResult.no_change("system"))
        engine.tick(now=1000)
        restored = seeded_engine(tmp_path, lambda ctx: CheckResult.no_change("system"))
        assert restored.next_due("system") > 1000
        assert restored.next_due("system") - 1000 <= restored.startup_stagger_s

    def test_one_failed_handler_records_failure_without_stopping_other_due_checks(tmp_path: Path) -> None:
        engine = engine_with_handlers(tmp_path, failing_handler, succeeding_handler)
        report = engine.tick(now=500)
        assert report["failed"] == 1 and report["completed"] == 1
        assert engine.diagnostics()["alive"] is True

- [ ] **Step 2: Run the test and confirm the missing-engine failure**

Run: python -m pytest tests/test_heartbeat_engine.py -q
Expected: FAIL because HeartbeatEngine is undefined.

- [ ] **Step 3: Implement one quiet engine**

Keep BackgroundScheduler as the only scheduler and the worker pool as the only executor. The scheduled tick only selects due checks and submits finite jobs at background priority. Each check has a timeout, one active claim, explicit SKIP/COALESCE/QUEUE_ONE behavior, and a final store update. First startup assigns deterministic stagger offsets to enabled noncritical checks. Do not run a model for any typed check. Convert existing battery, session, morning, calendar, and Dream eligibility code into registered handlers. HeartbeatEngine must return immediately when paused or nothing is due. Delete no legacy user checks; migrate them as disabled model-synthesis checks until explicitly enabled.

- [ ] **Step 4: Run engine and scheduler regressions**

Run: python -m pytest tests/test_heartbeat_engine.py tests/test_reenabled_performance_features.py tests/test_phase21_runtime.py -q
Expected: PASS.

- [ ] **Step 5: Commit engine consolidation**

    git add reyes_agent/proactive_checks.py reyes_agent/heartbeat_engine.py reyes_agent/heartbeat.py reyes_agent/proactive.py tests/test_heartbeat_engine.py
    git commit -m "feat(proactive): consolidate heartbeat scheduling"

### Task 3: Add deterministic importance, presence, quiet/focus policy, and delivery adapter

**Files:**
- Create: reyes_agent/proactive_delivery.py
- Modify: reyes_agent/notifications.py
- Modify: reyes_agent/heartbeat_engine.py
- Test: tests/test_proactive_delivery.py

**Interfaces:**
- Produces ProactiveImportanceEvaluator.evaluate(result, settings) -> Importance.
- Produces PresenceResolver.resolve() -> PresenceState.
- Produces DeliveryPolicy.decide(notice, presence, conversation_state, settings) -> DeliveryDecision.
- Produces ProactiveDeliveryAdapter.deliver(notice) -> DeliveryState.

- [ ] **Step 1: Write failing policy tests**

    def test_away_or_quiet_normal_notice_is_held_but_urgent_respects_owner_policy() -> None:
        policy = DeliveryPolicy(ProactiveSettings(quiet_hours_start=22, quiet_hours_end=7))
        normal = sample_notice(Importance.NOTIFY)
        urgent = sample_notice(Importance.URGENT)
        assert policy.decide(normal, PresenceState.AWAY, "IDLE", hour=23).state is DeliveryState.HELD
        assert policy.decide(urgent, PresenceState.AWAY, "IDLE", hour=23).voice is VoicePolicy.VOICE_NOW

    def test_active_conversation_queues_noncritical_notice_and_return_surfaces_one_digest() -> None:
        adapter = seeded_delivery_adapter()
        held = adapter.record(sample_notice(Importance.NOTIFY), PresenceState.ACTIVE, "THINKING")
        assert held.delivery_state is DeliveryState.HELD
        digest = adapter.owner_return(PresenceState.ACTIVE)
        assert digest["count"] == 1 and digest["voice"] is VoicePolicy.VISUAL_ONLY

    def test_deterministic_result_never_calls_model_or_duplicates_notification_delivery(monkeypatch) -> None:
        adapter = seeded_delivery_adapter()
        monkeypatch.setattr("reyes_agent.agent.run_agent", lambda *_a, **_k: pytest.fail("model called"))
        first = adapter.record(sample_notice(Importance.INBOX), PresenceState.ACTIVE, "IDLE")
        second = adapter.record(sample_notice(Importance.INBOX), PresenceState.ACTIVE, "IDLE")
        assert first.id == second.id and adapter.deliveries == 1

- [ ] **Step 2: Run delivery tests and confirm the missing-policy failure**

Run: python -m pytest tests/test_proactive_delivery.py -q
Expected: FAIL because proactive_delivery does not exist.

- [ ] **Step 3: Implement deterministic delivery**

Use activity_monitor idle signals, existing dashboard presence, and conversation_state only. Map existing notification settings rather than replacing them. Always store proactive notice first; the adapter invokes notifications.notify only after delivery policy permits it and only once for a dedupe revision. Implement pause, quiet hours, priority-only, DND, timed focus, away holding, active-conversation deferral, owner-return digest, and configurable urgent voice policy. Voice uses current notification/TTS delivery only; a failed delivery retains the notice. Keep notifications.py public API compatible and do not store proactive facts in its generic body field.

- [ ] **Step 4: Run delivery and notification regressions**

Run: python -m pytest tests/test_proactive_delivery.py tests/test_phase5_power.py tests/test_everyday.py tests/test_response_engine.py -q
Expected: PASS.

- [ ] **Step 5: Commit delivery policy**

    git add reyes_agent/proactive_delivery.py reyes_agent/notifications.py reyes_agent/heartbeat_engine.py tests/test_proactive_delivery.py
    git commit -m "feat(proactive): deliver quiet deduplicated notices"

### Task 4: Keep proactive turns inside ZENO's normal core and permission boundary

**Files:**
- Create: reyes_agent/turn_context.py
- Modify: reyes_agent/agent.py
- Modify: reyes_agent/tools/__init__.py
- Modify: reyes_agent/action_policy.py
- Test: tests/test_proactive_turns.py

**Interfaces:**
- Produces TurnContext.for_source(source, proactive=False, user_present=True, owner_authenticated=False).
- Extends run_agent(history, ..., turn_context: TurnContext | None = None).
- Extends Tool with proactive_allowed: bool = False and keeps existing registry calls compatible.
- Produces run_proactive_synthesis(context: TurnContext, facts: Sequence[dict]) -> str.

- [ ] **Step 1: Write failing shared-core and policy tests**

    def test_proactive_synthesis_uses_existing_agent_with_unverified_heartbeat_context(monkeypatch) -> None:
        received = {}
        monkeypatch.setattr(agent_module, "_run_agent_impl", lambda history, **kwargs: received.update(kwargs) or "Brief")
        run_proactive_synthesis(TurnContext.for_source("HEARTBEAT", proactive=True,
                                                       user_present=False, owner_authenticated=False),
                                [{"source": "calendar", "summary": "Meeting soon"}])
        assert received["action_source"] == "heartbeat"
        assert received["owner_authenticated"] is False

    def test_proactive_context_cannot_run_consequential_or_nonallowed_tool() -> None:
        with use_turn_context(TurnContext.for_source("HEARTBEAT", proactive=True,
                                                     user_present=False, owner_authenticated=False)):
            assert evaluate("send_message", {"destination": "Ada", "message": "Hi"}).effect is PolicyEffect.DENY
            assert run_tool(test_tool("safe_read", proactive_allowed=False), {}) == "Denied: proactive use is not allowed."

    def test_bounded_facts_are_the_only_synthesis_input() -> None:
        prompt = proactive_prompt([{"summary": "x" * 2000, "token": "secret"}])
        assert len(prompt) <= 3000 and "secret" not in prompt

- [ ] **Step 2: Run tests and confirm missing context/metadata failures**

Run: python -m pytest tests/test_proactive_turns.py -q
Expected: FAIL because TurnContext and proactive_allowed do not exist.

- [ ] **Step 3: Implement the one-core bridge**

Add immutable TurnContext without changing existing text, voice, phone, or panel routing signatures. Agent.run_agent maps context to its existing action source and owner-authentication arguments. Tool registration defaults proactive_allowed to false; only explicitly safe, read-only registered tools may be candidates. The existing action policy denies all proactive consequential calls regardless of tool metadata. Model synthesis is optional, rate-limited by ProactiveSettings, has bounded factual input, and returns an inbox candidate rather than an action.

- [ ] **Step 4: Run policy and agent regressions**

Run: python -m pytest tests/test_proactive_turns.py tests/test_smart_autonomy_policy.py tests/test_agent.py -q
Expected: PASS.

- [ ] **Step 5: Commit core and policy integration**

    git add reyes_agent/turn_context.py reyes_agent/agent.py reyes_agent/tools/__init__.py reyes_agent/action_policy.py tests/test_proactive_turns.py
    git commit -m "feat(proactive): route heartbeat through shared core safely"

### Task 5: Project one proactive inbox through workspace, desktop, and phone

**Files:**
- Modify: reyes_agent/workspace/defaults.py
- Modify: reyes_agent/workspace/service.py
- Modify: reyes_agent/workspace/api.py
- Modify: reyes_agent/panels.py
- Modify: reyes_agent/static/panels/renderers.js
- Modify: reyes_agent/static/panels/manager.js
- Test: tests/test_proactive_workspace.py

**Interfaces:**
- Adds PanelDefinition("proactive", "Proactive Center", "builtin:proactive").
- Adds WorkspaceService.proactive_snapshot() and bounded notice actions acknowledge, dismiss, why, pause, resume.
- Exposes loopback endpoints GET /api/workspace/proactive and POST /api/workspace/proactive/{notice_id}/{action}.
- Exposes GET /api/panels/proactive for existing panel renderer data.

- [ ] **Step 1: Write failing workspace/panel projection tests**

    def test_proactive_panel_is_registered_and_uses_shared_panel_metadata() -> None:
        registry = default_panel_registry()
        definition = registry.get("proactive")
        assert definition is not None and "minimize" in definition.supported_actions
        assert definition.supported_surfaces == ("desktop", "mini", "phone")

    def test_proactive_api_returns_redacted_shared_snapshot_and_action_is_loopback_only() -> None:
        local, service = proactive_client(("127.0.0.1", 5000))
        remote, _ = proactive_client(("203.0.113.9", 5000))
        assert "held" in local.get("/api/workspace/proactive").json()
        assert remote.post("/api/workspace/proactive/n-1/acknowledge").status_code == 403
        assert "token" not in repr(local.get("/api/workspace/proactive").json())

    def test_proactive_renderer_does_not_open_a_second_event_stream() -> None:
        source = (STATIC / "panels" / "renderers.js").read_text(encoding="utf-8")
        assert "proactive" in source and "new EventSource" not in source[source.index("proactive"):]

- [ ] **Step 2: Run tests and confirm the panel/API failures**

Run: python -m pytest tests/test_proactive_workspace.py -q
Expected: FAIL because proactive panel and endpoints are absent.

- [ ] **Step 3: Implement one bounded projection**

Add one registered builtin panel and reuse WorkspaceService revision events. Render NOW, NEEDS ATTENTION, HELD, COMPLETED, and DISMISSED from the same store snapshot. Acknowledge/dismiss/why/pause/resume actions are allowlisted and loopback-only. Manager.js reuses its existing host and listener; renderer updates do not mount a second manager, scheduler, or EventSource. Phone consumes the compact workspace projection rather than a new remote notice path. Exclude facts_json and any private content from all public rows.

- [ ] **Step 4: Run workspace/frontend tests**

Run: python -m pytest tests/test_proactive_workspace.py tests/test_workspace_api.py tests/test_workspace_frontend.py tests/test_panels.py -q
Expected: PASS.

- [ ] **Step 5: Commit the shared inbox projection**

    git add reyes_agent/workspace/defaults.py reyes_agent/workspace/service.py reyes_agent/workspace/api.py reyes_agent/panels.py reyes_agent/static/panels/renderers.js reyes_agent/static/panels/manager.js tests/test_proactive_workspace.py
    git commit -m "feat(proactive): project inbox through workspace panels"

### Task 6: Integrate Dream Mode, event-driven checks, commands, and diagnostics

**Files:**
- Modify: reyes_agent/dream_mode.py
- Modify: reyes_agent/heartbeat_engine.py
- Modify: reyes_agent/proactive.py
- Modify: reyes_agent/web.py
- Modify: reyes_agent/workspace/intent_router.py
- Test: tests/test_proactive_integration.py

**Interfaces:**
- Event Bus callbacks call HeartbeatEngine.run_event(event) without blocking publishers.
- Explicit commands pause proactive mode, resume it, set timed focus, and show proactive inbox.
- GET /api/diagnostics/proactive reports only safe counters and timing.

- [ ] **Step 1: Write failing event, Dream, command, and diagnostic tests**

    def test_event_change_creates_notice_without_waiting_for_poll() -> None:
        engine = seeded_engine()
        engine.run_event({"type": "download.completed", "payload": {"name": "report.pdf"}})
        assert engine.store.list_notices()[0].source == "downloads"

    def test_dream_yields_immediately_when_user_work_returns(monkeypatch) -> None:
        engine = seeded_engine()
        monkeypatch.setattr("reyes_agent.activity_monitor._idle_seconds", lambda: 0)
        assert engine.run_registered("dream_maintenance").state == "DEFERRED"

    def test_pause_resume_and_focus_do_not_block_direct_chat(client) -> None:
        assert client.post("/api/proactive/pause").json()["enabled"] is False
        assert client.post("/api/chat", json={"message": "hello"}).status_code == 200
        assert client.post("/api/proactive/resume").json()["enabled"] is True

    def test_proactive_diagnostics_excludes_notice_bodies(client) -> None:
        payload = client.get("/api/diagnostics/proactive").json()
        assert {"checks_registered", "held_notices", "last_tick_ms"} <= set(payload)
        assert "body" not in repr(payload)

- [ ] **Step 2: Run tests and confirm integration failures**

Run: python -m pytest tests/test_proactive_integration.py -q
Expected: FAIL because event dispatch, commands, and diagnostics are absent.

- [ ] **Step 3: Implement integration without new loops**

Subscribe once through the existing Event Bus service lifecycle, queue event handling through the managed worker pool, and ignore heartbeat/proactive events to prevent recursion. Register Dream maintenance as a low-priority engine handler with a continuation predicate that checks idle, active conversation, and load. Convert existing proactive direct notice calls into CheckResult paths. Add only explicit bounded command grammar and protected APIs; direct chat uses its unchanged turn path. Diagnostics returns counts, status, bounded failure codes, lease/pause/focus state, due time, and tick duration only.

- [ ] **Step 4: Run integration and existing runtime tests**

Run: python -m pytest tests/test_proactive_integration.py tests/test_reenabled_performance_features.py tests/test_phase21_runtime.py tests/test_phase22_stability.py -q
Expected: PASS.

- [ ] **Step 5: Commit integration**

    git add reyes_agent/dream_mode.py reyes_agent/heartbeat_engine.py reyes_agent/proactive.py reyes_agent/web.py reyes_agent/workspace/intent_router.py tests/test_proactive_integration.py
    git commit -m "feat(proactive): wire events dream and owner controls"

### Task 7: Stress, restart, and regression verification

**Files:**
- Create: tests/test_proactive_stress.py
- Modify only if a failing test demonstrates a defect in Tasks 1-6.

**Interfaces:**
- Produces run_proactive_stress(seed: int) -> dict with operations, errors, notices, active_handles, and database_valid.
- Produces no new runtime authority.

- [ ] **Step 1: Write deterministic stress and restart tests**

    def test_stress_dedupes_events_and_keeps_handles_bounded(tmp_path: Path) -> None:
        report = run_proactive_stress(tmp_path, seed=7, events=1000, ticks=500, restarts=100)
        assert report["errors"] == 0
        assert report["active_handles"] <= 1
        assert report["notice_rows"] <= 500
        assert report["database_valid"] is True

    def test_restart_does_not_fire_every_check_at_once(tmp_path: Path) -> None:
        report = run_restart_simulation(tmp_path, checks=40)
        assert report["first_tick_started"] < 8
        assert report["eventual_started"] == 40

- [ ] **Step 2: Run tests and confirm the missing stress helper failure**

Run: python -m pytest tests/test_proactive_stress.py -q
Expected: FAIL because the stress helpers do not exist.

- [ ] **Step 3: Implement test-only deterministic helpers and fix proved defects**

Use a fake monotonic clock, in-memory scheduler/worker handles, and a temporary SQLite store. Exercise 1,000 repeated state-change events, 500 due ticks, 250 overlap collisions, 250 pause/resume/focus changes, and 100 restart/load cycles. Assert no active handler leak, no duplicate delivery, valid SQLite integrity_check, bounded notice count, and staggered restart. Do not add sleep-based tests.

- [ ] **Step 4: Run the focused proactive suite**

Run: python -m pytest tests/test_proactive_store.py tests/test_heartbeat_engine.py tests/test_proactive_delivery.py tests/test_proactive_turns.py tests/test_proactive_workspace.py tests/test_proactive_integration.py tests/test_proactive_stress.py -q
Expected: PASS.

- [ ] **Step 5: Run relevant ZENO regressions and final checks**

Run:
    python -m pytest tests/test_smart_autonomy_policy.py tests/test_phase5_power.py tests/test_everyday.py tests/test_workspace_api.py tests/test_workspace_frontend.py tests/test_panels.py tests/test_phase21_runtime.py tests/test_phase22_stability.py tests/test_reenabled_performance_features.py -q
    python -m compileall -q reyes_agent
    git diff --check
    git status --short

Expected: all selected tests pass, compileall exits 0, git diff --check has no output, and status contains only proactive changes plus pre-existing owner changes.

- [ ] **Step 6: Commit only final defect fixes and verify before completion**

    git add reyes_agent tests/test_proactive_*.py
    git commit -m "test(proactive): verify durable quiet heartbeat"

Do not create this commit when no final defect fix exists. Before a completion claim, read and follow superpowers:verification-before-completion, rerun the focused suite after the final code change, and report actual test output, stress counts, and desktop-measurement limitations.

