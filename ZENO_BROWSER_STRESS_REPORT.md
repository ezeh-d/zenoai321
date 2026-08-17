# ZENO — Browser Stress Report

## Status: NOT RUN

The brief was explicit that the previous audit had skipped browser stress
testing and that this phase must complete it. **It did not.** No torture loop,
no multi-tab test, no dynamic-page test, no browser-restart recovery test was
executed in this phase.

I am recording that rather than presenting the static inspection below as if it
were a stress test.

## What was established (inspection only)

The router now sends browser commands to browser tools — measured, and this is
the one cross-system claim from Mission 4 that *is* verified:

| command | capability | tools exposed |
|---|---|---:|
| Open Chrome | browser | **12** |
| Search YouTube for football highlights | browser | **12** |
| "search for it" (after "Open Chrome") | browser (inherited) | 12 |

Against **105 before**. The brief's "critical cross-system test" — that browser
commands receive only browser-relevant tools — passes.

Nine browser tools are registered and reachable: `browser_open`,
`browser_click`, `browser_read`, `browser_fill`, `browser_scroll`,
`browser_extract`, `browser_screenshot`, `browser_close`,
`browser_vision_click`.

The presence of `browser_vision_click` alongside DOM-level tools suggests the
preferred hierarchy the brief asks for (DOM before vision before coordinates)
is at least structurally present. **I did not verify the fallback order in
practice.**

## What was NOT tested

Everything else in Mission 4:

- open / navigate / search / click / back / forward / refresh
- new tab, close tab, switch tab, multi-tab tracking
- scroll, text input, dropdown, checkbox, form interaction
- downloads, uploads
- dynamic pages: lazy loading, infinite scroll, modals, cookie banners, SPA navigation
- element recovery when a selector fails
- post-action verification (did YouTube actually load?)
- navigation / element / download / overall timeouts
- cancellation mid-task ("stop")
- browser disconnect and reconnect recovery
- the repeated stress loop for leaks and zombie Chrome processes
- prompt-injection resistance from page content

## Why

Mission 1 consumed the available budget, and it was the right priority: the
10-second latency problem was the measured reason for this phase, and browser
benchmarks taken against the slow build would have needed retaking anyway.

## The one thing I would test first

**Post-action verification.** The brief is right that "Open YouTube" must be
confirmed by YouTube actually being loaded. Everywhere else in this codebase
that pattern has already caught real defects — the Slack adapter refuses to
type into a window it cannot read, and the render pipeline asks the file what
it contains rather than trusting an exit code.

If browser actions currently report success from "the click did not raise",
that is the same class of defect and the most likely place a real failure is
hiding.

## Honest summary

**Mission 4 is incomplete.** One claim from it is verified — browser commands
now receive 12 tools instead of 105. Nothing else in this report is a test
result, and none of it should be read as one.
