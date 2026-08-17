# ZENO — Performance: Before vs After

All figures measured against the running server on this machine. Nothing here
is estimated.

## Headline

| command | before tools | after tools | before total | after total |
|---|---:|---:|---:|---:|
| What time is it? | 105 | **12** | **10.05 s** | **0.95 – 1.39 s** |
| Hello ZENO, how are you? | 105 | **2** | — | 2.17 – 5.29 s |
| What was my router test number? | 105 | 16 | — | **1.43 – 1.88 s** |
| Who are your agents? | 105 | 7 | 1.77 s | **1.29 – 1.56 s** |
| Remember my router test number is 7284 | 105 | 16 | — | 16.95 s (first call — see note) |

**"What time is it" went from 10.05 s to ~1.1 s — roughly 9×.** That was the
single worst number in the system and the reason this phase existed.

Two runs are shown where measured, because one sample is not a measurement.

## The numbers that are not clean wins

**"Hello ZENO, how are you?" varies 2.17–5.29 s with only 2 tools exposed.**
Tool count cannot be the cause at 2 schemas — this is provider latency, and it
varies run to run. A bare "hello" still returns in **0.11 s** through the local
fast-reply path, which never reaches a model at all.

**"Remember … 7284" took 16.95 s on first call.** A memory write with 16 tools
exposed. It was a cold first call, and the subsequent recall of that same fact
took 1.43 s and returned the correct value. I did not isolate whether the cost
is the write path or cold provider state, and I am not going to guess at it.

## Router overhead

Classification is deterministic — word-boundary regex plus recent conversational
context. **Under 15 ms**, asserted by a test. It adds no model call, because
trading one latency source for another would not be a fix.

## Speech recognition

| path | measured |
|---|---|
| Batch | median 1.86 s, min 0.34 s, max 10.42 s, n=97 |
| Streaming | transport verified; **end-to-end against the owner's voice not measured** |

Batch cannot beat this by tuning: the upload cannot begin before the speaker
stops. Streaming is enabled with batch retained as fallback, so a failed stream
costs quality rather than a turn.

## Voice gates, tuned against the real room

| gate | value | basis |
|---|---|---|
| VAD floor | 560 RMS | owner's speech measured 972–11,471 |
| Consecutive voiced frames | 5 | noise can be loud, but not for a fifth of a second |
| Clip peak | > 1,500 | room noise is flat; speech has peaks |

Before this tuning, most of 97 STT calls returned **zero characters** — ZENO was
paying to transcribe the room.

## Transport

- 52 frames/sec sustained on both Wi-Fi and hotspot
- Route enumeration **7.0 s → 2.6 s cold, 48 ms warm** (one `Get-NetAdapter`
  call cached 120 s instead of one per address)

## What the brief asked for and I did not do

**Prompt-token counts, `tool_schema_bytes`, first-token latency and first-audio
latency were not instrumented.** I measured end-to-end wall clock instead.

That is a real gap and worth naming plainly: the totals prove the win, but they
do not decompose it. I can show that removing 93 schemas removed ~9 seconds; I
cannot show from this data how much of the remaining ~1.1 s is provider time
versus ZENO's own preparation.

## Recommended next step

Instrument **first-token latency**. It is the single measurement that would
separate provider time from ZENO's own work, and without it every further
optimisation is guesswork.
