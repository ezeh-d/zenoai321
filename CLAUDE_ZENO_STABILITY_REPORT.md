# ZENO — Stability Report

## Headline

The most serious stability defect found was **not a crash**. It was three ZENO
runtimes running at once, each behaving correctly, producing two voices and
phantom "Checking" while the owner sat in silence. Fixed at the source: the
server now takes the existing single-instance guard.

## Tests performed

| test | result |
|---|---|
| Full suite | **972 pass, 0 fail** |
| Full suite **with ZENO live** | 972 pass — the condition that exposed both flakes |
| Duplicate runtime rejection | second instance refuses, exits 1, first keeps serving |
| Restart persistence | agents, voice profile, evidence pack all survive |
| Phone reconnect after restart | reconnects from the standing key, no re-scan |
| Microphone disconnect/reconnect | source demoted after 25 s silence, new source promoted |
| Hotspot loss and restore | route list drops it and recovers; never offers a dead address |
| Speaker enrolment | 8 clips captured from the live mic, profile built |
| Barge-in | speech onset stops TTS via the existing single speech queue |
| Presentation recovery | reports per step; refuses to claim RECOVERED over a dead mic |

## Failure injection

| injected | behaviour |
|---|---|
| Streaming STT socket fails | falls back to batch; a failed stream costs quality, never a turn |
| Deepgram unreachable | 30 s retry backoff (Codex) — previously a new thread per audio frame |
| Barge-in raises | caught; audio frames keep flowing (test asserts this) |
| Registry unreadable | agent roster still returns 14 — "asleep" never degrades to "unknown" |
| Capability probe throws | fails **closed**; a broken check never grants a capability |
| Slack UI unreadable | refuses to type rather than sending into an unknown conversation |
| Lock file unwritable | startup proceeds — the guard is a safety net, not a dependency |
| Wrong/rotated pairing key | 403 with a real sentence; phone forgets a dead key |

## Not tested, and stated plainly

- **30-minute and 1-hour soak runs.** Not performed. The session ran against a
  hard deadline for a supervisor visit.
- **Browser automation stress** (tabs, downloads, uploads, form interaction).
- **Windows automation across the named applications** (VS Code, PyCharm,
  Explorer, Terminal). Slack was exercised and correctly refused.
- **Opportunity engine and Builder chains.**
- **Network loss mid-conversation** beyond the offline presentation pack.

These are gaps in *coverage*, not known failures. I would not describe the
system as soak-tested.

## Known operational hazards

**Windows Mobile Hotspot switches itself off** when no device is connected. This
caught us three times. It is Windows behaviour, not a ZENO defect, but it
presents as "the phone cannot connect". `NetworkOperatorTetheringManager` can
restart it in one call.

**Chrome's secure-origin flag is per-origin and per-device.** A second phone
needs its own entry; the Wi-Fi origin does not cover the hotspot origin.

**The `/mic` page is now `no-store`.** Before that, two verified server-side
fixes never reached the phone because it was running cached JavaScript — the
owner was troubleshooting against code that was not the code on disk.

## Recovery posture

`presentation_recover` stops speech, cancels the running task, returns to
listening and re-opens the conversation window. It **never** deletes, resets,
wipes or restarts, every step is independently guarded, and it reports
**RECOVERED WITH PROBLEMS** — naming the microphone — rather than a comforting
green when something is genuinely wrong.
