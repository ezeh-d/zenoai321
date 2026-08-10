# ZENO Phase 4 — handoff

Every feature below carries a label. **Nothing is marked WORKING because a
dependency imported.** Where a claim is measured, the measurement is given.

Suite at handoff: **479 passed, 0 failed** (373 before Phase 4; +106 new tests).
Commits: `f2251f0`, `233bf70`, `609fa7e`.

---

## 1. Architecture before Phase 4

245 modules. Voice → intelligence router (FAST/DEEP) → model router with
provider fallback and circuit breakers → permission engine → tools/executors,
with vision (UIA), computer control (deterministic + agentic), browser
(Playwright), agents, memory, remote access and an event bus. Codex's Phase 3
had added a 25-service registry (`phase3.py`) of optional external integrations,
all flag-gated and mostly off.

## 2. Architecture after Phase 4

Fifteen new modules, all lazy, all off the startup path:

```
skills/                   OBSERVED → LEARNED → APPROVED, bounded by a constitution
missions/                 durable, restart-safe, SQLite-checkpointed
health/                   psutil metrics + a watchdog with circuit breakers
security/ai/              provenance-based guardrails (trust_context + guardrails)
security/privacy/         destination-aware detection and redaction
security/secrets/         OS credential store first, environment second
computer/agent_backends/  the cheapest-first technique ladder
computer/lifecycle.py     9 lifecycle stages on the EXISTING event bus
vision/models/            hardware-measured vision tier routing
vision/camera/            cv2 motion gating; off by default
tools/marketplace/        MCP trust states; discovery is not trust
research/crawler/         bounded, robots-respecting extraction with citations
knowledge/vector/         filter-by-metadata then BM25
audio/noise/              spectral subtraction before VAD
audio/diarization/        turn segmentation without invented speakers
web/ + netlify.toml       static public surface, no server-side code
```

Cold import of the full core is still **1.25s** — none of this loads until used.

## 3–7. Repositories inspected, and what was done with each

| # | Project | Classification | Why |
|---|---|---|---|
| 36 | NousResearch/hermes-agent | ARCHITECTURAL_REFERENCE | Concepts taken (procedural skills, confidence-gated learning, cross-session recall). ZENO stays ZENO; no code, no rename. |
| 37 | bytedance/UI-TARS-desktop | ARCHITECTURAL_REFERENCE | Its event-stream idea became `computer/lifecycle.py`. Its visual operator is rung 7 of the ladder — a real seam, not installed. |
| 38 | temporalio/sdk-python | ARCHITECTURAL_REFERENCE | Ideas adopted (idempotency keys, per-step checkpoints, bounded retries, terminal states). Runtime rejected: it needs a server to provide what SQLite already provides here. |
| 39 | qdrant/qdrant | **ARCHITECTURAL_REFERENCE** — capability built | `knowledge/vector/` does filter-then-BM25 locally. Qdrant is a server; it becomes right when the corpus outgrows memory or must be shared between machines. |
| 40 | unclecode/crawl4ai | **OPTIONAL_PLUGIN** — capability built | `research/crawler/` on requests, bounded and robots-respecting. Verified live against two real pages. Crawl4AI remains an optional extraction backend. |
| 41 | QwenLM/Qwen3-VL | OPTIONAL_PLUGIN (seam only) | Routing tier exists; no model. This machine has 7.9GB RAM and no CUDA — it genuinely cannot run one. |
| 42 | m87-labs/moondream | OPTIONAL_PLUGIN (seam only) | Same. LIGHT tier is routable and reports unavailable. |
| 43 | NVIDIA-NeMo/Guardrails | REJECTED (capability built directly) | NeMo is a Colang runtime and an LLM-call layer around the model. ZENO needed provenance enforcement, which is ~200 lines and has no runtime cost. Adding NeMo would have meant a second prompt pipeline for a weaker guarantee. |
| 44 | Presidio | REJECTED (capability built directly) | Presidio's value is NLP-based entity recognition; the destinations that matter here are credentials and structured identifiers, which are regex-and-Luhn problems. Presidio pulls spaCy + models for a capability that must run on every outbound string. |
| 45 | pyannote/pyannote-audio | **OPTIONAL_PLUGIN** — half built | Turn segmentation WORKING (numpy). Speaker attribution NOT IMPLEMENTED and deliberately not faked — that needs torch, absent. |
| 46 | xiph/rnnoise | **OPTIONAL_PLUGIN** — capability built | Spectral subtraction before VAD, measured effective on stationary noise. RNNoise adds non-stationary noise (keyboards, babble) which this cannot do. |
| 47 | nats-io/nats-server | REJECTED | `event_bus.py` (345 lines, persistent, bounded, already subscribed to by the dashboard) does this for one machine. The brief says not to add distributed infrastructure that does not earn itself. |
| 48 | modelcontextprotocol/registry | **DIRECT_DEPENDENCY** — built | `tools/marketplace/` with all eight trust states. No path to ENABLED avoids APPROVED. Requested vs granted capabilities are separate fields. |
| 49 | giampaolo/psutil | **DIRECT_DEPENDENCY** | Already installed; now used for real in `health/processes.py`. |
| 50 | jaraco/keyring | **DIRECT_DEPENDENCY** | Already installed; Windows Credential Manager confirmed present and working. |
| 51 | opencv/opencv | **DIRECT_DEPENDENCY** — built | `vision/camera/` real cv2 motion gating. Off by default, refuses to self-enable, discards boring frames locally. |
| 52 | Netlify | LOCAL_SERVICE (artifact ready, **not deployed**) | See §13–15. |

