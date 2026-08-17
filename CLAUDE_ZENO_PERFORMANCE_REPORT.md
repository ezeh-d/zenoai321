# ZENO — Performance Report

All figures measured on this machine, against the running server.

## End-to-end response latency

| request | measured | path |
|---|---|---|
| "hello" | **0.11 s** | local fast-reply, no model call |
| "who are your agents" | **1.77 s** | one model call, one tool |
| "what time is it" | **10.05 s** | model call + tool — **too slow** |

The first is excellent. The third is a real problem and is the single worst
number in the system.

## The dominant cost: tool schemas per turn

```
tools registered   226
CORE (every turn)  105
lazy (on demand)   121
```

The repository already measured this and recorded it in `tools/__init__.py`:
**~5.4 s per turn at 93 tool schemas versus ~1.5 s at 5 on Gemini.** Tool
*count*, not prompt text, dominates.

At **105 core tools** we are past the point where that measurement was taken.
Roughly half the ten seconds is likely schema overhead rather than thinking.

I moved four setup/recovery tools off the hot path this session
(`prepare_presentation_evidence`, `presentation_recover`, `assistant_mode_status`,
`type_message`) — 109 → 105. That is a trim, not a fix.

**Recommendation, not applied:** a capability-router that sends ~15–25 schemas
chosen by intent, rather than 105 every turn. Expected to bring the 10 s case
under 3 s. I did not attempt it during a live presentation window — it changes
routing for every request and needed more soak time than the deadline allowed.

## Speech recognition

| path | measured |
|---|---|
| Batch (upload after speaking) | median **1.86 s**, min 0.34 s, max **10.42 s**, n=97 |
| Streaming (upload while speaking) | transport verified; only the tail is outstanding at end of speech |

Batch cannot beat this by tuning — the upload cannot begin before the speaker
stops. Streaming is implemented and enabled (`STT_STREAMING`), with batch
retained as fallback so a failed stream costs quality, never a turn.

**Not measured:** streaming's end-to-end latency against the owner's voice. The
phone disconnected across several restarts and the deadline arrived first. The
number is unproven and is not claimed.

## Voice pipeline gates

Tuned against the owner's actual room and voice:

| gate | value | rationale |
|---|---|---|
| VAD floor | 560 RMS | owner's speech measured 972–11,471; room noise below |
| Consecutive voiced frames | 5 | noise can be loud, but not for a fifth of a second |
| Clip peak | > 1,500 | room noise is flat; speech has peaks |
| Conversation window | 180 s (300 s visiting) | a pause to think must not end a conversation |

Before tuning, most of 97 STT calls returned **zero characters** — ZENO was
paying to transcribe the room.

## Audio transport

- 52 frames/sec sustained, both Wi-Fi and hotspot
- Route enumeration: **2.6 s cold, 48 ms warm** (was 7.0 s — `Get-NetAdapter` was
  being invoked once per address; now one call cached 120 s, addresses read from
  psutil in-process every call)
- Local-address check moved off PowerShell entirely after it turned pairing into
  a multi-second stall

## UI

The Ultron HUD uses one canvas and one `requestAnimationFrame` loop, no
particles, no shaders, quality chosen from real `hardwareConcurrency` and
`deviceMemory`, and the loop **stops entirely** when the tab is hidden.

That optimisation revealed its own bug during verification: a backgrounded tab
left the canvas blank on activation. `renderFrame()` now paints one frame on
activation and on becoming visible.

## Honest summary

Fast where it matters most (0.11 s for conversational replies), and too slow on
the tool path. The cause is identified and measured; the fix is scoped but not
applied, because applying it hours before a supervisor visit would have been the
wrong trade.
