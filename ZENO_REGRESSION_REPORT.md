# ZENO — Regression Report

## Suite result

**1010 tests pass, 0 fail.**

That includes 36 new router tests. The suite was run three times during this
phase; the numbers below are the third and final run.

## Regression guards added

The router's win is worth nothing if it erodes. These tests fail if it does:

```
Hello ZENO, how are you?        <=  3 tools
What time is it?                <= 14
Open Chrome                     <= 16
Search YouTube for football      <= 16
Remember my colour is blue      <= 18
Look at my screen               <= 12
Fix this Python traceback       <= 16
```

Plus a blanket guard: **nothing ever exposes 30 or more tools**, against 226
registered. 105 was the number that cost 10 seconds.

And a guard on the router itself: **classification under 15 ms**, so schema
overload can never be traded for classifier overload.

## Misrouting guards

These are the tests I care most about, because the failure they prevent cannot
be undone by a retry:

| test | asserts |
|---|---|
| talking about deletion | `delete_file` **not** exposed for "what does deleting a folder mean" |
| asking to delete | `delete_file` **is** exposed for "delete the old report file" |
| asking about money | no `paper_trade` / `record_trade` / `backtest_strategy` for "how does PayPal work" |
| plain conversation | no `open_app`, `run_command`, `browser_open`, `delete_file` |

## Flakes found and repaired

**1. `test_uia_returns_real_structured_elements_fast`** — asserted an 8-second
wall clock. Failed in a full run only because ZENO was live and ~1000 tests
competed for CPU. Now best-of-two: a genuine regression to the 30-second COM
walk is slow every time and still fails, while transient load does not.

**2. Two `test_vad_pipeline` tests** — failed in one full run, passed in
isolation and in the next full run. Root cause found: an **external process was
editing `static/index.html` while the suite ran** (a cache-version bump,
`vad.js?v=1` → `?v=2`, which appeared in the working tree with no test and no
Python code responsible). Not a code defect. Worth recording because it will
recur if editing continues during test runs.

**3. My own test was wrong, not the code.** I asserted that "do that again"
after an expired context inherits nothing — but that phrase is *also* a
workflow pattern, so it correctly sets fresh context. Rewrote the test to use
"open it", which tests expiry rather than pattern overlap.

## Tests corrected rather than deleted

Two pre-existing tests asserted behaviour that changed deliberately:

- `test_phone_page_is_audio_endpoint_not_a_second_assistant` asserted the
  literal `echoCancellation:true`. That is now conditional — an external
  microphone gets the raw stream, because Chrome's AEC routes Android to the
  built-in mic and silenced the owner's OTG lav entirely (measured: peak RMS
  5.7 against 1377). Intent preserved, reason recorded in the test.
- `test_standing_mic_key_creates_audio_only_session` asserted audio-only
  scopes. Replaced with one asserting the grant is *usable* and one asserting
  money and credentials stay unreachable.

## Not covered

- Router behaviour against a **real** provider under load was measured
  end-to-end but not decomposed (see the performance report).
- No soak test; no browser stress. Both are missions in this brief that I did
  not complete — see the stability and browser reports for exactly what was and
  was not run.
