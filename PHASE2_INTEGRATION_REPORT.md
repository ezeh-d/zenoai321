# ZENO Phase 2 Integration Report — Steps 6–10

Date: 2026-08-10
Status: **READY WITH LIMITATIONS**

## Architecture overview

The existing `ZenoKernel`, worker pool, Event Bus, permission engine, agent
runtime, browser runtime, voice pipeline and Living Memory remain the
authorities. Phase 2 adds lazy adapters and one observable task trace; it does
not add another scheduler, Event Bus, microphone stream or permanent agent.

```text
User goal
  -> understand
  -> relevant session/Living Memory/Mem0 retrieval
  -> existing planner and agent router
  -> explicit autonomy classification
  -> existing tool gate
       -> MCP manager (allowlisted external tools)
       -> TOSIN/Open Interpreter (coding specialist)
       -> local Windows device manager
  -> observe actual result
  -> verify evidence
  -> bounded recovery (maximum 2 recorded attempts)
  -> selective memory write
  -> response
```

The health API is generated on demand. Optional modules expose honest
`STANDBY`, `DISABLED`, `DEGRADED` or `FAILED` states and do not poll.

## Files created

- `reyes_agent/memory/`: policy, privacy, retrieval, Mem0 adapter,
  consolidation and manager.
- `reyes_agent/wake/`: one-stream audio contract, VAD, state machine,
  openWakeWord adapter and engine.
- `reyes_agent/coding_system/`: workspace boundary, command policy,
  Open Interpreter client and redacted result parser.
- `reyes_agent/tools/mcp/`: registry, discovery, official SDK client,
  permissions, health and manager.
- `reyes_agent/devices/`: protocol, capabilities, base device, local Windows
  adapter, manager and health.
- `reyes_agent/autonomy.py`, `execution_lifecycle.py`, `system_health.py`.
- Agent-facing tool modules for coding, MCP and devices.
- `tests/test_phase2_foundations.py` and its local MCP protocol fixture.

## Files modified

`.env.example`, `requirements.txt`, `ROADMAP.md`, `AGENT.md`, and the existing
agent, kernel, permission, task, tool, web and Mini Orb frontend integration
points. Phase 1's deterministic computer fallback was adjusted only to stop a
failed/queued tool result from being presented as success.

## Dependencies

- Added and installed: `mcp>=2.0` (official Python SDK).
- Already installed: `openwakeword`; it remains lazy.
- Optional/not installed: `mem0ai`, Open Interpreter executable.
- No MCP server, wake model or external repository is downloaded
  automatically.

## Environment variables

All have safe off/empty defaults and are documented in `.env.example`:

- `ZENO_MEM0_ENABLED`, `ZENO_MEM0_MODE`, `ZENO_MEM0_USER_ID`,
  `ZENO_MEM0_RETRIEVAL_TIMEOUT_S`, optional `MEM0_API_KEY`.
- `ZENO_WAKE_MODEL_PATH`, `ZENO_WAKE_SENSITIVITY`,
  `ZENO_WAKE_VAD_THRESHOLD`, `ZENO_WAKE_COOLDOWN_S`,
  `ZENO_WAKE_REQUIRED_HITS`, `ZENO_WAKE_NOISE_SUPPRESSION`.
- `ZENO_OPEN_INTERPRETER_ENABLED`, `ZENO_OPEN_INTERPRETER_COMMAND`,
  `ZENO_OPEN_INTERPRETER_TIMEOUT_S`, `ZENO_CODING_WORKSPACES`.
- `ZENO_MCP_ALLOWLIST`; server definitions live in the private vault, not Git.

## Working features

- Selective, categorized, bounded session and durable memory policy.
- Relevant memory retrieval before planning with Living Memory fallback.
- Preview-first, non-deleting legacy-to-Mem0 migration.
- Single-stream local wake scoring, VAD, cooldown and deterministic states.
- Permission-gated, finite coding specialist with output/RAM limit.
- Real MCP 2.0 stdio discovery and tool call, read-only annotation gate,
  allowlist, health, concurrency limit and secret redaction.
- One local Windows device interface over deterministic/agentic Phase 1 paths.
- Autonomy levels 0–4, universal capability enforcement and hard-blocked
  financial execution.
- Central health API and failure isolation.

## Test and measurement record

- Phase 1 focused tests: 26/26 passed after the deterministic-success fix.
- Phase 2 tests: 26/26 passed, including a real official-SDK MCP subprocess
  and the startup-stage race regression.
- Whole repository: final 41/41 standalone files passed in 169.7 seconds,
  including the official MCP 2.0 compatibility and subprocess cleanup test.
- Python compilation, `git diff --check` and `pip check`: passed.
- Live desktop cold staged backend: 2,612.7 ms before; 2,600.9 ms final
  post-change measurement, with zero startup errors.
- Live Playwright: cold open/navigation 9,643.5 ms; rendered body read 168 ms;
  clean browser close succeeded.
- Live Gemini typed turn: 14,772.8 ms, exact requested reply, no tool call.
  The resulting ElevenLabs generation completed in 5,791.6 ms.
- Normal-development workload, 10-second process-tree sample: ZENO 10.078%
  CPU, WebView2 8.945%, WebView2 GPU 4.609%, 607.3 MiB, 189 threads across 11
  processes. System pressure was 83.3% CPU and 89.4% RAM.
- Runtime health: four worker threads alive, queue depth zero, 14/14 agents
  healthy and zero agent workers active on demand, browser closed. The live
  startup audit found and fixed an out-of-order stage race which could leave
  status at `executive_ready` even though all services were ready.

## Known limitations and incomplete deployment

- A trusted custom `ZENO` openWakeWord ONNX model has not been supplied. The
  existing VAD-bounded Deepgram wake-phrase fallback remains necessary, so
  idle wake recognition is not fully local yet.
- Mem0 is integrated but not installed/enabled; Living Memory is the active
  tested backend. Mem0 OSS also needs an explicitly chosen model/embedder for
  a privacy-conscious production deployment.
- Open Interpreter is integrated but not installed/enabled. TOSIN's existing
  permission-gated file and command tools are the live fallback.
- MCP is operational and locally tested, but there are no owner-reviewed
  production servers in the allowlist.
- Claude's Phase 1 external SDKs are mostly disabled/uninstalled. Existing
  ZENO fallbacks are functional; their external backends are not claimed live.
- The normal-workload WebView2 visual cost remains above the desired isolated
  target. Phase 2 added no visual loop, but this measurement prevents a claim
  that overall ZENO is already below the target.
- After the provider/TTS run, system RAM reached roughly 94%. The server probe
  recorded 211–1,314 ms event-loop heartbeat delays and ten status requests
  ranged from 36 ms to 16.8 seconds. A live stack capture showed the main
  event loop idle in Windows IOCP, all four ZENO workers idle on an empty
  queue, and no lock/future/provider call on the event loop. This supports
  machine-wide paging/scheduling pressure rather than a captured Python
  deadlock, but it does not prove isolated ZENO performance is acceptable.
- No one-hour memory measurement or five-minute isolated A/B run was performed
  in this phase. Long-duration claims are therefore not made.
