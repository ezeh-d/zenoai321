# ZENO — Soak Test Report

## Status: RUN — 30.7 minutes

Harness: `tools/soak_test.py`. Duration **30.7 minutes**, **89 requests**,
**60 samples** at 20-second intervals, against the live server.

This replaces the previous version of this file, which correctly recorded that
no soak test had been performed.

## Resource trends — the reason a soak exists

Growth judged by comparing the last quarter of the run against the first. A
single increase is not a leak; sustained monotonic growth is.

| resource | first | last | growth | peak | verdict |
|---|---:|---:|---:|---:|---|
| RSS (MB, all python) | 331.3 | 301.7 | **−8.9 %** | 463.3 | **stable** |
| Threads | 49.1 | 51.9 | +5.8 % | 71 | **stable** |
| Processes | 6.4 | 6.9 | +8.3 % | 8 | **stable** |
| Handles | 2 419.7 | 2 703.6 | +11.7 % | 3 281 | **stable** |

**No memory leak. No thread leak. No process accumulation.** Memory ended
*lower* than it started, which is what a healthy GC under varying load looks
like. Handles grew 11.7 % — real but well inside noise for a half-hour window,
and it did not climb monotonically.

This is the first evidence in the project that ZENO survives sustained use
without unbounded growth.

## Failures — 21.35 %, and they are real

| error | count |
|---|---:|
| TimeoutError (various categories) | 15 |
| HTTP 502 | 4 |

| latency | value |
|---|---:|
| median | **2.34 s** |
| p95 | **95.13 s** |
| max | **119.08 s** |

The median is healthy. The p95 is not, and I am not going to explain it away.

**What I can attribute:** the run overlapped deliberately with the browser
stress test and with a concurrent Codex session on the same machine — the
browser harness alone recorded an 81-second `browser_open` during this window
that took 5.3 s when run alone. Contention is a real part of the explanation.

**What I cannot attribute:** whether ZENO would show a 95-second p95 under
sustained load *without* that contention. I did not run a quiet-machine
control, so the number stands as measured and unexplained.

Every failure was a timeout or a 502 — **no crash, no hang, no corrupted
state, and the loop continued through all of them.** Malformed input
(null bytes, 4 000-character strings, 200 emoji, empty strings) produced no
failures at all.

## What the harness could not measure

`audio_sources` and `bus_subscribers` recorded **zero samples**. Both read
process-local or endpoint state that was unavailable from the harness's
process — the same trap that has bitten twice already in this project
(the frame counter and the readiness check).

So **event-subscriber multiplication and audio-source accumulation remain
untested.** Those are two of the specific leaks the brief names, and this run
does not cover them. Fixing the harness to query them over loopback is the
obvious next step.

## Workload exercised

Conversation, utility, memory writes and recalls, agent queries, diagnostics,
routing-sensitive phrasing, rapid 3-way concurrent bursts every third cycle,
and malformed input every fourth cycle.

Not exercised: desktop automation and browser launches (deliberately — those
belong to the browser harness), TTS/STT lifecycle, wake/standby transitions.

## Verdict

**Resource stability: passed.** No leak of memory, threads, processes or
handles over half an hour.

**Latency under contention: failed.** A 95-second p95 is not acceptable, and
the honest position is that contention explains some of it and I have not
proven how much.

**Coverage: incomplete.** Two named leak classes were not measured because the
harness could not see them.
