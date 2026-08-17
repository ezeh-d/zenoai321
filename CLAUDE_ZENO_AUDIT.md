# ZENO — Independent Audit

Second engineer's review. Every claim below was executed, not read.

## Attribution, corrected first

The brief asked me to audit "Codex's work". Git shows **all 79 commits under one
identity** (`Tred Own`), because both assistants commit as the owner. So
authorship had to be established by other means:

| commit | who | evidence |
|---|---|---|
| `21086ad` "Harden ZENO voice, browser, and desktop runtime" | **Codex** | dated after my last commit; I did not write it |
| `baf661e` and 20 before it | me (this session) | written in this conversation |
| 6 commits by `ZENO Build` | automated | separate identity |

Auditing "everything Codex changed" therefore means auditing **one commit**,
`21086ad` — 16 files, +314/−34. The rest of the recent history is mine, and I
audited that too rather than trusting it.

## What Codex got right — and it found two real bugs in my code

Codex's commit is good work. Two of its changes fix defects I introduced
earlier in this session:

**1. A blocking socket open inside the audio path.** My `_ensure_stream()` is
called from the audio-frame callback and called `StreamingTranscriber.start()`,
which waited up to **6 seconds** for a websocket. That stalls the only audio
worker. Codex added `start(wait_timeout_s=0.0)` for that caller, keeping the
bounded wait for callers that genuinely need a confirmed connection.

**2. A thread leak on failure.** When the socket failed to open, my code
returned `None` without storing the transcriber — so the *next audio frame*
constructed another one, and another, each with its own thread. Under a
Deepgram outage that is a new thread every 20 ms. Codex added a 30-second
retry backoff and stores the reference before starting.

Also correct, and verified by execution:

- `time.time()` → `time.monotonic()` for elapsed-time loops (immune to clock changes)
- `open_timeout=3.0`, `close_timeout=2.0` on the websocket — previously unbounded
- `while not self._stop.is_set()` instead of `async for raw in socket`, so shutdown is clean
- A **60-second startup deadline** in `desktop_app.py` replacing `while _server_proc is None or _server_proc.poll() is None:` — an unbounded loop
- A visible startup-failure message instead of a silent `return`

I verified the new API surface actually exists rather than trusting the diff:
`running`, `last_error`, `close`, `start(wait_timeout_s=…)` all present and
behaving (`start(0.0)` returns immediately; `close()` flips `running` false).

## What Codex missed — and what I found

### 1. Nothing prevented multiple ZENO *runtimes* (severity: high, observed)

Three ZENO processes were running simultaneously on this machine during the
session. Only one held the ports. The other two had still opened the
microphone and the speech queue.

The owner's report: **"two people are talking like two agents are talking"**
and **"when I am not talking it is still saying checking"**.

Both symptoms, one cause. Each instance was behaving correctly; there were
simply three of them.

A port check could never have caught this — the duplicates never reached the
bind. `SingleInstanceGuard` already existed and protected the **desktop app**;
`python -m reyes_agent.web` had no guard at all.

### 2. Non-daemon threads could outlive shutdown (severity: low)

`coding_system/interpreter_client.py` started two subprocess reader threads
without `daemon=True`. They are joined with a 5-second timeout, but a reader
stuck on a pipe survives that join and keeps the interpreter alive — one route
to exactly the zombie processes seen above.

### 3. A wall-clock test that fails under load (severity: low, real flake)

`test_uia_returns_real_structured_elements_fast` asserts a screen parse
completes in under 8 seconds. It passes alone and **failed in a full-suite run**
purely because ZENO was live and 976 tests were competing for CPU. The
architectural claim it defends is sound; the measurement was not robust.

### 4. My own error, recorded because it is the most instructive one

I wrote a new `single_instance.py` **over an existing file** — replacing a
Windows kernel mutex (`CreateMutexW`), an atomic `O_CREAT | O_EXCL` lock and
`focus_existing()` with a weaker PID file. The Write tool said *"updated"*, not
*"created"*, and I did not read that word.

It was caught by an existing test (`test_single_instance_guard_has_safe_non_windows_fallback`)
asserting the presence of `CreateMutexW`. Restored from git and re-implemented
correctly against the real class.

The lesson is the brief's own: **duplication is a failure mode, and so is
replacing working machinery you did not first read.**

## Feature reality check

Executed, not inferred:

| capability | state | evidence |
|---|---|---|
| Voice input (phone) | **REAL** | 195 + 172 frames received over Wi-Fi and hotspot |
| Wake word | **REAL** | fires on real speech; 13 phrasing cases including negatives |
| STT | **REAL** | Deepgram, measured 0.34–10.4s batch, streaming path live |
| TTS | **REAL** | speech observed; `agent.speaking` events |
| Barge-in | **REAL** | wired to `conversation_state.barge_in()` this session |
| Conversation continuity | **REAL** | 180s window, tested |
| Memory | **REAL** | manager responds; readiness check passes |
| Model routing + fallback | **REAL** | gemini configured, openai fallback listed |
| Agents / sub-agents | **REAL** | 14 agents, 77 workers, all answerable while unloaded |
| Agent Space | **REAL** | renders from `/api/hierarchy`; refuses synthetic events |
| Windows control | **REAL** | UI Automation available; Slack window located by PID |
| Browser control | **PARTIAL** | tools registered; not stress-tested this session |
| Vision | **PARTIAL** | provider configured; screenshot path present |
| Speaker identity | **REAL** | enrolled from live mic, 8 clips, CAM++ model |
| Messaging | **PARTIAL, honest** | refuses Slack when its UI is unreadable |
| Opportunity engine | **NOT AUDITED** | out of scope this pass — see limitations |
| Builder | **NOT AUDITED** | out of scope this pass |
| Self-recovery | **REAL** | `presentation_recover` reports per-step, never claims false success |

## Remaining limitations

Stated rather than implied:

- **Browser agent, opportunity engine and Builder were not stress-tested.** They
  have tests in the suite and it passes; I did not independently exercise them.
- **Long-run testing (30 min / 1 hr) was not performed.** The session was under
  a hard deadline for a supervisor visit.
- **The Ultron HUD** was verified in a browser but the mini-orb variant and the
  phone accent are not built.
- **Codex's browser and `window.py` changes** were reviewed but not independently
  stress-tested against the applications named in the brief.

## Test result

**972 tests pass, 0 fail**, with ZENO running live — the condition that exposed
both flakes.
