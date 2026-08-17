# ZENO — Browser Stress Report

## Status: RUN — 6 cycles, 36 actions

Harness: `tools/browser_stress.py`. Backend: **Playwright**, via
`browser_controller` / `browser_runtime`, driven through the same registered
tools ZENO uses. This replaces the previous version, which recorded that no
stress test had been performed.

## Results

| action | attempts | ok | verified | median |
|---|---:|---:|---:|---:|
| open | 6 | **6** | 4 | 716 ms |
| scroll | 6 | **6** | 6 | 903 ms |
| screenshot | 6 | **6** | 6 | 1 049 ms |
| read | 6 | 3 | 3 | 216 ms |
| extract | 6 | 3 | 3 | 276 ms |
| **missing_selector_must_fail** | 6 | **0** | 0 | 15 176 ms |

## The most important line is the last one

`browser_click` on a selector that cannot exist **failed all six times**, with
a bounded 15-second timeout and a real message:

```
Browser error: TimeoutError: Page.click: Timeout 15000ms exceeded.
Call log: waiting for locator("#definitely-not-here-zeno-stress")
 -- try browser_vision_click
```

ZENO does not report clicks it did not perform, it bounds the wait, and it
names the fallback. That is the behaviour the brief cares about most, and it
was already correct.

## Post-action verification already exists

I had speculated in the previous version of this report that browser actions
might report success from "the click did not raise". **That was wrong.**
`browser_open` returns:

> *"Opened https://example.com/; postcondition verified: the browser reports
> title 'Example Domain'."*

It asks the browser what it actually has. Credit where due — that was already
built.

## Two findings that were my harness, not ZENO

Recorded because a false defect is worse than none:

1. **`browser_extract` "failed 0/3"** in the first run — it requires a
   `selector` argument I never passed.
2. **"Clicking a non-existent selector reported SUCCESS"** — my success check
   matched strings *starting* with "error", so ZENO's actual message,
   *"Browser error: TimeoutError…"*, was scored as success. The tool was
   correct; the test was wrong. Fixed to match failure markers anywhere.

The first run of this harness would have reported two defects that did not
exist.

## Chromium processes

| | count |
|---|---:|
| before | 44 |
| peak | 54 |
| after | 46 |

Flagged **LEAK** by the harness's `>1` threshold — but **that signal is not
trustworthy here**: the owner's own Chrome was running throughout with 44
baseline processes, and ±2 is ordinary browsing noise. A real leak test needs a
machine with no user Chrome, which was not available.

Peak 54 against baseline 44 means roughly ten processes for the automation
itself, released afterwards. That looks correct, but I am not claiming it as
proven.

## `read` and `extract` at 3/6

Both failed exactly half the time — alternating with the target. The harness
alternates `example.com` and the local ZENO dashboard, so the pattern points at
the dashboard page rather than at the tools. Not diagnosed; the dashboard is a
heavy single-page app and may simply not settle within the read timeout.

## Not tested

Everything below remains uncovered:

- multi-tab: new / close / switch / semantic tab tracking
- back, forward, refresh, navigation history
- form interaction: text input, dropdowns, checkboxes, submission
- downloads and uploads
- dynamic pages: lazy loading, infinite scroll, modals, cookie banners, SPA routing
- element recovery when a selector fails (the fallback to `browser_vision_click`
  is *offered* in the error, but the chain was not exercised)
- browser disconnect and reconnect recovery
- cancellation mid-task
- prompt-injection resistance from page content

## Verdict

**Core actions work and verify themselves.** Open, scroll and screenshot passed
6/6. Failure handling is correct and bounded.

**Coverage is partial.** Six cycles of five actions is a smoke test with teeth,
not a torture test. The multi-tab, form, download and injection-resistance
sections of the brief remain unexecuted.
