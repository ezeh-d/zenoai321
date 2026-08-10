# ZENO Phase 3 — Advanced Capabilities Handoff

Date: 2026-08-10
Status: **FOUNDATION READY; EXTERNAL CAPABILITIES DISABLED OR PARTIAL**

## Architecture before vs after

Before Phase 3, ZENO already had the important authorities: one `ZenoKernel`,
bounded worker pool, one scheduler, one Event Bus, one provider seam with
fallback/circuit breaking, Living Memory/Mem0 policy, one microphone owner,
verified workflow teaching/replay, permissions, Playwright/UIA computer
control, specialist agents and on-demand health.

Phase 3 does not duplicate them. It adds:

```text
voice/text/device event
  -> existing managed agent turn
  -> Living Memory (always) + episodic provider (only for relevant explicit requests)
  -> existing cognition/model route
       -> capability-aware gateway facade
       -> Gemini/Anthropic/xAI/OpenAI/Ollama configured fallback chain
  -> existing agent planner
  -> one policy constitution over existing permissions
  -> lazy tool group
       -> structured documents / temporal graph / episodic context
       -> engineering/device/sandbox diagnostics
  -> existing observe/verify loop
  -> local redacted trace + Event Bus
```

Every optional long-running integration registers as Stage 3 metadata under
the existing kernel. Registration starts no process, thread, browser, model,
audio stream or poller.

## Integration decisions and current truth

Classification: A direct dependency, B external/local service, C MCP/API,
D optional plugin/adapter, E architectural/test inspiration, F reuse/reject
because ZENO already has a better authority.

| Capability | Decision | State on this machine | Implementation truth |
|---|---:|---|---|
| Universal model gateway / LiteLLM | F | WORKING | Reuses the measured `provider.py`/`model_router.py` seam; LiteLLM is installed but no second client is created. OpenAI routing was added. |
| Screenpipe | B | DISABLED | Loopback-only `/search` adapter, global capture kill switch and sensitive-window exclusions; no live service configured. |
| OpenAdapt | F | WORKING | Existing workflow engine already records, reviews, versions, replays and verifies without raw-coordinate-only replay. Source not embedded. |
| Graphiti | D | PARTIAL | Bounded SQLite temporal graph works with deduplication/history; Graphiti package/backing graph service is not installed. |
| Sherpa-ONNX | D | DISABLED | Honest lazy capability probe; no model installed and it never opens a microphone. |
| Docling | D | PARTIAL | Lazy adapter exists; existing OCR/document parser is the tested live fallback. Docling is not installed. |
| OpenHands | B | DISABLED | Engineering manager can select it only when enabled/installed; no executable is present. |
| agent-device | D | DISABLED | ADB discovery requires feature flag and explicit paired-device IDs; ADB is absent. |
| scrcpy | B | DISABLED | Controlled no-shell binary adapter with PID reuse and kernel shutdown cleanup; binary/device absent. |
| KDE Connect | B | DISABLED | Paired external bridge contract only; CLI absent. |
| Home Assistant | C | DISABLED | Authenticated, bounded REST read client; no URL/token configured. Security-sensitive control is not exposed. |
| Ollama / llama.cpp | B | WORKING / PARTIAL | Ollama and local models work; llama.cpp CLI is absent. ZENO local routing remains opt-in. |
| whisper.cpp | B | DISABLED | Router reports availability; binary absent. Existing faster-whisper remains local fallback. |
| Silero VAD | D | DISABLED | No competing VAD or microphone handle was added. |
| E2B | B | DISABLED | Placement policy exists; package/key absent, secrets/files are never forwarded implicitly. |
| Langfuse | D | DISABLED | Local bounded/redacted tracing works; exporter package/config absent. |
| Phoenix | D | DISABLED | Alternative exporter only, mutually exclusive with Langfuse. |
| ActivityWatch | B | DISABLED | Uses documented loopback bucket/events API with local privacy filtering; no live service configured. |
| APScheduler | F | WORKING | Rejected as a duplicate runtime; ZENO's one bounded scheduler and persistent scheduled-check path remain authoritative. |
| Promptfoo | E | PARTIAL | Portable AI routing/policy dataset and executable local regression contracts exist; Promptfoo CLI is not installed. |
| pywinauto | D | DISABLED | Optional fast-path adapter and routing priority exist; package absent, existing COM UIA works. |
| OPA | D | DISABLED | ZENO policy constitution is live; external OPA binary is absent. |
| n8n | B | DISABLED | HTTPS/loopback authenticated webhook adapter; no service configured. Source is not embedded. |
| Cross-device notifications | D | DISABLED | Reuses existing notification bus; phone bridge is opt-in and privacy defaults private. |
| Digital DNA | F | WORKING | Existing sampling is reused; observed patterns cannot become preferences, permissions or automation without owner confirmation. |
| Daytona | F | REJECTED | Explicitly excluded as requested; it is not a dependency or runtime component. |

