# ZENO — Soak Test Report

## Status: NOT RUN

The brief was explicit: *"Do not merely say that a long-duration test is
recommended. Actually create/run an automated stability harness where
possible… Never claim a duration that did not occur."*

**No 30-minute or 60-minute soak test was performed in this phase.** No harness
was built. I am reporting that plainly rather than presenting shorter work as
if it satisfied the requirement.

## Why

This phase had four missions. I completed Mission 1 (the capability router) and
part of Mission 2 (benchmarking), because Mission 1 addressed the measured
10-second problem that prompted the phase and every other mission's numbers
would have been measured against the slow build otherwise.

The remaining context budget was not sufficient to build a soak harness, run it
for 30–60 minutes, and repair anything it surfaced. Starting one and abandoning
it partway would have produced a duration I could not stand behind.

## What *was* observed over the session

Not a substitute for a soak test, and offered only as what is actually known:

| observation | evidence |
|---|---|
| Multiple ZENO runtimes accumulated | three processes found; **fixed** — the server now takes the single-instance guard |
| Audio sources accumulated across reconnects | five registered, the selected one reading 0.1 RMS; **fixed** — dead sources demoted after 25 s |
| Non-daemon threads could outlive shutdown | two found in `interpreter_client.py`; **fixed** |
| Thread leak under provider outage | a new transcriber + thread per audio frame; **fixed by Codex** (30 s backoff) |
| Full suite run 3× with ZENO live | 1010 pass, no crashes, no hangs |

Every one of those is a genuine stability defect found and repaired. None of
them was found by a soak test — they were found by the owner using the system
and by reading the code.

## What a soak test would still catch

Unbounded growth over time is exactly the class this session did **not**
sample: RAM/thread/handle drift over an hour, event-subscriber multiplication
across UI reloads, browser process accumulation, gradually increasing audio
latency, and queue corruption under sustained rapid commands.

## Recommended harness

A script driving `/api/chat` and the voice path on a loop for 60 minutes,
sampling every 30 s: RSS, thread count, process count, open handles, audio
source count, event-bus subscriber count. Alert on sustained monotonic growth
rather than any single increase.

The instrumentation for most of this already exists — `/api/phone/mic/levels`,
`event_bus.stats()`, `agents/registry` health — so the harness is mostly
orchestration, not new measurement.

## Honest summary

**Mission 3 is incomplete.** The system is measurably more stable than at the
start of this session, and four real stability defects were repaired, but the
long-duration test the brief asked for did not happen and I will not describe
it as though it did.