## 8. Files created

`reyes_agent/skills/{__init__,constitution,models,registry,learner,executor,manager}.py`
`reyes_agent/missions/{__init__,store,manager,temporal_backend}.py`
`reyes_agent/health/{__init__,watchdog,processes}.py`
`reyes_agent/security/ai/{__init__,trust_context,guardrails}.py`
`reyes_agent/security/privacy/{__init__,detector,redactor}.py`
`reyes_agent/security/secrets/{__init__,manager}.py`
`reyes_agent/computer/{lifecycle.py,agent_backends/{__init__,ladder}.py}`
`reyes_agent/vision/models/{__init__,router}.py`
`reyes_agent/vision/camera/{__init__,sensor}.py`
`reyes_agent/tools/marketplace/{__init__,trust,registry}.py`
`reyes_agent/research/{__init__,crawler/{__init__,limits,manager}}.py`
`reyes_agent/knowledge/vector/{__init__,index}.py`
`reyes_agent/audio/noise/{__init__,suppressor}.py`
`reyes_agent/audio/diarization/{__init__,router}.py`
`web/index.html`, `netlify.toml`, `scripts/build-config.js`
`tests/test_phase4_{skills,security,missions,health,routing,subsystems}.py`

## 9. Files modified

`.gitignore` only. **No Codex-owned file was touched.**

## 10–11. Dependencies and external services added

**None.** Everything uses what was already installed. No new service runs.

## 12. Environment variables (all optional, all default off)

`ZENO_AI_GUARDRAILS_ENABLED`, `ZENO_TEMPORAL_ENABLED`, `ZENO_AGENT_TARS_ENABLED`,
`ZENO_VISION_GROUNDING_ENABLED`, `ZENO_MOONDREAM_ENABLED`, `ZENO_QWEN_VL_ENABLED`,
`ZENO_CLOUD_VISION_ENABLED`, `ZENO_CAMERA_ENABLED`,
`ZENO_NOISE_SUPPRESSION_ENABLED`, `ZENO_DIARIZATION_ENABLED`.
Netlify build-time: `ZENO_PUBLIC_API_URL` (public).

## 13. Netlify configuration — WORKING (as an artifact)

`publish = "web"`, `command = "node scripts/build-config.js"`, Node 20, SPA
redirect, CSP/`X-Frame-Options: DENY`/`Permissions-Policy` denying camera and
microphone, `form-action 'none'`. **No `[functions]` block** — the site ships no
server-side code, which is the simplest possible guarantee that no public
endpoint can reach the desktop.

## 14–15. Netlify site URL and connected GitHub repo — **NOT DONE**

I did not create a Netlify site, connect a repository, or deploy. Creating
accounts and granting OAuth are yours to do, and publishing is outward-facing.
What is ready: the site builds and runs locally, verified offline.

To finish it: push this repo to GitHub, create a Netlify site from it (try
`zeno-ai`, `zeno-assistant`, `zeno-aios`, `zeno-system` — availability unknown),
and set `ZENO_PUBLIC_API_URL` in Netlify's environment UI if you want live
status. Leaving it unset is safe: the page shows OFFLINE.

## 16. Feature flags

All ten above default **off**. Rungs 1–5 of the computer ladder and the
ACCESSIBILITY vision tier need no flag and work today.

## 17–18. Tests executed and results