## Files created

- `reyes_agent/phase3.py`, `phase3_flags.py`
- `reyes_agent/models/` and `models/local/`
- `reyes_agent/context/episodic/`
- `reyes_agent/memory/graph/`
- `reyes_agent/knowledge/documents/`
- `reyes_agent/engineering/`
- `reyes_agent/audio/local/`, `voice_stt_router.py`
- `reyes_agent/devices/mobile/`, `devices/android/`, `devices/bridge/`
- `reyes_agent/security/policy/`, `sandbox/`, `smart_home/`
- `reyes_agent/observability/`, `activity/`, `learning/`
- `reyes_agent/workflow_integrations/n8n.py`
- `reyes_agent/cross_device_notifications.py`
- `reyes_agent/computer/windows/pywinauto_backend.py`
- `reyes_agent/tools/phase3_tools.py`
- `evals/zeno_phase3_cases.json`
- `tests/test_phase3_foundations.py`

## Files modified

`.env.example`, `.gitignore`, `agent.py`, `config.py`, `model_router.py`,
`provider.py`, `permissions.py`, `system_health.py`, `tools/__init__.py`,
`tools/council_tools.py`, `web.py`, `ROADMAP.md`, and `AGENT.md`.

## Packages and external services

No package was installed in this phase. `litellm`, `ollama`, `mcp`,
`openwakeword` and `faster-whisper` were already installed. Optional packages
remain optional because enabling everything would violate startup/resource
requirements.

External services/binaries are required for Screenpipe, ActivityWatch,
Graphiti's full backend, OpenHands, ADB/agent-device, scrcpy, KDE Connect,
Home Assistant, llama.cpp, whisper.cpp, E2B, Langfuse/Phoenix, OPA and n8n.

All flags and endpoint/token variables are documented in `.env.example`.
Heavy flags default false. `ZENO_EPISODIC_MEMORY_ENABLED=false` is the global
capture kill switch even if a provider-specific flag is accidentally enabled.

## Security controls

- One shared tool gate now applies `ALLOW` / `CONFIRM` / `DENY` policy over
  existing permissions; financial, credential and security-disabling actions
  are structurally denied.
- Episodic providers must be loopback and exclude password managers, banking,
  incognito/private windows, and owner-defined patterns.
- n8n credentials may only be sent over HTTPS or loopback.
- Mobile control requires exact paired IDs; no public control endpoint exists.
- Home Assistant tokens are never returned by diagnostics.
- E2B receives no implicit environment variables or files.
- Engineering remains inside configured workspace roots.
- Traces redact key/token/password/secret/cookie fields and keep at most 500
  local records.
- Optional integrations start no background poller merely because installed.

## Verification and measurements

- Pre-change checkpoint: `fe8f513`; Claude's follow-up landed separately as
  `c090a24` without being overwritten.
