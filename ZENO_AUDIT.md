# ZENO Full-System Audit

Date: 2026-08-17

## Outcome

ZENO remains one native operating assistant rather than a collection of
third-party runtimes. The authoritative path is `main.py` ->
`reyes_agent.desktop_app` -> loopback `reyes_agent.web` -> `ZenoKernel` -> the
existing bounded scheduler/worker pool, Event Bus, agent runtime, voice,
browser, memory, permission, and tool authorities.

The maintained baseline passed 960/960 tests before this upgrade. This pass
found and repaired four concrete defects and implemented the one wholly absent
phase from the supplied specification: the evidence-led Opportunity Engine.

## Repository map

| Area | Authority | Notes |
|---|---|---|
| Desktop host | `reyes_agent/desktop_app.py` | PySide6/pywebview host, Mini Orb, staged backend |
| HTTP/SSE/WebSocket | `reyes_agent/web.py` | loopback desktop API plus authenticated phone routes |
| Lifecycle | `reyes_agent/kernel.py` | singleton, three stages, ordered shutdown |
| Work | `worker_pool.py`, `scheduler.py`, `task_engine.py` | reusable workers, bounded queues/deadlines |
| Brain | `agent.py`, `cognition.py`, `model_router.py`, `provider.py` | one provider-independent agent loop |
| Agents | `agent_runtime.py`, `agent_teams.py`, `agents/registry.py` | lazy specialists, bounded depth/fan-out |
| Tools/policy | `tools/__init__.py`, `permissions.py`, `security/` | one execution and confirmation boundary |
| Voice | `audio/manager.py`, `voice/`, `wake/` | one audio owner and deterministic state machine |
| Browser | `browser/`, `browser_runtime.py` | one persistent Playwright authority with recovery |
| Windows | `computer/`, `executors/desktop.py` | API/UIA/Win32/deterministic/visual fallback ladder |
| Memory | `memory/`, `living_memory.py` | bounded session + durable fallback + optional Mem0 |
| Learning | `skills/`, `workflow_engine.py`, `learning_mode.py` | approved skills and demonstration replay |
| Health | `system_health.py`, `performance_monitor.py`, `health/` | cached health, heartbeat, freezes, queues |
| Opportunity | `opportunity.py`, `tools/opportunity_tools.py` | evidence types, expiry, transparent score |

Compatibility launchers and old folders remain on disk because deleting them
would be a destructive migration. They do not replace the authoritative
`reyes_agent` runtime.

## Confirmed findings and repairs

1. **Opportunity Engine absent.** Added deterministic scoring across all nine
   requested factors, dated FACT/ESTIMATE/ASSUMPTION/OPINION/EXPERIMENT_RESULT
   evidence, expiry revalidation, SQLite persistence, guarded deletion, Event
   Bus events, lazy tools, routing, capability registration, and existing-agent
   component mapping.
2. **Approved skill context silently lost.** `agent.run_agent` appended skill
   context before `system` was assigned; a broad exception hid the
   `UnboundLocalError`. Context is now buffered and appended after prompt and
   memory assembly. A model-boundary regression proves delivery.
3. **Execution diagnostics overclaimed success.** `ExecutionTrace` treated
   every normal return as verified. It now reuses the authoritative result
   classifier and distinguishes failed, pending, returned/unverified, and
   completed/verified evidence.
4. **Plugin scanning was an import-time side effect.** Importing the global
   registry scanned manifests and could execute approved sandboxes. Plugins
   now load once, explicitly, only for admin/extended requests.
5. **Notification polling occupied a general worker while WinRT worked.** The
   existing dedicated WinRT loop is now submitted asynchronously; the same
   non-overlap gate, timeout, backoff, cleanup, and shutdown remain.

## Other audit results

- No `.env`, private key, browser profile, generated audio, log, or cache is
  tracked. Secret-like test strings occur only in redaction/security tests.
- No new Event Bus, provider runtime, browser scheduler, agent supervisor, or
  microphone loop was introduced.
- Python compilation, `pip check`, JavaScript syntax, and `git diff --check`
  pass.
- The explicit marker scan found exception isolation, protocols, and honest
  cross-runtime markers—not a newly discovered fake success implementation.
- Claude's concurrent presentation and single-instance changes were preserved
  and not overwritten.

## Honest limits

- A custom, consented ZENO wake model and owner voice corpus are not supplied.
- LiveKit, Agent Framework, Browser Use, Open Interpreter, Mem0 and other
  optional stacks remain lazy/unavailable unless health checks pass.
- Arbitrary cloud reasoning cannot be guaranteed in 1.5 seconds. Cached voice
  acknowledgements help perceived latency while real latency stays observable.
- Opportunity scores compare supplied evidence; they are not revenue
  forecasts, guarantees, financial advice, or permission to transact.

See the companion V2 architecture, capability, security, test, performance,
GitHub-integration, and money-engine reports in the repository root.