| Suite | Result |
|---|---|
| `test_phase4_skills.py` | **12 passed** |
| `test_phase4_security.py` | **13 passed** |
| `test_phase4_missions.py` | **9 passed** |
| `test_phase4_health.py` | **12 passed** |
| `test_phase4_routing.py` | **18 passed** |
| `test_phase4_subsystems.py` | **26 passed** |
| Whole repository | **479 passed, 0 failed** |

Against the brief's lettered tests:

- **TEST A** (skill learning) — WORKING. Four repeats → suggestion → approval.
- **TEST B** (durable mission) — WORKING. A real child process killed with
  `os._exit(9)` mid-mission; a fresh process resumed at step 2 and completed,
  with no duplicate created.
- **TEST E** (local vision) — PARTIAL. Routing is real; no local model exists
  to route to, and it says so.
- **TEST F** (fallback to visual agent) — WORKING as routing. The visual rung
  itself is not installed.
- **TEST G** (malicious content) — WORKING. Including an injection matching
  none of the patterns, which is still neutralised by provenance.
- **TEST J** (watchdog) — WORKING, including that it stops.
- **TEST K** (event order) — WORKING. All 7 stages in order off the live bus.
- **TEST L** (secret redaction) — WORKING.
- **TEST N** (backend offline) — WORKING. Verified in a real browser.
- **TEST C** (semantic search) — WORKING. Filtering provably narrows before scoring.
- **TEST D** (research) — WORKING. Live fetch of two real pages, dedupe by shingle
  overlap, citations kept, content fenced as untrusted.
- **TEST H** (noisy audio) — WORKING. Residual error measurably falls; a clean
  mic is detected and returned untouched.
- **TEST I** (multi-speaker) — PARTIAL. Turn boundaries found correctly; speaker
  identity refused rather than guessed.
- **TEST M** (Netlify deploy) — NOT RUN. Needs your account.

## 19. Performance

| Measure | Result |
|---|---|
| Cold import, full core | **1.25s** |
| Phase 4 subsystems at startup | **0** — all lazy |
| Skill learning over 122 real actions | **0.13s** |
| Mission step (commit included) | ~0.3s |
| UIA structural read | **0.2–0.8s**, no model, no GPU |

## 20. Security controls

Skill constitution (8 prohibitions, enforced at store/approve/run, security
surface unwritable); provenance-based prompt-injection defence; destination-aware
redaction with credentials unconditional; OS credential store; watchdog circuit
breakers; a public web surface with no server-side code.

## 21–25. Capability summary

- **Offline** — WORKING. Voice, UIA, skills, missions, watchdog, redaction and
  secrets all run with no network.
- **Local AI** — PARTIAL. Ollama is in the provider chain; no local vision model
  can run on this hardware.
- **Vision** — WORKING via UIA (ground truth, sub-second). Model tiers: seams only.
- **Missions** — WORKING and genuinely restart-safe.
- **Skill learning** — WORKING, and currently correctly silent: the best real
  pattern (`build_project → website_restore_checkpoint → website_project`)
  appears in 2 sessions against a threshold of 3. One more occurrence and ZENO
  will offer it.

## 26. Known limitations

1. All 17 subsystems are now built. Six were added after the first pass:
   MCP marketplace, camera, research crawler, semantic index, noise
   suppression and turn segmentation. The named libraries for four of them
   (Qdrant, Crawl4AI, RNNoise, pyannote) are still not installed — the
   capability exists without them, and each says what the library would add.
2. No local visual model can run here (7.9GB RAM, no CUDA).
3. RESOLVED by CODEX: `classify_tool_result` now gives the skill executor a
   structured outcome, so a step no longer advances on an unverified result.
4. Netlify is not deployed.
5. `reyes_agent/voice/stt/` is an empty directory with a stale `__pycache__`;
   worth deleting so the shadowing that broke transcription cannot return.
6. Five other ZENO processes were running during this work — worth a look.

## 27. Still mocked

Nothing. Every unavailable backend reports its real state; none returns
fabricated success. The vision and TARS/CUA tiers are seams that say they are
seams.

## 28. Recommended Phase 5

1. Wire skills and missions into `agent.py`'s turn (Codex owns that file) — both
   are complete and currently unreachable from conversation.
2. Speaker attribution — the one genuinely missing capability, needing torch.
3. A structured refusal contract from `run_tool`, fixing limitation 3.
4. Deploy the web surface once you have made the Netlify decisions.
5. Audio: RNNoise and diarization, the one untouched sensory area.