- Baseline before Phase 3: 41/41 standalone test files passed in 297.9 s.
- Phase 3 contracts: 30/30 pass.
- Focused Phase 1: 38/38 pass after Claude's follow-up.
- Phase 2: 26/26 pass; Phase 21: 15/15; Phase 22: 9/9.
- Python compileall, `git diff --check`, and `pip check`: pass.
- Final whole repository: 42/42 standalone test files passed in 156.1 s while
  the managed desktop instance remained running.
- Isolated Phase 3 import: 15.26 ms; status: 153.50 ms; RSS delta 112 KiB;
  one thread before/after.
- Tool payload: one small core status tool; seven operational Phase 3 schemas
  load only for relevant requests (1,934 additional JSON bytes measured).
- Live restart: HTTP shell visible/reachable about 8.3 s after process launch;
  staged backend ready in 2,652.0 ms; no boot errors; four workers; queue zero.
- Live advanced status under 88% system RAM: 1,431.1 ms; health: 1,496.0 ms.
- Live Gemini natural-language turn called `phase3_status` and returned the
  measured 5/25 result in 26,982.6 ms.
- Real local Ollama `llama3.2:3b` returned exactly `LOCAL_OK` in 33,088.6 ms.
  During that load ZENO status still responded in 532 ms with queue zero.
- Running ZENO/WebView2 tree after restart: 595.1 MiB, 206 threads across 11
  processes while system RAM was 88%. Phase 3 itself added zero idle threads.
- Computer-control window enumeration confirmed `ZENO Mini Orb` is the only
  visible ZENO window after restart.
- A final live worker audit exposed the optional Windows notification baseline
  and poll exceeding their 15–16 second managed deadlines. That contention
  also caused one voice transcription deadline. The WinRT await is now bounded
  to two seconds, overlapping calls are skipped, repeated failure backs off to
  five minutes, the error log rotates, and worker diagnostics expose only task
  name/exception class (never exception text). After restart, six notification
  cycles completed with zero failures, zero timeouts, zero overlaps, an empty
  queue and all four workers available. Three following idle status probes were
  629.4 ms, 229.2 ms and 117.9 ms; the Mini Orb host remained responding.

## Known limitations

- The host-to-HTTP-shell portion of startup remains about 8.3 seconds on this
  pressured machine. Phase 3 did not rewrite the desktop host, so this is not
  claimed fixed.
- WebView2/desktop visual process cost remains the dominant ZENO resource use;
  Phase 3 adds backend capability contracts, not a frontend performance fix.
- No real Screenpipe, ActivityWatch, Graphiti, Docling, Sherpa, OpenHands,
  phone, Home Assistant, E2B, Langfuse, Phoenix, pywinauto, OPA or n8n service
  was available to exercise. Their adapters are therefore PARTIAL/DISABLED.
- OpenAI routing is implemented and tested structurally, but no OpenAI key was
  configured for a live call.
- Local Ollama inference works, but the configured custom local ZENO wake model
  still does not exist; a full internet-disconnected voice turn was not proven.
- No one-hour soak, paired-phone test, smart-home action or physical-security
  action was run.
- The current machine remained memory pressured, so live latency numbers are
  evidence for this workload, not isolated best-case benchmarks.

## Regression found and fixed during validation

The first whole-repository run found that a new `voice/stt/` package shadowed
the existing live `voice/stt.py` module, breaking speaker-confidence imports
and Deepgram timeout state. The fallback diagnostics were moved to the
non-conflicting `voice_stt_router.py`. Focused speech tests and the complete
42-file suite then passed. This regression was not hidden by the Phase 3-only
tests and is why the final whole-project run remains mandatory.

The post-commit live audit then found a separate pre-existing resource issue:
unbounded WinRT notification awaits could occupy managed workers long enough
to delay voice work. This was corrected and verified in the running desktop
process rather than merely documented as a limitation.

## Recommended next phase

Deploy and acceptance-test one optional system at a time. Highest value order:
custom ZENO wake model; Screenpipe **or** ActivityWatch (not both); Docling;
then a paired Android bridge. Keep every other heavy flag off until its own
resource, privacy and shutdown test passes.
