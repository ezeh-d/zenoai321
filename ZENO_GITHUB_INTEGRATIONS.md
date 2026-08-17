# ZENO GitHub Integration Decisions

Reviewed against upstream repositories on 2026-08-17. Nothing was copied
wholesale and no framework becomes ZENO's master.

| Repository | License observed | Useful concept | Decision |
|---|---|---|---|
| `openai/openai-agents-python` | MIT | tools, handoffs, guardrails, sessions, tracing | retain ZENO loop; adapter seam only |
| `microsoft/UFO` | MIT | Windows GUI/API control, device abstraction, DAG ideas | adapted into `computer/` and `devices/` |
| `livekit/agents` | Apache-2.0; separate model license | remote realtime voice/session patterns | optional remote adapter; local default |
| `browser-use/browser-use` | MIT | adaptive browser fallback | optional behind deterministic Playwright |
| `openinterpreter/openinterpreter` | Apache-2.0 | coding harness/result capture | optional specialist, never unrestricted shell |
| `SYSTRAN/faster-whisper` | MIT | local CTranslate2 STT | existing lazy fallback |
| `snakers4/silero-vad` | MIT | lightweight neural VAD | optional benchmark candidate; one AudioManager |
| `dscripka/openWakeWord` | Apache-2.0 code; bundled models CC BY-NC-SA 4.0 | local wake/training interface | adapter exists; custom licensed model required |
| `SAGAR-TAMANG/ultron-by-sagar-builds` | MIT | visual inspiration | no Three.js copy; efficient ZENO identity retained |

## Rules

1. Enable only through an independently health-checked adapter.
2. Never run duplicate agent schedulers, browser owners, wake listeners, or
   audio pipelines.
3. Prefer concepts/interfaces unless copied code has need, compatible license,
   provenance, and tests.
4. Heavy SDKs must beat native fallbacks in a real benchmark before default.
5. Model/data licenses are reviewed separately from code licenses.

Upstream references:

- https://github.com/openai/openai-agents-python
- https://github.com/microsoft/UFO
- https://github.com/livekit/agents
- https://github.com/browser-use/browser-use
- https://github.com/openinterpreter/openinterpreter
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/snakers4/silero-vad
- https://github.com/dscripka/openWakeWord
- https://github.com/SAGAR-TAMANG/ultron-by-sagar-builds
